"""Read seeded points and reuse training feature calculations for GEO-03.

No writes or model loading. OPS owns feed health and the publication cutoff.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.scope import CALIFORNIA_BBOX, in_california_scope
from dataset_build.build_v1 import DTYPES, load_inputs
from features.alignment import build_input_features
from features.idw import interpolate_to_grid as interpolate_frames
from ingestion.batch.batch_ingest import PilotEvent
from ml.feature_columns import FEATURES

INPUT_COLUMNS = [column for column in FEATURES if column != "horizon_hours"]
OUTPUT_COLUMNS = ["forecast_point_id", "issued_at", *INPUT_COLUMNS]


def _empty_features() -> pd.DataFrame:
    """Keep the inference adapter's UTC and numeric schema even with no rows."""
    return pd.DataFrame({
        "forecast_point_id": pd.Series(dtype="string"),
        "issued_at": pd.Series(dtype="datetime64[ns, UTC]"),
        **{column: pd.Series(dtype=DTYPES[column]) for column in INPUT_COLUMNS},
    })


def load_monitor_points(connection: Connection) -> pd.DataFrame:
    """Seeded active outdoor AirNow points; keep both namespaces explicit."""
    points = pd.read_sql(text("""
        SELECT fp.id AS forecast_point_id, m.external_id, m.aqs_code,
               ST_Y(fp.geom::geometry) AS location_lat,
               ST_X(fp.geom::geometry) AS location_lon
        FROM forecast_points fp JOIN monitors m ON m.id = fp.monitor_id
        WHERE fp.kind = 'monitor' AND fp.active AND m.active
          AND m.source = 'airnow' AND m.location_type = 'outdoor'
        ORDER BY fp.id
    """), connection)
    return points.loc[points.aqs_code.map(in_california_scope)].reset_index(drop=True)


def build_monitor_features(
    t: object,
    *,
    connection: Connection,
    fire_feed_available: bool,
    row_scope: str = "live",
    event: PilotEvent | None = None,
) -> pd.DataFrame:
    """One PM-03 input row per eligible seeded monitor at UTC hour t.

    Use historical scope and the original event for Parquet parity. Live calls
    cover California plus the loader's source-specific margins. A healthy empty
    fire feed means no fires; an unavailable feed must skip the cycle.
    """
    issued_at = pd.Timestamp(t)
    if pd.isna(issued_at) or issued_at.tzinfo is None:
        raise ValueError("t must be a timezone-aware UTC hour")
    issued_at = issued_at.tz_convert("UTC")
    if issued_at != issued_at.floor("h"):
        raise ValueError("t must be the top of an hour")
    if not fire_feed_available:
        raise RuntimeError("Fire feed unavailable; skip this forecast cycle")
    if event is None:
        day = issued_at.date().isoformat()
        event = PilotEvent("GEO-03", "California live", str(CALIFORNIA_BBOX), day, day)
    points = load_monitor_points(connection)
    if points.empty:
        raise RuntimeError(
            "No active seeded California monitor forecast points; "
            "run python -m app.db.seed_ca_forecast_grid --sync-monitors first"
        )
    frames = load_inputs(connection, event, row_scope=row_scope)
    history = frames["pm25_history"].copy()
    # The loader uses monitors.external_id; serving output uses forecast_points.id.
    history = history.rename(columns={"forecast_point_id": "external_id"}).merge(
        points[["external_id", "forecast_point_id"]], on="external_id", validate="many_to_one"
    )
    history["issue_time"] = pd.to_datetime(history["issue_time"], utc=True)
    recent = history.loc[
        history.issue_time.ge(issued_at - pd.Timedelta(hours=24))
        & history.issue_time.lt(issued_at) & history.pm25.notna(), "forecast_point_id"
    ]
    points = points.loc[points.forecast_point_id.isin(recent)]
    if points.empty:
        return _empty_features()
    rows = build_input_features(
        points, pd.Series([issued_at]), frames["fires"], history, frames["weather"], horizons=(1,)
    )
    for column in INPUT_COLUMNS:
        dtype = DTYPES[column]
        rows[column] = (rows[column].astype(bool) if dtype == "bool" else
                        pd.to_numeric(rows[column], errors="raise").astype(dtype))
    return rows.rename(columns={"issue_time": "issued_at"})[OUTPUT_COLUMNS]


def interpolate_to_grid(monitor_forecasts: pd.DataFrame, *, connection: Connection) -> pd.DataFrame:
    """Interpolate onto active seeded grid centroids; return rows for OPS to write."""
    grid = pd.read_sql(text("""
        SELECT id AS forecast_point_id, ST_Y(geom::geometry) AS location_lat,
               ST_X(geom::geometry) AS location_lon
        FROM forecast_points WHERE kind = 'grid_cell' AND active ORDER BY id
    """), connection)
    if grid.empty:
        raise RuntimeError("No active seeded grid cells; run python -m app.db.seed_ca_forecast_grid first")
    return interpolate_frames(monitor_forecasts, load_monitor_points(connection), grid)
