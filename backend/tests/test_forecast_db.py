"""API-02: /grid/cells and /forecast/* on a real PostGIS database, checked against the spec.

Needs TEST_DATABASE_URL (see conftest.py); skipped without it.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_api_contract import assert_matches_spec

from app.api.deps import get_repository
from app.core.scope import CALIFORNIA_BBOX
from app.db.seed_fake_forecasts import FAKE_MODEL_KEY, seed_fake_forecasts
from app.main import app
from app.models.values import HORIZON_HOURS
from app.repositories import database as queries
from app.repositories.cache import CycleCache
from app.repositories.database import DatabaseRepository

ISSUED = datetime(2024, 7, 27, 18, tzinfo=UTC)
PRODUCTION = "baseline_v2/1.0.0"
SHADOW = "baseline_v3/0.1.0"
RETIRED = "baseline_v1/1.0.0"

CELLS = {  # id: (minLon, minLat, maxLon, maxLat)
    "cell-covered": (-122.0, 39.0, -121.9, 39.1),
    "cell-empty": (-121.0, 41.0, -120.9, 41.1),
    "cell-south": (-117.1, 32.53, -117.0, 32.6),
}
MONITORS = {  # id: (lat, lon, source)
    "monitor-usable": (39.2, -121.95, "v2"),
    "monitor-fallback": (39.06, -121.96, "fallback"),
}
INSIDE_COVERED = {"lat": "39.05", "lon": "-121.95"}
INSIDE_EMPTY = {"lat": "41.05", "lon": "-120.95"}
RENO = {"lat": "39.53", "lon": "-119.81"}  # inside the rough California box

GRID = "/api/v1/forecast/grid"
CELLS_PATH = "/api/v1/grid/cells"
MONITORS_PATH = "/api/v1/forecast/monitors"
POINT = "/api/v1/forecast/point"

client = TestClient(app, raise_server_exceptions=False)

INSERT_FORECAST = text("""
    INSERT INTO forecasts (
        id, forecast_point_id, model_key, issued_at, horizon_hours, target_time,
        pm25_predicted, source, nearest_monitor_dist_km, is_shadow
    ) VALUES (
        gen_random_uuid()::text, :point, :model, :issued, :hours,
        CAST(:issued AS timestamptz) + make_interval(hours => :hours),
        :pm25, :source, :distance, :shadow
    )
