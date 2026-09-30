"""NOAA NCEI historical weather connector (Global Hourly / ISD).

api.weather.gov only serves recent observations, so historical surface
weather for pilot events comes from NCEI's Global Hourly dataset: hourly
station reports (METAR/synoptic) going back decades.

The connector:
1. Finds ISD stations inside a bounding box from NCEI's station list.
2. Pulls each station's hourly reports from the NCEI Access Data Service.
3. Decodes the packed ISD fields (wind, temperature, dew point, pressure,
   precipitation), drops values that fail NCEI quality control, and derives
   relative humidity from dew point.
4. Builds records shaped like the weather_observations table.

It does NOT write to the database yet. No API key is required.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from ingestion.connectors._common import (
    TIMEOUT,
    get_with_retry,
    load_env,
)
from ingestion.normalize import (
    point_wkt,
    relative_humidity_from_dewpoint,
    to_float,
)


NCEI_DATA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
ISD_HISTORY_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"

# Sacramento-area development box, matching the FIRMS/AirNow POC.
# Format: west, south, east, north
DEFAULT_BBOX = "-122.5,38.0,-120.5,39.5"

# Two days inside PE-001 (August Complex) as a known smoky window.
DEFAULT_START_DATE = "2020-09-09"
DEFAULT_END_DATE = "2020-09-10"

# Routine hourly reports. FM-16 (SPECI) are off-cycle specials and
# SOD/SOM are daily/monthly summaries with no hourly values.
HOURLY_REPORT_TYPES = frozenset({"FM-15", "FM-12", "SAO"})

# One request per station per chunk keeps each response a few hundred KB.
CHUNK_DAYS = 31

# ISD quality codes meaning "suspect" or "erroneous". Everything else
# (0, 1, 4, 5, 9, A, C, I, M, P, R, U) passed or was corrected by NCEI QC.
BAD_QUALITY_CODES = frozenset({"2", "3", "6", "7"})


# ---------------------------------------------------------
# ISD field decoding
# ---------------------------------------------------------


def _split(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").split(",")]


def parse_wind(value: object) -> tuple[float | None, float | None, bool]:
    """Decode WND, e.g. "270,1,N,0046,1" -> (270.0, 4.6, ok).

    Returns (direction_deg, speed_ms, passed_qc). Direction is where the
    wind blows FROM. Calm ("C") gives speed 0 and no direction.
    """

    parts = _split(value)
    if len(parts) < 5:
        return None, None, True

    dir_raw, dir_q, type_code, speed_raw, speed_q = parts[:5]
    passed = True

    direction = None
    if dir_raw != "999":
        if dir_q in BAD_QUALITY_CODES:
            passed = False
        else:
            direction = to_float(dir_raw)

    speed = None
    if speed_raw != "9999":
        if speed_q in BAD_QUALITY_CODES:
            passed = False
        else:
            tenths = to_float(speed_raw)
            speed = None if tenths is None else tenths / 10

    if type_code == "C":
        direction, speed = None, 0.0

    # Schema allows 0–360; anything else is a decoding problem.
    if direction is not None and not 0 <= direction <= 360:
        direction = None

    return direction, speed, passed


def parse_tenths(
    value: object,
    missing: str,
) -> tuple[float | None, bool]:
    """Decode a "value,quality" field stored in tenths, e.g. "+0250,1" -> 25.0.

    Used for TMP, DEW (missing "+9999") and SLP (missing "99999").
    """

    parts = _split(value)
    if len(parts) < 2 or parts[0] == missing:
        return None, True

    if parts[1] in BAD_QUALITY_CODES:
        return None, False

    tenths = to_float(parts[0])
    return (None if tenths is None else tenths / 10), True


def parse_precip_1h(row: dict[str, Any]) -> tuple[float | None, bool]:
    """Find a 1-hour accumulation in AA1–AA4, e.g. "01,0005,9,1" -> 0.5 mm."""

    for column in ("AA1", "AA2", "AA3", "AA4"):
        parts = _split(row.get(column))
        if len(parts) < 4 or parts[0] != "01":
            continue

        depth_raw, quality = parts[1], parts[3]
        if depth_raw == "9999":
            return None, True
        if quality in BAD_QUALITY_CODES:
            return None, False

        tenths = to_float(depth_raw)
        return (None if tenths is None else tenths / 10), True

    return None, True


def parse_ncei_timestamp(value: object) -> datetime:
    """NCEI DATE is already UTC, e.g. "2020-09-09T00:53:00"."""

    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid NCEI timestamp: {value!r}") from exc

    return parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------
# Station discovery
# ---------------------------------------------------------


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    """Parse "west,south,east,north" into floats."""

    parts = [to_float(part) for part in bbox.split(",")]
    if len(parts) != 4 or any(part is None for part in parts):
        raise ValueError(f"Invalid bbox {bbox!r}; expected west,south,east,north")

    west, south, east, north = parts
    return west, south, east, north


def fetch_isd_stations(client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Download and parse NCEI's full ISD station list (~30k stations)."""

    if client is None:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as own:
            return fetch_isd_stations(own)

    response = get_with_retry(client, ISD_HISTORY_URL)

    if response.status_code != 200:
        raise RuntimeError(
            f"NCEI station list request failed with HTTP "
            f"{response.status_code}: {response.text[:300]}"
        )

    return parse_isd_stations(response.text)


