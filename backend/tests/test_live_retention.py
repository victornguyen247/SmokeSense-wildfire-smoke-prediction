"""DATA-06 retention: the ~72 h window applies to live rows only; historical rows survive."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from ingestion.live import __main__ as cli
from ingestion.live import retention

NOW = datetime(2026, 10, 24, 9, 15, tzinfo=timezone.utc)
OLD = NOW - timedelta(hours=80)  # outside the 72 h window
NEW = NOW - timedelta(hours=10)
# A DATA-03 pilot-event timestamp (PE-002 Dixie), long outside any live window.
PILOT = datetime(2021, 8, 6, 16, 0, tzinfo=timezone.utc)


def seed(live_db) -> None:
    """Live and historical rows, old and new, in all three tables."""
    with live_db() as s:
        s.execute(
            text("""
            insert into monitors (id, source, external_id, name, geom, first_seen_at)
            values ('m1', 'airnow', 'airnow:x', 'Test', ST_GeogFromText('POINT(-121 38)'), now())
        """)
        )
        for i, (ts, run_id) in enumerate(
            [
                (OLD, "run-1"),
                (NEW, "run-1"),
                (PILOT, None),
                (OLD - timedelta(hours=1), None),
            ]
        ):
            params = {"ts": ts, "run": run_id, "id": f"f{i}", "ext": f"firms:{i}"}
            s.execute(
                text(
                    "insert into observations (monitor_id, valid_at, received_at, pm25, "
                    "correction, ingestion_run_id) "
                    "values ('m1', :ts, :ts, 10, 'regulatory', :run)"
                ),
                params,
            )
            s.execute(
                text(
                    "insert into fire_detections (id, external_id, satellite, product, geom, "
                    "detected_at, received_at, confidence_raw, confidence_level, ingestion_run_id) "
                    "values (:id, :ext, 'VIIRS_SNPP', 'NRT', ST_GeogFromText('POINT(-121 38)'), "
                    ":ts, :ts, 'n', 'nominal', :run)"
                ),
                params,
            )
            s.execute(
                text(
                    "insert into weather_observations (station_id, valid_at, received_at, geom, "
                    "ingestion_run_id) "
                    "values ('KSAC', :ts, :ts, ST_GeogFromText('POINT(-121 38)'), :run)"
                ),
                params,
            )
        s.commit()


def counts(live_db) -> dict[str, tuple[int, int]]:
    """{table: (live rows, historical rows)}."""
    out = {}
    with live_db() as s:
        for table, _ in retention.LIVE_TABLES:
            out[table] = tuple(
                s.execute(
                    text(
                        f"select count(*) filter (where ingestion_run_id is not null), "
                        f"count(*) filter (where ingestion_run_id is null) from {table}"
                    )
                ).one()
            )
    return out


@pytest.fixture(autouse=True)
def default_env(monkeypatch):
    """Retention's own defaults: no LIVE_RETENTION_DELETE, 72 h window."""
    monkeypatch.delenv("LIVE_RETENTION_DELETE", raising=False)
    monkeypatch.delenv("LIVE_RETENTION_HOURS", raising=False)


def assert_window_enforced_on_live_rows_only(live_db) -> None:
    # One old live row gone per table; the new live row and both historical rows
    # (the 2021 pilot-event row and one older than the window) survive.
    assert counts(live_db) == {t: (1, 2) for t, _ in retention.LIVE_TABLES}
    with live_db() as s:
        oldest_live = s.scalar(
            text(
                "select min(valid_at) from observations where ingestion_run_id is not null"
            )
        )
        pilot = s.scalar(
            text("select count(*) from observations where valid_at = :t"), {"t": PILOT}
        )
    assert oldest_live >= NOW - timedelta(hours=72)
    assert pilot == 1


def test_default_enforces_the_window_on_live_rows_only(live_db, caplog):
    seed(live_db)
    caplog.set_level(logging.INFO, logger="ingestion.live")

    result = retention.run(session_factory=live_db, now=NOW)

    assert result["status"] == "success" and result["dry_run"] is False
    assert {t: result["rows"][t] for t, _ in retention.LIVE_TABLES} == {
        "observations": 1,
        "fire_detections": 1,
        "weather_observations": 1,
    }
    assert_window_enforced_on_live_rows_only(live_db)
    logged = [
        r for r in caplog.records if r.getMessage().startswith("retention: deleted")
    ]
    assert logged and logged[0].levelno == logging.INFO
    assert "'observations': 1" in logged[0].getMessage()


@pytest.mark.parametrize("value", ["0", "false", "off"])
def test_dry_run_is_opt_in_and_deletes_nothing(live_db, monkeypatch, value):
    monkeypatch.setenv("LIVE_RETENTION_DELETE", value)
    seed(live_db)

    result = retention.run(session_factory=live_db, now=NOW)

    assert result["status"] == "success" and result["dry_run"] is True
    assert {t: result["rows"][t] for t, _ in retention.LIVE_TABLES} == {
        "observations": 1,
        "fire_detections": 1,
        "weather_observations": 1,
    }
    assert counts(live_db) == {t: (2, 2) for t, _ in retention.LIVE_TABLES}


