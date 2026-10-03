from datetime import date, datetime, timezone

import httpx
import pytest

from ingestion.connectors import ncei

# Shaped like the NCEI Access Data Service CSV (global-hourly, quoted header).
CSV_BODY = (
    '"STATION","DATE","SOURCE","LATITUDE","LONGITUDE","ELEVATION","NAME",'
    '"REPORT_TYPE","CALL_SIGN","QUALITY_CONTROL","WND","TMP","DEW","SLP","AA1"\n'
    '"72592024257","2020-09-09T00:53:00","7","40.5178","-122.2986","153.9",'
    '"REDDING MUNICIPAL AIRPORT, CA US","FM-15","KRDD ","V020",'
    '"320,1,N,0036,1","+0306,1","+0072,1","10112,1","01,0000,9,1"\n'
    '"72592024257","2020-09-09T23:59:00","6","40.5178","-122.2986","153.9",'
    '"REDDING MUNICIPAL AIRPORT, CA US","SOD  ","99999","V020",'
    '"","","","",""\n'
)

ISD_HISTORY = (
    '"USAF","WBAN","STATION NAME","CTRY","STATE","ICAO","LAT","LON","ELEV(M)","BEGIN","END"\n'
    '"725920","24257","REDDING MUNICIPAL AIRPORT","US","CA","KRDD","+40.518","-122.299","+0153.9","19860101","20260920"\n'
    '"724830","23232","SACRAMENTO EXECUTIVE AIRPORT","US","CA","KSAC","+38.507","-121.495","+0004.6","19450101","20260920"\n'
    '"999999","99999","CLOSED STATION","US","CA","","+38.600","-121.500","+0010.0","19700101","19991231"\n'
    '"999998","99999","NO COORDS","US","CA","","","","","19700101","20260920"\n'
)


def base_row(**overrides):
    row = {
        "STATION": "72592024257",
        "DATE": "2020-09-09T00:53:00",
        "LATITUDE": "40.5178",
        "LONGITUDE": "-122.2986",
        "NAME": "REDDING",
        "REPORT_TYPE": "FM-15",
        "CALL_SIGN": "KRDD ",
        "WND": "320,1,N,0036,1",
        "TMP": "+0306,1",
        "DEW": "+0072,1",
        "SLP": "10112,1",
        "AA1": "01,0005,9,1",
    }
    row.update(overrides)
    return row


# --- ISD field decoding ------------------------------------------------------


def test_parse_wind():
    assert ncei.parse_wind("320,1,N,0036,1") == (320.0, 3.6, True)


def test_parse_wind_calm():
    assert ncei.parse_wind("999,9,C,0000,1") == (None, 0.0, True)


def test_parse_wind_missing():
    assert ncei.parse_wind("999,9,9,9999,9") == (None, None, True)


def test_parse_wind_rejects_bad_quality():
    assert ncei.parse_wind("320,3,N,0036,1") == (None, 3.6, False)


def test_parse_tenths():
    assert ncei.parse_tenths("-0012,1", missing="+9999") == (-1.2, True)
    assert ncei.parse_tenths("+9999,9", missing="+9999") == (None, True)
    assert ncei.parse_tenths("+0306,7", missing="+9999") == (None, False)
    assert ncei.parse_tenths("10112,1", missing="99999") == (1011.2, True)


def test_parse_precip_uses_one_hour_period_only():
    assert ncei.parse_precip_1h({"AA1": "06,0020,9,1"}) == (None, True)
    assert ncei.parse_precip_1h({"AA1": "06,0020,9,1", "AA2": "01,0005,9,1"}) == (
        0.5,
        True,
    )


# --- Row normalization -------------------------------------------------------


def test_normalize_row():
    ingested = datetime(2026, 9, 30, tzinfo=timezone.utc)
    record = ncei.normalize_ncei_row(base_row(), ingested_at=ingested)

    assert record["station_id"] == "KRDD"
    assert record["valid_at"] == datetime(2020, 9, 9, 0, 53, tzinfo=timezone.utc)
    assert record["geom_wkt"] == "POINT(-122.2986 40.5178)"
    assert record["wind_dir_deg"] == 320.0
    assert record["wind_speed_ms"] == 3.6
    assert record["temp_c"] == 30.6
    assert record["rh_pct"] == pytest.approx(23.1, abs=0.2)
    assert record["pressure_hpa"] == 1011.2
    assert record["precip_1h_mm"] == 0.5
    assert record["qc_flag"] == "V"
    assert record["received_at"] == ingested
    assert record["source_metadata"]["ncei_station_id"] == "72592024257"


