"""PM-03 Stage B: deterministic IDW of monitor forecasts at grid centroids."""
from __future__ import annotations

import numpy as np
import pandas as pd

from features.alignment import ALLOWED_HORIZONS
from features.spatial import EARTH_RADIUS_KM

OUTPUT_COLUMNS = ["forecast_point_id", "issued_at", "horizon_hours", "pm25_predicted",
                  "source", "model_key", "target_time", "nearest_monitor_dist_km", "feature_snapshot"]
POINT_COLUMNS = ["forecast_point_id", "location_lat", "location_lon"]


def _points(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(POINT_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing point columns: {sorted(missing)}")
    if frame.forecast_point_id.isna().any() or frame.forecast_point_id.duplicated().any():
        raise ValueError("Point IDs must be present and unique")
    coords = frame[["location_lat", "location_lon"]].to_numpy(dtype=float)
    if not np.isfinite(coords).all() or (np.abs(coords) > [90, 180]).any():
        raise ValueError("Point coordinates must be finite WGS84 coordinates")
    return frame[POINT_COLUMNS]


def interpolate_to_grid(
    monitor_forecasts: pd.DataFrame,
    monitor_points: pd.DataFrame,
    grid_points: pd.DataFrame,
) -> pd.DataFrame:
    """Four nearest v2/persistence monitors within 50 km; 1/max(d, 1)^2.

    Groups are independent UTC issue-hour/horizon pairs. Null/nonfinite model
    predictions produce no contribution. Uncovered cells produce no row.
    Snapshot weights are normalized, distances retain their unfloored values.
    """
    monitors, grid = _points(monitor_points), _points(grid_points)
    required = {"forecast_point_id", "issued_at", "horizon_hours", "pm25_predicted",
                "source", "model_key"}
    missing = required - set(monitor_forecasts.columns)
    if missing:
        raise ValueError(f"Missing forecast columns: {sorted(missing)}")
    forecasts = monitor_forecasts[list(required)].copy()
    if any(pd.Timestamp(t).tzinfo is None for t in forecasts.issued_at):
        raise ValueError("issued_at must be timezone-aware")
    forecasts["issued_at"] = pd.to_datetime(forecasts.issued_at, utc=True)
    if forecasts.issued_at.isna().any() or (
        forecasts.issued_at != forecasts.issued_at.dt.floor("h")
    ).any():
        raise ValueError("issued_at must be a UTC hour")
    if not forecasts.horizon_hours.isin(ALLOWED_HORIZONS).all():
        raise ValueError("Unsupported forecast horizon")
    forecasts["target_time"] = forecasts.issued_at + pd.to_timedelta(forecasts.horizon_hours, unit="h")
    if "target_time" in monitor_forecasts:
        target = monitor_forecasts.target_time
        if any(pd.Timestamp(t).tzinfo is None for t in target):
            raise ValueError("target_time must be timezone-aware")
        if not pd.to_datetime(target, utc=True).eq(forecasts.target_time).all():
            raise ValueError("target_time must equal issued_at plus horizon_hours")
    if forecasts.duplicated(["forecast_point_id", "issued_at", "horizon_hours"]).any():
        raise ValueError("Duplicate monitor forecasts")
    if not forecasts.source.isin(["v2", "persistence", "fallback"]).all():
        raise ValueError("Unexpected Stage A source")
    values = pd.to_numeric(forecasts.pm25_predicted, errors="raise")
    if (values < 0).any():
        raise ValueError("PM2.5 predictions must be nonnegative")
    forecasts["pm25_predicted"] = values
    forecasts = forecasts.loc[forecasts.source.isin(["v2", "persistence"]) & np.isfinite(values)]
    # An unknown/inactive monitor must never silently project onto the grid.
    if not forecasts.forecast_point_id.isin(monitors.forecast_point_id).all():
        raise ValueError("Forecast refers to an unknown or inactive monitor point")
    forecasts = forecasts.merge(monitors, on="forecast_point_id", validate="many_to_one")
    rows = []
    grid_radians = np.radians(grid[["location_lat", "location_lon"]].to_numpy(dtype=float))
    for (issued_at, horizon), group in forecasts.groupby(["issued_at", "horizon_hours"], sort=True):
        if (group.model_key.isna().any() or group.model_key.nunique() != 1
                or not str(group.model_key.iloc[0]).strip()):
            raise ValueError("Each issue hour/horizon must use one explicit model_key")
        group = group.sort_values("forecast_point_id").reset_index(drop=True)
        coords = np.radians(group[["location_lat", "location_lon"]].to_numpy(dtype=float))
        delta = coords[None, :, :] - grid_radians[:, None, :]
        a = np.sin(delta[:, :, 0] / 2) ** 2 + (
            np.cos(grid_radians[:, None, 0]) * np.cos(coords[None, :, 0])
            * np.sin(delta[:, :, 1] / 2) ** 2
        )
        distances = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
        for cell, cell_distances in zip(grid.itertuples(index=False), distances):
            order = np.argsort(cell_distances, kind="stable")
            # Micrometre tolerance for floating-point roundoff at exactly 50 km.
            selected = order[cell_distances[order] <= 50.0 + 1e-9][:4]
            if not len(selected):
                continue
            d = cell_distances[selected]
            weights = 1 / np.maximum(d, 1.0) ** 2
            weights /= weights.sum()
            neighbors = group.iloc[selected]
            snapshot = [{"id": r.forecast_point_id, "distance_km": float(distance),
                         "weight": float(weight), "pm25": float(r.pm25_predicted), "source": r.source}
                        for r, distance, weight in zip(neighbors.itertuples(index=False), d, weights)]
            rows.append({
                "forecast_point_id": cell.forecast_point_id, "issued_at": issued_at,
                "horizon_hours": int(horizon),
                "pm25_predicted": float(np.dot(weights, neighbors.pm25_predicted)),
                "source": "idw", "model_key": group.model_key.iloc[0],
                "target_time": issued_at + pd.Timedelta(hours=int(horizon)),
                "nearest_monitor_dist_km": float(d[0]), "feature_snapshot": {"monitors": snapshot},
            })
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    for column in ("issued_at", "target_time"):
        result[column] = pd.to_datetime(result[column], utc=True)
    return result
