
"""Leave-one-monitor-out IDW PM2.5 features for SmokeSense ML-02."""

from __future__ import annotations

import numpy as np
import pandas as pd


LAG_HOURS = (1, 3, 6, 12, 24)
EARTH_RADIUS_KM = 6371.0088

# Provisional settings; align with PM-03 before final evaluation.
DEFAULT_POWER = 2.0
DEFAULT_RADIUS_KM = 100.0
DEFAULT_K = 4


def idw_average(values, distances_km, power=2.0):
    """Calculate an inverse-distance weighted average."""
    values = np.asarray(values, dtype=float)
    distances = np.asarray(distances_km, dtype=float)

    if values.shape != distances.shape:
        raise ValueError("Values and distances must match")

    if not np.isfinite(power) or power <= 0:
        raise ValueError("IDW power must be positive and finite")

    valid = (
        np.isfinite(values)
        & np.isfinite(distances)
        & (distances > 0)
    )

    if not valid.any():
        return np.nan

    weights = distances[valid] ** (-power)

    return float(
        np.average(values[valid], weights=weights)
    )


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate great-circle distances in kilometers."""
    lat1, lon1, lat2, lon2 = map(
        np.radians, [lat1, lon1, lat2, lon2]
    )

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1)
        * np.cos(lat2)
        * np.sin(dlon / 2) ** 2
    )

    a = np.clip(a, 0.0, 1.0)

    return 2 * EARTH_RADIUS_KM * np.arcsin(
        np.sqrt(a)
    )


def compute_idw_lags(
    dataframe: pd.DataFrame,
    pm25_observations: pd.DataFrame,
    *,
    power: float = DEFAULT_POWER,
    max_radius_km: float = DEFAULT_RADIUS_KM,
    k: int = DEFAULT_K,
) -> pd.DataFrame:
    """
    Generate leave-one-monitor-out IDW PM2.5 lag features.

    For every forecast point and issue time:
      1. Look up observations at issue_time - lag_hours.
      2. Exclude the target monitor by ID.
      3. Find neighboring monitors within the search radius.
      4. Select the k nearest eligible neighbors.
      5. Compute IDW using their PM2.5 measurements.
      6. Return NaN when no valid neighbors exist.

    Supported lag hours: 1, 3, 6, 12, 24.

    Required dataframe columns:
        forecast_point_id
        location_lat
        location_lon
        issue_time

    Required pm25_observations columns:
        monitor_id
        valid_at
        pm25
        latitude
        longitude

    Returns:
        Copy of dataframe with five pm25_lag_* columns.

    Important:
        This function assumes observation timestamps are
        normalized and measurements are available by the
        requested forecast issue time.
    """
    if not np.isfinite(power) or power <= 0:
        raise ValueError(
            "power must be positive and finite"
        )

    if (
        not np.isfinite(max_radius_km)
        or max_radius_km <= 0
    ):
        raise ValueError(
            "max_radius_km must be positive and finite"
        )

    if type(k) is not int or k < 1:
        raise ValueError(
            "k must be a positive integer"
        )

    required_points = {
        "forecast_point_id",
        "location_lat",
        "location_lon",
        "issue_time",
    }

    required_observations = {
        "monitor_id",
        "valid_at",
        "pm25",
        "latitude",
        "longitude",
    }

    missing_points = (
        required_points - set(dataframe.columns)
    )

    if missing_points:
        raise ValueError(
            f"Missing forecast point columns: "
            f"{sorted(missing_points)}"
        )

    missing_obs = (
        required_observations
        - set(pm25_observations.columns)
    )

    if missing_obs:
        raise ValueError(
            f"Missing observation columns: "
            f"{sorted(missing_obs)}"
        )

    result = dataframe.copy()
    obs = pm25_observations.copy()

    result["issue_time"] = pd.to_datetime(
        result["issue_time"],
        utc=True,
    )

    obs["valid_at"] = pd.to_datetime(
        obs["valid_at"],
        utc=True,
    )

    for column in (
        "pm25",
        "latitude",
        "longitude",
    ):
        obs[column] = pd.to_numeric(
            obs[column],
            errors="coerce",
        )

    obs = obs.dropna(
        subset=[
            "monitor_id",
            "valid_at",
            "pm25",
            "latitude",
            "longitude",
        ]
    ).copy()

    obs = obs[
        np.isfinite(obs["pm25"])
        & (obs["pm25"] >= 0)
        & obs["latitude"].between(-90, 90)
        & obs["longitude"].between(-180, 180)
    ].copy()

    # Ambiguous duplicate observations must be resolved
    # upstream rather than silently selecting one.
    if obs.duplicated(
        ["monitor_id", "valid_at"]
    ).any():
        raise ValueError(
            "Duplicate observations for the same "
            "monitor and timestamp"
        )

    observations_by_time = {
        timestamp: group
        for timestamp, group in obs.groupby(
            "valid_at",
            sort=False,
        )
    }

    lag_columns = [
        f"pm25_lag_{h}h"
        for h in LAG_HOURS
    ]

    # Remove existing lag columns before generating new ones.
    result = result.drop(
        columns=lag_columns,
        errors="ignore",
    )

    unique_points = result[
        [
            "forecast_point_id",
            "location_lat",
            "location_lon",
            "issue_time",
        ]
    ].drop_duplicates()

    # Every point/time must map to one location.
    if unique_points.duplicated(
        ["forecast_point_id", "issue_time"]
    ).any():
        raise ValueError(
            "Conflicting coordinates for a forecast "
            "point at the same issue time"
        )

    lag_rows = []

    for point in unique_points.itertuples(
        index=False
    ):
        lag_row = {
            "forecast_point_id": point.forecast_point_id,
            "issue_time": point.issue_time,
        }

        for lag_hours in LAG_HOURS:
            lag_column = (
                f"pm25_lag_{lag_hours}h"
            )

            history_time = (
                point.issue_time
                - pd.Timedelta(hours=lag_hours)
            )

            candidates = observations_by_time.get(
                history_time
            )

            if candidates is None or candidates.empty:
                lag_row[lag_column] = np.nan
                continue

            # Leave-one-monitor-out exclusion.
            neighbors = candidates[
                candidates["monitor_id"]
                != point.forecast_point_id
            ].copy()

            if neighbors.empty:
                lag_row[lag_column] = np.nan
                continue

            distances = haversine_km(
                point.location_lat,
                point.location_lon,
                neighbors["latitude"].to_numpy(
                    dtype=float
                ),
                neighbors["longitude"].to_numpy(
                    dtype=float
                ),
            )

            neighbors["distance_km"] = distances

            neighbors = neighbors[
                np.isfinite(neighbors["distance_km"])
                & (
                    neighbors["distance_km"]
                    <= max_radius_km
                )
                & (
                    neighbors["distance_km"]
                    >= 0
                )
            ].copy()

            if neighbors.empty:
                lag_row[lag_column] = np.nan
                continue

            neighbors = (
                neighbors.sort_values(
                    ["distance_km", "monitor_id"],
                    kind="mergesort",
                )
                .head(k)
            )

            # Distinct monitor IDs may share coordinates.
            # At zero distance, use colocated readings.
            zero_distance = neighbors[
                neighbors["distance_km"] == 0
            ]

            if not zero_distance.empty:
                prediction = float(
                    zero_distance["pm25"].mean()
                )
            else:
                prediction = idw_average(
                    neighbors["pm25"].to_numpy(
                        dtype=float
                    ),
                    neighbors["distance_km"].to_numpy(
                        dtype=float
                    ),
                    power=power,
                )

            lag_row[lag_column] = prediction

        lag_rows.append(lag_row)

    lag_frame = pd.DataFrame(
        lag_rows,
        columns=[
            "forecast_point_id",
            "issue_time",
            *lag_columns,
        ],
    )

    result = result.merge(
        lag_frame,
        on=[
            "forecast_point_id",
            "issue_time",
        ],
        how="left",
        validate="many_to_one",
        sort=False,
    )

    return result
