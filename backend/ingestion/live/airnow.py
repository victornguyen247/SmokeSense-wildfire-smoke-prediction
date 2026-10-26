"""Live AirNow job: hourly regulatory PM2.5 at California monitors.

Rows are normalized by the batch connector's normalize_airnow_row, exactly as for
training: pm25 is RawConcentration, AQS codes are cut to 9 characters, per-site time
offsets are applied (airnow_time_offsets.py, incl. Red Bluff), -999 and anything
below -5 are dropped and [-5, 0) is clamped to 0. Only permanent monitors
(monitorType 0, set by the connector) in California scope (in_california_scope,
decision #17) are kept.

Each run re-fetches LIVE_AIRNOW_OVERLAP_HOURS before the last successful run, so
late revisions update the stored value.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.scope import in_california_scope
from ingestion.connectors.airnow import fetch_airnow_rows, normalize_airnow_row
from ingestion.connectors.airnow_time_offsets import max_abs_shift_hours
from ingestion.live.common import (
    CA_BBOX,
    JobResult,
    bbox_str,
    client_scope,
    env_int,
    floor_hour,
    lookback_start,
    run_job,
    utc_now,
)
from ingestion.live.store import upsert_observations

SOURCE = "airdata"  # ingestion_runs.source for AirNow (/meta reports it as "airnow")

# AirNow allows 500 requests per hour and a 429 means "no data until the next hour"
# (docs/data-sources.md), so only server errors are retried; a 429 waits for the
# next scheduled run. A run makes one request (more only if the record cap bisects).
RETRY_STATUSES = frozenset({500, 502, 503, 504})


def fetch_records(
    client: httpx.Client, start: datetime, now: datetime
) -> tuple[int, list[dict]]:
    """(rows returned by AirNow, normalized California rows with valid_at in [start, now])."""
    if not settings.airnow_api_key:
        raise RuntimeError("AIRNOW_API_KEY is not set")

    first = floor_hour(start)
    last = floor_hour(now)
    # Pad the request by the largest time correction, as the batch does, so a
    # shifted site still supplies the window's first hour.
    request_start = first - timedelta(hours=max_abs_shift_hours())

    rows = fetch_airnow_rows(
        settings.airnow_api_key,
        bbox=bbox_str(CA_BBOX),
        start_date=request_start.date().isoformat(),
        start_hour=f"{request_start.hour:02d}",
        end_date=last.date().isoformat(),
        end_hour=f"{last.hour:02d}",
        client=client,
    )

    records: dict[tuple, dict] = {}
    for row in rows:
        record = normalize_airnow_row(row, ingested_at=now)
        if record is None:
            continue
        if not in_california_scope(record["source_metadata"]["station_id"]):
            continue
        valid_at = record["observation"]["valid_at"]
        if not first <= valid_at <= last:
            continue
        records.setdefault((record["monitor"]["external_id"], valid_at), record)
    return len(rows), list(records.values())


def job(client: httpx.Client | None = None):
    def _job(session: Session, run_id: str, now: datetime) -> JobResult:
        start = lookback_start(
            session, SOURCE, now, env_int("LIVE_AIRNOW_OVERLAP_HOURS", 3, minimum=0)
        )
        with client_scope(client, RETRY_STATUSES) as http:
            fetched, records = fetch_records(http, start, now)
        result = JobResult(rows_fetched=fetched)
        result.rows_written = upsert_observations(session, records, run_id)
        for record in records:
            result.see(record["observation"]["valid_at"])
        return result

    return _job


def run(
    *,
    session_factory=None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict:
    """Run the AirNow job once. Never raises; the outcome is in the returned dict."""
    if session_factory is None:
        from ingestion.db import SessionLocal as session_factory
    return run_job(
        SOURCE, job(client), session_factory=session_factory, now=now or utc_now()
    )
