"""Unit tests for the coverage report's FIRMS and AirNow null_counts.

Fixtures are real rows from the 2026-10-03 PE-002 (Dixie Fire) test window,
2021-08-05..06, bbox -123.1,39.3,-120.0,41.2, run through the real
normalizers.

FIRMS: bright_t31_k is counted over MODIS rows only -- the VIIRS CSV has no
bright_t31 column (it has bright_ti5), so it is null on every VIIRS row by
design.

AirNow: every nullable stored column is null by design, so null_counts
reports missing station-hours instead. In the real window, Red Bluff -
Walnut office had 45 of 48 hours: 17:00 and 18:00 UTC on Aug 5 were never
sent, and 19:00 was the -999 sentinel that normalize_airnow_row drops.

Red Bluff's AirNow labels are 1 h late in this window, so normalize_airnow_row
moves every reading 1 h earlier (airnow_time_offsets.py). The batch pads its
AirNow fetch by the largest configured shift (1 h) on both ends, so the
fixtures carry labels Aug 4 23:00 .. Aug 7 00:00: Red Bluff's label Aug 7
00:00 fills Aug 6 23:00, and rows corrected to outside the window are
dropped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from ingestion.batch.batch_ingest import (
    PilotEvent,
    count_firms_nulls,
    count_missing_station_hours,
)
from ingestion.connectors.airnow import get_airnow_pm25_records
from ingestion.connectors.airnow_time_offsets import (
    AIRNOW_TIME_OFFSETS,
    OffsetPeriod,
)
from ingestion.connectors.firms import normalize_firms_row


# ---------------------------------------------------------------------------
# FIRMS
# ---------------------------------------------------------------------------

def _viirs_snpp_row(**overrides):
    # Real VIIRS_SNPP_SP row, 2021-08-05 08:58 UTC.
    row = {
        "latitude": "40.31534", "longitude": "-121.2429", "bright_ti4": "301.53",
        "scan": "0.56", "track": "0.69", "acq_date": "2021-08-05",
        "acq_time": "858", "satellite": "N", "instrument": "VIIRS",
        "confidence": "n", "version": "2", "bright_ti5": "287.68",
        "frp": "5.22", "daynight": "N", "type": "0",
    }
    row.update(overrides)
    return normalize_firms_row(row, source="VIIRS_SNPP_SP")


def _modis_terra_row(**overrides):
    # Real MODIS_SP Terra row, 2021-08-05 06:04 UTC.
    row = {
        "latitude": "39.931", "longitude": "-121.1963", "brightness": "307.9",
        "scan": "1", "track": "1", "acq_date": "2021-08-05", "acq_time": "604",
        "satellite": "Terra", "instrument": "MODIS", "confidence": "73",
        "version": "6.03", "bright_t31": "289.5", "frp": "9.3",
        "daynight": "N", "type": "0",
    }
    row.update(overrides)
    return normalize_firms_row(row, source="MODIS_SP")


def _modis_aqua_row(**overrides):
    # Real MODIS_SP Aqua row, 2021-08-05 10:20 UTC.
    row = {
        "latitude": "40.0185", "longitude": "-121.1265", "brightness": "300.4",
        "scan": "1.2", "track": "1.1", "acq_date": "2021-08-05",
        "acq_time": "1020", "satellite": "Aqua", "instrument": "MODIS",
        "confidence": "25", "version": "6.03", "bright_t31": "290.3",
        "frp": "5.6", "daynight": "N", "type": "0",
    }
    row.update(overrides)
    return normalize_firms_row(row, source="MODIS_SP")


def test_real_rows_have_no_nulls():
    records = [_viirs_snpp_row(), _modis_terra_row(), _modis_aqua_row()]

    assert count_firms_nulls(records) == {
        "confidence_level": 0,
        "frp_mw": 0,
        "scan_km": 0,
        "track_km": 0,
        "daynight": 0,
        "bright_t31_k": 0,
    }


def test_viirs_missing_bright_t31_is_not_counted():
    """VIIRS has no T31 band: its null bright_t31_k is by design."""
    viirs = _viirs_snpp_row()
    assert viirs["bright_t31_k"] is None

    counts = count_firms_nulls([viirs] * 100 + [_modis_terra_row()])
    assert counts["bright_t31_k"] == 0


def test_modis_missing_bright_t31_is_counted():
    records = [_modis_terra_row(bright_t31=""), _modis_aqua_row(), _viirs_snpp_row()]
    assert count_firms_nulls(records)["bright_t31_k"] == 1


def test_blank_numeric_fields_are_counted():
    records = [
        _viirs_snpp_row(frp=""),
        _modis_terra_row(scan="", track=""),
        _modis_aqua_row(daynight=""),
    ]
    counts = count_firms_nulls(records)

    assert counts["frp_mw"] == 1
    assert counts["scan_km"] == 1
    assert counts["track_km"] == 1
    assert counts["daynight"] == 1


def test_unrecognized_confidence_is_counted():
    """A null confidence_level would fail the NOT NULL insert; counting it
    first means the computed report says why."""
    records = [_modis_terra_row(confidence="101"), _viirs_snpp_row(confidence="x")]
    assert count_firms_nulls(records)["confidence_level"] == 2


def test_empty_firms_window():
    assert count_firms_nulls([]) == {
        "confidence_level": 0, "frp_mw": 0, "scan_km": 0, "track_km": 0,
        "daynight": 0, "bright_t31_k": 0,
    }


# ---------------------------------------------------------------------------
# AirNow
# ---------------------------------------------------------------------------

# The six real sites in the window (raw /aq/data/ fields as returned).
AIRNOW_SITES = [
    ("Weaverville", 40.734722, -122.941109, "061050002"),
    ("Redding", 40.5497, -122.3792, "060890004"),
    ("Red Bluff - Walnut office", 40.170917, -122.255667, "061030007"),
    ("Willows-Colusa", 39.53387, -122.190834, "060210003"),
    ("Chico -  East", 39.76168, -121.84047, "060070008"),
    ("Gridley", 39.32756, -121.66881, "060074001"),
]
WINDOW_START = datetime(2021, 8, 5, tzinfo=timezone.utc)


def _airnow_raw_row(site, hour, value=10.0):
    name, lat, lon, aqs = site
    return {
        "Latitude": lat, "Longitude": lon,
        "UTC": (WINDOW_START + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M"),
        "Parameter": "PM2.5", "Unit": "UG/M3",
        "Value": value, "RawConcentration": value,
        "SiteName": name, "AgencyName": "x",
        "FullAQSCode": aqs, "IntlAQSCode": "840" + aqs,
    }


# Labels the batch requests for the 2-day window, padded by 1 h each side.
PADDED_HOURS = range(-1, 49)


def _real_window_raw_rows():
    """Raw rows matching the real window: 6 sites x 48 hours, except Red
    Bluff 17:00/18:00 never sent and 19:00 sent as -999, plus each site's
    padding labels (Aug 4 23:00 and Aug 7 00:00)."""
    red_bluff = AIRNOW_SITES[2]
    rows = []
    for site in AIRNOW_SITES:
        for hour in PADDED_HOURS:
            if site is red_bluff and hour in (17, 18):
                continue
            value = -999.0 if (site is red_bluff and hour == 19) else 10.0
            rows.append(_airnow_raw_row(site, hour, value))
    return rows


def _records(raw_rows):
    with patch("ingestion.connectors.airnow.fetch_airnow_rows", return_value=raw_rows):
        return get_airnow_pm25_records(api_key="x")


def test_real_window_has_three_missing_station_hours():
    raw = _real_window_raw_rows()
    assert len(raw) == 286 + 12  # the real response, plus 2 padding labels per site

    records = _records(raw)
    assert len(records) == 285 + 12  # -999 dropped

    assert count_missing_station_hours(records, "2021-08-05", "2021-08-06") == 3


def test_complete_window_has_no_missing_hours():
    raw = [_airnow_raw_row(site, h) for site in AIRNOW_SITES for h in PADDED_HOURS]
    assert count_missing_station_hours(_records(raw), "2021-08-05", "2021-08-06") == 0


def test_sentinel_hour_counts_as_missing():
    site = AIRNOW_SITES[4]  # Chico: no time correction
    raw = [_airnow_raw_row(site, h, -999.0 if h == 19 else 10.0) for h in range(24)]
    assert count_missing_station_hours(_records(raw), "2021-08-05", "2021-08-05") == 1


def test_duplicate_hours_count_once():
    site = AIRNOW_SITES[0]
    raw = [_airnow_raw_row(site, h) for h in range(24)] + [_airnow_raw_row(site, 0)]
    assert count_missing_station_hours(_records(raw), "2021-08-05", "2021-08-05") == 0


def test_rows_outside_window_are_ignored():
    site = AIRNOW_SITES[0]
    raw = [_airnow_raw_row(site, h) for h in range(24)] + [_airnow_raw_row(site, 30)]
    assert count_missing_station_hours(_records(raw), "2021-08-05", "2021-08-05") == 0


def test_no_rows_means_no_known_sites():
    """A site that sent nothing isn't in the response, so it can't be counted."""
    assert count_missing_station_hours([], "2021-08-05", "2021-08-06") == 0


# ---------------------------------------------------------------------------
# Wiring: ingest_event puts both into the report
# ---------------------------------------------------------------------------

@patch("ingestion.batch.batch_ingest.mark_progress")
@patch("ingestion.batch.batch_ingest.SessionLocal")
@patch("ingestion.batch.batch_ingest.get_purpleair_pm25_records", return_value=[])
@patch("ingestion.batch.batch_ingest.get_ncei_weather_records", return_value=[])
@patch("ingestion.batch.batch_ingest.insert_weather_observations", return_value=0)
@patch("ingestion.batch.batch_ingest.insert_airnow_observations", return_value=285)
@patch("ingestion.batch.batch_ingest.insert_fire_detections", return_value=3)
@patch("ingestion.batch.batch_ingest.get_airnow_pm25_records")
@patch("ingestion.batch.batch_ingest.get_firms_records")
def test_ingest_event_reports_firms_and_airnow_null_counts(
    get_firms, get_airnow, *_mocks,
):
    from ingestion.batch.batch_ingest import ingest_event

    get_firms.return_value = [
        _viirs_snpp_row(), _modis_terra_row(bright_t31=""), _modis_aqua_row(),
    ]
    get_airnow.return_value = _records(_real_window_raw_rows())

    event = PilotEvent(
        event_id="TEST-PE002-DIXIE", name="t", bbox="-123.1,39.3,-120.0,41.2",
        start_date="2021-08-05", end_date="2021-08-06",
        firms_products=["VIIRS_SNPP_SP"],
    )
    sources = ingest_event(event).to_dict()["sources"]

    assert sources["firms"]["null_counts"] == {
        "confidence_level": 0, "frp_mw": 0, "scan_km": 0, "track_km": 0,
        "daynight": 0, "bright_t31_k": 1,
    }
    assert sources["airnow"]["null_counts"] == {"pm25_missing_station_hours": 3}
    # Only rows whose corrected hour is inside the event are counted.
    assert sources["airnow"]["rows_fetched"] == 285

    # One padded window: the event's 48 hours plus 1 h each side.
    kwargs = get_airnow.call_args.kwargs
    assert (kwargs["start_date"], kwargs["start_hour"]) == ("2021-08-04", "23")
    assert (kwargs["end_date"], kwargs["end_hour"]) == ("2021-08-07", "00")


def _fetch_by_label(sites):
    """Fake fetch_airnow_rows: one row per site for every requested label."""
    def fetch(api_key, bbox, start_date, start_hour, end_date, end_hour, verbose=False):
        start = datetime.fromisoformat(f"{start_date}T{start_hour}:00+00:00")
        end = datetime.fromisoformat(f"{end_date}T{end_hour}:00+00:00")
        hours = int((end - start).total_seconds() // 3600)
        return [
            _airnow_raw_row(site, (start - WINDOW_START).total_seconds() / 3600 + h)
            for site in sites
            for h in range(hours + 1)
        ]
    return fetch


@patch("ingestion.batch.batch_ingest.mark_progress")
@patch("ingestion.batch.batch_ingest.SessionLocal")
@patch("ingestion.batch.batch_ingest.get_purpleair_pm25_records", return_value=[])
@patch("ingestion.batch.batch_ingest.get_ncei_weather_records", return_value=[])
@patch("ingestion.batch.batch_ingest.insert_weather_observations", return_value=0)
@patch("ingestion.batch.batch_ingest.insert_airnow_observations")
@patch("ingestion.batch.batch_ingest.insert_fire_detections", return_value=0)
@patch("ingestion.batch.batch_ingest.get_firms_records", return_value=[])
def test_shifted_sites_keep_first_and_last_event_hours(
    _firms, _insert_fire, insert_airnow, *_mocks,
):
    """A -1 site and a +1 site both cover every event hour; an unshifted
    site keeps exactly its labels."""
    from ingestion.batch.batch_ingest import ingest_event

    redding, red_bluff, chico = AIRNOW_SITES[1], AIRNOW_SITES[2], AIRNOW_SITES[4]
    # Test-only +1 period for Redding (the real config has none in 2021);
    # Red Bluff's real -1 period covers the window.
    plus_one = OffsetPeriod(
        datetime(2021, 8, 1, tzinfo=timezone.utc),
        datetime(2021, 8, 10, tzinfo=timezone.utc),
        +1,
        "test only",
    )
    insert_airnow.side_effect = lambda session, rows: len(rows)

    event = PilotEvent(
        event_id="TEST-SHIFT", name="t", bbox="-123.1,39.3,-120.0,41.2",
        start_date="2021-08-05", end_date="2021-08-06",
        firms_products=["VIIRS_SNPP_SP"],
    )
    with patch.dict(AIRNOW_TIME_OFFSETS, {redding[3]: [plus_one]}), patch(
        "ingestion.connectors.airnow.fetch_airnow_rows",
        side_effect=_fetch_by_label([redding, red_bluff, chico]),
    ):
        sources = ingest_event(event).to_dict()["sources"]

    # First call is AirNow; PurpleAir writes through the same function after.
    stored = insert_airnow.call_args_list[0].args[1]
    window = {WINDOW_START + timedelta(hours=h) for h in range(48)}
    for name, *_ in (redding, red_bluff, chico):
        hours = [r["observation"]["valid_at"] for r in stored if r["monitor"]["name"] == name]
        assert sorted(hours) == sorted(window), name
        assert min(hours) == datetime(2021, 8, 5, 0, tzinfo=timezone.utc)
        assert max(hours) == datetime(2021, 8, 6, 23, tzinfo=timezone.utc)

    assert sources["airnow"]["rows_fetched"] == 3 * 48
    assert sources["airnow"]["null_counts"] == {"pm25_missing_station_hours": 0}
