"""Unit tests for per-site AirNow UTC label corrections.

shift_hours is added to AirNow's UTC label to get the true hour: Red Bluff's
AirNow 2021-08-06T17:00 (204.0) is AQS GMT 16:00, so true = label - 1 h.

Fixtures are real /aq/data/ rows (dataType=C, verbose=1,
includerawconcentrations=1). Each Red Bluff case carries the AQS 88101
hourly value (POC 3, GMT columns) at the expected true hour, which equals
RawConcentration -- and differs at the uncorrected hour wherever the
correction matters.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from ingestion.connectors.airnow import normalize_airnow_row
from ingestion.connectors.airnow_time_offsets import (
    AIRNOW_TIME_OFFSETS,
    airnow_time_shift,
    max_abs_shift_hours,
)


RED_BLUFF = "061030007"


def _utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def _red_bluff_row(label, raw, value):
    return {
        "Latitude": 40.170917,
        "Longitude": -122.255667,
        "UTC": label,
        "Parameter": "PM2.5",
        "Unit": "UG/M3",
        "Value": value,
        "RawConcentration": raw,
        "SiteName": "Red Bluff - Walnut office",
        "AgencyName": "Tehama County Air Pollution Control District",
        "FullAQSCode": "061030007",
        "IntlAQSCode": "840061030007",
    }


# (AirNow label, RawConcentration, Value, expected true hour, AQS at true hour)
# Pairs are the last real row before each switch and the first one after.
RED_BLUFF_BOUNDARY_ROWS = [
    # End of the Jan-Feb 2017 early period; the archive gap follows.
    ("2017-02-10T21:00", 6.0, 4.8, "2017-02-10T22:00", 6.0),
    # First rows after the gap are correct, then late from 23:00.
    ("2017-08-31T21:00", 76.0, 85.7, "2017-08-31T21:00", 76.0),
    ("2017-08-31T23:00", 134.0, 114.9, "2017-08-31T22:00", 134.0),
    # 2021-09-14: consecutive hours, late until 15:00, correct from 16:00.
    ("2021-09-14T15:00", 61.0, 63.8, "2021-09-14T14:00", 61.0),
    ("2021-09-14T16:00", 26.0, 44.9, "2021-09-14T16:00", 26.0),
    # 2022-08-24: correct until 16:00, labels 17:00-19:00 missing, then late.
    ("2022-08-24T16:00", 9.0, 8.6, "2022-08-24T16:00", 9.0),
    ("2022-08-24T20:00", 4.0, -999.0, "2022-08-24T19:00", 4.0),
    # 2022-09-26: late until 13:00, then (after a gap in both sources) early.
    ("2022-09-26T13:00", 4.0, 3.6, "2022-09-26T12:00", 4.0),
    ("2022-09-26T23:00", 11.0, -999.0, "2022-09-27T00:00", 11.0),
    # 2022-10-01: early until 03:00 (04:00-06:00 fit too), 07:00 missing,
    # correct from 08:00.
    ("2022-10-01T03:00", 3.0, 2.7, "2022-10-01T04:00", 3.0),
    ("2022-10-01T08:00", 6.0, 5.0, "2022-10-01T08:00", 6.0),
    # 2023-01: correct until Jan 1 06:00, gap, late from Jan 4.
    ("2023-01-01T06:00", 5.0, 4.4, "2023-01-01T06:00", 5.0),
    ("2023-01-04T01:00", 5.0, 5.0, "2023-01-04T00:00", 5.0),
    # 2023-04-01: late until 06:00, 07:00 missing, correct from 09:00.
    ("2023-04-01T06:00", 5.0, 4.9, "2023-04-01T05:00", 5.0),
    ("2023-04-01T09:00", 4.0, 4.7, "2023-04-01T09:00", 4.0),
]


@pytest.mark.parametrize(
    "label, raw, value, true_hour, aqs", RED_BLUFF_BOUNDARY_ROWS,
    ids=[case[0] for case in RED_BLUFF_BOUNDARY_ROWS],
)
def test_red_bluff_boundary_rows(label, raw, value, true_hour, aqs):
    obs = normalize_airnow_row(_red_bluff_row(label, raw, value))["observation"]

    assert obs["valid_at"] == _utc(true_hour)
    assert obs["pm25"] == aqs


def test_red_bluff_smoke_peak_is_moved_to_aqs_hour():
    # The sign-convention example: AirNow 17:00 = AQS GMT 16:00 (204.0).
    record = normalize_airnow_row(
        _red_bluff_row("2021-08-06T17:00", 204.0, 117.8)
    )

    assert record["observation"]["valid_at"] == _utc("2021-08-06T16:00")
    assert record["source_metadata"]["source_timestamp"] == _utc("2021-08-06T16:00")


def test_red_bluff_uncorrected_period_is_unchanged():
    # Real row, 2024-01-10 18:00 UTC: AQS GMT 18:00 = 4.6 (17:00 = 6.1).
    obs = normalize_airnow_row(
        _red_bluff_row("2024-01-10T18:00", 4.6, 4.5)
    )["observation"]

    assert obs["valid_at"] == _utc("2024-01-10T18:00")


def test_other_station_in_red_bluff_period_is_unchanged():
    # Real Redding row, 2021-08-05 19:00 UTC, inside Red Bluff's late period.
    # AQS 88502 GMT 19:00 = 7.0 (18:00 = 9.0).
    row = {
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

    assert normalize_airnow_row(row)["observation"]["valid_at"] == _utc("2021-08-05T19:00")


def test_chico_is_unchanged():
    # Real Chico - East row, 2021-09-10 18:00 UTC, inside Red Bluff's late
    # period. AQS 88101 GMT 18:00 = 7.0 (17:00 = 9.0).
    row = {
        "Latitude": 39.76168,
        "Longitude": -121.84047,
        "UTC": "2021-09-10T18:00",
        "Parameter": "PM2.5",
        "Unit": "UG/M3",
        "Value": 8.3,
        "RawConcentration": 7.0,
        "SiteName": "Chico -  East",
        "AgencyName": "California Air Resources Board",
        "FullAQSCode": "060070008",
        "IntlAQSCode": "840060070008",
    }

    assert normalize_airnow_row(row)["observation"]["valid_at"] == _utc("2021-09-10T18:00")


# ---------------------------------------------------------------------------
# Lookup semantics: start inclusive, end exclusive, keyed on station_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label, hours",
    [
        ("2017-01-03T14:00", 0),     # before the first encoded period
        ("2017-01-03T15:00", +1),    # start is inclusive
        ("2017-02-10T22:00", 0),     # end is exclusive
        ("2017-08-31T21:00", 0),
        ("2017-08-31T22:00", -1),
        ("2021-09-14T15:00", -1),
        ("2021-09-14T16:00", 0),
        ("2022-08-24T16:00", 0),
        ("2022-08-24T17:00", -1),
        ("2022-09-26T13:00", -1),
        ("2022-09-26T14:00", +1),    # late period ends where early begins
        ("2022-10-01T06:00", +1),
        ("2022-10-01T07:00", 0),
        ("2023-01-01T06:00", 0),
        ("2023-01-01T07:00", -1),
        ("2023-04-01T06:00", -1),
        ("2023-04-01T07:00", 0),
        ("2016-06-01T00:00", 0),     # before any evidence: unchanged
    ],
)
def test_red_bluff_shift_at_boundaries(label, hours):
    assert airnow_time_shift(RED_BLUFF, _utc(label)) == timedelta(hours=hours)


def test_lookup_uses_station_id_form():
    # The connector's station_id for /aq/data/ rows is FullAQSCode; the
    # 12-digit IntlAQSCode form is not a key.
    assert airnow_time_shift("840061030007", _utc("2021-08-06T17:00")) == timedelta(0)


def test_periods_are_sorted_and_do_not_overlap():
    for station_id, periods in AIRNOW_TIME_OFFSETS.items():
        for period in periods:
            assert period.start_utc < period.end_utc, station_id
            assert period.start_utc.tzinfo is timezone.utc, station_id
            assert period.shift_hours != 0, station_id
            assert period.evidence.strip(), station_id
        for earlier, later in zip(periods, periods[1:]):
            assert earlier.end_utc <= later.start_utc, station_id


def test_max_abs_shift_hours():
    assert max_abs_shift_hours() == 1

    with patch.dict(AIRNOW_TIME_OFFSETS, clear=True):
        assert max_abs_shift_hours() == 0
