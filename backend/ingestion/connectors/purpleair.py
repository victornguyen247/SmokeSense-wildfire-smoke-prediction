"""PurpleAir historical PM2.5 connector.

PurpleAir's low-cost sensors fill in label density where regulatory
monitors are sparse. Raw readings over-report in heavy smoke, so every
reading is EPA (Barkjohn) corrected before it can be used as a label.

The connector:
1. Finds outdoor sensors inside a bounding box that were online during
   the requested window.
2. Pulls each sensor's hourly-averaged history (A/B channels + humidity).
3. Checks A/B channel agreement and applies the Barkjohn correction.
4. Builds monitor + observation records in the same shape as the AirNow
   connector, so the same DB insert path works for both.

It does NOT write to the database yet.

Cost: PurpleAir bills points per field per row. Each sensor-hour here costs
3 fields. Keep bboxes tight, use max_sensors while testing, and contact
PurpleAir before pulling thousands of sensors (docs/data-sources.md §4).
"""

from __future__ import annotations

import math
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx

from ingestion.connectors._common import (
    TIMEOUT,
    get_with_retry,
    load_env,
    require_env,
)
from ingestion.normalize import (
    barkjohn_correct,
    point_wkt,
    purpleair_channel_qa,
    to_float,
)


PURPLEAIR_BASE_URL = "https://api.purpleair.com/v1"

# Sacramento-area development box, matching the FIRMS/AirNow POC.
# Format: west, south, east, north
DEFAULT_BBOX = "-122.5,38.0,-120.5,39.5"

# One day inside PE-002 (Dixie Fire), when PurpleAir coverage was good.
DEFAULT_START_DATE = "2021-08-05"
DEFAULT_END_DATE = "2021-08-05"

# Hourly averages line up with observations.valid_at (start of hour, UTC).
AVERAGE_MINUTES = 60

# PurpleAir caps the time span per history request by averaging period;
# 14 days is the limit for 60-minute averages.
MAX_HISTORY_DAYS = 14

SENSOR_FIELDS = (
    "name",
    "latitude",
    "longitude",
    "altitude",
    "location_type",
    "date_created",
    "last_seen",
)

HISTORY_FIELDS = (
    "pm2.5_cf_1_a",
    "pm2.5_cf_1_b",
    "humidity",
)

FEET_TO_M = 0.3048

# Sensors per run unless PURPLEAIR_MAX_SENSORS says otherwise. Must match
# the purpleair_max_sensors default in app/core/config.py (the batch reads
# that one); a test keeps the two in sync.
DEFAULT_MAX_SENSORS = 5


