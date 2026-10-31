"""Unit tests for FIRMS confidence normalization.

VIIRS reports confidence as letter codes (l/n/h); MODIS reports a number
0-100. fire_detections.confidence_level is NOT NULL, so a MODIS value that
normalizes to None crashes the insert.
"""

from __future__ import annotations

import pytest

from ingestion.connectors.firms import normalize_firms_row
from ingestion.normalize import normalize_confidence


# ---------------------------------------------------------------------------
# VIIRS letter codes (existing behavior must not regress)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("l", "low"),
        ("n", "nominal"),
        ("h", "high"),
        ("L", "low"),
        ("N", "nominal"),
        ("H", "high"),
        (" h ", "high"),
        ("low", "low"),
        ("nominal", "nominal"),
        ("HIGH", "high"),
    ],
)
def test_viirs_letter_codes(raw, expected):
    assert normalize_confidence(raw) == expected


# ---------------------------------------------------------------------------
# MODIS numeric 0-100: <30 low, 30-79 nominal, 80+ high
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0", "low"),
        ("1", "low"),
        ("29", "low"),
        ("30", "nominal"),
        ("55", "nominal"),
        ("79", "nominal"),
        ("80", "high"),
        ("100", "high"),
    ],
)
def test_modis_numeric_thresholds(raw, expected):
    assert normalize_confidence(raw) == expected


def test_modis_boundaries_are_exact():
    assert normalize_confidence("29") == "low"
    assert normalize_confidence("30") == "nominal"
    assert normalize_confidence("79") == "nominal"
    assert normalize_confidence("80") == "high"


@pytest.mark.parametrize(
    "raw, expected",
    [
        (75, "nominal"),
        (75.0, "nominal"),
        ("75.0", "nominal"),
        (" 85 ", "high"),
        (29.9, "low"),
        (79.9, "nominal"),
        (0, "low"),
    ],
)
def test_modis_numeric_types_and_formats(raw, expected):
    """Values may arrive as int/float, or as floats rendered by CSV tooling."""
    assert normalize_confidence(raw) == expected


# ---------------------------------------------------------------------------
# Invalid input stays None (callers must not insert these)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "x", "unknown", "nan", "inf", "-1", "101", 150, -5, True, "null"],
)
def test_invalid_values_return_none(raw):
    assert normalize_confidence(raw) is None


# ---------------------------------------------------------------------------
# End to end: a MODIS CSV row must produce a non-null confidence_level
# ---------------------------------------------------------------------------

def _firms_row(**overrides):
    row = {
        "latitude": "38.5",
        "longitude": "-121.5",
        "brightness": "330.1",
        "scan": "1.1",
        "track": "1.0",
        "acq_date": "2026-09-25",
        "acq_time": "1230",
        "satellite": "Terra",
        "instrument": "MODIS",
        "confidence": "75",
        "version": "6.1NRT",
        "bright_t31": "295.2",
        "frp": "12.3",
        "daynight": "D",
    }
    row.update(overrides)
    return row


def test_modis_row_gets_confidence_level_and_keeps_raw():
    record = normalize_firms_row(_firms_row(confidence="75"), source="MODIS_NRT")

    assert record["confidence_raw"] == "75"
    assert record["confidence_level"] == "nominal"
    assert record["satellite"] == "MODIS_Terra"


@pytest.mark.parametrize(
    "raw, expected", [("12", "low"), ("30", "nominal"), ("95", "high")]
)
def test_modis_row_levels(raw, expected):
    record = normalize_firms_row(_firms_row(confidence=raw), source="MODIS_NRT")
    assert record["confidence_level"] == expected


def test_viirs_row_still_works():
    record = normalize_firms_row(
        _firms_row(satellite="N", instrument="VIIRS", confidence="h"),
        source="VIIRS_SNPP_NRT",
    )

    assert record["confidence_raw"] == "h"
    assert record["confidence_level"] == "high"
