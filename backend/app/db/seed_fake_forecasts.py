"""Seed one fake forecast cycle, so the API can run before the pipeline exists (API-02).

Run in the backend environment, after the grid is seeded:
    python -m app.db.seed_fake_forecasts

The values are invented and carry the model_key below. They are public on purpose
(is_shadow false, production model), so the script refuses to run against anything but
a local database. To remove them, delete the forecasts with that model_key.

Existing monitor forecast points are used; if there are none, a few fake ones are added.
--radius-km 100000 forecasts every cell, the worst case for /forecast/grid's payload.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.ids import uuid7
from app.models.values import HORIZON_HOURS

FAKE_MODEL_NAME = "fake_forecasts"
FAKE_MODEL_VERSION = "0.0.0"
FAKE_MODEL_KEY = f"{FAKE_MODEL_NAME}/{FAKE_MODEL_VERSION}"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}
MAX_INTERPOLATION_KM = 50.0
TIMEZONE = "America/Los_Angeles"

# (name, lat, lon). Spread out, so some cells end up with no monitor in range.
FAKE_MONITORS = (
    ("Fake Redding", 40.59, -122.39),
    ("Fake Sacramento", 38.58, -121.49),
    ("Fake San Francisco", 37.77, -122.42),
    ("Fake Fresno", 36.74, -119.79),
    ("Fake Bakersfield", 35.37, -119.02),
    ("Fake Los Angeles", 34.05, -118.24),
    ("Fake San Diego", 32.72, -117.16),
)

INSERT_MODEL = text("""
    INSERT INTO model_versions (
        model_key, model_name, version, algorithm, artifact_uri, artifact_sha256,
        feature_list, status, notes
    ) VALUES (
        :model_key, :model_name, :version, 'fake', 'none', 'none',
        CAST('[]' AS jsonb), 'production', 'Invented values from seed_fake_forecasts.'
    )
    ON CONFLICT (model_key) DO NOTHING
""")

INSERT_MONITOR = text("""
    INSERT INTO monitors (
        id, source, external_id, aqs_code, name, geom, first_seen_at
    ) VALUES (
        :id, 'airnow', :external_id, :aqs_code, :name,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :seen_at
    )
""")

INSERT_MONITOR_POINT = text("""
    INSERT INTO forecast_points (id, kind, label, geom, monitor_id, timezone)
    VALUES (
        :id, 'monitor', :name,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :monitor_id, :timezone
    )
""")

# Every fifth monitor is a `fallback` one, which never feeds a cell.
INSERT_MONITOR_FORECASTS = text("""
    INSERT INTO forecasts (
        id, forecast_point_id, model_key, issued_at, horizon_hours, target_time,
        pm25_predicted, source, nearest_monitor_dist_km
    )
    SELECT gen_random_uuid()::text, fp.id, :model_key, CAST(:issued_at AS timestamptz), h.hours,
           CAST(:issued_at AS timestamptz) + make_interval(hours => h.hours),
           mod(abs(hashtext(fp.id)::bigint), 1500) / 10.0 + h.hours,
           CASE WHEN fp.rank % 5 = 0 THEN 'fallback'
                WHEN h.hours = 1 THEN 'persistence'
                ELSE 'v2' END,
           0
    FROM (
        SELECT id, row_number() OVER (ORDER BY id) AS rank
        FROM forecast_points
        WHERE kind = 'monitor' AND active
    ) AS fp
    CROSS JOIN unnest(CAST(:horizons AS int[])) AS h(hours)
    ON CONFLICT (forecast_point_id, model_key, issued_at, horizon_hours) DO NOTHING
