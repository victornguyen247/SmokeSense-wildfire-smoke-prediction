"""DATA-06 shared plumbing: bounded retries honoring Retry-After, redaction, run bookkeeping."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from ingestion.live import common
from ingestion.live.common import (
    JobResult,
    RetryTransport,
    lookback_start,
    retry_after_seconds,
    run_job,
)

NOW = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)


class Script(httpx.BaseTransport):
    """Replays a list of responses (or exceptions) and counts requests."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def handle_request(self, request):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def client(steps, statuses=frozenset({429, 503}), max_wait_s=60.0):
    sleeps: list[float] = []
    script = Script(steps)
    transport = RetryTransport(
        statuses,
        attempts=3,
        backoff_s=2.0,
        max_wait_s=max_wait_s,
        sleep=sleeps.append,
        transport=script,
    )
    return httpx.Client(transport=transport), script, sleeps


def test_retries_with_exponential_backoff_then_succeeds():
    c, script, sleeps = client(
        [httpx.Response(503), httpx.Response(503), httpx.Response(200)]
    )
    assert c.get("https://x.test/").status_code == 200
    assert script.calls == 3 and sleeps == [2.0, 4.0]


def test_retry_after_is_honored_when_longer_than_backoff():
    c, _, sleeps = client(
        [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)]
    )
    assert c.get("https://x.test/").status_code == 200
    assert sleeps == [7.0]


def test_retry_after_beyond_cap_is_not_slept():
    """AirNow-style "come back next hour": give up this run instead of sleeping or hammering."""
    c, script, sleeps = client([httpx.Response(429, headers={"Retry-After": "3600"})])
    assert c.get("https://x.test/").status_code == 429
    assert script.calls == 1 and sleeps == []


def test_attempts_are_bounded():
    c, script, sleeps = client([httpx.Response(503)] * 3)
    assert c.get("https://x.test/").status_code == 503
    assert script.calls == 3 and len(sleeps) == 2


def test_status_outside_the_retry_set_is_returned_at_once():
    c, script, _ = client([httpx.Response(429)], statuses=frozenset({503}))
    assert c.get("https://x.test/").status_code == 429
    assert script.calls == 1


def test_network_errors_are_retried_then_raised():
    c, script, sleeps = client([httpx.ConnectError("boom")] * 3)
    with pytest.raises(httpx.ConnectError):
        c.get("https://x.test/")
    assert script.calls == 3 and sleeps == [2.0, 4.0]


def test_retry_after_http_date():
    when = "Sat, 24 Oct 2026 02:00:30 GMT"
    response = httpx.Response(429, headers={"Retry-After": when})
    assert retry_after_seconds(response, now=NOW) == 30.0
    assert retry_after_seconds(httpx.Response(429)) is None


def test_safe_error_redacts_configured_keys(monkeypatch):
    monkeypatch.setattr(common.settings, "airnow_api_key", "AIRNOW-SECRET-1234")
    monkeypatch.setattr(
        common.settings, "nws_user_agent", "SmokeSense (someone@lab.test)"
    )
    exc = RuntimeError(
        "HTTP 401 for API_KEY=AIRNOW-SECRET-1234 from SmokeSense (someone@lab.test)"
    )
    message = common.safe_error(exc)
    assert "AIRNOW-SECRET-1234" not in message and "someone@lab.test" not in message
    assert message.startswith("RuntimeError: HTTP 401")


def test_failed_job_is_recorded_logged_without_keys_and_does_not_raise(
    monkeypatch, live_db, caplog
):
    monkeypatch.setattr(common.settings, "firms_map_key", "FIRMS-SECRET-5678")
    caplog.set_level(logging.DEBUG)

    def boom(session, run_id, now):
        raise RuntimeError("FIRMS said no to key FIRMS-SECRET-5678")

    result = run_job("firms", boom, session_factory=live_db, now=NOW)

    assert result["status"] == "failed"
    assert "FIRMS-SECRET-5678" not in caplog.text
    assert "FIRMS-SECRET-5678" not in result["error"]
    with live_db() as s:
        run = s.execute(
            text("select status, error, finished_at from ingestion_runs")
        ).one()
    assert run.status == "failed" and run.finished_at is not None
    assert "FIRMS-SECRET-5678" not in run.error


def test_db_error_recording_the_outcome_is_logged_not_raised(
    monkeypatch, live_db, caplog
):
    """The final commit fails (DB gone mid-run): rolled back, closed, reported as failed."""
    from sqlalchemy.exc import OperationalError

    monkeypatch.setattr(common.settings, "firms_map_key", "FIRMS-SECRET-9999")
    caplog.set_level(logging.DEBUG)
    calls = {"commit": 0, "rollback": 0, "close": 0}

    def factory():
        session = live_db()
        real_commit, real_rollback, real_close = (
            session.commit,
            session.rollback,
            session.close,
        )

        def commit():
            calls["commit"] += 1
            if calls["commit"] == 3:  # open run, job, then the outcome
                raise OperationalError(
                    "UPDATE ingestion_runs", {}, Exception("FIRMS-SECRET-9999 gone")
                )
            real_commit()

        def rollback():
            calls["rollback"] += 1
            real_rollback()

        def close():
            calls["close"] += 1
            real_close()

        session.commit, session.rollback, session.close = commit, rollback, close
        return session

    result = run_job(
        "firms", lambda s, r, n: JobResult(rows_fetched=1), session_factory=factory
    )

    assert set(result) == {"source", "status", "error"}
    assert result["source"] == "firms" and result["status"] == "failed"
    assert result["error"].startswith("OperationalError")
    assert "FIRMS-SECRET-9999" not in result["error"]
    assert calls == {"commit": 3, "rollback": 1, "close": 1}
    assert "could not record the outcome of run" in caplog.text
    assert "FIRMS-SECRET-9999" not in caplog.text
    with live_db() as s:  # the run stays 'running' until retention closes it
        assert s.scalar(text("select status from ingestion_runs")) == "running"


def test_partial_job_is_recorded_as_partial(live_db):
    def some_failed(session, run_id, now):
        return JobResult(
            rows_fetched=3, rows_written=2, watermark=NOW, errors=["KXYZ: HTTP 500"]
        )

    result = run_job("nws_obs", some_failed, session_factory=live_db, now=NOW)
    assert result["status"] == "partial" and result["error"] == "KXYZ: HTTP 500"


def test_lookback_backfills_the_window_then_overlaps_from_last_success(live_db):
    with live_db() as s:
        assert lookback_start(s, "airdata", NOW, overlap_hours=3) == NOW - timedelta(
            hours=72
        )

    run_job("airdata", lambda s, r, n: JobResult(), session_factory=live_db, now=NOW)
    with live_db() as s:
        last = s.scalar(text("select started_at from ingestion_runs"))
        later = last + timedelta(hours=1)
        assert lookback_start(s, "airdata", later, overlap_hours=3) == last - timedelta(
            hours=3
        )
        # Another source's runs do not count.
        assert lookback_start(s, "firms", later, overlap_hours=3) == later - timedelta(
            hours=72
        )
