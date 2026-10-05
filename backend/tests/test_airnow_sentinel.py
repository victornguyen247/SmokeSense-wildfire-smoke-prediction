"""Unit tests for AirNow pm25: RawConcentration, sentinels and negatives.

pm25 is AirNow's RawConcentration, the 1-hour average. "Value" is the
NowCast (a 12-hour weighted average) and is never used: NowCast recomputed
from AQS hourly data reproduces Value exactly, while RawConcentration equals
the AQS hourly measurement (docs/data-sources.md).

observations.pm25 has CHECK (pm25 >= 0). Per Vuong: -999 ("no reading") is
dropped, raw values below -5 are dropped, and values from -5 up to 0 are
clamped to 0.

Fixtures are real /aq/data/ rows (dataType=C, verbose=1,
includerawconcentrations=1), as returned by fetch_airnow_rows.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ingestion.connectors.airnow import (
    RAW_NEGATIVE_FLOOR,
    get_airnow_pm25_records,
    normalize_airnow_row,
)


def _red_bluff_nowcast_sentinel_row(**overrides):
    # Real row, 2021-08-05 19:00 UTC: NowCast unavailable (-999) because the
    # two previous hours were missing, but the hourly reading was 12.0.
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


def _red_bluff_smoke_peak_row():
    # Real row, 2021-08-06 17:00 UTC: hourly 204.0, NowCast 117.8. AQS
    # hourly_88101 has 204.0 for this reading.
    return {
        "Latitude": 40.170917,
        "Longitude": -122.255667,
        "UTC": "2021-08-06T17:00",
        "Parameter": "PM2.5",
        "Unit": "UG/M3",
        "Value": 117.8,
        "RawConcentration": 204.0,
        "SiteName": "Red Bluff - Walnut office",
        "AgencyName": "Tehama County Air Pollution Control District",
        "FullAQSCode": "061030007",
        "IntlAQSCode": "840061030007",
    }


def _anaheim_small_negative_row(**overrides):
    # Real row, 2026-10-05 00:00 UTC: raw -3.2, NowCast 0.0.
    row = {
        "Latitude": 33.830586,
        "Longitude": -117.938509,
        "UTC": "2026-10-05T00:00",
        "Parameter": "PM2.5",
        "Unit": "UG/M3",
        "Value": 0.0,
        "RawConcentration": -3.2,
        "SiteName": "Anaheim",
        "AgencyName": "South Coast AQMD",
        "FullAQSCode": "060590007",
        "IntlAQSCode": "840060590007",
    }
    row.update(overrides)
    return row


def _carpinteria_raw_sentinel_row():
    # Real row, 2026-10-03 21:00 UTC: no hourly reading (-999), but a NowCast
    # of 14.9 from earlier hours -- falling back to Value would store it.
    return {
        "Latitude": 34.39424,
        "Longitude": -119.51472,
        "UTC": "2026-10-03T21:00",
        "Parameter": "PM2.5",
        "Unit": "UG/M3",
        "Value": 14.9,
        "RawConcentration": -999.0,
        "SiteName": "CarpPM",
        "AgencyName": "Santa Barbara County Air Pollution Control District",
        "FullAQSCode": "840060839001",
        "IntlAQSCode": "840060839001",
    }


def _redding_row():
    # Real row from the same response as the Red Bluff 19:00 row.
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


def _pm25(row):
    return normalize_airnow_row(row)["observation"]["pm25"]


# ---------------------------------------------------------------------------
# pm25 is RawConcentration, not the NowCast Value
# ---------------------------------------------------------------------------

def test_nowcast_sentinel_with_valid_raw_is_stored():
    """Value=-999 no longer drops the hour: the 1-hour reading was 12.0."""
    assert _pm25(_red_bluff_nowcast_sentinel_row()) == 12.0


def test_raw_not_nowcast_at_smoke_peak():
    assert _pm25(_red_bluff_smoke_peak_row()) == 204.0


def test_valid_row_from_same_response_uses_raw():
    record = normalize_airnow_row(_redding_row())

    assert record["observation"]["pm25"] == 7.0
    assert record["observation"]["correction"] == "regulatory"
    assert record["monitor"]["name"] == "Redding"


def test_value_is_ignored_entirely():
    row = _red_bluff_smoke_peak_row()
    row["Value"] = 9999.0
    assert _pm25(row) == 204.0


def test_snake_case_raw_alias():
    row = _red_bluff_smoke_peak_row()
    row["raw_concentration"] = row.pop("RawConcentration")
    assert _pm25(row) == 204.0


# ---------------------------------------------------------------------------
# Sentinels and negatives (RawConcentration)
# ---------------------------------------------------------------------------

def test_raw_sentinel_is_dropped_even_with_a_nowcast():
    assert normalize_airnow_row(_carpinteria_raw_sentinel_row()) is None


def test_small_negative_is_clamped_to_zero():
    assert _pm25(_anaheim_small_negative_row()) == 0.0


def test_negative_below_floor_is_dropped():
    # The Anaheim row with raw -7: no real raw value between -999 and -5
    # appeared in a 48-hour California pull, so this one is constructed.
    assert normalize_airnow_row(_anaheim_small_negative_row(RawConcentration=-7.0)) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        (-5.0, 0.0),       # floor itself is clamped
        (-4.8, 0.0),
        (-0.1, 0.0),
        (0.0, 0.0),
        ("-3.2", 0.0),     # string input
        (3.0, 3.0),
    ],
)
def test_clamp_range(raw, expected):
    assert _pm25(_anaheim_small_negative_row(RawConcentration=raw)) == expected


@pytest.mark.parametrize("raw", [-5.01, -7, -999, -999.0, "-999"])
def test_drop_range(raw):
    assert normalize_airnow_row(_anaheim_small_negative_row(RawConcentration=raw)) is None


def test_floor_constant():
    assert RAW_NEGATIVE_FLOOR == -5.0


# ---------------------------------------------------------------------------
# Missing RawConcentration fails loudly, never falls back to Value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [None, "", "x"])
def test_unusable_raw_raises(raw):
    row = _red_bluff_smoke_peak_row()
    row["RawConcentration"] = raw

    with pytest.raises(ValueError, match="no RawConcentration"):
        normalize_airnow_row(row)


def test_absent_raw_raises_instead_of_using_value():
    row = _red_bluff_smoke_peak_row()
    del row["RawConcentration"]

    with pytest.raises(ValueError, match="includerawconcentrations=1"):
        normalize_airnow_row(row)


# ---------------------------------------------------------------------------
# End to end through get_airnow_pm25_records
# ---------------------------------------------------------------------------

def test_get_records_applies_raw_rules():
    rows = [
        _redding_row(),
        _red_bluff_nowcast_sentinel_row(),
        _red_bluff_smoke_peak_row(),
        _anaheim_small_negative_row(),
        _carpinteria_raw_sentinel_row(),
    ]

    with patch("ingestion.connectors.airnow.fetch_airnow_rows", return_value=rows):
        records = get_airnow_pm25_records(api_key="x")

    assert [(r["monitor"]["name"], r["observation"]["pm25"]) for r in records] == [
        ("Redding", 7.0),
        ("Red Bluff - Walnut office", 12.0),
        ("Red Bluff - Walnut office", 204.0),
        ("Anaheim", 0.0),
    ]
