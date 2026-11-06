"""API-03: /fires/active, /observations/pm25/latest and /meta on real PostGIS.

Needs TEST_DATABASE_URL (see conftest.py); skipped without it.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_api_contract import assert_matches_spec

from app.api.deps import get_repository
from app.core.config import settings
from app.core.ids import uuid7
from app.main import app
from app.models.values import HORIZON_HOURS
from app.repositories.cache import CycleCache
from app.repositories.database import DatabaseRepository
from shared.aqi import AQI_CATEGORIES, AQI_TABLE_VERSION

FIRES = "/api/v1/fires/active"
OBSERVATIONS = "/api/v1/observations/pm25/latest"
META = "/api/v1/meta"
MODEL = "baseline_v2/1.0.0"
NEVADA = "-119.9,39.4,-119.7,39.6"

client = TestClient(app, raise_server_exceptions=False)


def hours_ago(hours: float) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def add_fire(c, age_hours=1.0, *, satellite="VIIRS_SNPP", confidence="nominal", raw="n", lat=39.8,
             lon=-121.6, frp=12.34, daynight="D") -> str:
    fire_id = uuid7()
    c.execute(
        text("""
            INSERT INTO fire_detections (
                id, external_id, satellite, product, geom, detected_at, received_at,
                confidence_raw, confidence_level, frp_mw, daynight
            ) VALUES (
                :id, :id, :satellite, 'NRT', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :detected_at, :detected_at, :raw, :confidence, :frp, :daynight
            )
        """),
        {"id": fire_id, "satellite": satellite, "lat": lat, "lon": lon, "raw": raw,
         "detected_at": hours_ago(age_hours), "confidence": confidence, "frp": frp,
         "daynight": daynight},
    )
    return fire_id


def add_monitor(c, *, source="airnow", code="060070008", location_type="outdoor", active=True,
                lat=39.76, lon=-121.84) -> str:
    monitor_id = uuid7()
    c.execute(
        text("""
            INSERT INTO monitors (
                id, source, external_id, aqs_code, name, location_type, geom, active, first_seen_at
            ) VALUES (
                :id, :source, :external_id, :aqs, 'Chico', :location_type,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :active, :seen
            )
        """),
        {"id": monitor_id, "source": source, "external_id": code,
         "aqs": code if source == "airnow" else None, "location_type": location_type,
         "lat": lat, "lon": lon, "active": active, "seen": hours_ago(100)},
    )
    return monitor_id


def add_reading(c, monitor_id, age_hours, pm25=40.06, correction="regulatory", qa_flag=None):
    c.execute(
        text("""
            INSERT INTO observations (monitor_id, valid_at, received_at, pm25, correction, qa_flag)
            VALUES (:monitor, :valid_at, :valid_at, :pm25, :correction, :qa_flag)
        """),
        {"monitor": monitor_id, "valid_at": hours_ago(age_hours), "pm25": pm25,
         "correction": correction, "qa_flag": qa_flag},
    )


def add_cell(c) -> None:
    c.execute(text("""
        INSERT INTO forecast_points (id, kind, label, geom, cell_geom, timezone)
        VALUES ('cell', 'grid_cell', 'cell',
                ST_Centroid(ST_MakeEnvelope(-122, 39, -121, 40, 4326))::geography,
                ST_MakeEnvelope(-122, 39, -121, 40, 4326)::geography, 'America/Los_Angeles')
    """))


def add_model(c, status="production") -> None:
    c.execute(
        text("""
            INSERT INTO model_versions (
                model_key, model_name, version, algorithm, artifact_uri, artifact_sha256,
                feature_list, status
            ) VALUES (:key, 'baseline_v2', '1.0.0', 'xgb', 'x', 'x', CAST('[]' AS jsonb), :status)
        """),
        {"key": MODEL, "status": status},
    )


def add_cycle(c, age_hours: float) -> datetime:
    issued = hours_ago(age_hours).replace(minute=0, second=0, microsecond=0)
    c.execute(
        text("""
            INSERT INTO forecasts (
                id, forecast_point_id, model_key, issued_at, horizon_hours, target_time,
                pm25_predicted, source, nearest_monitor_dist_km
            ) VALUES (
                gen_random_uuid()::text, 'cell', :model, :issued, 1,
                CAST(:issued AS timestamptz) + make_interval(hours => 1), 10, 'idw', 5
            )
        """),
        {"model": MODEL, "issued": issued},
    )
    return issued


def add_run(c, source: str, finished_ago_minutes: float, watermark_ago_minutes: float,
            status="success") -> None:
    finished = datetime.now(UTC) - timedelta(minutes=finished_ago_minutes)
    c.execute(
        text("""
            INSERT INTO ingestion_runs (id, source, started_at, finished_at, status, watermark)
            VALUES (:id, :source, :finished, :finished, :status, :watermark)
        """),
        {"id": uuid7(), "source": source, "finished": finished, "status": status,
         "watermark": datetime.now(UTC) - timedelta(minutes=watermark_ago_minutes)},
    )


@pytest.fixture
def engine(live_db, live_db_engine, monkeypatch):
    """An empty database behind the API, with one grid cell so a bbox can be in scope."""
    with live_db_engine.begin() as c:
        c.execute(text("TRUNCATE model_versions CASCADE"))
        add_cell(c)
    monkeypatch.setattr(settings, "mock_mode", False)
    cache = CycleCache()
    app.dependency_overrides[get_repository] = lambda: DatabaseRepository(live_db, cache)
    yield live_db_engine
    app.dependency_overrides.clear()


def get(path: str, status: int = 200, **params) -> dict:
    response = client.get(path, params=params)
    assert response.status_code == status, response.text
    assert_matches_spec(path, status, response.json())
    return response.json()


# --- /fires/active ---


def test_fires_keep_only_the_72_hour_viirs_snpp_window(engine):
    with engine.begin() as c:
        inside = add_fire(c, age_hours=71)
        add_fire(c, age_hours=73)
        add_fire(c, age_hours=-1)  # a future row is outside [window_start, window_end)
        add_fire(c, satellite="VIIRS_NOAA20")
    body = get(FIRES)
    assert [f["properties"]["detection_id"] for f in body["features"]] == [inside]
    assert body["detection_count"] == 1 and body["window_hours"] == 72
    start = datetime.fromisoformat(body["window_start"])
    assert datetime.fromisoformat(body["window_end"]) - start == timedelta(hours=72)


def test_fire_fields_and_low_confidence_are_returned(engine):
    with engine.begin() as c:
        add_fire(c, confidence="low", raw="l", frp=None, daynight=None)
    feature = get(FIRES)["features"][0]
    assert feature["geometry"]["coordinates"] == [-121.6, 39.8]
    assert feature["properties"]["confidence"] == "low"
    assert feature["properties"]["confidence_raw"] == "l"
    assert feature["properties"]["frp_mw"] is None


def test_fires_are_newest_first_and_frp_is_rounded(engine):
    with engine.begin() as c:
        older = add_fire(c, age_hours=5)
        newer = add_fire(c, age_hours=1)
    properties = [f["properties"] for f in get(FIRES)["features"]]
    assert [p["detection_id"] for p in properties] == [newer, older]
    assert properties[0]["frp_mw"] == 12.3


def test_fires_filter_by_bbox(engine):
    with engine.begin() as c:
        inside = add_fire(c, lat=39.5, lon=-121.5)
        add_fire(c, lat=34.0, lon=-118.0)
    body = get(FIRES, bbox="-122,39,-121,40")
    assert [f["properties"]["detection_id"] for f in body["features"]] == [inside]


def test_a_fire_just_over_the_border_stays_on_the_default_map(engine):
    with engine.begin() as c:
        add_fire(c, lat=39.5, lon=-119.8)  # Nevada, inside the rough box
    assert get(FIRES)["detection_count"] == 1


def test_a_bbox_outside_the_state_is_404(engine):
    assert get(FIRES, status=404, bbox=NEVADA)["code"] == "out_of_scope"
    assert get(OBSERVATIONS, status=404, bbox=NEVADA)["code"] == "out_of_scope"


# --- /observations/pm25/latest ---


def test_observation_is_the_newest_reading_with_its_source_and_time(engine):
    with engine.begin() as c:
        monitor = add_monitor(c)
        add_reading(c, monitor, 1.5, pm25=99.0)
        add_reading(c, monitor, 0.5)
    body = get(OBSERVATIONS)
    assert len(body["features"]) == 1
    properties = body["features"][0]["properties"]
    assert properties["monitor_id"] == monitor
    assert properties["provider"] == "airnow" and properties["station_code"] == "060070008"
    assert properties["correction"] == "regulatory"
    assert properties["pm25"] == 40.0 and properties["aqi_category"] == "unhealthy_sensitive"
    assert properties["valid_at"].endswith("Z")
    assert body["max_age_hours"] == 2 and body["aqi_table_version"] == AQI_TABLE_VERSION


def test_readings_older_than_two_hours_or_in_the_future_are_left_out(engine):
    with engine.begin() as c:
        add_reading(c, add_monitor(c, code="060070001"), 2.5)
        add_reading(c, add_monitor(c, code="060070002"), -1)
    assert get(OBSERVATIONS)["features"] == []


def test_indoor_and_inactive_sensors_are_left_out(engine):
    with engine.begin() as c:
        add_reading(c, add_monitor(c, code="060070001", location_type="indoor"), 0.5)
        add_reading(c, add_monitor(c, code="060070002", active=False), 0.5)
    assert get(OBSERVATIONS)["features"] == []


def test_purpleair_serves_only_corrected_readings_that_passed_qa(engine):
    with engine.begin() as c:
        good = add_monitor(c, source="purpleair", code="12345")
        add_reading(c, good, 1.5, pm25=20.0, correction="purpleair_barkjohn", qa_flag="ok")
        add_reading(c, good, 0.5, pm25=300.0, correction="purpleair_raw", qa_flag="ok")
        add_reading(c, good, 0.25, pm25=300.0, correction="purpleair_barkjohn", qa_flag="suspect")
        raw_only = add_monitor(c, source="purpleair", code="67890")
        add_reading(c, raw_only, 0.5, correction="purpleair_raw", qa_flag="ok")
    features = get(OBSERVATIONS)["features"]
    assert len(features) == 1
    properties = features[0]["properties"]
    assert properties["provider"] == "purpleair" and properties["station_code"] == "12345"
    assert properties["correction"] == "purpleair_barkjohn" and properties["pm25"] == 20.0


def test_observations_filter_by_bbox(engine):
    with engine.begin() as c:
        add_reading(c, add_monitor(c, code="060070001"), 0.5)
        add_reading(c, add_monitor(c, code="060370001", lat=34.0, lon=-118.0), 0.5)
    features = get(OBSERVATIONS, bbox="-122,39,-121,40")["features"]
    assert [f["properties"]["station_code"] for f in features] == ["060070001"]


# --- /meta ---


def test_meta_before_any_model_or_forecast_is_valid_and_stale(engine):
    body = get(META)
    assert body["model_key"] is None and body["model_status"] is None
    assert body["latest_issued_at"] is None and body["forecast_age_minutes"] is None
    assert body["forecast_stale"] is True
    assert body["mock_mode"] is False
    assert body["horizons"] == list(HORIZON_HOURS)
    assert body["aqi_categories"] == [category._asdict() for category in AQI_CATEGORIES]


def test_meta_with_a_promoted_model_but_no_forecast_yet(engine):
    with engine.begin() as c:
        add_model(c)
    body = get(META)
    assert body["model_key"] == MODEL and body["model_status"] == "production"
    assert body["latest_issued_at"] is None and body["forecast_stale"] is True


def test_meta_reports_a_fresh_forecast_cycle(engine):
    with engine.begin() as c:
        add_model(c)
        issued = add_cycle(c, 0)
    body = get(META)
    assert body["latest_issued_at"] == issued.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert 0 <= body["forecast_age_minutes"] <= 60
    assert body["forecast_stale"] is False


def test_meta_flags_a_forecast_past_its_threshold(engine, monkeypatch):
    monkeypatch.setattr(settings, "forecast_stale_after_minutes", 60)
    with engine.begin() as c:
        add_model(c)
        add_cycle(c, 3)
    body = get(META)
    assert body["forecast_stale"] is True and body["forecast_stale_after_minutes"] == 60


def test_meta_flags_a_source_that_misses_its_cadence(engine):
    with engine.begin() as c:
        add_run(c, "airdata", finished_ago_minutes=20, watermark_ago_minutes=80)
        add_run(c, "firms", finished_ago_minutes=120, watermark_ago_minutes=300)
    sources = {source["source"]: source for source in get(META)["sources"]}
    assert sources["airnow"]["stale"] is False
    assert sources["airnow"]["age_minutes"] in (79, 80)  # rounded down
    assert sources["firms"]["stale"] is True
    assert sources["nws_obs"]["stale"] is True and sources["nws_obs"]["last_success_at"] is None
    assert "purpleair" not in sources  # no live job (decision #41)


def test_a_quiet_feed_is_not_stale_when_its_job_ran(engine):
    with engine.begin() as c:
        add_run(c, "firms", finished_ago_minutes=10, watermark_ago_minutes=600)
    firms = next(source for source in get(META)["sources"] if source["source"] == "firms")
    assert firms["stale"] is False and firms["age_minutes"] in (599, 600)


def test_a_failed_run_does_not_count_as_fresh(engine):
    with engine.begin() as c:
        add_run(c, "firms", finished_ago_minutes=5, watermark_ago_minutes=5, status="failed")
    firms = next(source for source in get(META)["sources"] if source["source"] == "firms")
    assert firms["stale"] is True


# --- performance on a full-California bbox (issue #56) ---


def test_full_california_bboxes_stay_fast(engine):
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO fire_detections (
                id, external_id, satellite, product, geom, detected_at, received_at,
                confidence_raw, confidence_level, frp_mw, daynight
            )
            SELECT gen_random_uuid()::text, n::text, 'VIIRS_SNPP', 'NRT',
                   ST_SetSRID(ST_MakePoint(-124 + mod(n, 900) * 0.01,
                                           33 + mod(n, 800) * 0.01), 4326)::geography,
                   now() - make_interval(mins => mod(n, 4300)), now(),
                   'n', 'nominal', 10, 'D'
            FROM generate_series(1, 20000) AS n
        """))
        c.execute(text("""
            WITH sensors AS (
                INSERT INTO monitors (id, source, external_id, aqs_code, geom, first_seen_at)
                SELECT gen_random_uuid()::text, 'airnow', n::text, lpad(n::text, 9, '0'),
                       ST_SetSRID(ST_MakePoint(-122 + n * 0.005, 37 + n * 0.002), 4326)::geography,
                       now()
                FROM generate_series(1, 200) AS n
                RETURNING id
            )
            INSERT INTO observations (monitor_id, valid_at, received_at, pm25, correction)
            SELECT s.id, date_trunc('hour', now()) - make_interval(hours => h), now(), 10,
                   'regulatory'
            FROM sensors AS s
            CROSS JOIN generate_series(0, 71) AS h
        """))
        c.execute(text("ANALYZE fire_detections"))
        c.execute(text("ANALYZE observations"))
    # The limits are wider for fires: 20,000 detections is a busy fire season, and most of
    # the time is building and sending about 6 MB of GeoJSON, not the query.
    for path, limit in ((FIRES, 3.0), (OBSERVATIONS, 1.0), (META, 1.0)):
        started = time.perf_counter()
        response = client.get(path)
        elapsed = time.perf_counter() - started
        print(f"{path}: {elapsed:.3f}s, {len(response.content):,} bytes")
        assert response.status_code == 200
        assert elapsed < limit
