"""Live PurpleAir job: EPA-corrected PM2.5 for the map layer only.

PurpleAir is not a model input in v1 (decision #12): nothing here feeds
ml.feature_columns, and the GEO-03 lags read only correction = 'regulatory' rows.

One /v1/sensors call per run returns the latest reading of every outdoor sensor in
the California box seen in the last LIVE_PURPLEAIR_MAX_AGE_S seconds. Each reading
goes through the batch normalize_purpleair_row: A/B channel QA, then the EPA
U.S.-wide correction (Barkjohn, Gantt and Clements 2021, Atmos. Meas. Tech. 14,
4617-4637, https://doi.org/10.5194/amt-14-4617-2021):

    PM2.5 = 0.524 * PA_cf1 - 0.0862 * RH + 5.75

The reading is the sensor's current ~2-minute value, not an hourly average, stored
under the hour it falls in (valid_at = start of that hour); a later run in the same
hour replaces it. That is enough for a map of current conditions; it is not a label.

Cost: PurpleAir bills points per field per sensor returned, so a run costs about
(sensors returned) x (len(FIELDS)) points. Only the fields the map needs are
requested, slow-moving metadata (name, altitude) is not, and max_age drops offline
sensors. LIVE_PURPLEAIR_EVERY_MINUTES (default 120; 0 disables the job) is the cost
knob: ~42.6k points per run on 2026-10-23, so ~0.5M points a day at 120 min.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from ingestion.connectors.purpleair import (
    PURPLEAIR_BASE_URL,
    _check_response,
    _zip_columnar,
    normalize_purpleair_row,
)
from ingestion.live.common import (
    CA_BBOX,
    DEFAULT_WINDOW_HOURS,
    JobResult,
    client_scope,
    env_int,
    floor_hour,
    run_job,
    utc_now,
)
from ingestion.live.store import upsert_observations

SOURCE = "purpleair"  # ingestion_runs.source

# sensor_index is always returned. Every field is billed per sensor.
FIELDS = (
    "latitude",
    "longitude",
    "last_seen",
    "humidity",
    "pm2.5_cf_1_a",
    "pm2.5_cf_1_b",
)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def fetch_records(client: httpx.Client, now: datetime) -> tuple[int, list[dict]]:
    """(sensors returned, normalized readings within the live window)."""
    if not settings.purpleair_api_key:
        raise RuntimeError("PURPLEAIR_API_KEY is not set")

    west, south, east, north = CA_BBOX
    response = client.get(
        f"{PURPLEAIR_BASE_URL}/sensors",
        params={
            "fields": ",".join(FIELDS),
            "location_type": 0,  # outdoor only
            "nwlng": west,
            "nwlat": north,
            "selng": east,
            "selat": south,
            "max_age": env_int("LIVE_PURPLEAIR_MAX_AGE_S", 3600),
        },
        headers={"X-API-Key": settings.purpleair_api_key},
    )
    sensors = _zip_columnar(_check_response(response, "sensors"))

    earliest = now - timedelta(hours=DEFAULT_WINDOW_HOURS)
    records: dict[tuple, dict] = {}
    for sensor in sensors:
        last_seen = sensor.get("last_seen")
        if (
            last_seen is None
            or sensor.get("latitude") is None
            or sensor.get("longitude") is None
        ):
            continue
        hour = floor_hour(datetime.fromtimestamp(int(last_seen), tz=timezone.utc))
        row = {
            "time_stamp": int(hour.timestamp()),
            "pm2.5_cf_1_a": sensor.get("pm2.5_cf_1_a"),
            "pm2.5_cf_1_b": sensor.get("pm2.5_cf_1_b"),
            "humidity": sensor.get("humidity"),
        }
        record = normalize_purpleair_row(row, sensor, ingested_at=now)
        if record is None or not earliest <= record["observation"]["valid_at"] <= now:
            continue
        records.setdefault((record["monitor"]["external_id"], hour), record)
    return len(sensors), list(records.values())


def job(client: httpx.Client | None = None):
    def _job(session: Session, run_id: str, now: datetime) -> JobResult:
        with client_scope(client, RETRY_STATUSES) as http:
            fetched, records = fetch_records(http, now)
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
    """Run the PurpleAir job once. Never raises; the outcome is in the returned dict."""
    if session_factory is None:
        from ingestion.db import SessionLocal as session_factory
    return run_job(
        SOURCE, job(client), session_factory=session_factory, now=now or utc_now()
    )
