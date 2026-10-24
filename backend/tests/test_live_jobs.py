"""DATA-06 jobs as a whole: independent schedules, failure isolation, light imports."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import text

from ingestion.live import __main__ as cli
from ingestion.live import airnow, firms, nws, purpleair
from ingestion.live.schedule import beat_schedule

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures/live"
NOW = datetime(2026, 10, 24, 2, 40, tzinfo=timezone.utc)


def test_each_source_is_its_own_beat_entry():
    schedule = beat_schedule()
    assert {e["task"] for e in schedule.values()} == {
        "ingestion.live.firms",
        "ingestion.live.airnow",
        "ingestion.live.nws",
        "ingestion.live.purpleair",
        "ingestion.live.retention",
    }
    for entry in schedule.values():
        assert "link" not in entry.get("options", {})  # no chaining between sources
        assert entry["options"]["expires"] > 0


def test_cadences_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LIVE_FIRMS_EVERY_MINUTES", "10")
    monkeypatch.setenv("LIVE_AIRNOW_MINUTE", "40")
    schedule = beat_schedule()
    assert schedule["live-firms"]["schedule"].total_seconds() == 600
    assert schedule["live-airnow"]["schedule"].minute == {40}


def test_tasks_are_registered():
    from ingestion.tasks import celery_app

    for entry in beat_schedule().values():
        assert entry["task"] in celery_app.tasks


def test_a_failing_source_does_not_block_the_others(monkeypatch, live_db):
    """AirNow is down (HTTP 503 every time); FIRMS, NWS and PurpleAir still land."""
    monkeypatch.setattr(firms.settings, "firms_map_key", "k-firms-0001")
    monkeypatch.setattr(airnow.settings, "airnow_api_key", "k-airnow-0001")
    monkeypatch.setattr(purpleair.settings, "purpleair_api_key", "k-purple-0001")
    monkeypatch.setattr(
        nws.settings, "nws_user_agent", "SmokeSense-test (ops@smokesense.test)"
    )
    pages = json.loads((FIXTURES / "nws_krdd_observations.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "firms" in host:
            return httpx.Response(
                200, text=(FIXTURES / "firms_viirs_snpp_nrt.csv").read_text()
            )
        if "airnow" in host:
            return httpx.Response(503, text="maintenance")
        if "purpleair" in host:
            return httpx.Response(
                200, json=json.loads((FIXTURES / "purpleair_sensors.json").read_text())
            )
        return httpx.Response(
            200, json=pages["page2"] if "cursor" in str(request.url) else pages["page1"]
        )

    def client():
        return httpx.Client(transport=httpx.MockTransport(handler))

    results = {
        "airnow": airnow.run(session_factory=live_db, client=client(), now=NOW),
        "firms": firms.run(session_factory=live_db, client=client(), now=NOW),
        "nws": nws.run(
            session_factory=live_db,
            client=client(),
            now=NOW,
            stations=["KRDD"],
            sleep=lambda s: None,
        ),  # fmt: skip
        "purpleair": purpleair.run(session_factory=live_db, client=client(), now=NOW),
    }

    assert results["airnow"]["status"] == "failed"
    assert all(results[s]["status"] == "success" for s in ("firms", "nws", "purpleair"))
    with live_db() as s:
        runs = dict(s.execute(text("select source, status from ingestion_runs")).all())
    assert runs == {"airdata": "failed", "firms": "success", "nws_obs": "success",
                    "purpleair": "success"}  # fmt: skip


def test_ingestion_does_not_load_ml_or_pandas():
    """Tasks may run on a 512 MB host: the worker must not pull in the model stack."""
    code = (
        "import sys, ingestion.tasks, ingestion.live.__main__\n"
        "heavy = [m for m in ('xgboost', 'ml', 'pandas', 'sklearn') if m in sys.modules]\n"
        "print(','.join(heavy))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == ""


def test_smoke_needs_its_env_flag(monkeypatch, capsys):
    monkeypatch.delenv("LIVE_INGEST_SMOKE", raising=False)
    assert cli.main(["smoke"]) == 2
    assert "LIVE_INGEST_SMOKE=1" in capsys.readouterr().out


def test_smoke_prints_counts_only(monkeypatch, capsys):
    monkeypatch.setenv("LIVE_INGEST_SMOKE", "1")
    monkeypatch.setattr(firms.settings, "firms_map_key", "k-firms-SECRET")

    real = httpx.Client
    body = (FIXTURES / "firms_viirs_snpp_nrt.csv").read_text()
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *a, **k: real(
            *a,
            **{
                **k,
                "transport": httpx.MockTransport(
                    lambda r: httpx.Response(200, text=body)
                ),
            },
        ),
    )
    assert cli.main(["smoke", "firms"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("firms: fetched=6 normalized=") and "SECRET" not in out


def test_no_keys_in_logs_on_a_retried_live_run(monkeypatch, live_db, caplog):
    """The AirNow key rides in the query string; retries and errors must not log it."""
    import logging

    from ingestion.live.common import RetryTransport

    key = "AIRNOW-KEY-MUST-NOT-LEAK-777"
    monkeypatch.setattr(airnow.settings, "airnow_api_key", key)
    caplog.set_level(logging.DEBUG)
    replies = iter([httpx.Response(503, text=f"bad gateway for API_KEY={key}")] * 3)
    transport = RetryTransport(
        airnow.RETRY_STATUSES,
        sleep=lambda s: None,
        transport=httpx.MockTransport(lambda r: next(replies)),
    )

    result = airnow.run(
        session_factory=live_db, client=httpx.Client(transport=transport), now=NOW
    )

    assert result["status"] == "failed"
    assert "retry 1/2" in caplog.text  # the retries were logged...
    assert key not in caplog.text  # ...without the key
    assert key not in result["error"]
    with live_db() as s:
        assert key not in s.scalar(text("select error from ingestion_runs"))
