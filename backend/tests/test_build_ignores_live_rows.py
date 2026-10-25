"""smokesense_v1 builds from historical rows only; live DATA-06 rows never leak in.

Live rows share observations, fire_detections and weather_observations with the
DATA-03 rows the dataset is built from (decision #34). Before the build filtered on
ingestion_run_id, live rows inside an event's window and bbox changed the dataset's
sha256 (found by running scripts/reproduce_data04.sh with live rows loaded).
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import text

from dataset_build.build_v1 import forecast_points, load_inputs

BOX = "-122.04,39.59,-120.00,40.81"  # PE-002's bbox
EVENT = SimpleNamespace(
    event_id="PE-TEST",
    start_date="2021-08-05",
    end_date="2021-08-06",
    bbox=BOX,
    firms_bbox=BOX,
    ncei_bbox=BOX,
    firms_start_date="2021-08-05",
    airnow_start_date="2021-08-05",
    airnow_end_date="2021-08-06",
    ncei_start_date="2021-08-05",
)
POINT = "ST_GeogFromText('POINT(-121.84 39.76)')"


def seed(live_db) -> None:
    """One historical and one live row in each table, both inside the event."""
    with live_db() as s:
        s.execute(
            text(f"""
            insert into monitors (id, source, external_id, aqs_code, name, geom, first_seen_at)
            values ('hist-m', 'airnow', 'airnow:hist', '060070008', 'Chico', {POINT}, now()),
                   ('live-m', 'airnow', 'airnow:live', '060070009', 'Live only', {POINT}, now())
        """)
        )
        rows = (
            (None, "hist-m", "10"),  # historical
            ("run-1", "hist-m", "11"),  # live, at a historical monitor
            ("run-1", "live-m", "12"),  # live, at a live-only monitor
        )
        for run, monitor, hour in rows:
            ts = f"2021-08-05T{hour}:00Z"
            p = {
                "run": run,
                "ts": ts,
                "m": monitor,
                "id": f"f-{hour}",
                "ext": f"x-{hour}",
            }
            s.execute(
                text(
                    "insert into observations (monitor_id, valid_at, received_at, pm25, correction, "
                    "ingestion_run_id) values (:m, :ts, :ts, 50, 'regulatory', :run)"
                ),
                p,
            )
            s.execute(
                text(
                    "insert into fire_detections (id, external_id, satellite, product, geom, "
                    "detected_at, received_at, confidence_raw, confidence_level, ingestion_run_id) "
                    f"values (:id, :ext, 'VIIRS_SNPP', 'SP', {POINT}, :ts, :ts, 'n', 'nominal', :run)"
                ),
                p,
            )
            s.execute(
                text(
                    "insert into weather_observations (station_id, valid_at, received_at, geom, "
                    f"temp_c, ingestion_run_id) values ('KCIC', :ts, :ts, {POINT}, 30, :run)"
                ),
                p,
            )
        s.commit()


def test_build_queries_read_historical_rows_only(live_db):
    seed(live_db)
    with live_db() as s:
        c = s.connection()
        points, _ = forecast_points(c, EVENT, registry={})
        frames = load_inputs(c, EVENT)

    # The live-only monitor is not a forecast point, and no live row is an input.
    assert list(points["forecast_point_id"]) == ["airnow:hist"]
    hours = {
        name: sorted(frames[name][col].dt.hour.tolist())
        for name, col in (
            ("fires", "detected_at"),
            ("weather", "valid_at"),
            ("pm25_observations", "valid_at"),
        )
    }
    assert hours == {"fires": [10], "weather": [10], "pm25_observations": [10]}
