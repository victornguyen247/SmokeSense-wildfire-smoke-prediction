"""AirNow monitoring-site PM2.5 ingestion connector.

Retrieves hourly PM2.5 observations from AirNow monitoring sites
inside a geographic bounding box.

The connector:
1. Requests monitoring-site observations from AirNow.
2. Normalizes timestamps to UTC.
3. Builds monitor metadata compatible with the SmokeSense schema.
4. Builds observation records compatible with the observations table.

It does not write to PostgreSQL yet.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from ingestion.connectors._common import (
    TIMEOUT,
    load_env,
    require_env,
)
from ingestion.normalize import (
    parse_airnow_timestamp,
    point_wkt,
    stable_external_id,
    to_float,
)


AIRNOW_BASE_URL = "https://www.airnowapi.org/aq"

# Sacramento-area POC bounding box.
#
# Format:
# west, south, east, north
DEFAULT_BBOX = "-122.5,38.0,-120.5,39.5"

# One-hour POC window.
DEFAULT_START_DATE = "2026-09-25"
DEFAULT_START_HOUR = "12"
DEFAULT_END_DATE = "2026-09-25"
DEFAULT_END_HOUR = "13"


# ---------------------------------------------------------------------------
# Request-size limits
# ---------------------------------------------------------------------------
# /aq/data/ has a per-query RECORD cap (not a date cap). Measured live on
# 2026-10-02 with PM25 / all monitor types:
#   * Sacramento box (~400 rows/day): 20 days = 8,275 rows OK, 21 days -> HTTP 400
#   * the failure is loud (HTTP 400 + WebServiceError "exceeds the record
#     query limit ... narrow the date range and/or area"), never a silent
#     truncation
#   * latency is ~1s per day of data; the shared 30s read timeout is hit
#     around 25-30 days even below the record cap
# The cap is row-based, so denser boxes (metro areas) hit it sooner than
# sparse ones. Callers should chunk by date (see split_airnow_range) and
# fetch_airnow_rows additionally bisects a window if the cap is hit anyway.
MAX_CHUNK_DAYS = 7

RECORD_LIMIT_MARKER = "record query limit"

# RawConcentration below this is dropped (this includes the -999 "no
# reading" sentinel); values from here up to 0 are clamped to 0. Decided by
# Vuong. A 48-hour California pull (2026-10-05) had 256 raw negatives other
# than -999, all between -4.8 and -1.0.
RAW_NEGATIVE_FLOOR = -5.0


class AirNowRecordLimitError(RuntimeError):
    """The requested window/area returned more records than AirNow allows."""


def split_airnow_range(
    start_date: str,
    end_date: str,
    max_days: int = MAX_CHUNK_DAYS,
) -> list[tuple[str, str]]:
    """Split an inclusive start/end date range into AirNow-sized chunks.

    Returns (chunk_start_date, chunk_end_date) pairs. Pair each with
    start_hour="00" / end_hour="23" so chunks tile the range exactly with
    no gap and no overlap.

    e.g. split_airnow_range("2026-09-01", "2026-09-10", max_days=7) ->
        [("2026-09-01", "2026-09-07"), ("2026-09-08", "2026-09-10")]
    """
    if max_days < 1:
        raise ValueError("max_days must be at least 1")

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    if end < start:
        raise ValueError(f"end_date {end_date} is before start_date {start_date}")

    chunks: list[tuple[str, str]] = []
    cursor = start

    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        chunks.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)

    return chunks


def _request_airnow_rows(
    api_key: str,
    bbox: str,
    start: datetime,
    end: datetime,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Make exactly one /aq/data/ request for an inclusive hourly window."""

    # The monitoring-site endpoint accepts a geographic bounding box and
    # hourly date range. The historical/state endpoint is a different API
    # intended for reporting-area AQI history.
    url = f"{AIRNOW_BASE_URL}/data/"

    params = {
        "format": "application/json",
        "BBOX": bbox,
        "startDate": start.strftime("%Y-%m-%dT%H"),
        "endDate": end.strftime("%Y-%m-%dT%H"),
        "parameters": "PM25",
        "dataType": "C",
        "monitorType": 0,
        "verbose": 1,
        "includerawconcentrations": 1,
        "API_KEY": api_key,
    }

    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = client.get(url, params=params)

    if verbose:
        print("HTTP status:", response.status_code)
        print("Response preview:")
        print(response.text[:3000])

    if response.status_code != 200:
        if RECORD_LIMIT_MARKER in response.text.lower():
            raise AirNowRecordLimitError(
                f"AirNow record limit exceeded for "
                f"{params['startDate']}..{params['endDate']}: "
                f"{response.text[:300]}"
            )
        raise RuntimeError(
            f"AirNow request failed with HTTP "
            f"{response.status_code}: {response.text[:500]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("AirNow returned invalid JSON.") from exc

    if isinstance(payload, dict) and "WebServiceError" in payload:
        messages = "; ".join(
            error.get("Message", "")
            for error in payload.get("WebServiceError", [])
        )
        if RECORD_LIMIT_MARKER in messages.lower():
            raise AirNowRecordLimitError(
                f"AirNow record limit exceeded for "
                f"{params['startDate']}..{params['endDate']}: {messages}"
            )
        raise RuntimeError(f"AirNow returned an API error: {messages}")

    if not isinstance(payload, list):
        raise RuntimeError(
            f"AirNow returned an unexpected response type: {type(payload).__name__}"
        )

    return payload


def _fetch_window(
    api_key: str,
    bbox: str,
    start: datetime,
    end: datetime,
    verbose: bool,
) -> list[dict[str, Any]]:
    """Fetch an inclusive hourly window, bisecting it if AirNow's record cap is hit."""

    try:
        return _request_airnow_rows(api_key, bbox, start, end, verbose)
    except AirNowRecordLimitError:
        hours = int((end - start).total_seconds() // 3600) + 1

        if hours <= 1:
            # Nothing left to split: the area alone is too dense.
            raise

        # Halves are [start, mid] and [mid + 1h, end]: contiguous, no overlap.
        mid = start + timedelta(hours=hours // 2 - 1)
        first = _fetch_window(api_key, bbox, start, mid, verbose)
        second = _fetch_window(api_key, bbox, mid + timedelta(hours=1), end, verbose)
        return first + second


def fetch_airnow_rows(
    api_key: str,
    bbox: str = DEFAULT_BBOX,
    start_date: str = DEFAULT_START_DATE,
    start_hour: str = DEFAULT_START_HOUR,
    end_date: str = DEFAULT_END_DATE,
    end_hour: str = DEFAULT_END_HOUR,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Fetch AirNow monitoring-site PM2.5 rows for an inclusive hourly window.

    If AirNow rejects the window for exceeding its per-query record cap,
    the window is split in half (recursively) and the results are joined,
    so a too-large request degrades into more requests rather than a
    failure. Prefer chunking up front with split_airnow_range() for long
    ranges -- it avoids the wasted failed request and keeps each call
    well inside the client read timeout.

    Raises AirNowRecordLimitError only if a single hour is over the cap.
    """

    start = datetime.strptime(
        f"{start_date}T{start_hour.zfill(2)}", "%Y-%m-%dT%H"
    )
    end = datetime.strptime(
        f"{end_date}T{end_hour.zfill(2)}", "%Y-%m-%dT%H"
    )

    if end < start:
        raise ValueError(
            f"AirNow window end {end_date}T{end_hour} is before "
            f"start {start_date}T{start_hour}"
        )

    return _fetch_window(api_key, bbox, start, end, verbose)


def normalize_airnow_row(
    row: dict[str, Any],
    ingested_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Normalize one AirNow monitoring-site PM2.5 observation.

    pm25 is RawConcentration, the 1-hour average. Returns None for rows to
    skip: non-PM2.5 parameters, the -999 "no reading" sentinel, and any
    value below RAW_NEGATIVE_FLOOR. Values from the floor up to 0 are
    clamped to 0.
    """

    parameter = str(
        row.get("Parameter")
        or row.get("parameterName")
        or ""
    ).strip().upper()

    # AirNow may represent PM2.5 as PM2.5 or PM25 depending
    # on the output format.
    if parameter not in {"PM2.5", "PM25"}:
        return None

    # ---------------------------------------------------------
    # Monitor identity
    # ---------------------------------------------------------

    station_id = str(
        row.get("StationID")
        or row.get("AQSID")
        or row.get("FullAQSCode")
        or row.get("IntlAQSCode")
        or row.get("FullAQSId")
        or row.get("FullAQSID")
        or row.get("SiteID")
        or ""
    ).strip()

    site_name = str(
        row.get("SiteName")
        or row.get("site_name")
        or row.get("siteName")
        or ""
    ).strip()

    agency_name = str(
        row.get("AgencyName")
        or row.get("Agency")
        or row.get("site_agency")
        or row.get("reportingAgency")
        or ""
    ).strip()

    if not station_id:
        # Do not create a fake station ID from the observation
        # timestamp. We want the source station identity preserved.
        raise ValueError(
            f"AirNow PM2.5 record for {site_name or 'unknown site'} "
            "has no station identifier."
        )

    monitor_external_id = stable_external_id(
        "airnow",
        station_id,
    )

    # ---------------------------------------------------------
    # Location
    # ---------------------------------------------------------

    latitude = to_float(
        row.get("Latitude")
        or row.get("latitude")
    )

    longitude = to_float(
        row.get("Longitude")
        or row.get("longitude")
    )

    elevation_m = to_float(
        row.get("Elevation")
        or row.get("elevation")
    )

    geom_wkt = None

    if latitude is not None and longitude is not None:
        geom_wkt = point_wkt(
            latitude,
            longitude,
        )

    # ---------------------------------------------------------
    # Observation timestamp
    # ---------------------------------------------------------

    date_observed = (
        row.get("DateObserved")
        or row.get("dateObserved")
    )

    hour_observed = (
        row.get("HourObserved")
        or row.get("hourObserved")
    )

    timezone_name = (
        row.get("LocalTimeZone")
        or row.get("localTimeZone")
        or ""
    )

    utc_timestamp = row.get("UTC") or row.get("time")
    if utc_timestamp and not date_observed:
        timestamp_text = str(utc_timestamp).strip().replace("Z", "+00:00")
        valid_at = datetime.fromisoformat(timestamp_text)
        if valid_at.tzinfo is None:
            valid_at = valid_at.replace(tzinfo=timezone.utc)
        else:
            valid_at = valid_at.astimezone(timezone.utc)
    else:
        valid_at = parse_airnow_timestamp(
            date_observed,
            hour_observed,
            timezone_name,
        )

    # ---------------------------------------------------------
    # PM2.5 concentration
    # ---------------------------------------------------------

    # pm25 is the 1-hour average: RawConcentration. "Value" is the NowCast
    # (a 12-hour weighted average) and is never used, not even as a
    # fallback -- recomputing NowCast from AQS hourly data reproduces Value
    # exactly, while RawConcentration equals the AQS hourly measurement.
    raw = row.get("RawConcentration", row.get("raw_concentration"))
    pm25 = to_float(raw) if raw not in (None, "") else None

    if pm25 is None:
        # Present on every row when the request sets
        # includerawconcentrations=1, so a missing value means the request
        # is wrong -- fail loudly rather than store something else.
        raise ValueError(
            f"AirNow PM2.5 record for {site_name or station_id} has no "
            "RawConcentration; request it with includerawconcentrations=1."
        )

    # -999 is AirNow's "no reading for this hour". Small negatives are
    # instrument noise around zero; observations.pm25 has CHECK (pm25 >= 0).
    if pm25 < RAW_NEGATIVE_FLOOR:
        return None
    if pm25 < 0:
        pm25 = 0.0

    if ingested_at is None:
        ingested_at = datetime.now(timezone.utc)

    # ---------------------------------------------------------
    # Output compatible with SmokeSense schema
    # ---------------------------------------------------------

    return {
        "monitor": {
            "source": "airnow",
            "external_id": monitor_external_id,
            "name": site_name or station_id,
            "location_type": "outdoor",
            "geom_wkt": geom_wkt,
            "latitude": latitude,
            "longitude": longitude,
            "elevation_m": elevation_m,
            "active": True,
            "first_seen_at": ingested_at,
            "last_seen_at": ingested_at,
        },
        "observation": {
            "monitor_external_id": monitor_external_id,
            "valid_at": valid_at,
            "received_at": ingested_at,
            "ingested_at": ingested_at,
            "pm25": pm25,
            "correction": "regulatory",
            "data_status": "preliminary",
            "pm25_cf1_a": None,
            "pm25_cf1_b": None,
            "rh_pct": None,
            "qa_flag": None,
        },
        "source_metadata": {
            "source": "airnow",
            "station_id": station_id,
            "site_name": site_name,
            "agency_name": agency_name,
            "parameter": parameter,
            "source_timestamp": valid_at,
        },
    }


def get_airnow_pm25_records(
    api_key: str,
    bbox: str = DEFAULT_BBOX,
    start_date: str = DEFAULT_START_DATE,
    start_hour: str = DEFAULT_START_HOUR,
    end_date: str = DEFAULT_END_DATE,
    end_hour: str = DEFAULT_END_HOUR,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Fetch and normalize AirNow PM2.5 monitoring-site records.

    For ranges longer than ~a week, call this once per chunk from
    split_airnow_range() rather than once for the whole range.
    """

    rows = fetch_airnow_rows(
        api_key=api_key,
        bbox=bbox,
        start_date=start_date,
        start_hour=start_hour,
        end_date=end_date,
        end_hour=end_hour,
        verbose=verbose,
    )

    records = []

    for row in rows:
        record = normalize_airnow_row(row)

        if record is not None:
            records.append(record)

    return records


def main() -> None:
    """Run a manual AirNow monitoring-site ingestion smoke test."""

    load_env()

    api_key = require_env(
        "AIRNOW_API_KEY",
        how_to_get="Set AIRNOW_API_KEY to your AirNow API key.",
    )

    bbox = os.getenv(
        "AIRNOW_BBOX",
        DEFAULT_BBOX,
    )

    start_date = os.getenv(
        "AIRNOW_START_DATE",
        DEFAULT_START_DATE,
    )

    start_hour = os.getenv(
        "AIRNOW_START_HOUR",
        DEFAULT_START_HOUR,
    )

    end_date = os.getenv(
        "AIRNOW_END_DATE",
        DEFAULT_END_DATE,
    )

    end_hour = os.getenv(
        "AIRNOW_END_HOUR",
        DEFAULT_END_HOUR,
    )

    records = get_airnow_pm25_records(
        api_key=api_key,
        bbox=bbox,
        start_date=start_date,
        start_hour=start_hour,
        end_date=end_date,
        end_hour=end_hour,
        verbose=True,
    )

    print(
        f"AirNow PM2.5 monitoring records retrieved: "
        f"{len(records)}"
    )

    for record in records[:3]:
        print(record)


if __name__ == "__main__":
    main()