def _zip_columnar(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """PurpleAir returns {"fields": [...], "data": [[...], ...]}; zip them."""

    fields = payload.get("fields")
    data = payload.get("data")

    if not isinstance(fields, list) or not isinstance(data, list):
        raise RuntimeError(
            "PurpleAir returned an unexpected response shape "
            f"(keys: {sorted(payload)})."
        )

    return [dict(zip(fields, row)) for row in data]


def _check_response(response: httpx.Response, what: str) -> dict[str, Any]:
    """Raise a readable error for non-200s; return the parsed JSON body."""

    if response.status_code != 200:
        hint = ""
        if response.status_code == 403:
            hint = (
                " A 403 with a valid-looking key usually means a WRITE key; "
                "PurpleAir requires a READ key."
            )
        raise RuntimeError(
            f"PurpleAir {what} request failed with HTTP "
            f"{response.status_code}: {response.text[:300]}{hint}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"PurpleAir {what} returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"PurpleAir {what} returned an unexpected response type: "
            f"{type(payload).__name__}"
        )

    return payload


def _day_bounds(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """Inclusive dates -> [start 00:00 UTC, day-after-end 00:00 UTC)."""

    start = datetime.combine(date.fromisoformat(start_date), time(), timezone.utc)
    end = datetime.combine(date.fromisoformat(end_date), time(), timezone.utc)

    if end < start:
        raise ValueError(f"end_date {end_date} is before start_date {start_date}")

    return start, end + timedelta(days=1)


def fetch_purpleair_sensors(
    api_key: str,
    bbox: str = DEFAULT_BBOX,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """List outdoor sensors in bbox that were online during the window."""

    if client is None:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as own:
            return fetch_purpleair_sensors(api_key, bbox, start_date, end_date, own)

    west, south, east, north = (float(part) for part in bbox.split(","))
    window_start, window_end = _day_bounds(start_date, end_date)

    params = {
        "fields": ",".join(SENSOR_FIELDS),
        "location_type": 0,  # outdoor only
        "nwlng": west,
        "nwlat": north,
        "selng": east,
        "selat": south,
        # 0 = include sensors regardless of when they last reported.
        # The default hides anything offline for 7+ days, i.e. most
        # sensors relevant to past fires.
        "max_age": 0,
    }

    response = get_with_retry(
        client,
        f"{PURPLEAIR_BASE_URL}/sensors",
        params=params,
        headers={"X-API-Key": api_key},
    )

    sensors = []

    for sensor in _zip_columnar(_check_response(response, "sensors")):
        if sensor.get("latitude") is None or sensor.get("longitude") is None:
            continue

        created = sensor.get("date_created")
        last_seen = sensor.get("last_seen")

        if created is not None and created >= window_end.timestamp():
            continue
        if last_seen is not None and last_seen < window_start.timestamp():
            continue

        sensors.append(sensor)

    return sensors


def fetch_purpleair_history_rows(
    api_key: str,
    sensor_index: int,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch hourly-averaged history for one sensor, chunked to API limits."""

    if client is None:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as own:
            return fetch_purpleair_history_rows(
                api_key, sensor_index, start_date, end_date, own
            )

    window_start, window_end = _day_bounds(start_date, end_date)
    rows: list[dict[str, Any]] = []

    cursor = window_start
    while cursor < window_end:
        chunk_end = min(cursor + timedelta(days=MAX_HISTORY_DAYS), window_end)

        params = {
            "start_timestamp": int(cursor.timestamp()),
            "end_timestamp": int(chunk_end.timestamp()),
            "average": AVERAGE_MINUTES,
            "fields": ",".join(HISTORY_FIELDS),
        }

        response = get_with_retry(
            client,
            f"{PURPLEAIR_BASE_URL}/sensors/{sensor_index}/history",
            params=params,
            headers={"X-API-Key": api_key},
        )

        chunk = _zip_columnar(_check_response(response, "history"))

        if chunk and "time_stamp" not in chunk[0]:
            raise RuntimeError(
                f"PurpleAir history for sensor {sensor_index} has no time_stamp field."
            )

        rows.extend(chunk)
        cursor = chunk_end

    return rows


def _non_negative(value: object) -> float | None:
    number = to_float(value)
    return number if number is not None and number >= 0 else None


def _utc_from_epoch(value: object) -> datetime | None:
    number = to_float(value)
    if number is None:
        return None
    return datetime.fromtimestamp(int(number), tz=timezone.utc)


def normalize_purpleair_row(
    row: dict[str, Any],
    sensor: dict[str, Any],
    ingested_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Normalize one hourly PurpleAir reading into monitor + observation.

    Returns None when neither channel reported (nothing to store).

    correction is "purpleair_barkjohn" when humidity is available and
    "purpleair_raw" (never label-eligible) when it is not. qa_flag comes
    from A/B channel agreement: "ok", "suspect" (one channel), or "invalid".
    """

    sensor_index = sensor.get("sensor_index")
    if sensor_index is None:
        raise ValueError("PurpleAir sensor record has no sensor_index.")

    valid_at = _utc_from_epoch(row.get("time_stamp"))
    if valid_at is None:
        raise ValueError(f"PurpleAir row for sensor {sensor_index} has no time_stamp.")

    cf1_a = _non_negative(row.get("pm2.5_cf_1_a"))
    cf1_b = _non_negative(row.get("pm2.5_cf_1_b"))

    cf1_mean, qa_flag = purpleair_channel_qa(cf1_a, cf1_b)
    if cf1_mean is None:
        return None

    rh_pct = to_float(row.get("humidity"))
    if rh_pct is not None and not 0 <= rh_pct <= 100:
        rh_pct = None

    if rh_pct is None:
        pm25 = cf1_mean
        correction = "purpleair_raw"
    else:
        pm25 = barkjohn_correct(cf1_mean, rh_pct)
        correction = "purpleair_barkjohn"

    latitude = to_float(sensor.get("latitude"))
    longitude = to_float(sensor.get("longitude"))

    if latitude is None or longitude is None:
        raise ValueError(f"PurpleAir sensor {sensor_index} has no coordinates.")

    altitude_ft = to_float(sensor.get("altitude"))

    if ingested_at is None:
        ingested_at = datetime.now(timezone.utc)

    # Schema: PurpleAir monitors use the raw sensor_index as external_id.
    monitor_external_id = str(sensor_index)

    return {
        "monitor": {
            "source": "purpleair",
            "external_id": monitor_external_id,
            "name": sensor.get("name") or monitor_external_id,
            "location_type": "outdoor",
            "geom_wkt": point_wkt(latitude, longitude),
            "latitude": latitude,
            "longitude": longitude,
            "elevation_m": None
            if altitude_ft is None
            else round(altitude_ft * FEET_TO_M, 1),
            "active": True,
            "first_seen_at": _utc_from_epoch(sensor.get("date_created")) or ingested_at,
            "last_seen_at": _utc_from_epoch(sensor.get("last_seen")) or ingested_at,
        },
        "observation": {
            "monitor_external_id": monitor_external_id,
            "valid_at": valid_at,
            "received_at": ingested_at,
            "ingested_at": ingested_at,
            "pm25": round(pm25, 2),
            "correction": correction,
            "data_status": None,
            "pm25_cf1_a": cf1_a,
            "pm25_cf1_b": cf1_b,
            "rh_pct": rh_pct,
            "qa_flag": qa_flag,
        },
        "source_metadata": {
            "source": "purpleair",
            "sensor_index": sensor_index,
            "sensor_name": sensor.get("name"),
            "average_minutes": AVERAGE_MINUTES,
            "source_timestamp": valid_at,
        },
    }


def nearest_to_bbox_center(
    sensors: list[dict[str, Any]], bbox: str
) -> list[dict[str, Any]]:
    """Sort sensors nearest-first to the bbox center, for max_sensors.

    A ranking heuristic only -- not a distance, and not used for any other
    decision. Squared lat/lon difference, with longitude scaled by
    cos(center latitude) so an east-west degree isn't over-weighted. Ties
    keep sensor_index order so the selection is deterministic.
    """

    west, south, east, north = (float(part) for part in bbox.split(","))
    center_lat = (south + north) / 2
    center_lon = (west + east) / 2
    lon_scale = math.cos(math.radians(center_lat))

    def rank(sensor: dict[str, Any]) -> tuple[float, int]:
        d_lat = sensor["latitude"] - center_lat
        d_lon = (sensor["longitude"] - center_lon) * lon_scale
        return (d_lat * d_lat + d_lon * d_lon, sensor.get("sensor_index", 0))

    return sorted(sensors, key=rank)


def get_purpleair_pm25_records(
    api_key: str,
    bbox: str = DEFAULT_BBOX,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    max_sensors: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch and normalize hourly PurpleAir PM2.5 for all sensors in bbox.

    With max_sensors, only the sensors nearest the bbox center are pulled
    (see nearest_to_bbox_center).

    Rows are de-duplicated on (sensor, valid_at), the observations primary
    key, since adjacent history chunks can share a boundary hour.
    """

    _, window_end = _day_bounds(start_date, end_date)

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        sensors = fetch_purpleair_sensors(api_key, bbox, start_date, end_date, client)

        if max_sensors is not None:
            # The API's order is arbitrary; keep the sensors nearest the
            # bbox center so a cap doesn't drop the ones that matter.
            sensors = nearest_to_bbox_center(sensors, bbox)[:max_sensors]

        ingested_at = datetime.now(timezone.utc)
        records: dict[tuple[str, datetime], dict[str, Any]] = {}

        for sensor in sensors:
            rows = fetch_purpleair_history_rows(
                api_key,
                sensor["sensor_index"],
                start_date,
                end_date,
                client,
            )

            for row in rows:
                record = normalize_purpleair_row(row, sensor, ingested_at)
                if record is None:
                    continue

                valid_at = record["observation"]["valid_at"]
                if valid_at >= window_end:
                    continue

                key = (record["monitor"]["external_id"], valid_at)
                records.setdefault(key, record)

    return sorted(
        records.values(),
        key=lambda r: (r["monitor"]["external_id"], r["observation"]["valid_at"]),
    )


def main() -> None:
    """Run a small manual PurpleAir ingestion smoke test."""

    load_env()

    api_key = require_env(
        "PURPLEAIR_API_KEY",
        how_to_get="Request a READ key at https://develop.purpleair.com/",
    )

    bbox = os.getenv("PURPLEAIR_BBOX", DEFAULT_BBOX)
    start_date = os.getenv("PURPLEAIR_START_DATE", DEFAULT_START_DATE)
    end_date = os.getenv("PURPLEAIR_END_DATE", DEFAULT_END_DATE)

    # Small default so a smoke test cannot burn through the points balance.
    max_sensors = int(os.getenv("PURPLEAIR_MAX_SENSORS", str(DEFAULT_MAX_SENSORS)))

    records = get_purpleair_pm25_records(
        api_key=api_key,
        bbox=bbox,
        start_date=start_date,
        end_date=end_date,
        max_sensors=max_sensors or None,
    )

    corrected = sum(
        r["observation"]["correction"] == "purpleair_barkjohn" for r in records
    )
    ok = sum(r["observation"]["qa_flag"] == "ok" for r in records)

    print(f"PurpleAir PM2.5 records retrieved: {len(records)}")
    print(f"Barkjohn-corrected: {corrected}; qa_flag ok: {ok}")

    for record in records[:3]:
        print(record)


if __name__ == "__main__":
    main()
