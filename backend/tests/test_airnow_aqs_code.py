"""AirNow AQS codes are normalized to 9 digits before identity and time offsets.

AirNow's FullAQSCode arrives as 9 digits for most sites ("060072003") and with
the "840" country prefix for some ("840060072003"); both must map to the same
monitor, and the time-offset table (keyed by 9 digits) must apply to either.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingestion.connectors.airnow import normalize_airnow_row, normalize_aqs_code


def _row(code: str, utc: str = "2020-09-10T20:00", site: str = "Paradise - Clark Road") -> dict:
    return {
        "UTC": utc, "Parameter": "PM2.5", "Unit": "UG/M3", "Value": 20.0, "RawConcentration": 12.0,
        "Latitude": 39.7586, "Longitude": -121.5864, "SiteName": site,
        "AgencyName": "Butte County AQMD", "FullAQSCode": code, "IntlAQSCode": code,
    }


@pytest.mark.parametrize("raw, expected", [
    ("840060072003", "060072003"),
    ("060072003", "060072003"),
    (" 840061030007 ", "061030007"),
    ("840TT5821016", "TT5821016"),  # tribal site (Morongo)
    ("84032005TRP1", "32005TRP1"),  # agency code (TRPA, Nevada)
    ("TT5821016", "TT5821016"),
    ("ABC123", "ABC123"),  # unknown short form: left alone
])
def test_normalize_aqs_code(raw, expected):
    assert normalize_aqs_code(raw) == expected


def test_prefixed_and_plain_codes_give_the_same_monitor():
    a = normalize_airnow_row(_row("840060072003"))
    b = normalize_airnow_row(_row("060072003"))
    assert a["monitor"]["external_id"] == b["monitor"]["external_id"]
    assert a["source_metadata"]["station_id"] == b["source_metadata"]["station_id"] == "060072003"


@pytest.mark.parametrize("code", ["061030007", "840061030007"])
def test_red_bluff_offset_applies_with_or_without_prefix(code):
    # Red Bluff labels are 1 h late from 2017-08-31 to 2021-09-14 (airnow_time_offsets.py).
    rec = normalize_airnow_row(_row(code, utc="2020-09-10T20:00", site="Red Bluff - Walnut office"))
    assert rec["observation"]["valid_at"] == datetime(2020, 9, 10, 19, tzinfo=timezone.utc)
