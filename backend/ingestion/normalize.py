"""Normalization helpers for ingestion connectors.

These functions convert source-specific values into the formats expected
by the SmokeSense database schema.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from hashlib import sha256
from zoneinfo import ZoneInfo


# AirNow may return either abbreviations or IANA timezone names.
AIRNOW_TIMEZONES = {
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
}


def to_float(value: object) -> float | None:
    """Convert a value to float, returning None for missing/invalid values."""
    if value is None:
        return None

    text = str(value).strip()

    if not text or text.lower() in {"null", "none", "na", "n/a"}:
        return None

    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_firms_timestamp(
    acq_date: object,
    acq_time: object,
) -> datetime:
    """Convert FIRMS acquisition date/time into UTC."""

    date_text = str(acq_date).strip()

    # FIRMS normally gives HHMM, but CSV parsing can sometimes turn
    # values such as 30 into 30.0.
    time_text = str(acq_time).strip()

    try:
        time_value = int(float(time_text))
    except ValueError as exc:
        raise ValueError(f"Invalid FIRMS acquisition time: {acq_time}") from exc

    time_text = f"{time_value:04d}"

    hour = int(time_text[:2])
    minute = int(time_text[2:])

    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid FIRMS acquisition time: {acq_time}")

    return datetime.strptime(
        f"{date_text} {hour:02d}:{minute:02d}",
        "%Y-%m-%d %H:%M",
    ).replace(tzinfo=timezone.utc)


def parse_airnow_timestamp(
    date_observed: object,
    hour_observed: object,
    local_timezone: object,
) -> datetime:
    """Convert an AirNow local observation timestamp to UTC."""

    date_text = str(date_observed).strip()
    hour_text = str(hour_observed).strip()

    # AirNow may return hourObserved as either:
    #   "12"
    #   "12:00"
    #   12
    # Normalize both forms to an integer hour.
    try:
        if ":" in hour_text:
            hour = int(hour_text.split(":", 1)[0])
        else:
            hour = int(float(hour_text))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Invalid AirNow observation hour: {hour_observed}"
        ) from exc

    if not 0 <= hour <= 24:
        raise ValueError(
            f"Invalid AirNow observation hour: {hour_observed}"
        )

    local_dt = datetime.strptime(
        date_text,
        "%Y-%m-%d",
    )

    # AirNow uses 24:00 to represent midnight at the end of the day.
    if hour == 24:
        from datetime import timedelta

        local_dt += timedelta(days=1)
        hour = 0

    timezone_text = str(local_timezone).strip()
    timezone_name = AIRNOW_TIMEZONES.get(
        timezone_text.upper(),
        timezone_text,
    )

    try:
        zone = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(
            f"Unsupported AirNow timezone: {local_timezone}"
        ) from exc

    local_dt = local_dt.replace(
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=zone,
    )

    return local_dt.astimezone(timezone.utc)


FIRMS_CONFIDENCE_LABELS = {
    "l": "low",
    "n": "nominal",
    "h": "high",
    "low": "low",
    "nominal": "nominal",
    "high": "high",
}

# FIRMS convention for MODIS's numeric 0-100 confidence:
#   0-29 = low, 30-79 = nominal, 80-100 = high
MODIS_NOMINAL_MIN = 30
MODIS_HIGH_MIN = 80


def normalize_confidence(value: object) -> str | None:
    """Normalize FIRMS confidence values into PM-01 enum values.

    Handles both formats FIRMS uses:
      * VIIRS: letter codes ("l"/"n"/"h") or the full words.
      * MODIS: a number from 0 to 100 (e.g. "75", "75.0", 75), mapped by
        the standard FIRMS thresholds (<30 low, 30-79 nominal, 80+ high).

    Returns None for missing, unrecognized, or out-of-range (<0, >100,
    NaN) values. fire_detections.confidence_level is NOT NULL, so callers
    must treat None as a bad row rather than inserting it.
    """

    if value is None or isinstance(value, bool):
        return None

    text = str(value).strip().lower()

    if text in FIRMS_CONFIDENCE_LABELS:
        return FIRMS_CONFIDENCE_LABELS[text]

    number = to_float(text)

    # NaN fails the range comparison, so it is rejected here too.
    if number is None or not 0 <= number <= 100:
        return None

    if number >= MODIS_HIGH_MIN:
        return "high"
    if number >= MODIS_NOMINAL_MIN:
        return "nominal"
    return "low"


def stable_external_id(prefix: str, *parts: object) -> str:
    """Create a deterministic external ID for source records.

    This lets us identify the same source record on a rerun without
    storing the complete raw source payload.
    """

    canonical = "|".join(
        "" if part is None else str(part).strip()
        for part in parts
    )

    digest = sha256(canonical.encode("utf-8")).hexdigest()[:24]

    return f"{prefix}:{digest}"


def point_wkt(latitude: float, longitude: float) -> str:
    """Create WKT for a PostGIS geographic point.

    WKT uses longitude first, then latitude.
    """

    return f"POINT({longitude} {latitude})"


def relative_humidity_from_dewpoint(
    temp_c: float | None,
    dewpoint_c: float | None,
) -> float | None:
    """Relative humidity (%) from air temperature and dew point.

    Uses the Magnus approximation (Alduchov & Eskridge 1996 constants),
    accurate to well under 1% RH across normal surface temperatures.
    NCEI hourly data reports dew point, not RH, so this fills rh_pct.
    """

    if temp_c is None or dewpoint_c is None:
        return None

    a, b = 17.625, 243.04

    rh = 100.0 * math.exp(
        (a * dewpoint_c) / (b + dewpoint_c)
        - (a * temp_c) / (b + temp_c)
    )

    # Dew point can read a hair above temperature in saturated air.
    return round(min(max(rh, 0.0), 100.0), 1)


# PurpleAir A/B channel agreement thresholds (Barkjohn et al. 2021).
# Channels disagree when BOTH the absolute and relative gaps are large.
PURPLEAIR_MAX_ABS_DIFF = 5.0  # µg/m³
PURPLEAIR_MAX_REL_DIFF = 0.70  # |A - B| / mean(A, B)


def purpleair_channel_qa(
    cf1_a: float | None,
    cf1_b: float | None,
) -> tuple[float | None, str]:
    """Combine PurpleAir A/B channels into one cf_1 value plus a qa_flag.

    Returns (mean_cf1, qa_flag) where qa_flag is one of the schema values:
    - "ok":      both channels present and agreeing
    - "suspect": only one channel reported, so agreement cannot be checked
    - "invalid": channels disagree, or neither reported
    """

    if cf1_a is None and cf1_b is None:
        return None, "invalid"

    if cf1_a is None or cf1_b is None:
        single = cf1_a if cf1_a is not None else cf1_b
        return single, "suspect"

    mean = (cf1_a + cf1_b) / 2
    abs_diff = abs(cf1_a - cf1_b)
    rel_diff = abs_diff / mean if mean > 0 else 0.0

    if abs_diff > PURPLEAIR_MAX_ABS_DIFF and rel_diff > PURPLEAIR_MAX_REL_DIFF:
        return mean, "invalid"

    return mean, "ok"


def barkjohn_correct(
    cf1: float,
    rh_pct: float,
) -> float:
    """EPA U.S.-wide PurpleAir correction (Barkjohn et al. 2021).

    PM2.5 = 0.524 * PA_cf1 - 0.0862 * RH + 5.75

    cf1 is the mean of the A and B pm2.5_cf_1 channels (µg/m³); rh_pct is the
    sensor's own humidity reading. Negative results are clamped to 0 because
    observations.pm25 has CHECK (pm25 >= 0).

    Note: EPA later published an extended version for very high smoke
    concentrations. Raw channels are stored, so rows can be recomputed if
    the team switches formulas.
    """

    return max(0.524 * cf1 - 0.0862 * rh_pct + 5.75, 0.0)
