"""DATA-06 live NWS job: NCEI-identical field mapping, METAR reports only, partial failures."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from ingestion.connectors.ncei import normalize_ncei_row
from ingestion.connectors.nws import normalize_nws_observation, quantity, SPEED_TO_MS
from ingestion.connectors.nws_stations import NO_NWS_STATION, NWS_STATIONS
from ingestion.live import nws
from ingestion.normalize import relative_humidity_from_dewpoint

PAGES = json.loads(
    (Path(__file__).parent / "fixtures/live/nws_krdd_observations.json").read_text()
)
NOW = datetime(2021, 8, 6, 18, 5, tzinfo=timezone.utc)
UA = "SmokeSense-test (ops@smokesense.test)"
METAR_1753 = PAGES["page1"]["features"][1]


def utc(text_: str) -> datetime:
    return datetime.fromisoformat(text_).replace(tzinfo=timezone.utc)


def mock_client(
    seen: list | None = None, fail: frozenset[str] = frozenset()
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        station = request.url.path.split("/")[2]
        if station in fail:
            return httpx.Response(500, text="upstream error")
        if request.url.params.get("cursor") == "page2":
            return httpx.Response(200, json=PAGES["page2"])
        if request.url.params.get("cursor"):
            return httpx.Response(200, json={"features": []})
        return httpx.Response(200, json=PAGES["page1"])

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def user_agent(monkeypatch):
    monkeypatch.setattr(nws.settings, "nws_user_agent", UA)


def test_field_mapping_matches_the_serving_contract():
    r = normalize_nws_observation(METAR_1753, ingested_at=NOW)
    assert r["station_id"] == "KRDD" and r["valid_at"] == utc("2021-08-06T17:53")
    assert r["wind_speed_ms"] == 3.6  # 12.96 km/h / 3.6
    assert r["wind_dir_deg"] == 20
    assert r["temp_c"] == 17.8
    assert r["rh_pct"] == relative_humidity_from_dewpoint(
        17.8, 1.1
    )  # not NWS relativeHumidity (99)
    assert r["pressure_hpa"] == 1008.7  # seaLevelPressure, not barometricPressure
    assert r["precip_1h_mm"] == 0.0
    assert r["qc_flag"] == "V"


def test_same_report_decodes_like_ncei():
    """Parity: the 17:53 METAR as NCEI ISD packs it gives the same weather row."""
    isd = {
        "STATION": "72592024257", "DATE": "2021-08-06T17:53:00", "REPORT_TYPE": "FM-15",
        "LATITUDE": "40.5", "LONGITUDE": "-122.3", "CALL_SIGN": "KRDD ", "NAME": "REDDING",
        "WND": "020,1,N,0036,1", "TMP": "+0178,1", "DEW": "+0011,1", "SLP": "10087,1",
        "AA1": "01,0000,9,1",
    }  # fmt: skip
    ncei = normalize_ncei_row(
        isd, {"icao": "KRDD", "latitude": 40.5, "longitude": -122.3}, NOW
    )
    live = normalize_nws_observation(METAR_1753, ingested_at=NOW)
    fields = ("station_id", "valid_at", "geom_wkt", "wind_speed_ms", "wind_dir_deg", "temp_c",
              "rh_pct", "pressure_hpa", "precip_1h_mm", "qc_flag")  # fmt: skip
    assert {f: live[f] for f in fields} == {f: ncei[f] for f in fields}


def test_calm_missing_and_qc():
    page = PAGES["page1"]["features"]
    assert normalize_nws_observation(page[0]) is None  # 5-minute reading, not a METAR
    calm = normalize_nws_observation(
        page[2]
    )  # METAR fields without raw text, calm wind
    assert (calm["wind_speed_ms"], calm["wind_dir_deg"], calm["pressure_hpa"]) == (
        0.0,
        None,
        1010.2,
    )
    assert calm["precip_1h_mm"] is None  # missing stays missing, never 0
    rejected = normalize_nws_observation(page[3])  # temperature QC "X"
    assert rejected["temp_c"] is None and rejected["rh_pct"] is None
    assert rejected["pressure_hpa"] is None and rejected["qc_flag"] == "suspect"


def test_units_are_read_per_value():
    assert quantity({"unitCode": "wmoUnit:m_s-1", "value": 4.0}, SPEED_TO_MS) == (
        4.0,
        True,
    )
    assert quantity({"unitCode": "wmoUnit:kn", "value": 10}, SPEED_TO_MS)[
        0
    ] == pytest.approx(5.14444)
    assert quantity({"unitCode": "wmoUnit:furlong", "value": 1}, SPEED_TO_MS) == (
        None,
        False,
    )
    assert quantity({"unitCode": "wmoUnit:km_h-1", "value": None}, SPEED_TO_MS) == (
        None,
        True,
    )


def test_stations_are_the_training_stations():
    assert len(NWS_STATIONS) == 109 and len(set(NWS_STATIONS)) == 109
    assert len(NO_NWS_STATION) == 5 and not set(NO_NWS_STATION) & set(NWS_STATIONS)
    assert {"KRDD", "KSAC", "KRBL", "KRNO"} <= set(NWS_STATIONS)


def test_run_pages_windows_and_sends_user_agent(live_db):
    seen: list[httpx.Request] = []
    result = nws.run(
        session_factory=live_db, client=mock_client(seen), now=NOW, stations=["KRDD"],
        sleep=lambda s: None,
    )  # fmt: skip

    assert result["status"] == "success"
    assert result["rows_fetched"] == 5  # in-window observations across both pages
    assert result["rows_written"] == 4  # METAR reports only
    assert [r.url.params.get("cursor") for r in seen] == [
        None,
        "page2",
    ]  # stops at the window
    assert all(r.headers["user-agent"] == UA for r in seen)
    assert seen[0].url.params["start"] == "2021-08-03T18:05:00Z"
    with live_db() as s:
        times = s.scalars(
            text("select valid_at from weather_observations order by valid_at")
        ).all()
        marked = s.scalar(
            text(
                "select count(*) from weather_observations where ingestion_run_id is not null"
            )
        )
    assert [t.strftime("%H:%M") for t in times] == ["14:53", "15:53", "16:53", "17:53"]
    assert marked == 4


def test_rerun_is_idempotent(live_db):
    kwargs = dict(session_factory=live_db, stations=["KRDD"], sleep=lambda s: None)
    first = nws.run(client=mock_client(), now=NOW, **kwargs)
    second = nws.run(client=mock_client(), now=NOW + timedelta(hours=1), **kwargs)
    assert (first["rows_written"], second["rows_written"]) == (4, 0)
    with live_db() as s:
        assert s.scalar(text("select count(*) from weather_observations")) == 4


def test_one_failing_station_makes_the_run_partial(live_db):
    result = nws.run(
        session_factory=live_db, client=mock_client(fail=frozenset({"KBAD"})), now=NOW,
        stations=["KBAD", "KRDD"], sleep=lambda s: None,
    )  # fmt: skip
    assert result["status"] == "partial" and result["rows_written"] == 4
    assert result["error"].startswith(
        "KBAD: RuntimeError: NWS observations for KBAD failed"
    )


def test_placeholder_user_agent_fails_the_run(monkeypatch, live_db):
    monkeypatch.setattr(
        nws.settings, "nws_user_agent", "SmokeSense (contact@example.com)"
    )
    result = nws.run(
        session_factory=live_db, client=mock_client(), now=NOW, stations=["KRDD"]
    )
    assert result["status"] == "failed" and "NWS_USER_AGENT" in result["error"]
