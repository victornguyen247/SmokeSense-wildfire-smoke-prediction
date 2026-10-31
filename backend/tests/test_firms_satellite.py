"""Unit tests for FIRMS satellite-name normalization.

fire_detections.satellite has CHECK (satellite IN ('MODIS_Terra',
'MODIS_Aqua', 'VIIRS_SNPP', 'VIIRS_NOAA20', 'VIIRS_NOAA21')). An
unrecognized raw code passes through unchanged and crashes the insert.

The FIRMS archive (_SP) feeds use different VIIRS codes than the NRT
feeds: VIIRS_NOAA20_SP sends "N20", not "J".
"""

from __future__ import annotations

import pytest

from ingestion.connectors.firms import normalize_firms_row


def _viirs_noaa20_sp_row(**overrides):
    # Real VIIRS_NOAA20_SP row (2021-08-05 09:49 UTC, Dixie Fire area) that
    # failed fire_detections_satellite_check before "N20" was mapped.
    row = {
        "latitude": "39.93137",
        "longitude": "-121.20034",
        "bright_ti4": "327.24",
        "scan": "0.41",
        "track": "0.37",
        "acq_date": "2021-08-05",
        "acq_time": "949",
        "satellite": "N20",
        "instrument": "VIIRS",
        "confidence": "n",
        "version": "2",
        "bright_ti5": "288.46",
        "frp": "1.41",
        "daynight": "N",
        "type": "0",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Regression: archive NOAA-20 code
# ---------------------------------------------------------------------------

def test_noaa20_archive_code_maps_to_schema_name():
    record = normalize_firms_row(_viirs_noaa20_sp_row(), source="VIIRS_NOAA20_SP")

    assert record["satellite"] == "VIIRS_NOAA20"
    assert record["product"] == "SP"
    assert record["confidence_level"] == "nominal"


@pytest.mark.parametrize("raw", ["n20", " N20 ", "N20"])
def test_noaa20_archive_code_is_case_and_space_insensitive(raw):
    record = normalize_firms_row(
        _viirs_noaa20_sp_row(satellite=raw), source="VIIRS_NOAA20_SP"
    )
    assert record["satellite"] == "VIIRS_NOAA20"


# ---------------------------------------------------------------------------
# Existing codes (must not regress)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, source, expected",
    [
        ("N", "VIIRS_SNPP_SP", "VIIRS_SNPP"),
        ("N", "VIIRS_SNPP_NRT", "VIIRS_SNPP"),
        ("J", "VIIRS_NOAA20_NRT", "VIIRS_NOAA20"),
        ("1", "VIIRS_NOAA21_NRT", "VIIRS_NOAA21"),
    ],
)
def test_existing_viirs_codes(raw, source, expected):
    record = normalize_firms_row(_viirs_noaa20_sp_row(satellite=raw), source=source)
    assert record["satellite"] == expected


@pytest.mark.parametrize("raw, expected", [("Terra", "MODIS_Terra"), ("Aqua", "MODIS_Aqua")])
def test_modis_codes(raw, expected):
    record = normalize_firms_row(
        _viirs_noaa20_sp_row(satellite=raw, instrument="MODIS", confidence="75"),
        source="MODIS_SP",
    )
    assert record["satellite"] == expected