def test_explicit_delete_enforces_the_window_on_live_rows_only(live_db, monkeypatch):
    monkeypatch.setenv("LIVE_RETENTION_DELETE", "0")  # the argument wins over the env
    seed(live_db)

    result = retention.run(session_factory=live_db, now=NOW, delete=True)

    assert result["dry_run"] is False
    assert_window_enforced_on_live_rows_only(live_db)


@pytest.mark.parametrize(
    ("args", "env", "delete"),
    [
        ([], None, None),  # default: LIVE_RETENTION_DELETE decides (unset = delete)
        (["--dry-run"], None, False),
        (["--delete"], "0", True),  # the old flag still works, and wins over the env
    ],
)
def test_cli_retention_flags(monkeypatch, args, env, delete):
    if env is not None:
        monkeypatch.setenv("LIVE_RETENTION_DELETE", env)
    seen = {}

    def fake_run(*, delete=None):
        seen["delete"] = delete
        return {"status": "success"}

    monkeypatch.setattr(retention, "run", fake_run)
    assert cli.main(["retention", *args]) == 0
    assert seen == {"delete": delete}


def test_cli_rejects_dry_run_with_delete():
    with pytest.raises(SystemExit):
        cli.main(["retention", "--dry-run", "--delete"])


def test_env_one_deletes_and_window_is_configurable(live_db, monkeypatch):
    monkeypatch.setenv("LIVE_RETENTION_DELETE", "1")
    monkeypatch.setenv("LIVE_RETENTION_HOURS", "5")
    seed(live_db)

    retention.run(session_factory=live_db, now=NOW)

    # With a 5 h window the 10 h-old live row goes too; historical rows still stay.
    assert counts(live_db) == {t: (0, 2) for t, _ in retention.LIVE_TABLES}


def test_old_ingestion_runs_are_pruned_and_partitions_kept_ahead(live_db):
    with live_db() as s:
        s.execute(
            text("""
            insert into ingestion_runs (id, source, started_at, finished_at, status)
            values ('old', 'firms', :old, :old, 'success'), ('new', 'firms', :new, :new, 'success')
        """),
            {"old": NOW - timedelta(days=91), "new": NOW - timedelta(days=1)},
        )
        s.commit()

    result = retention.run(session_factory=live_db, now=NOW, delete=True)

    assert result["rows"]["ingestion_runs"] == 1
    assert set(result["partitions"].values()) == {"ok"}
    with live_db() as s:
        assert s.scalars(text("select id from ingestion_runs")).all() == ["new"]
        ahead = (NOW + timedelta(days=3)).strftime("%Y%m%d")
        assert s.scalar(
            text(f"select to_regclass('observations_p{ahead}') is not null")
        )


def seed_runs(live_db) -> None:
    with live_db() as s:
        s.execute(
            text("""
            insert into ingestion_runs (id, source, started_at, finished_at, status)
            values ('orphan', 'nws_obs', :orphan, null, 'running'),
                   ('old-orphan', 'firms', :ancient, null, 'running'),
                   ('busy', 'airdata', :busy, null, 'running'),
                   ('done', 'firms', :orphan, :orphan, 'success')
        """),
            {
                "orphan": NOW - timedelta(hours=7),  # worker died 7 h ago
                "ancient": NOW - timedelta(days=95),  # orphaned long ago
                "busy": NOW - timedelta(minutes=20),  # genuinely still running
            },
        )
        s.commit()


def runs(live_db) -> dict[str, tuple]:
    with live_db() as s:
        return {
            r.id: (r.status, r.error, r.finished_at is not None)
            for r in s.execute(
                text("select id, status, error, finished_at from ingestion_runs")
            )
        }


def test_orphaned_running_runs_are_closed_then_pruned(live_db):
    seed_runs(live_db)

    result = retention.run(session_factory=live_db, now=NOW)  # the default deletes

    assert result["abandoned_runs"] == 2
    assert result["rows"]["ingestion_runs"] == 1  # the 95-day-old orphan
    assert runs(live_db) == {
        "orphan": ("failed", "abandoned (worker stopped)", True),
        "busy": ("running", None, False),
        "done": ("success", None, True),
    }


def test_dry_run_counts_orphans_without_touching_them(live_db, monkeypatch):
    monkeypatch.setenv("LIVE_RETENTION_DELETE", "0")
    seed_runs(live_db)
    before = runs(live_db)

    result = retention.run(session_factory=live_db, now=NOW)

    assert (result["abandoned_runs"], result["rows"]["ingestion_runs"]) == (2, 1)
    assert runs(live_db) == before
