"""NASA FIRMS ingestion connector.

This module retrieves FIRMS fire detections, validates the response,
and converts the source rows into the normalized SmokeSense format.

It does NOT write to the database yet.
"""

from __future__ import annotations

import csv
import io
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
    normalize_confidence,
    parse_firms_timestamp,
    point_wkt,
    stable_external_id,
    to_float,
)


FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/"

DEFAULT_SOURCE = "VIIRS_SNPP_NRT"

# Temporary development area.
# This can be replaced with the actual pilot-fire bounding box.
DEFAULT_BBOX = "-122.5,38.0,-120.5,39.5"

DEFAULT_DAY_RANGE = 1


def build_url(
    map_key: str,
    source: str,
    bbox: str,
    day_range: int,
    start_date: str | None = None,
) -> str:
    """Build a FIRMS area CSV API URL."""

    url = (
        f"{FIRMS_BASE_URL}"
        f"area/csv/"
        f"{map_key}/"
        f"{source}/"
        f"{bbox}/"
        f"{day_range}"
    )

    if start_date:
        url = f"{url}/{start_date}"

    return url


def fetch_firms_rows(
    map_key: str,
    source: str = DEFAULT_SOURCE,
    bbox: str = DEFAULT_BBOX,
    day_range: int = DEFAULT_DAY_RANGE,
    start_date: str | None = None,
) -> list[dict[str, str]]:
    """Fetch FIRMS CSV data and return parsed source rows."""

    url = build_url(
        map_key=map_key,
        source=source,
        bbox=bbox,
        day_range=day_range,
        start_date=start_date,
    )

    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.get(url)

    if response.status_code != 200:
        raise RuntimeError(
            f"FIRMS request failed with HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    body = response.text.strip()

    if not body:
        return []

    # FIRMS can return an HTTP 200 containing an error message.
    first_line = body.splitlines()[0].lower()

    if not first_line.startswith("latitude,longitude"):
        raise RuntimeError(
            "FIRMS returned an unexpected response instead of CSV. "
            f"Response: {body[:500]}"
        )

    reader = csv.DictReader(io.StringIO(body))

    return list(reader)


def normalize_firms_row(
    row: dict[str, str],
    source: str,
    ingested_at: datetime | None = None,
) -> dict[str, Any]:
    """Convert one FIRMS row to the SmokeSense fire_detections shape."""

    latitude = to_float(row.get("latitude"))
    longitude = to_float(row.get("longitude"))

    if latitude is None or longitude is None:
        raise ValueError("FIRMS row is missing latitude/longitude.")

    detected_at = parse_firms_timestamp(
        row.get("acq_date"),
        row.get("acq_time"),
    )

    satellite_raw = str(row.get("satellite", "")).strip().upper()
    instrument_raw = str(row.get("instrument", "")).strip().upper()

    satellite_map = {
        # FIRMS VIIRS codes
        "N": "VIIRS_SNPP",
        "J": "VIIRS_NOAA20",
        "1": "VIIRS_NOAA21",

        # Explicit satellite names
        "SNPP": "VIIRS_SNPP",
        "NOAA20": "VIIRS_NOAA20",
        "NOAA-20": "VIIRS_NOAA20",
        "NOAA21": "VIIRS_NOAA21",
        "NOAA-21": "VIIRS_NOAA21",

        # MODIS
        "TERRA": "MODIS_TERRA",
        "AQUA": "MODIS_AQUA",
    }

    satellite = satellite_map.get(
        satellite_raw,
        satellite_raw,
    )

    product = source.rsplit("_", 1)[-1].upper()

    confidence_raw = row.get("confidence")

    # Include source-identifying fields in the deterministic ID.
    external_id = stable_external_id(
        "firms",
        source,
        satellite,
        row.get("acq_date"),
        row.get("acq_time"),
        row.get("latitude"),
        row.get("longitude"),
        row.get("scan"),
        row.get("track"),
        row.get("frp"),
    )

    if ingested_at is None:
        ingested_at = datetime.now(timezone.utc)

    return {
        "external_id": external_id,
        "satellite": satellite,
        "product": product,
        "geom_wkt": point_wkt(latitude, longitude),
        "latitude": latitude,
        "longitude": longitude,
        "detected_at": detected_at,
        "received_at": ingested_at,
        "ingested_at": ingested_at,
        "confidence_raw": confidence_raw,
        "confidence_level": normalize_confidence(confidence_raw),
        "frp_mw": to_float(row.get("frp")),
        "bright_t31_k": to_float(row.get("bright_t31")),
        "scan_km": to_float(row.get("scan")),
        "track_km": to_float(row.get("track")),
        "daynight": (
            str(row.get("daynight", "")).strip().upper()
            or None
        ),
        "source": "firms",
    }


def get_firms_records(
    map_key: str,
    source: str = DEFAULT_SOURCE,
    bbox: str = DEFAULT_BBOX,
    day_range: int = DEFAULT_DAY_RANGE,
    start_date: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch and normalize FIRMS records."""

    rows = fetch_firms_rows(
        map_key=map_key,
        source=source,
        bbox=bbox,
        day_range=day_range,
        start_date=start_date,
    )

    return [
        normalize_firms_row(row, source=source)
        for row in rows
    ]


def main() -> None:
    """Run a small manual FIRMS ingestion smoke test."""

    load_env()

    map_key = require_env(
        "FIRMS_MAP_KEY",
        how_to_get="Get a FIRMS map key from NASA FIRMS and set it in the environment.",
    )

    source = os.getenv(
        "FIRMS_SOURCE",
        DEFAULT_SOURCE,
    )

    bbox = os.getenv(
        "FIRMS_BBOX",
        DEFAULT_BBOX,
    )

    day_range = int(
        os.getenv(
            "FIRMS_DAY_RANGE",
            str(DEFAULT_DAY_RANGE),
        )
    )

    start_date = os.getenv("FIRMS_START_DATE") or None

    records = get_firms_records(
        map_key=map_key,
        source=source,
        bbox=bbox,
        day_range=day_range,
        start_date=start_date,
    )

    print(f"FIRMS records retrieved: {len(records)}")

    for record in records[:3]:
        print(record)


if __name__ == "__main__":
    main()