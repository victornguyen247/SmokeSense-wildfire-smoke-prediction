"""Feature-row alignment helpers for GEO-01."""

from __future__ import annotations

import numpy as np
import pandas as pd

from features.spatial import (
    aggregate_fire_features_200km,
)
from features.temporal import (
    add_lagged_pm25,
    add_temporal_features,
)

ALLOWED_HORIZONS = (1, 3, 6, 12, 24)


def build_feature_times(
    forecast_points: pd.DataFrame,
    issue_times: pd.Series,
    horizons: tuple[int, ...] = ALLOWED_HORIZONS,
) -> pd.DataFrame:
    """
    Create one feature row for each forecast point, issue time,
    and forecast horizon.

    target_time is always calculated from issue_time.

    Parameters
    ----------
    forecast_points:
        DataFrame containing at least:
        forecast_point_id, location_lat, location_lon.

    issue_times:
        UTC timestamps representing when the prediction is issued.

    horizons:
        Forecast horizons in hours.

    Returns
    -------
    pd.DataFrame
        One row per:
        (forecast_point_id, issue_time, horizon_hours).
    """

    if not set(horizons).issubset(set(ALLOWED_HORIZONS)):
        raise ValueError(
            f"Horizons must be from {ALLOWED_HORIZONS}"
        )

    required_columns = {
        "forecast_point_id",
        "location_lat",
        "location_lon",
    }

    missing = required_columns - set(forecast_points.columns)

    if missing:
        raise ValueError(
            f"Missing forecast point columns: {sorted(missing)}"
        )

    normalized_times = pd.to_datetime(
        issue_times,
        utc=True,
    )

    point_count = len(forecast_points)
    time_count = len(normalized_times)
    horizon_values = np.asarray(horizons)
    row_count = point_count * time_count * len(horizons)

    result = pd.DataFrame(
        {
            "forecast_point_id": np.repeat(
                forecast_points["forecast_point_id"].to_numpy(),
                time_count * len(horizons),
            ),
            "location_lat": np.repeat(
                forecast_points["location_lat"].to_numpy(),
                time_count * len(horizons),
            ),
            "location_lon": np.repeat(
                forecast_points["location_lon"].to_numpy(),
                time_count * len(horizons),
            ),
            "issue_time": np.tile(
                np.repeat(normalized_times.to_numpy(), len(horizons)),
                point_count,
            ),
            "horizon_hours": np.tile(
                horizon_values,
                point_count * time_count,
            ),
        },
        index=range(row_count),
    )
    result["issue_time"] = pd.to_datetime(result["issue_time"], utc=True)
    result["target_time"] = result["issue_time"] + pd.to_timedelta(
        result["horizon_hours"], unit="h"
    )
    return result