""")

# Each cell copies its nearest usable monitor. Real cells are an IDW of up to four.
INSERT_CELL_FORECASTS = text("""
    INSERT INTO forecasts (
        id, forecast_point_id, model_key, issued_at, horizon_hours, target_time,
        pm25_predicted, source, nearest_monitor_dist_km
    )
    SELECT gen_random_uuid()::text, cell.id, :model_key, CAST(:issued_at AS timestamptz),
           h.hours, near.target_time, near.pm25_predicted, 'idw', near.km
    FROM forecast_points AS cell
    CROSS JOIN unnest(CAST(:horizons AS int[])) AS h(hours)
    CROSS JOIN LATERAL (
        SELECT f.target_time, f.pm25_predicted,
               ST_Distance(m.geom, cell.geom, false) / 1000 AS km
        FROM forecasts AS f
        JOIN forecast_points AS m ON m.id = f.forecast_point_id
        WHERE f.model_key = :model_key
          AND f.issued_at = CAST(:issued_at AS timestamptz)
          AND f.horizon_hours = h.hours
          AND m.kind = 'monitor'
          AND f.source IN ('v2', 'persistence')
        ORDER BY km
        LIMIT 1
    ) AS near
    WHERE cell.kind = 'grid_cell' AND cell.active AND near.km <= :radius_km
    ON CONFLICT (forecast_point_id, model_key, issued_at, horizon_hours) DO NOTHING
""")


def require_local_database(database_url: str) -> None:
    """Fake forecasts look real to every API client. Prints no URL: it can hold a password."""
    if make_url(database_url).host not in LOCAL_HOSTS:
        raise SystemExit("Refusing to seed fake forecasts into a database that isn't local.")


def seed_monitors(connection: Connection, seen_at: datetime) -> None:
    for number, (name, lat, lon) in enumerate(FAKE_MONITORS, start=1):
        monitor_id = uuid7()
        connection.execute(
            INSERT_MONITOR,
            {
                "id": monitor_id,
                "external_id": f"fake:{number}",
                "aqs_code": f"FK{number:07d}",
                "name": name,
                "lat": lat,
                "lon": lon,
                "seen_at": seen_at,
            },
        )
        connection.execute(
            INSERT_MONITOR_POINT,
            {
                "id": uuid7(),
                "name": name,
                "lat": lat,
                "lon": lon,
                "monitor_id": monitor_id,
                "timezone": TIMEZONE,
            },
        )


def seed_fake_forecasts(
    connection: Connection,
    issued_at: datetime,
    radius_km: float = MAX_INTERPOLATION_KM,
) -> None:
    has_cells = connection.scalar(
        text("SELECT EXISTS (SELECT 1 FROM forecast_points WHERE kind = 'grid_cell' AND active)")
    )
    if not has_cells:
        raise SystemExit("No grid cells: run python -m app.db.seed_ca_forecast_grid first.")
    has_monitors = connection.scalar(
        text("SELECT EXISTS (SELECT 1 FROM forecast_points WHERE kind = 'monitor' AND active)")
    )
    if not has_monitors:
        seed_monitors(connection, issued_at)
    connection.execute(
        INSERT_MODEL,
        {
            "model_key": FAKE_MODEL_KEY,
            "model_name": FAKE_MODEL_NAME,
            "version": FAKE_MODEL_VERSION,
        },
    )
    params = {
        "model_key": FAKE_MODEL_KEY,
        "issued_at": issued_at,
        "horizons": list(HORIZON_HOURS),
    }
    connection.execute(INSERT_MONITOR_FORECASTS, params)
    connection.execute(INSERT_CELL_FORECASTS, {**params, "radius_km": radius_km})


def top_of_this_hour() -> datetime:
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issued-at",
        type=datetime.fromisoformat,
        help="Cycle time, ISO-8601 with an offset. Default: the top of this UTC hour.",
    )
    parser.add_argument("--radius-km", type=float, default=MAX_INTERPOLATION_KM)
    args = parser.parse_args()

    require_local_database(settings.database_url)
    issued_at = args.issued_at or top_of_this_hour()
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            seed_fake_forecasts(connection, issued_at, args.radius_km)
    finally:
        engine.dispose()
    print(f"Seeded fake forecast cycle {issued_at.isoformat()} as {FAKE_MODEL_KEY}")


if __name__ == "__main__":
    main()
