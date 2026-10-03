"""Unit tests for AirNow's -999 "no reading" sentinel.

observations.pm25 has CHECK (pm25 >= 0). AirNow reports -999 when it has no
valid value for an hour; passed through, that one row fails the insert for
the whole AirNow source.

A sentinel row is dropped (normalize_airnow_row returns None, which callers
already skip), not filled from another concentration field: the real row
had Value=-999 with RawConcentration=12.0, and a raw reading is not the
regulatory value AirNow withheld.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ingestion.connectors.airnow import get_airnow_pm25_records, normalize_airnow_row


def _red_bluff_row(**overrides):
    # Real AirNow /aq/data/ row (2021-08-05 19:00 UTC, PE-002 Dixie test
    # window) that failed observations_pm25_check before this fix.
    row = {
        "Latitude": 40.170917,
        "Longitude": -122.255667,
        "UTC": "2021-08-05T19:00",
        "Parameter": "PM2.5",
        "Unit": "UG/M3",
        "Value": -999.0,
        "RawConcentration": 12.0,
        "SiteName": "Red Bluff - Walnut office",
        "AgencyName": "Tehama County Air Pollution Control District",
        "FullAQSCode": "061030007",
        "IntlAQSCode": "840061030007",
    }
    row.update(overrides)
    return row


def _redding_row():
    # Real row from the same hour and response, with a valid value.
    return {
        "Latitude": 40.5497,
        "Longitude": -122.3792,
        "UTC": "2021-08-05T19:00",
        "Parameter": "PM2.5",
        "Unit": "UG/M3",
        "Value": 7.8,
        "RawConcentration": 7.0,
        "SiteName": "Redding",
        "AgencyName": "Shasta County Air Quality Management District",
        "FullAQSCode": "060890004",
        "IntlAQSCode": "840060890004",
    }


# ---------------------------------------------------------------------------
# Regression: -999 sentinel
# ---------------------------------------------------------------------------

def test_sentinel_row_is_dropped():
    assert normalize_airnow_row(_red_bluff_row()) is None


def test_sentinel_does_not_fall_back_to_raw_concentration():
    """RawConcentration=12.0 must not stand in for the withheld Value."""
    assert normalize_airnow_row(_red_bluff_row(RawConcentration=12.0)) is None


@pytest.mark.parametrize("value", [-999, -999.0, "-999", "-999.0", -1, "-0.5"])
def test_negative_values_are_dropped(value):
    assert normalize_airnow_row(_red_bluff_row(Value=value)) is None


def test_negative_raw_concentration_without_value_is_dropped():
    row = _red_bluff_row()
    del row["Value"]
    row["RawConcentration"] = -999.0

    assert normalize_airnow_row(row) is None


# ---------------------------------------------------------------------------
# Existing behavior (must not regress)
# ---------------------------------------------------------------------------

def test_valid_row_from_same_response_is_kept():
    record = normalize_airnow_row(_redding_row())

    assert record["observation"]["pm25"] == 7.8
    assert record["observation"]["correction"] == "regulatory"
    assert record["monitor"]["name"] == "Redding"


def test_zero_is_a_valid_reading():
    record = normalize_airnow_row(_red_bluff_row(Value=0.0))
    assert record["observation"]["pm25"] == 0.0


def test_row_with_no_concentration_still_raises():
    """Malformed rows still fail loudly; only the sentinel is skipped."""
    row = _red_bluff_row()
    del row["Value"]
    del row["RawConcentration"]

    with pytest.raises(ValueError, match="has no usable concentration"):
        normalize_airnow_row(row)


# ---------------------------------------------------------------------------
# End to end: the sentinel row no longer reaches the insert
# ---------------------------------------------------------------------------

def test_get_records_skips_sentinel_and_keeps_the_rest():
    rows = [_redding_row(), _red_bluff_row()]

    with patch("ingestion.connectors.airnow.fetch_airnow_rows", return_value=rows):
        records = get_airnow_pm25_records(api_key="x")

    assert [r["monitor"]["name"] for r in records] == ["Redding"]
    assert all(r["observation"]["pm25"] >= 0 for r in records)
