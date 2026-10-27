"""NWS station observations connector (live weather, DATA-06).

Live weather features must match the NCEI Global Hourly rows the model was trained
on (docs/ml/serving-contract.md, "Weather field mapping"). This module decodes
api.weather.gov /stations/{id}/observations into the same weather_observations shape
as ncei.normalize_ncei_row, using the same rules:

- units are read from each value's unitCode, never assumed;
- wind direction is null when the wind is calm (speed 0), as NCEI calm reports;
- rh_pct comes from temperature and dew point (relative_humidity_from_dewpoint),
  never from NWS relativeHumidity;
- pressure_hpa is seaLevelPressure (not barometricPressure, the station pressure),
  null if <= 800 hPa;
- precip_1h_mm is precipitationLastHour; missing stays null, never 0;
- a value failing QC is dropped and the row's qc_flag is "suspect", else "V".

Only METAR reports are kept (see is_metar_report). NCEI's hourly data holds routine
reports, not the 5-minute ASOS readings NWS also serves, which carry no sea-level
pressure or precipitation; keeping those would make the newest report nearly always
one without pressure or precipitation, unlike training.

No API key; NWS requires a User-Agent with a contact (NWS_USER_AGENT).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from ingestion.normalize import point_wkt, relative_humidity_from_dewpoint, to_float

NWS_BASE_URL = "https://api.weather.gov"

# MADIS quality-control codes NWS attaches to each value: X rejected, B subjectively
# bad, Q questioned. The rest (V verified, C coarse pass, S screened, G good,
# Z preliminary/no QC) are kept, as NCEI keeps values that passed or were not checked.
BAD_QC = frozenset({"X", "B", "Q"})

# unitCode -> factor (or function) into the weather_observations unit.
SPEED_TO_MS = {"wmoUnit:m_s-1": 1.0, "wmoUnit:km_h-1": 1 / 3.6, "wmoUnit:kn": 0.514444}
ANGLE_DEG = {"wmoUnit:degree_(angle)": 1.0}
TEMP_TO_C = {
    "wmoUnit:degC": lambda v: v,
    "wmoUnit:degF": lambda v: (v - 32) * 5 / 9,
    "wmoUnit:K": lambda v: v - 273.15,
}
PRESSURE_TO_HPA = {"wmoUnit:Pa": 0.01, "wmoUnit:hPa": 1.0}
LENGTH_TO_MM = {"wmoUnit:mm": 1.0, "wmoUnit:m": 1000.0}

# Pages followed per station request; 72 h of one station is ~2 pages of 500.
MAX_PAGES = 5


def nws_headers(user_agent: str) -> dict[str, str]:
    return {"User-Agent": user_agent, "Accept": "application/geo+json"}


def quantity(value: Any, units: dict) -> tuple[float | None, bool]:
    """Decode one NWS quantity {unitCode, value, qualityControl} -> (value, passed QC).

    A missing value is (None, True). A value that failed QC, or whose unit is not
    known, is (None, False): it is dropped and flags the row, never guessed at.
    """
    if not isinstance(value, dict):
        return None, True
    number = to_float(value.get("value"))
    if number is None:
        return None, True
    if str(value.get("qualityControl") or "").upper() in BAD_QC:
        return None, False
    convert = units.get(value.get("unitCode"))
    if convert is None:
        return None, False
    return (convert(number) if callable(convert) else number * convert), True


def is_metar_report(properties: dict[str, Any]) -> bool:
    """A METAR (routine or special) report, not a 5-minute ASOS reading.

    METAR-derived observations carry the raw METAR text, or at least the
    precipitationLastHour group; 5-minute readings have neither (checked on
    KRDD, KSAC, KO22, KBLU and KLAX, 2026-10-23).
    """
    return bool(str(properties.get("rawMessage") or "").strip()) or (
        "precipitationLastHour" in properties
    )


def parse_nws_timestamp(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid NWS timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_nws_observation(
    feature: dict[str, Any],
    station_id: str | None = None,
    ingested_at: datetime | None = None,
) -> dict[str, Any] | None:
    """One NWS observation feature -> the weather_observations shape of normalize_ncei_row.

    Returns None for 5-minute readings (not METAR reports).
    """
    props = feature.get("properties") or {}
    if not is_metar_report(props):
        return None

    station_id = str(props.get("stationId") or station_id or "").strip().upper()
    if not station_id:
        raise ValueError("NWS observation has no station id.")

    coordinates = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coordinates) < 2:
        raise ValueError(f"NWS observation for {station_id} has no coordinates.")
    longitude, latitude = to_float(coordinates[0]), to_float(coordinates[1])
    if latitude is None or longitude is None:
        raise ValueError(f"NWS observation for {station_id} has no coordinates.")

    wind_speed, speed_ok = quantity(props.get("windSpeed"), SPEED_TO_MS)
    wind_dir, dir_ok = quantity(props.get("windDirection"), ANGLE_DEG)
    temp_c, temp_ok = quantity(props.get("temperature"), TEMP_TO_C)
    dewpoint_c, dew_ok = quantity(props.get("dewpoint"), TEMP_TO_C)
    pressure_hpa, slp_ok = quantity(props.get("seaLevelPressure"), PRESSURE_TO_HPA)
    precip_mm, precip_ok = quantity(props.get("precipitationLastHour"), LENGTH_TO_MM)

    if wind_speed is not None and wind_speed < 0:
        wind_speed, speed_ok = None, False
    if wind_speed is not None:
        wind_speed = round(wind_speed, 1)  # NCEI stores tenths of m/s
    # NCEI reports calm as speed 0 with no direction; match it.
    if wind_speed == 0:
        wind_dir = None
    if wind_dir is not None and not 0 <= wind_dir <= 360:
        wind_dir, dir_ok = None, False

    # Same rule as NCEI SLP (schema CHECK pressure_hpa > 800).
    if pressure_hpa is not None:
        pressure_hpa = round(pressure_hpa, 1)
        if pressure_hpa <= 800:
            pressure_hpa, slp_ok = None, False

    if precip_mm is not None and precip_mm < 0:
        precip_mm, precip_ok = None, False

    all_ok = speed_ok and dir_ok and temp_ok and dew_ok and slp_ok and precip_ok

    if ingested_at is None:
        ingested_at = datetime.now(timezone.utc)

    return {
        "station_id": station_id,
        "valid_at": parse_nws_timestamp(props.get("timestamp")),
        "received_at": ingested_at,
        "ingested_at": ingested_at,
        "geom_wkt": point_wkt(latitude, longitude),
        "latitude": latitude,
        "longitude": longitude,
        "wind_speed_ms": wind_speed,
        "wind_dir_deg": wind_dir,
        "temp_c": None if temp_c is None else round(temp_c, 1),
        "rh_pct": relative_humidity_from_dewpoint(temp_c, dewpoint_c),
        "pressure_hpa": pressure_hpa,
        "precip_1h_mm": precip_mm,
        "qc_flag": "V" if all_ok else "suspect",
        "source": "nws",
        "source_metadata": {
            "nws_station_id": station_id,
            "station_name": str(props.get("stationName") or "").strip(),
            "source_timestamp": str(props.get("timestamp") or "").strip(),
        },
    }


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_station_observations(
    client: httpx.Client,
    station_id: str,
    start: datetime,
    end: datetime,
    headers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Observation features for one station with start <= timestamp <= end.

    Follows NWS cursor pagination (newest first) until a page reaches start.
    headers should be nws_headers(user_agent): NWS rejects requests without one.
    """
    url = f"{NWS_BASE_URL}/stations/{station_id}/observations"
    params: dict[str, str] | None = {"start": _iso(start), "end": _iso(end)}
    features: list[dict[str, Any]] = []

    for _ in range(MAX_PAGES):
        response = client.get(url, params=params, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(
                f"NWS observations for {station_id} failed with HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"NWS observations for {station_id} returned invalid JSON"
            ) from exc

        page = payload.get("features") or []
        oldest = None
        for feature in page:
            ts = parse_nws_timestamp((feature.get("properties") or {}).get("timestamp"))
            oldest = ts if oldest is None or ts < oldest else oldest
            if start <= ts <= end:
                features.append(feature)

        url = (payload.get("pagination") or {}).get("next")
        params = None  # the next URL carries its own query
        if not page or not url or (oldest is not None and oldest <= start):
            break

    return features
