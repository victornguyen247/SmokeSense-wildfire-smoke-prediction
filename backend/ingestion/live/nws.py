"""Live NWS job: station observations at the stations the model was trained on.

The stations are the NCEI training stations (connectors/nws_stations.py, 109 of 114
have an NWS feed under the same ICAO id). Every METAR report time is stored as is;
the GEO-03 feature builder applies the "latest report within 3 h" rule, as training
did. Fields are decoded by connectors/nws.py to the NCEI units and rules.

Stations are fetched one at a time, spaced by LIVE_NWS_REQUEST_SPACING_S, and each
station's rows are committed before the next, so memory stays flat and one failing
station only makes the run "partial".
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from ingestion.connectors.nws import (
    fetch_station_observations,
    normalize_nws_observation,
    nws_headers,
)
from ingestion.connectors.nws_stations import NWS_STATIONS
from ingestion.live.common import (
    JobResult,
    client_scope,
    env_float,
    env_int,
    lookback_start,
    run_job,
    safe_error,
    utc_now,
)
from ingestion.live.store import upsert_weather

SOURCE = "nws_obs"  # ingestion_runs.source

# NWS publishes no limit; an over-limit error "may be retried after ~5 seconds"
# (docs/data-sources.md), so 429 is retried with backoff along with server errors.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def user_agent() -> str:
    ua = (settings.nws_user_agent or "").strip()
    if "@" not in ua or "example.com" in ua.lower():
        raise RuntimeError(
            "NWS_USER_AGENT must name the app and a real contact address"
        )
    return ua


def station_records(
    client: httpx.Client, station: str, start: datetime, now: datetime, headers: dict
) -> tuple[int, list[dict]]:
    """(observations returned, normalized METAR records deduped on valid_at) for one station."""
    features = fetch_station_observations(client, station, start, now, headers=headers)
    records: dict[datetime, dict] = {}
    for feature in features:
        record = normalize_nws_observation(feature, station_id=station, ingested_at=now)
        if record is not None:
            records.setdefault(record["valid_at"], record)
    return len(features), list(records.values())


def job(
    client: httpx.Client | None = None,
    stations: Sequence[str] = NWS_STATIONS,
    sleep: Callable[[float], None] = time.sleep,
):
    def _job(session: Session, run_id: str, now: datetime) -> JobResult:
        headers = nws_headers(user_agent())
        start = lookback_start(
            session, SOURCE, now, env_int("LIVE_NWS_OVERLAP_HOURS", 3)
        )
        spacing = env_float("LIVE_NWS_REQUEST_SPACING_S", 0.5)
        result = JobResult()
        failed = 0
        with client_scope(client, RETRY_STATUSES) as http:
            for i, station in enumerate(stations):
                if i and spacing > 0:
                    sleep(spacing)
                try:
                    fetched, records = station_records(
                        http, station, start, now, headers
                    )
                    written = upsert_weather(session, records, run_id)
                    session.commit()
                except Exception as exc:
                    session.rollback()
                    failed += 1
                    result.errors.append(f"{station}: {safe_error(exc, 160)}")
                    continue
                result.rows_fetched += fetched
                result.rows_written += written
                for record in records:
                    result.see(record["valid_at"])
        result.failed = bool(stations) and failed == len(stations)
        return result

    return _job


def run(
    *,
    session_factory=None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    stations: Sequence[str] = NWS_STATIONS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Run the NWS job once. Never raises; the outcome is in the returned dict."""
    if session_factory is None:
        from ingestion.db import SessionLocal as session_factory
    return run_job(
        SOURCE,
        job(client, stations, sleep),
        session_factory=session_factory,
        now=now or utc_now(),
    )
