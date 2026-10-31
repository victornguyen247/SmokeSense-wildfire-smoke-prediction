"""Live FIRMS job: VIIRS SNPP NRT detections over California + 200 km.

SNPP NRT only, the sensor the model was trained on (decisions #11, #13): no NOAA-20,
NOAA-21 or MODIS. Rows are normalized by the batch connector's normalize_firms_row,
so a live row is built exactly like a historical one (product NRT instead of SP).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from ingestion.batch.firms_extent import FIRMS_MARGIN_KM, expand_bbox_km
from ingestion.connectors.firms import fetch_firms_rows, normalize_firms_row
from ingestion.live.common import (
    CA_BBOX,
    DEFAULT_WINDOW_HOURS,
    JobResult,
    bbox_str,
    client_scope,
    env_int,
    lookback_start,
    run_job,
    utc_now,
)
from ingestion.live.store import fire_key, insert_fire_detections

SOURCE = "firms"  # ingestion_runs.source
PRODUCT = "VIIRS_SNPP_NRT"
SATELLITE = "VIIRS_SNPP"

# The FIRMS area API serves 1..5 days per request, counted back from today (UTC).
MAX_DAY_RANGE = 5

# FIRMS: 5,000 transactions per 10 minutes (docs/data-sources.md); one request per run.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def firms_bbox() -> str:
    """California + FIRMS_MARGIN_KM (200 km): fires that can feed a California point."""
    return expand_bbox_km(bbox_str(CA_BBOX), FIRMS_MARGIN_KM)


def day_range_for(start: datetime, now: datetime) -> int:
    """FIRMS day_range covering [start, now]: whole UTC days, today included."""
    days = (now.date() - start.date()).days + 1
    return max(1, min(MAX_DAY_RANGE, math.ceil(days)))


def fetch_records(
    client: httpx.Client,
    start: datetime,
    now: datetime,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> tuple[int, list[dict]]:
    """(rows returned by FIRMS, normalized SNPP rows inside the window, deduped)."""
    if not settings.firms_map_key:
        raise RuntimeError("FIRMS_MAP_KEY is not set")

    rows = fetch_firms_rows(
        map_key=settings.firms_map_key,
        source=PRODUCT,
        bbox=firms_bbox(),
        day_range=day_range_for(start, now),
        client=client,
    )

    earliest = now - timedelta(hours=window_hours)
    records: dict[tuple, dict] = {}
    for row in rows:
        record = normalize_firms_row(row, source=PRODUCT, ingested_at=now)
        # The product is SNPP-only; anything else would be a FIRMS-side surprise.
        if record["satellite"] != SATELLITE or record["confidence_level"] is None:
            continue
        if not earliest <= record["detected_at"] <= now:
            continue
        records.setdefault(fire_key(record), record)
    return len(rows), list(records.values())


def job(client: httpx.Client | None = None):
    def _job(session: Session, run_id: str, now: datetime) -> JobResult:
        start = lookback_start(
            session, SOURCE, now, env_int("LIVE_FIRMS_OVERLAP_HOURS", 24, minimum=0)
        )
        with client_scope(client, RETRY_STATUSES) as http:
            fetched, records = fetch_records(http, start, now)
        result = JobResult(rows_fetched=fetched)
        result.rows_written = insert_fire_detections(session, records, run_id)
        for record in records:
            result.see(record["detected_at"])
        return result

    return _job


def run(
    *,
    session_factory=None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict:
    """Run the FIRMS job once. Never raises; the outcome is in the returned dict."""
    if session_factory is None:
        from ingestion.db import SessionLocal as session_factory
    return run_job(
        SOURCE, job(client), session_factory=session_factory, now=now or utc_now()
    )
