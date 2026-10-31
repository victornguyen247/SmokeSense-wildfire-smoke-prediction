"""DATA-06 jobs as a whole: independent schedules, failure isolation, light imports."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from ingestion.live import __main__ as cli
from ingestion.live import airnow, firms, nws
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


DEFAULT_CADENCES = {
    "firms": 30 * 60,
    "airnow": {25},
    "nws": {5},
    "retention": ({9}, {15}),
}


def cadences(schedule: dict) -> dict:
    retention = schedule["live-retention"]["schedule"]
    return {
        "firms": schedule["live-firms"]["schedule"].total_seconds(),
        "airnow": schedule["live-airnow"]["schedule"].minute,
        "nws": schedule["live-nws"]["schedule"].minute,
        "retention": (retention.hour, retention.minute),
    }


@pytest.mark.parametrize(
    ("name", "value", "problem"),
    [
        ("LIVE_FIRMS_EVERY_MINUTES", "30min", "is not a number"),
        ("LIVE_FIRMS_EVERY_MINUTES", "0", "is below 1"),
        ("LIVE_AIRNOW_MINUTE", "75", "is above 59"),
        ("LIVE_NWS_MINUTE", "five", "is not a number"),
        ("LIVE_RETENTION_HOUR", "24", "is above 23"),
        ("LIVE_RETENTION_MINUTE", "-1", "is below 0"),
    ],
)
def test_a_bad_cadence_falls_back_without_stopping_beat(
    monkeypatch, caplog, name, value, problem
):
    """Logged as an ERROR naming the variable and value; every other entry keeps its value."""
    import logging

    for var in ("LIVE_FIRMS_EVERY_MINUTES", "LIVE_AIRNOW_MINUTE", "LIVE_NWS_MINUTE",
                "LIVE_RETENTION_HOUR", "LIVE_RETENTION_MINUTE"):  # fmt: skip
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(name, value)
    caplog.set_level(logging.ERROR, logger="ingestion.live")

    schedule = beat_schedule()

    assert cadences(schedule) == DEFAULT_CADENCES
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert f"{name}={value!r} {problem}; using the default" in errors[0].getMessage()


def test_a_bad_value_leaves_the_other_sources_alone(monkeypatch):
    monkeypatch.setenv("LIVE_FIRMS_EVERY_MINUTES", "30min")
    monkeypatch.setenv("LIVE_AIRNOW_MINUTE", "40")
    monkeypatch.setenv("LIVE_NWS_MINUTE", "75")
    monkeypatch.setenv("LIVE_RETENTION_HOUR", "3")
    monkeypatch.setenv("LIVE_RETENTION_MINUTE", "0")
    assert cadences(beat_schedule()) == {
        "firms": 30 * 60,  # default
        "airnow": {40},
        "nws": {5},  # default
        "retention": ({3}, {0}),
    }


@pytest.mark.parametrize("value", ["fast", "nan", "inf", "0.5"])
def test_env_float_falls_back_on_bad_values(monkeypatch, caplog, value):
    import logging

    from ingestion.live.common import env_float

    monkeypatch.setenv("LIVE_HTTP_TIMEOUT_S", value)
    caplog.set_level(logging.ERROR, logger="ingestion.live")
    assert env_float("LIVE_HTTP_TIMEOUT_S", 120.0, minimum=1) == 120.0
    assert "LIVE_HTTP_TIMEOUT_S=" in caplog.text and repr(value) in caplog.text


def test_worker_and_beat_import_with_bad_values():
    """ingestion.tasks builds the beat schedule at import; bad values must not break it."""
    import os

    env = {
        **os.environ,
        "LIVE_FIRMS_EVERY_MINUTES": "30min",
        "LIVE_AIRNOW_MINUTE": "75",
        "LIVE_NWS_MINUTE": "0x",
        "LIVE_RETENTION_HOUR": "-3",
        "LIVE_HTTP_ATTEMPTS": "0",
    }
    code = (
        "from ingestion.tasks import celery_app\n"
        "print(sorted(celery_app.conf.beat_schedule))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr[-500:]
    assert "live-firms" in out.stdout and "live-retention" in out.stdout
    assert "LIVE_FIRMS_EVERY_MINUTES='30min' is not a number" in out.stderr


def test_purpleair_has_no_live_job():
    """Team decision 2026-10-26 (#41): no PurpleAir task, beat entry or CLI command."""
    from ingestion.tasks import celery_app

    assert "ingestion.live.purpleair" not in celery_app.tasks
    assert "purpleair" not in cli.JOBS
    assert set(beat_schedule()) == {
        "live-firms",
        "live-airnow",
        "live-nws",
        "live-retention",
    }


def test_tasks_are_registered():
    from ingestion.tasks import celery_app

    for entry in beat_schedule().values():
        assert entry["task"] in celery_app.tasks


def test_a_failing_source_does_not_block_the_others(monkeypatch, live_db):
    """AirNow is down (HTTP 503 every time); FIRMS and NWS still land."""
    monkeypatch.setattr(firms.settings, "firms_map_key", "k-firms-0001")
    monkeypatch.setattr(airnow.settings, "airnow_api_key", "k-airnow-0001")
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
    }

    assert results["airnow"]["status"] == "failed"
    assert all(results[s]["status"] == "success" for s in ("firms", "nws"))
    with live_db() as s:
        runs = dict(s.execute(text("select source, status from ingestion_runs")).all())
    assert runs == {"airdata": "failed", "firms": "success", "nws_obs": "success"}


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


def test_smoke_without_sources_covers_firms_airnow_and_nws(monkeypatch):
    monkeypatch.setenv("LIVE_INGEST_SMOKE", "1")
    seen = []
    monkeypatch.setattr(cli, "smoke", lambda sources: seen.extend(sources) or 0)
    assert cli.main(["smoke"]) == 0
    assert sorted(seen) == ["airnow", "firms", "nws"]
    with pytest.raises(SystemExit):
        cli.main(["smoke", "purpleair"])


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