""")


def add_model(c, key: str, status: str) -> None:
    name, version = key.split("/")
    c.execute(
        text("""
            INSERT INTO model_versions (
                model_key, model_name, version, algorithm, artifact_uri, artifact_sha256,
                feature_list, status
            ) VALUES (:key, :name, :version, 'xgb', 'x', 'x', CAST('[]' AS jsonb), :status)
        """),
        {"key": key, "name": name, "version": version, "status": status},
    )


def add_forecasts(c, point, *, model=PRODUCTION, issued=ISSUED, pm25=40.06, source="idw",
                  distance=16.72, shadow=False, horizons=HORIZON_HOURS) -> None:
    for hours in horizons:
        c.execute(
            INSERT_FORECAST,
            {"point": point, "model": model, "issued": issued, "hours": hours, "pm25": pm25,
             "source": source, "distance": distance, "shadow": shadow},
        )


def add_cell(c, cell_id: str, box: tuple[float, float, float, float]) -> None:
    c.execute(
        text("""
            INSERT INTO forecast_points (id, kind, label, geom, cell_geom, timezone)
            VALUES (
                :id, 'grid_cell', :id,
                ST_Centroid(ST_MakeEnvelope(:w, :s, :e, :n, 4326))::geography,
                ST_MakeEnvelope(:w, :s, :e, :n, 4326)::geography,
                'America/Los_Angeles'
            )
        """),
        {"id": cell_id, "w": box[0], "s": box[1], "e": box[2], "n": box[3]},
    )


def add_monitor(c, point_id: str, lat: float, lon: float, number: int) -> None:
    params = {"point": point_id, "monitor": f"m-{point_id}", "lat": lat, "lon": lon,
              "aqs": f"06007{number:04d}", "seen": ISSUED}
    c.execute(
        text("""
            INSERT INTO monitors (id, source, external_id, aqs_code, name, geom, first_seen_at)
            VALUES (:monitor, 'airnow', :monitor, :aqs, :point,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :seen)
        """),
        params,
    )
    c.execute(
        text("""
            INSERT INTO forecast_points (id, kind, label, geom, monitor_id, timezone)
            VALUES (:point, 'monitor', :point,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :monitor,
                    'America/Los_Angeles')
        """),
        params,
    )


@pytest.fixture
def places(live_db, live_db_engine):
    """Cells, monitors, a ZIP and models, but no forecast yet."""
    with live_db_engine.begin() as c:
        c.execute(text("TRUNCATE model_versions CASCADE"))
        add_model(c, PRODUCTION, "production")
        add_model(c, SHADOW, "shadow")
        add_model(c, RETIRED, "retired")
        for cell_id, box in CELLS.items():
            add_cell(c, cell_id, box)
        for number, (point_id, (lat, lon, _)) in enumerate(MONITORS.items()):
            add_monitor(c, point_id, lat, lon, number)
        c.execute(
            text("""
                INSERT INTO zip_codes (zcta, state, geom, area_km2, forecast_point_id)
                VALUES ('95965', 'CA', ST_SetSRID(ST_MakePoint(-121.95, 39.05), 4326)::geography,
                        120.5, 'cell-covered')
            """)
        )
    cache = CycleCache()
    app.dependency_overrides[get_repository] = lambda: DatabaseRepository(live_db, cache)
    yield live_db_engine
    app.dependency_overrides.clear()


@pytest.fixture
def cycle(places):
    """One production cycle, surrounded by rows the API must never return."""
    with places.begin() as c:
        add_forecasts(c, "cell-covered")
        add_forecasts(c, "cell-south", pm25=5.0, distance=30.0)
        for point_id, (_, _, source) in MONITORS.items():
            add_forecasts(c, point_id, pm25=12.34, source=source, distance=0)
        # An older cycle, including a cell the current cycle left out.
        previous = ISSUED - timedelta(hours=1)
        add_forecasts(c, "cell-covered", issued=previous, pm25=999.0)
        add_forecasts(c, "cell-empty", issued=previous, pm25=999.0)
        # Newer rows that aren't public.
        later = ISSUED + timedelta(hours=1)
        add_forecasts(c, "cell-covered", model=SHADOW, issued=later, pm25=888.0, shadow=True)
        add_forecasts(c, "cell-covered", model=RETIRED, issued=later, pm25=777.0)
    return places


def get(path: str, status: int = 200, **params) -> dict:
    response = client.get(path, params=params)
    assert response.status_code == status, response.text
    assert_matches_spec(path, status, response.json())
    return response.json()


def grid_ids(body: dict, hours: int = 1) -> list[str]:
    entry = next(item for item in body["horizons"] if item["horizon_hours"] == hours)
    return [cell["id"] for cell in entry["cells"]]


# --- which forecasts are served ---


def test_grid_serves_only_the_latest_public_cycle(cycle):
    body = get(GRID)
    assert body["issued_at"] == "2024-07-27T18:00:00Z"
    assert body["model_key"] == PRODUCTION
    assert [item["horizon_hours"] for item in body["horizons"]] == list(HORIZON_HOURS)
    assert grid_ids(body) == ["cell-covered", "cell-south"]
    assert body["horizons"][0]["target_time"] == "2024-07-27T19:00:00Z"
    assert body["horizons"][0]["cells"][0] == {
        "id": "cell-covered",
        "pm25": 40.0,
        "aqi_category": "unhealthy_sensitive",
        "nearest_monitor_dist_km": 16.7,
    }


def test_shadow_rows_of_a_production_model_are_excluded(cycle):
    with cycle.begin() as c:
        later = ISSUED + timedelta(hours=2)
        add_forecasts(c, "cell-covered", issued=later, pm25=666.0, shadow=True)
    assert get(GRID)["issued_at"] == "2024-07-27T18:00:00Z"


def test_no_cycle_is_503(places):
    for path in (GRID, MONITORS_PATH):
        assert get(path, status=503)["code"] == "forecast_unavailable"
    assert get(POINT, status=503, **INSIDE_COVERED)["code"] == "forecast_unavailable"


def test_a_new_cycle_replaces_the_cached_response(cycle):
    assert get(GRID)["horizons"][0]["cells"][0]["pm25"] == 40.0
    with cycle.begin() as c:
        add_forecasts(c, "cell-covered", issued=ISSUED + timedelta(hours=2), pm25=20.0)
    body = get(GRID)
    assert body["issued_at"] == "2024-07-27T20:00:00Z"
    assert body["horizons"][0]["cells"][0]["pm25"] == 20.0


def test_grid_is_served_from_the_cache_within_a_cycle(cycle, monkeypatch):
    first = get(GRID)

    def no_second_build(*args):
        raise AssertionError("rebuilt a cached response")

    monkeypatch.setattr(DatabaseRepository, "_grid_forecast", no_second_build)
    assert get(GRID) == first


# --- grid cells, monitors and bbox ---


def test_grid_cells_are_polygons_with_their_key(cycle):
    body = get(CELLS_PATH)
    assert body["cell_count"] == len(CELLS)
    assert body["features"][0]["geometry"]["type"] == "Polygon"
    assert sorted(f["properties"]["id"] for f in body["features"]) == sorted(CELLS)


def test_monitors_carry_their_identity_and_source(cycle):
    body = get(MONITORS_PATH)
    by_id = {f["properties"]["forecast_point_id"]: f for f in body["features"]}
    assert set(by_id) == set(MONITORS)
    fallback = by_id["monitor-fallback"]
    assert fallback["geometry"]["coordinates"] == [-121.96, 39.06]
    assert len(fallback["properties"]["forecasts"]) == len(HORIZON_HOURS)
    assert {v["source"] for v in fallback["properties"]["forecasts"]} == {"fallback"}
    assert {v["method"] for v in fallback["properties"]["forecasts"]} == {"model"}


def test_bbox_filters_and_is_echoed_clipped(cycle):
    body = get(GRID, bbox="-122.5,38.9,-121.5,39.5")
    assert grid_ids(body) == ["cell-covered"]
    assert body["bbox"] == [-122.5, 38.9, -121.5, 39.5]
    # Touches cell-covered, and stops north of monitor-fallback.
    features = get(MONITORS_PATH, bbox="-122.5,39.09,-121.5,39.5")["features"]
    assert [f["properties"]["forecast_point_id"] for f in features] == ["monitor-usable"]


def test_a_wide_bbox_keeps_cells_on_its_southern_edge(cycle):
    # A geography polygon's bottom edge bows north, past this cell, at this width.
    assert "cell-south" in grid_ids(get(GRID, bbox="-124,32.5,-114.2,33"))


def test_bbox_inside_the_rough_box_but_outside_the_state_is_404(cycle):
    nevada = "-119.9,39.4,-119.7,39.6"
    for path in (GRID, CELLS_PATH, MONITORS_PATH):
        assert get(path, status=404, bbox=nevada)["code"] == "out_of_scope"


# --- /forecast/point ---


def test_point_returns_its_cell_and_the_nearest_monitor_of_any_source(cycle):
    body = get(POINT, **INSIDE_COVERED)
    assert body["query"] == {"lat": 39.05, "lon": -121.95, "zip": None, "zip_area_km2": None}
    cell = body["cell"]
    assert cell["forecast_point_id"] == "cell-covered"
    assert cell["has_forecast"] is True and cell["no_forecast_reason"] is None
    assert cell["nearest_monitor_dist_km"] == 16.7
    assert [v["horizon_hours"] for v in cell["forecasts"]] == list(HORIZON_HOURS)
    assert {(v["method"], v["source"]) for v in cell["forecasts"]} == {("interpolated", "idw")}
    assert body["nearest_monitor"]["forecast_point_id"] == "monitor-fallback"
    assert body["nearest_monitor"]["distance_km"] == pytest.approx(1.4, abs=0.1)


def test_cell_without_a_forecast_is_200_with_the_distance_filled_in(cycle):
    body = get(POINT, **INSIDE_EMPTY)
    cell = body["cell"]
    assert cell["has_forecast"] is False and cell["forecasts"] == []
    assert cell["no_forecast_reason"] == "no_monitor_within_50km"
    # From the centroid to the usable monitor (never the fallback one), with no 50 km limit.
    assert cell["nearest_monitor_dist_km"] == 222.6  # checked by hand with the haversine formula
    assert body["nearest_monitor"]["forecast_point_id"] == "monitor-usable"


def test_zip_resolves_to_its_centroid_and_cell(cycle):
    body = get(POINT, zip="95965")
    assert body["query"] == {"lat": 39.05, "lon": -121.95, "zip": "95965", "zip_area_km2": 120.5}
    assert body["cell"]["forecast_point_id"] == "cell-covered"


def test_point_outside_the_state_but_inside_the_rough_box_is_404(cycle):
    assert get(POINT, status=404, **RENO)["code"] == "out_of_scope"


def test_unknown_california_zip_is_404(cycle):
    assert get(POINT, status=404, zip="90001")["code"] == "zip_not_found"


# --- fake seed ---


def test_fake_seed_writes_a_cycle_the_api_serves(places):
    with places.begin() as c:
        c.execute(text("DELETE FROM zip_codes"))
        c.execute(text("DELETE FROM forecast_points WHERE kind = 'monitor'"))
        c.execute(text("DELETE FROM monitors"))
        seed_fake_forecasts(c, ISSUED, radius_km=100_000)
        seed_fake_forecasts(c, ISSUED, radius_km=100_000)  # safe to run twice
    body = get(GRID)
    assert body["model_key"] == FAKE_MODEL_KEY
    assert len(grid_ids(body)) == len(CELLS)
    features = get(MONITORS_PATH)["features"]
    sources = {v["source"] for f in features for v in f["properties"]["forecasts"]}
    assert sources == {"persistence", "v2", "fallback"}


# --- performance (issue #55) ---


@pytest.fixture
def full_grid(places):
    """The real size of the grid, with a forecast at every horizon: the worst case."""
    with places.begin() as c:
        c.execute(text("""
            INSERT INTO forecast_points (id, kind, label, geom, cell_geom, timezone)
            SELECT 'grid-ca-epsg3310-12500m-r+' || lpad(r::text, 6, '0') || '-c-'
                       || lpad(col::text, 6, '0') || '-p00',
                   'grid_cell', 'cell',
                   ST_Centroid(box)::geography, box::geography, 'America/Los_Angeles'
            FROM generate_series(0, 49) AS r
            CROSS JOIN generate_series(0, 58) AS col
            CROSS JOIN LATERAL (
                SELECT ST_MakeEnvelope(-123.9 + col * 0.14, 33.0 + r * 0.14,
                                       -123.76 + col * 0.14, 33.14 + r * 0.14, 4326) AS box
            ) AS cell
        """))
        c.execute(
            text("""
                INSERT INTO forecasts (
                    id, forecast_point_id, model_key, issued_at, horizon_hours, target_time,
                    pm25_predicted, source, nearest_monitor_dist_km
                )
                SELECT gen_random_uuid()::text, fp.id, :model, :issued, h,
                       CAST(:issued AS timestamptz) + make_interval(hours => h),
                       123.456, 'idw', 24.68
                FROM forecast_points AS fp
                CROSS JOIN unnest(ARRAY[1, 3, 6, 12, 24]) AS h
                WHERE fp.kind = 'grid_cell'
            """),
            {"model": PRODUCTION, "issued": ISSUED},
        )
        c.execute(text("ANALYZE forecasts"))
        c.execute(text("ANALYZE forecast_points"))
    return places


def test_full_california_grid_meets_the_issue_limits(full_grid):
    started = time.perf_counter()
    response = client.get(GRID)
    elapsed = time.perf_counter() - started
    print(f"grid: {elapsed:.3f}s, {len(response.content):,} bytes, {response.num_bytes_downloaded:,} gzipped")
    assert response.status_code == 200
    assert sum(len(item["cells"]) for item in response.json()["horizons"]) >= 2950 * 5
    assert elapsed < 1.0
    assert len(response.content) < 2.2 * 1024 * 1024
    assert response.headers["content-encoding"] == "gzip"


@pytest.fixture
def forecast_history(full_grid):
    """A day of older cycles, so reading one cycle is a small part of the table, as it is
    at 30-day retention. With one cycle, a sequential scan would be the right plan."""
    with full_grid.begin() as c:
        c.execute(text("""
            INSERT INTO forecasts (
                id, forecast_point_id, model_key, issued_at, horizon_hours, target_time,
                pm25_predicted, source, nearest_monitor_dist_km
            )
            SELECT gen_random_uuid()::text, f.forecast_point_id, f.model_key,
                   f.issued_at - make_interval(hours => back), f.horizon_hours,
                   f.target_time - make_interval(hours => back),
                   f.pm25_predicted, f.source, f.nearest_monitor_dist_km
            FROM forecasts AS f
            CROSS JOIN generate_series(1, 24) AS back
        """))
    with full_grid.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("VACUUM ANALYZE forecasts"))
    return full_grid


def plan(engine, query, params: dict) -> str:
    """The plan Postgres picks by itself: no planner setting is changed."""
    with engine.begin() as c:
        rows = c.execute(text(f"EXPLAIN (FORMAT JSON) {query.text}"), params).scalar()
    return json.dumps(rows)


def test_reads_use_the_indexes(forecast_history):
    engine = forecast_history
    small = {"min_lon": -122.0, "min_lat": 38.0, "max_lon": -121.0, "max_lat": 39.0}
    state = CALIFORNIA_BBOX._asdict()
    cycle = {"model_key": PRODUCTION, "issued_at": ISSUED}
    assert "ix_forecasts_serving" in plan(engine, queries.LATEST_CYCLE, {})
    assert "ix_forecast_points_cell_geom_planar" in plan(engine, queries.GRID_CELLS, small)

    # A small bbox finds its few cells first, then each cell's forecasts.
    small_plan = plan(engine, queries.GRID_VALUES, {**small, **cycle})
    assert "ix_forecast_points_cell_geom_planar" in small_plan
    assert "ix_forecasts_point_issued" in small_plan
    # The whole state reads the cycle; nearly every cell matches, so no spatial index helps.
    assert "ix_forecasts_serving" in plan(engine, queries.GRID_VALUES, {**state, **cycle})