def test_station_icao_wins_over_call_sign():
    station = {"icao": "KRDD", "latitude": 40.5, "longitude": -122.3}
    record = ncei.normalize_ncei_row(base_row(CALL_SIGN="99999"), station)
    assert record["station_id"] == "KRDD"


def test_falls_back_to_ncei_id_without_call_sign():
    record = ncei.normalize_ncei_row(base_row(CALL_SIGN="99999"))
    assert record["station_id"] == "72592024257"


def test_skips_daily_summary_rows():
    assert ncei.normalize_ncei_row(base_row(REPORT_TYPE="SOD  ")) is None


def test_bad_quality_value_is_dropped_and_flagged():
    record = ncei.normalize_ncei_row(base_row(TMP="+0306,3"))

    assert record["temp_c"] is None
    assert record["rh_pct"] is None
    assert record["qc_flag"] == "suspect"


def test_missing_coordinates_raise():
    with pytest.raises(ValueError):
        ncei.normalize_ncei_row(base_row(LATITUDE="", LONGITUDE=""))


# --- Station selection -------------------------------------------------------


def test_parse_isd_stations_skips_rows_without_coordinates():
    stations = ncei.parse_isd_stations(ISD_HISTORY)

    assert [s["ncei_id"] for s in stations] == [
        "72592024257",
        "72483023232",
        "99999999999",
    ]
    assert stations[0]["icao"] == "KRDD"
    assert stations[2]["icao"] is None


def test_select_by_bbox_and_active_period():
    stations = ncei.parse_isd_stations(ISD_HISTORY)

    selected = ncei.select_stations(
        stations,
        bbox="-122.5,38.0,-120.5,39.5",
        start_date="2020-09-01",
        end_date="2020-09-30",
    )

    # Redding is outside the box; the closed station ended in 1999.
    assert [s["icao"] for s in selected] == ["KSAC"]


def test_select_by_explicit_ids():
    stations = ncei.parse_isd_stations(ISD_HISTORY)

    selected = ncei.select_stations(stations, station_ids=["krdd", "72483023232"])

    assert {s["icao"] for s in selected} == {"KRDD", "KSAC"}


def test_date_chunks():
    assert ncei.date_chunks("2020-01-01", "2020-01-05", chunk_days=2) == [
        (date(2020, 1, 1), date(2020, 1, 2)),
        (date(2020, 1, 3), date(2020, 1, 4)),
        (date(2020, 1, 5), date(2020, 1, 5)),
    ]


def test_date_chunks_rejects_reversed_range():
    with pytest.raises(ValueError):
        ncei.date_chunks("2020-01-05", "2020-01-01")


# --- HTTP --------------------------------------------------------------------


def test_fetch_rows_parses_csv_and_chunks_requests():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=CSV_BODY)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = ncei.fetch_ncei_rows("72592024257", "2020-09-01", "2020-10-15", client)

    assert len(requests) == 2  # 31-day chunks
    assert requests[0].url.params["startDate"] == "2020-09-01T00:00:00"
    assert requests[0].url.params["endDate"] == "2020-10-01T23:59:59"
    assert requests[1].url.params["startDate"] == "2020-10-02T00:00:00"
    assert len(rows) == 4
    assert rows[0]["WND"] == "320,1,N,0036,1"


def test_fetch_rows_empty_body_is_no_data():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=""))
    )
    assert ncei.fetch_ncei_rows("72592024257", "2020-09-01", "2020-09-01", client) == []


def test_fetch_rows_raises_on_error_body():
    body = '{"errorMessage": "Invalid station"}'
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))
    )

    with pytest.raises(RuntimeError, match="unexpected response"):
        ncei.fetch_ncei_rows("bad", "2020-09-01", "2020-09-01", client)


def test_fetch_rows_raises_on_http_error():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad"))
    )

    with pytest.raises(RuntimeError, match="HTTP 400"):
        ncei.fetch_ncei_rows("bad", "2020-09-01", "2020-09-01", client)