def parse_isd_stations(text: str) -> list[dict[str, Any]]:
    """Parse isd-history.csv into station dicts with usable coordinates."""

    stations = []

    for row in csv.DictReader(io.StringIO(text)):
        latitude = to_float(row.get("LAT"))
        longitude = to_float(row.get("LON"))

        if latitude is None or longitude is None:
            continue

        usaf = str(row.get("USAF", "")).strip()
        wban = str(row.get("WBAN", "")).strip()

        stations.append(
            {
                "ncei_id": f"{usaf}{wban}",
                "icao": str(row.get("ICAO", "")).strip().upper() or None,
                "name": str(row.get("STATION NAME", "")).strip(),
                "country": str(row.get("CTRY", "")).strip(),
                "latitude": latitude,
                "longitude": longitude,
                "elevation_m": to_float(row.get("ELEV(M)")),
                "begin": str(row.get("BEGIN", "")).strip(),
                "end": str(row.get("END", "")).strip(),
            }
        )

    return stations


def select_stations(
    stations: list[dict[str, Any]],
    bbox: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    station_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter stations by bbox, active period, and/or explicit IDs.

    station_ids may be ICAO codes ("KRDD") or NCEI IDs ("72592024257").
    """

    wanted = {sid.strip().upper() for sid in station_ids or [] if sid.strip()}

    # isd-history BEGIN/END are YYYYMMDD strings, so they compare as text.
    start_key = start_date.replace("-", "") if start_date else None
    end_key = end_date.replace("-", "") if end_date else None

    if bbox:
        west, south, east, north = parse_bbox(bbox)

    selected = []

    for station in stations:
        if wanted and not {station["ncei_id"], station["icao"]} & wanted:
            continue

        if bbox and not (
            west <= station["longitude"] <= east
            and south <= station["latitude"] <= north
        ):
            continue

        if start_key and station["end"] and station["end"] < start_key:
            continue

        if end_key and station["begin"] and station["begin"] > end_key:
            continue

        selected.append(station)

    return selected


# ---------------------------------------------------------
# Observations
# ---------------------------------------------------------


def date_chunks(
    start_date: str,
    end_date: str,
    chunk_days: int = CHUNK_DAYS,
) -> list[tuple[date, date]]:
    """Split an inclusive date range into inclusive chunks."""

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    if end < start:
        raise ValueError(f"end_date {end_date} is before start_date {start_date}")

    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)

    return chunks


def fetch_ncei_rows(
    ncei_id: str,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    client: httpx.Client | None = None,
) -> list[dict[str, str]]:
    """Fetch Global Hourly rows for one station over an inclusive date range."""

    if client is None:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as own:
            return fetch_ncei_rows(ncei_id, start_date, end_date, own)

    rows: list[dict[str, str]] = []

    for chunk_start, chunk_end in date_chunks(start_date, end_date):
        params = {
            "dataset": "global-hourly",
            "stations": ncei_id,
            "startDate": f"{chunk_start.isoformat()}T00:00:00",
            "endDate": f"{chunk_end.isoformat()}T23:59:59",
            "format": "csv",
            "includeStationName": "true",
            "includeStationLocation": "1",
        }

        response = get_with_retry(client, NCEI_DATA_URL, params=params)

        if response.status_code != 200:
            raise RuntimeError(
                f"NCEI request for station {ncei_id} failed with HTTP "
                f"{response.status_code}: {response.text[:300]}"
            )

        body = response.text.strip()

        # No reports for this station/window.
        if not body:
            continue

        # Errors come back as JSON; data comes back as CSV with a header.
        first_line = body.splitlines()[0].replace('"', "").upper()
        if not first_line.startswith("STATION,"):
            raise RuntimeError(
                f"NCEI returned an unexpected response for station {ncei_id} "
                f"instead of CSV. Response: {body[:500]}"
            )

        rows.extend(csv.DictReader(io.StringIO(body)))

    return rows


def normalize_ncei_row(
    row: dict[str, Any],
    station: dict[str, Any] | None = None,
    ingested_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Convert one Global Hourly row to the weather_observations shape.

    Returns None for report types that are not routine hourly reports.
    Values failing NCEI QC are dropped (NULL) and the row's qc_flag is set
    to "suspect"; otherwise qc_flag is "V" (verified).
    """

    report_type = str(row.get("REPORT_TYPE", "")).strip()
    if report_type not in HOURLY_REPORT_TYPES:
        return None

    ncei_id = str(row.get("STATION", "")).strip()

    latitude = to_float(row.get("LATITUDE"))
    longitude = to_float(row.get("LONGITUDE"))

    if (latitude is None or longitude is None) and station:
        latitude, longitude = station["latitude"], station["longitude"]

    if latitude is None or longitude is None:
        raise ValueError(f"NCEI row for station {ncei_id} has no coordinates.")

    # Prefer the ICAO code (e.g. KRDD) so historical rows share station_id
    # with the live NWS observations for the same airport.
    call_sign = str(row.get("CALL_SIGN", "")).strip().upper()
    if call_sign in {"", "99999"}:
        call_sign = ""

    station_id = (station or {}).get("icao") or call_sign or ncei_id

    wind_dir, wind_speed, wind_ok = parse_wind(row.get("WND"))
    temp_c, temp_ok = parse_tenths(row.get("TMP"), missing="+9999")
    dewpoint_c, dew_ok = parse_tenths(row.get("DEW"), missing="+9999")
    pressure_hpa, slp_ok = parse_tenths(row.get("SLP"), missing="99999")
    precip_mm, precip_ok = parse_precip_1h(row)

    # Schema CHECK (pressure_hpa > 800); sea-level pressure below that is bad data.
    if pressure_hpa is not None and pressure_hpa <= 800:
        pressure_hpa, slp_ok = None, False

    all_ok = wind_ok and temp_ok and dew_ok and slp_ok and precip_ok

    if ingested_at is None:
        ingested_at = datetime.now(timezone.utc)

    return {
        "station_id": station_id,
        "valid_at": parse_ncei_timestamp(row.get("DATE")),
        "received_at": ingested_at,
        "ingested_at": ingested_at,
        "geom_wkt": point_wkt(latitude, longitude),
        "latitude": latitude,
        "longitude": longitude,
        "wind_speed_ms": wind_speed,
        "wind_dir_deg": wind_dir,
        "temp_c": temp_c,
        "rh_pct": relative_humidity_from_dewpoint(temp_c, dewpoint_c),
        "pressure_hpa": pressure_hpa,
        "precip_1h_mm": precip_mm,
        "qc_flag": "V" if all_ok else "suspect",
        "source": "ncei",
        "source_metadata": {
            "ncei_station_id": ncei_id,
            "station_name": str(row.get("NAME", "")).strip(),
            "report_type": report_type,
            "source_timestamp": str(row.get("DATE", "")).strip(),
        },
    }


def get_ncei_weather_records(
    bbox: str = DEFAULT_BBOX,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    station_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Discover stations, fetch their hourly reports, and normalize them.

    When station_ids is given, those stations are used regardless of bbox.
    Rows are de-duplicated on (station_id, valid_at), the table's primary key.
    """

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        stations = select_stations(
            fetch_isd_stations(client),
            bbox=None if station_ids else bbox,
            start_date=start_date,
            end_date=end_date,
            station_ids=station_ids,
        )

        ingested_at = datetime.now(timezone.utc)
        records: dict[tuple[str, datetime], dict[str, Any]] = {}

        for station in stations:
            rows = fetch_ncei_rows(
                station["ncei_id"],
                start_date=start_date,
                end_date=end_date,
                client=client,
            )

            for row in rows:
                record = normalize_ncei_row(row, station, ingested_at)
                if record is None:
                    continue

                key = (record["station_id"], record["valid_at"])
                records.setdefault(key, record)

    return sorted(records.values(), key=lambda r: (r["station_id"], r["valid_at"]))


def main() -> None:
    """Run a small manual NCEI ingestion smoke test."""

    load_env()

    bbox = os.getenv("NCEI_BBOX", DEFAULT_BBOX)
    start_date = os.getenv("NCEI_START_DATE", DEFAULT_START_DATE)
    end_date = os.getenv("NCEI_END_DATE", DEFAULT_END_DATE)

    station_ids = [
        sid for sid in os.getenv("NCEI_STATIONS", "").split(",") if sid.strip()
    ] or None

    records = get_ncei_weather_records(
        bbox=bbox,
        start_date=start_date,
        end_date=end_date,
        station_ids=station_ids,
    )

    stations = {record["station_id"] for record in records}
    suspect = sum(record["qc_flag"] != "V" for record in records)

    print(f"NCEI weather records retrieved: {len(records)}")
    print(f"Stations: {len(stations)} ({', '.join(sorted(stations)) or 'none'})")
    print(f"Rows with a QC-rejected value: {suspect}")

    for record in records[:3]:
        print(record)


if __name__ == "__main__":
    main()
