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
from datetime import datetime, timezone
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


def fetch_airnow_rows(
    api_key: str,
    bbox: str = DEFAULT_BBOX,
    start_date: str = DEFAULT_START_DATE,
    start_hour: str = DEFAULT_START_HOUR,
    end_date: str = DEFAULT_END_DATE,
    end_hour: str = DEFAULT_END_HOUR,
) -> list[dict[str, Any]]:
    """Inspect the AirNow historical/state response."""

    # The monitoring-site endpoint accepts a geographic bounding box and
    # hourly date range. The historical/state endpoint is a different API
    # intended for reporting-area AQI history.
    url = f"{AIRNOW_BASE_URL}/data/"

    start_datetime = f"{start_date}T{start_hour.zfill(2)}"
    end_datetime = f"{end_date}T{end_hour.zfill(2)}"

    params = {
        "format": "application/json",
        "BBOX": bbox,
        "startDate": start_datetime,
        "endDate": end_datetime,
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

    print("HTTP status:", response.status_code)
    print("Response preview:")
    print(response.text[:3000])

    if response.status_code != 200:
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
        raise RuntimeError(f"AirNow returned an API error: {messages}")

    if not isinstance(payload, list):
        raise RuntimeError(
            f"AirNow returned an unexpected response type: {type(payload).__name__}"
        )

    return payload


def normalize_airnow_row(
    row: dict[str, Any],
    ingested_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Normalize one AirNow monitoring-site PM2.5 observation."""

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

    pm25 = None

    # Depending on AirNow output settings, concentration may
    # appear under one of these fields.
    concentration_fields = (
        "Value",
        "Concentration",
        "ConcentrationValue",
        "concentration",
        "PM2.5",
        "PM25",
        "RawConcentration",
        "raw_concentration",
    )

    for field in concentration_fields:
        value = row.get(field)

        if value not in (None, ""):
            pm25 = to_float(value)

            if pm25 is not None:
                break

    if pm25 is None:
        raise ValueError(
            f"AirNow PM2.5 record for {site_name or station_id} "
            "has no usable concentration."
        )

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
) -> list[dict[str, Any]]:
    """Fetch and normalize AirNow PM2.5 monitoring-site records."""

    rows = fetch_airnow_rows(
        api_key=api_key,
        bbox=bbox,
        start_date=start_date,
        start_hour=start_hour,
        end_date=end_date,
        end_hour=end_hour,
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
    )

    print(
        f"AirNow PM2.5 monitoring records retrieved: "
        f"{len(records)}"
    )

    for record in records[:3]:
        print(record)


if __name__ == "__main__":
    main()
