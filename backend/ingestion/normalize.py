"""Normalization helpers for ingestion connectors.

These functions convert source-specific values into the formats expected
by the SmokeSense database schema.
"""

from __future__ import annotations

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


def normalize_confidence(value: object) -> str | None:
    """Normalize FIRMS confidence codes into PM-01 enum values."""

    if value is None:
        return None

    text = str(value).strip().lower()

    confidence_map = {
        "l": "low",
        "n": "nominal",
        "h": "high",
        "low": "low",
        "nominal": "nominal",
        "high": "high",
    }

    return confidence_map.get(text)


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