def add_temporal_alignment_features(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add leakage-free temporal features to aligned feature rows.

    Temporal features are calculated from issue_time because all
    prediction features must be available when the prediction is issued.
    """

    return add_temporal_features(
        dataframe,
        timestamp_column="issue_time",
    )

def add_fire_alignment_features(
    dataframe: pd.DataFrame,
    fire_detections: pd.DataFrame,
    lookback_hours: float = 24.0,
) -> pd.DataFrame:
    """
    Add spatial fire features to aligned prediction rows.

    Only fire detections available before issue_time are used.
    Fire features are calculated relative to each forecast point.

    lookback_hours sets the maximum age of included fire detections.
    """

    result = dataframe.copy()

    required_columns = {
        "forecast_point_id",
        "location_lat",
        "location_lon",
        "issue_time",
    }

    missing = required_columns - set(result.columns)

    if missing:
        raise ValueError(
            f"Missing feature columns: {sorted(missing)}"
        )

    unique_rows = result[
        [
            "forecast_point_id",
            "location_lat",
            "location_lon",
            "issue_time",
        ]
    ].drop_duplicates(["forecast_point_id", "issue_time"])

    fire_feature_rows = []

    for row in unique_rows.itertuples(index=False, name=None):
        features = aggregate_fire_features_200km(
            location_latitude=row[1],
            location_longitude=row[2],
            fire_detections=fire_detections,
            issue_time=row[3],
            lookback_hours=lookback_hours,
        )

        fire_feature_rows.append(
            {
                "forecast_point_id": row[0],
                "issue_time": row[3],
                **features,
            }
        )
    return result.merge(
        pd.DataFrame(fire_feature_rows),
        on=["forecast_point_id", "issue_time"],
        how="left",
        validate="many_to_one",
    )

def add_pm25_alignment_features(
    dataframe: pd.DataFrame,
    pm25_history: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add historical PM2.5 lag features to aligned rows.

    PM2.5 history must contain one or more observations per
    forecast point and issue_time.

    Lag values are calculated only from observations earlier
    than the current issue_time.
    """

    result = dataframe.copy()

    required_feature_columns = {
        "forecast_point_id",
        "issue_time",
    }

    missing = (
        required_feature_columns
        - set(result.columns)
    )

    if missing:
        raise ValueError(
            f"Missing feature columns: {sorted(missing)}"
        )

    required_history_columns = {
        "forecast_point_id",
        "issue_time",
        "pm25",
    }

    missing = (
        required_history_columns
        - set(pm25_history.columns)
    )

    if missing:
        raise ValueError(
            f"Missing PM2.5 columns: {sorted(missing)}"
        )

    history = pm25_history.copy()

    history["issue_time"] = pd.to_datetime(
        history["issue_time"],
        utc=True,
    )

    result["issue_time"] = pd.to_datetime(
        result["issue_time"],
        utc=True,
    )

    # Compute lags for unique (point, issue_time) pairs. Aligned output
    # has one row per horizon, so processing it directly creates duplicate
    # placeholder timestamps and ambiguous many-to-many merges.
    prediction_times = result[["forecast_point_id", "issue_time"]].drop_duplicates()
    combined = pd.concat(
        [history, prediction_times.assign(pm25=float("nan"))],
        ignore_index=True,
    )
    combined = add_lagged_pm25(
        combined,
        group_column="forecast_point_id",
        timestamp_column="issue_time",
        pm25_column="pm25",
    )

    lag_columns = [
        "pm25_lag_1h",
        "pm25_lag_3h",
        "pm25_lag_6h",
        "pm25_lag_12h",
        "pm25_lag_24h",
    ]

    lag_values = combined[
        ["forecast_point_id", "issue_time"] + lag_columns
    ].drop_duplicates(["forecast_point_id", "issue_time"])
    result = result.merge(
        lag_values,
        on=["forecast_point_id", "issue_time"],
        how="left",
        validate="many_to_one",
    )
    for column in lag_columns:
        if column not in result:
            result[column] = pd.NA

    return result

def add_weather_alignment_features(
    dataframe: pd.DataFrame,
    weather_forecasts: pd.DataFrame,
    point_weather_map: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add leakage-free NWS forecast features.

    For each prediction row, select the latest weather forecast
    issued before issue_time whose valid_at matches target_time.

    The point_weather_map connects each forecast point to its
    corresponding NWS grid.
    """

    result = dataframe.copy()

    required_feature_columns = {
        "forecast_point_id",
        "issue_time",
        "target_time",
    }

    missing = (
        required_feature_columns
        - set(result.columns)
    )

    if missing:
        raise ValueError(
            f"Missing feature columns: {sorted(missing)}"
        )

    required_weather_columns = {
        "grid_id",
        "issued_at",
        "valid_at",
        "wind_speed_ms",
        "wind_dir_deg",
        "temp_c",
        "rh_pct",
        "precip_prob_pct",
    }

    missing = (
        required_weather_columns
        - set(weather_forecasts.columns)
    )

    if missing:
        raise ValueError(
            f"Missing weather columns: {sorted(missing)}"
        )

    required_map_columns = {
        "forecast_point_id",
        "grid_id",
    }

    missing = (
        required_map_columns
        - set(point_weather_map.columns)
    )

    if missing:
        raise ValueError(
            f"Missing weather-map columns: {sorted(missing)}"
        )

    result["issue_time"] = pd.to_datetime(
        result["issue_time"],
        utc=True,
    )

    result["target_time"] = pd.to_datetime(
        result["target_time"],
        utc=True,
    )

    weather = weather_forecasts.copy()

    weather["issued_at"] = pd.to_datetime(
        weather["issued_at"],
        utc=True,
    )

    weather["valid_at"] = pd.to_datetime(
        weather["valid_at"],
        utc=True,
    )

    feature_columns = [
        "wind_alignment", "wind_speed_ms", "wind_dir_sin", "wind_dir_cos",
        "temp_c", "rh_pct", "precip_prob_pct",
    ]
    result = result.drop(
        columns=[*feature_columns, "grid_id"],
        errors="ignore",
    )

    # Match each row to the latest forecast issued strictly before issue_time.
    # merge_asof avoids filtering the full weather table once per feature row.
    map_columns = point_weather_map[
        ["forecast_point_id", "grid_id"]
    ].drop_duplicates("forecast_point_id")
    result = result.reset_index(drop=True).copy()
    result["_row_id"] = np.arange(len(result))
    result = result.merge(map_columns, on="forecast_point_id", how="left")
    result = result.set_index("_row_id", drop=False).sort_index()
    candidates = result.dropna(
        subset=["grid_id", "issue_time", "target_time"]
    ).copy()
    weather_columns = [
        "grid_id", "issued_at", "wind_speed_ms",
        "wind_dir_deg", "temp_c", "rh_pct", "precip_prob_pct",
    ]
    weather_for_join = weather[weather_columns].copy()
    weather_for_join["target_time"] = weather["valid_at"]
    weather_for_join = weather_for_join.dropna(
        subset=["grid_id", "issued_at", "target_time"]
    )
    weather_for_join = weather_for_join.sort_values(
        "issued_at", kind="mergesort"
    ).drop_duplicates(
        ["grid_id", "target_time", "issued_at"],
        keep="first",
    )
    matched = pd.merge_asof(
        candidates.sort_values("issue_time", kind="mergesort"),
        weather_for_join,
        left_on="issue_time",
        right_on="issued_at",
        by=["grid_id", "target_time"],
        direction="backward",
        allow_exact_matches=False,
    )

    result[feature_columns] = pd.NA
    matched = matched.set_index("_row_id")
    row_ids = matched.index
    wind_direction = pd.to_numeric(
        matched["wind_dir_deg"], errors="coerce"
    )
    radians = np.radians(wind_direction)
    result.loc[row_ids, "wind_dir_sin"] = np.sin(radians)
    result.loc[row_ids, "wind_dir_cos"] = np.cos(radians)
    for column in ("wind_speed_ms", "temp_c", "rh_pct", "precip_prob_pct"):
        result.loc[row_ids, column] = matched[column]

    # Wind direction uses the meteorological FROM convention. Converting
    # both angles to their TO directions adds 180 degrees to each, which
    # cancels in the cosine difference.
    bearing = pd.to_numeric(result.loc[row_ids, "fire_bearing_deg"], errors="coerce")
    result.loc[row_ids, "wind_alignment"] = np.cos(
        np.radians(bearing - wind_direction)
    )

    return result.drop(columns="_row_id").reset_index(drop=True)

def add_pm25_target(
    dataframe: pd.DataFrame,
    observations: pd.DataFrame,
    max_distance_km: float = 25.0,
) -> pd.DataFrame:
    """
    Attach the PM2.5 training target for each prediction row.

    Only observations matching target_time are eligible.

    Eligible observations:
        - correction == regulatory
        - correction == purpleair_barkjohn
        - qa_flag == ok

    The nearest eligible monitor within max_distance_km is used.
    """

    result = dataframe.copy()

    required_feature_columns = {
        "forecast_point_id",
        "location_lat",
        "location_lon",
        "target_time",
    }

    missing = (
        required_feature_columns
        - set(result.columns)
    )

    if missing:
        raise ValueError(
            f"Missing feature columns: {sorted(missing)}"
        )

    required_observation_columns = {
        "monitor_id",
        "valid_at",
        "pm25",
        "correction",
        "qa_flag",
        "latitude",
        "longitude",
    }

    missing = (
        required_observation_columns
        - set(observations.columns)
    )

    if missing:
        raise ValueError(
            f"Missing observation columns: {sorted(missing)}"
        )

    result["target_time"] = pd.to_datetime(
        result["target_time"],
        utc=True,
    )

    obs = observations.copy()

    obs["valid_at"] = pd.to_datetime(
        obs["valid_at"],
        utc=True,
    )

    # Only use target observations allowed by the
    # Parquet training contract.
    obs = obs[
        obs["correction"].isin(
            [
                "regulatory",
                "purpleair_barkjohn",
            ]
        )
        & (obs["qa_flag"] == "ok")
    ].copy()

    result["target_pm25"] = pd.NA
    result["target_source"] = pd.NA
    result["target_monitor_dist_km"] = pd.NA
    result["target_monitor_id"] = pd.NA

    observations_by_time = {
        timestamp: group
        for timestamp, group in obs.groupby("valid_at", sort=False)
    }

    for index, row in result.iterrows():
        candidates = observations_by_time.get(row["target_time"])

        if candidates is None or candidates.empty:
            continue

        lat1 = np.radians(float(row["location_lat"]))
        lat2 = np.radians(candidates["latitude"].to_numpy(dtype=float))
        delta_lat = lat2 - lat1
        delta_lon = np.radians(
            candidates["longitude"].to_numpy(dtype=float)
            - float(row["location_lon"])
        )
        a = (
            np.sin(delta_lat / 2) ** 2
            + np.cos(lat1) * np.cos(lat2) * np.sin(delta_lon / 2) ** 2
        )
        distances = 2 * 6371.008 * np.arctan2(
            np.sqrt(a), np.sqrt(1 - a)
        )
        eligible = np.flatnonzero(distances <= max_distance_km)
        if not len(eligible):
            continue

        nearest_position = eligible[np.argmin(distances[eligible])]
        target = candidates.iloc[nearest_position]

        result.at[index, "target_pm25"] = (
            target["pm25"]
        )

        result.at[index, "target_source"] = (
            target["correction"]
        )

        result.at[index, "target_monitor_dist_km"] = (
            distances[nearest_position]
        )

        result.at[index, "target_monitor_id"] = (
            target["monitor_id"]
        )

    return result

def build_feature_dataset(
    forecast_points: pd.DataFrame,
    issue_times: pd.Series,
    fire_detections: pd.DataFrame,
    pm25_history: pd.DataFrame,
    weather_forecasts: pd.DataFrame,
    point_weather_map: pd.DataFrame,
    pm25_observations: pd.DataFrame,
    pilot_event_id: str | None = None,
    horizons: tuple[int, ...] = ALLOWED_HORIZONS,
    lookback_hours: float = 24.0,
) -> pd.DataFrame:
    """
    Build the complete GEO-01 feature dataset.

    The pipeline applies feature transformations in dependency order:

        1. Create aligned prediction rows.
        2. Add temporal features.
        3. Add fire features.
        4. Add PM2.5 lag features.
        5. Add NWS forecast features.
        6. Add PM2.5 target labels.

    Returns a DataFrame containing the feature columns required
    by the GEO-01 Parquet contract.

    lookback_hours controls how far back fire detections are included.
    """

    result = build_feature_times(
        forecast_points=forecast_points,
        issue_times=issue_times,
        horizons=horizons,
    )

    result = add_temporal_alignment_features(
        result,
    )

    result = add_fire_alignment_features(
        result,
        fire_detections,
        lookback_hours=lookback_hours,
    )

    result = add_pm25_alignment_features(
        result,
        pm25_history,
    )

    result = add_weather_alignment_features(
        result,
        weather_forecasts,
        point_weather_map,
    )

    # Current NWS forecast input does not include pressure. Keep the
    # documented Parquet field present and null until that source is added.
    result["pressure_hpa"] = pd.NA

    result = add_pm25_target(
        result,
        pm25_observations,
    )

    if pilot_event_id is not None:
        result["pilot_event_id"] = pilot_event_id
    else:
        result["pilot_event_id"] = pd.NA

    # Drop rows that do not have an eligible PM2.5 training target.
    result = result.dropna(
        subset=["target_pm25"]
    ).reset_index(drop=True)

    from features.validation import validate_feature_dataset

    validate_feature_dataset(result)

    return result
