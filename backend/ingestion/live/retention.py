"""Live-data retention: keep a rolling window of LIVE rows only.

Deletes rows older than LIVE_RETENTION_HOURS (default 72) from observations,
fire_detections and weather_observations, but only rows a live job wrote
(ingestion_run_id IS NOT NULL, migration 0006). Historical DATA-03 rows, which
smokesense_v1 is built from, have ingestion_run_id NULL and are never deleted,
whatever their timestamp. ingestion_runs rows older than 90 days are pruned
(docs/schema.md).

Dry run by default: it only counts what it would delete. Set LIVE_RETENTION_DELETE=1
(or pass --delete to the CLI) to delete.

It also keeps daily partitions created ahead (create_daily_partitions, migration
0001), so live rows land in their day's partition rather than DEFAULT.

Rows are deleted, not partitions dropped: a daily partition can hold historical
rows too, so dropping it is not safe.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from ingestion.live.common import (
    DEFAULT_WINDOW_HOURS,
    env_flag,
    env_int,
    safe_error,
    utc_now,
)

logger = logging.getLogger("ingestion.live")

# (table, time column) of the tables that hold live rows.
LIVE_TABLES = (
    ("observations", "valid_at"),
    ("fire_detections", "detected_at"),
    ("weather_observations", "valid_at"),
)

INGESTION_RUNS_RETENTION_DAYS = 90

# Days of partitions kept ahead, as in migration 0001's PARTITIONED_TABLES.
PARTITION_DAYS_AHEAD = {
    "observations": 3,
    "fire_detections": 3,
    "weather_observations": 3,
    "weather_forecasts": 8,
}


def run(
    *,
    session_factory=None,
    now: datetime | None = None,
    delete: bool | None = None,
) -> dict:
    """Enforce the live window once. Never raises; returns what was (or would be) deleted."""
    if session_factory is None:
        from ingestion.db import SessionLocal as session_factory
    now = now or utc_now()
    delete = env_flag("LIVE_RETENTION_DELETE") if delete is None else delete
    window_hours = env_int("LIVE_RETENTION_HOURS", DEFAULT_WINDOW_HOURS)
    cutoff = now - timedelta(hours=window_hours)
    runs_cutoff = now - timedelta(days=INGESTION_RUNS_RETENTION_DAYS)

    result = {
        "source": "retention",
        "status": "success",
        "dry_run": not delete,
        "cutoff": cutoff.isoformat(),
        "rows": {},
        "partitions": {},
    }
    session = session_factory()
    try:
        for table, column in LIVE_TABLES:
            where = f"ingestion_run_id IS NOT NULL AND {column} < :cutoff"
            if delete:
                count = session.execute(
                    text(f"DELETE FROM {table} WHERE {where}"), {"cutoff": cutoff}
                ).rowcount
            else:
                count = session.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE {where}"),
                    {"cutoff": cutoff},
                )
            result["rows"][table] = count

        where = "status <> 'running' AND started_at < :cutoff"
        if delete:
            count = session.execute(
                text(f"DELETE FROM ingestion_runs WHERE {where}"),
                {"cutoff": runs_cutoff},
            ).rowcount
        else:
            count = session.scalar(
                text(f"SELECT count(*) FROM ingestion_runs WHERE {where}"),
                {"cutoff": runs_cutoff},
            )
        result["rows"]["ingestion_runs"] = count
        session.commit()

        # From tomorrow on: a day that already has rows in DEFAULT cannot get a partition.
        first = now.date() + timedelta(days=1)
        for table, ahead in PARTITION_DAYS_AHEAD.items():
            try:
                with session.begin_nested():
                    session.execute(
                        text("SELECT create_daily_partitions(:t, :d0, :d1)"),
                        {
                            "t": table,
                            "d0": first,
                            "d1": now.date() + timedelta(days=ahead),
                        },
                    )
                result["partitions"][table] = "ok"
            except Exception as exc:
                result["partitions"][table] = safe_error(exc, 200)
                logger.warning(
                    "retention: partitions for %s: %s", table, safe_error(exc, 200)
                )
        session.commit()
    except Exception as exc:
        session.rollback()
        result["status"] = "failed"
        result["error"] = safe_error(exc)
        logger.error("retention failed: %s", result["error"])
    finally:
        session.close()

    if result["status"] != "failed":
        verb = "deleted" if delete else "would delete (dry run)"
        logger.info(
            "retention: %s %s older than %s", verb, result["rows"], cutoff.isoformat()
        )
    return result
