"""/observations/wind/latest on a real PostGIS database, checked against the spec.

Needs TEST_DATABASE_URL (see conftest.py); skipped without it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_api_contract import assert_matches_spec

from app.api.deps import get_repository
from app.main import app
from app.repositories.cache import CycleCache
from app.repositories.database import DatabaseRepository

WIND = "/api/v1/observations/wind/latest"

client = TestClient(app, raise_server_exceptions=False)

INSERT_OBSERVATION = text("""
    INSERT INTO weather_observations (station_id, valid_at, received_at, geom, wind_speed_ms, wind_dir_deg)
    VALUES (:station, :valid_at, :valid_at, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :speed, :direction)
""")


@pytest.fixture
def stations(live_db, live_db_engine):
    """Readings around Chico, plus rows the endpoint must leave out. Grid cells make the
    bbox scope check pass, as in production."""
    now = datetime.now(UTC).replace(microsecond=0)
    rows = [
        # station, minutes ago, lat, lon, speed m/s, direction
        ("KCIC", 30, 39.795, -121.858, 4.63, 230.4),
        ("KCIC", 90, 39.795, -121.858, 2.0, 180.0),  # older: replaced by the 30 min reading
        ("KOVE", 20, 39.49, -121.618, 0.0, 0.0),  # calm
        ("KRBL", 50, 40.15, -122.252, None, 200.0),  # no speed: falls back to the older reading
        ("KRBL", 100, 40.15, -122.252, 5.7, 200.0),
        ("KAUN", 200, 38.955, -121.082, 3.1, 250.0),  # older than 3 h
        ("PRIVATE01", 10, 39.6, -121.7, 2.0, 90.0),  # not an NWS station id
    ]
    with live_db_engine.begin() as c:
        c.execute(
            text("""
                INSERT INTO forecast_points (id, kind, label, geom, cell_geom, timezone)
                VALUES ('cell-chico', 'grid_cell', 'cell-chico',
                        ST_Centroid(ST_MakeEnvelope(-123, 38.5, -121, 40.5, 4326))::geography,
                        ST_MakeEnvelope(-123, 38.5, -121, 40.5, 4326)::geography,
                        'America/Los_Angeles')
            """)
        )
        for station, minutes, lat, lon, speed, direction in rows:
            c.execute(
                INSERT_OBSERVATION,
                {"station": station, "valid_at": now - timedelta(minutes=minutes), "lat": lat,
                 "lon": lon, "speed": speed, "direction": direction},
            )
    app.dependency_overrides[get_repository] = lambda: DatabaseRepository(live_db, CycleCache())
    yield now
    app.dependency_overrides.clear()


def test_latest_reading_per_station(stations):
    response = client.get(WIND)
    assert response.status_code == 200
    body = response.json()
    assert_matches_spec(WIND, 200, body)
    assert body["max_age_hours"] == 3

    by_station = {f["properties"]["station_id"]: f["properties"] for f in body["features"]}
    assert set(by_station) == {"KCIC", "KOVE", "KRBL"}
    assert by_station["KCIC"]["wind_speed_ms"] == 4.6
    assert by_station["KCIC"]["wind_dir_deg"] == 230
    assert by_station["KOVE"] == {**by_station["KOVE"], "wind_speed_ms": 0.0, "wind_dir_deg": None}
    assert by_station["KRBL"]["wind_speed_ms"] == 5.7


def test_bbox_filters_stations(stations):
    response = client.get(WIND, params={"bbox": "-122.0,39.7,-121.7,39.9"})
    assert response.status_code == 200
    assert [f["properties"]["station_id"] for f in response.json()["features"]] == ["KCIC"]


def test_bbox_outside_the_grid_is_out_of_scope(stations):
    # Inside the rough California box but with no grid cell (Reno).
    response = client.get(WIND, params={"bbox": "-119.9,39.4,-119.7,39.6"})
    assert response.status_code == 404
    assert response.json()["code"] == "out_of_scope"
