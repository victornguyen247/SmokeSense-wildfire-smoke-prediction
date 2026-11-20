"""row_scope in dataset_build.build_v1: smokesense_v1 reads historical rows only by
default, and GEO-03 can read live rows (or both) through the same functions.

Live rows share observations, fire_detections and weather_observations with the
DATA-03 rows the dataset is built from (decision #34). Before the build filtered on
ingestion_run_id, live rows inside an event's window and bbox changed the dataset's
sha256 (found by running scripts/reproduce_data04.sh with live rows loaded).

Fires also differ by satellite (decision #49): historical rows are VIIRS SNPP, live rows
VIIRS NOAA-20, since FIRMS stopped serving SNPP on 2026-11-02.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from dataset_build.build_v1 import forecast_points, load_inputs, scope_sql

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
FIRE_SQL = (
    "insert into fire_detections (id, external_id, satellite, product, geom, "
    "detected_at, received_at, confidence_raw, confidence_level, ingestion_run_id) "
    f"values (:id, :ext, :sat, :product, {POINT}, :ts, :ts, 'n', 'nominal', :run)"
)


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
            # Historical fires are SNPP (_SP); live fires NOAA-20 NRT.
            sat, product = ("VIIRS_NOAA20", "NRT") if run else ("VIIRS_SNPP", "SP")
            s.execute(text(FIRE_SQL), {**p, "sat": sat, "product": product})
            s.execute(
                text(
                    "insert into weather_observations (station_id, valid_at, received_at, geom, "
                    f"temp_c, ingestion_run_id) values ('KCIC', :ts, :ts, {POINT}, 30, :run)"
                ),
                p,
            )
        # Decoy fires on the other satellite: neither "historical" nor "live" reads them.
        decoys = (
            (
                "13",
                "run-1",
                "VIIRS_SNPP",
                "NRT",
            ),  # live SNPP, from before the retirement
            ("14", None, "VIIRS_NOAA20", "SP"),  # historical NOAA-20
        )
        for hour, run, sat, product in decoys:
            ts = f"2021-08-05T{hour}:00Z"
            s.execute(
                text(FIRE_SQL),
                {
                    "id": f"f-{hour}",
                    "ext": f"x-{hour}",
                    "ts": ts,
                    "run": run,
                    "sat": sat,
                    "product": product,
                },
            )
        s.commit()


def read(live_db, **scope) -> tuple[list[str], dict[str, list[int]]]:
    """(forecast point ids, input hours per frame) for the event, with an optional row_scope."""
    with live_db() as s:
        c = s.connection()
        points, _ = forecast_points(c, EVENT, registry={}, **scope)
        frames = load_inputs(c, EVENT, **scope)
    hours = {
        name: sorted(frames[name][col].dt.hour.tolist())
        for name, col in (
            ("fires", "detected_at"),
            ("weather", "valid_at"),
            ("pm25_observations", "valid_at"),
        )
    }
    return sorted(points["forecast_point_id"]), hours


def test_default_reads_historical_rows_only(live_db):
    """smokesense_v1's build: the live-only monitor is no point and no live row an input."""
    seed(live_db)
    assert read(live_db) == read(live_db, row_scope="historical")
    points, hours = read(live_db)
    assert points == ["airnow:hist"]
    assert hours == {"fires": [10], "weather": [10], "pm25_observations": [10]}


def test_live_scope_reads_live_rows_only(live_db):
    """GEO-03's case: features from live rows, at historical and live-only monitors.

    Live fires are NOAA-20 only: the live SNPP row (13) and historical NOAA-20 row (14)
    are ignored."""
    seed(live_db)
    points, hours = read(live_db, row_scope="live")
    assert points == ["airnow:hist", "airnow:live"]
    assert hours == {
        "fires": [11, 12],
        "weather": [11, 12],
        "pm25_observations": [11, 12],
    }


def test_any_scope_reads_both(live_db):
    """Both scopes and both satellites."""
    seed(live_db)
    points, hours = read(live_db, row_scope="any")
    assert points == ["airnow:hist", "airnow:live"]
    assert hours == {
        "fires": [10, 11, 12, 13, 14],
        "weather": [10, 11, 12],
        "pm25_observations": [10, 11, 12],
    }


def test_unknown_scope_is_rejected():
    with pytest.raises(ValueError, match="row_scope"):
        scope_sql("everything")
    assert scope_sql("historical", "o") == "o.ingestion_run_id is null"
