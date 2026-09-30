"""Feature-row alignment helpers for GEO-01."""

from __future__ import annotations

import math

import pandas as pd

from features.spatial import (
    aggregate_fire_features_200km,
    haversine_distance_km,
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

    rows = []

    for _, point in forecast_points.iterrows():
        for issue_time in normalized_times:
            for horizon in horizons:
                target_time = (
                    issue_time
                    + pd.Timedelta(hours=horizon)
                )

                rows.append(
                    {
                        "forecast_point_id": (
                            point["forecast_point_id"]
                        ),
                        "location_lat": point["location_lat"],
                        "location_lon": point["location_lon"],
                        "issue_time": issue_time,
                        "target_time": target_time,
                        "horizon_hours": horizon,
                    }
                )

    return pd.DataFrame(rows)

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
) -> pd.DataFrame:
    """
    Add spatial fire features to aligned prediction rows.

    Only fire detections available before issue_time are used.
    Fire features are calculated relative to each forecast point.
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

    for index, row in result.iterrows():
        features = aggregate_fire_features_200km(
            location_latitude=row["location_lat"],
            location_longitude=row["location_lon"],
            fire_detections=fire_detections,
            issue_time=row["issue_time"],
        )

        for column, value in features.items():
            result.at[index, column] = value

    return result

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

    # Combine historical observations with the
    # prediction rows so shift() can calculate
    # the historical values.
    combined = pd.concat(
        [
            history,
            result[
                [
                    "forecast_point_id",
                    "issue_time",
                ]
            ].assign(pm25=float("nan")),
        ],
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

    prediction_times = result[
        [
            "forecast_point_id",
            "issue_time",
        ]
    ].copy()

    prediction_times["_prediction_row"] = (
        prediction_times.index
    )

    combined = combined.merge(
        prediction_times,
        on=[
            "forecast_point_id",
            "issue_time",
        ],
        how="inner",
    )

    lag_values = combined[
        ["_prediction_row"] + lag_columns
    ].drop_duplicates(
        "_prediction_row"
    ).set_index("_prediction_row")

    for column in lag_columns:
        result[column] = lag_values[column]

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

    # Connect each forecast point to its NWS grid.
    result = result.merge(
        point_weather_map[
            [
                "forecast_point_id",
                "grid_id",
            ]
        ].drop_duplicates(
            "forecast_point_id"
        ),
        on="forecast_point_id",
        how="left",
    )

    # Create output columns first.
    result["wind_alignment"] = pd.NA
    result["wind_speed_ms"] = pd.NA
    result["wind_dir_sin"] = pd.NA
    result["wind_dir_cos"] = pd.NA
    result["temp_c"] = pd.NA
    result["rh_pct"] = pd.NA
    result["precip_prob_pct"] = pd.NA

    for index, row in result.iterrows():
        grid_id = row["grid_id"]
        issue_time = row["issue_time"]
        target_time = row["target_time"]

        if pd.isna(grid_id):
            continue

        candidates = weather[
            (weather["grid_id"] == grid_id)
            & (weather["valid_at"] == target_time)
            & (weather["issued_at"] < issue_time)
        ].copy()

        if candidates.empty:
            continue

        # Use the most recently issued forecast that was
        # already available when the prediction was made.
        forecast = candidates.loc[
            candidates["issued_at"].idxmax()
        ]

        wind_direction = forecast["wind_dir_deg"]

        if pd.notna(wind_direction):
            wind_radians = math.radians(
                float(wind_direction)
            )

            result.at[index, "wind_dir_sin"] = (
                math.sin(wind_radians)
            )

            result.at[index, "wind_dir_cos"] = (
                math.cos(wind_radians)
            )

        result.at[index, "wind_speed_ms"] = (
            forecast["wind_speed_ms"]
        )

        result.at[index, "temp_c"] = (
            forecast["temp_c"]
        )

        result.at[index, "rh_pct"] = (
            forecast["rh_pct"]
        )

        result.at[index, "precip_prob_pct"] = (
            forecast["precip_prob_pct"]
        )

        # The Parquet contract defines wind_alignment as:
        #
        # cos(fire_bearing_deg - wind_dir_deg)
        #
        # wind_dir_deg is the meteorological "FROM" direction.
        if (
            pd.notna(wind_direction)
            and pd.notna(row.get("fire_bearing_deg"))
        ):
            fire_bearing = float(
                row["fire_bearing_deg"]
            )

            wind_alignment = math.cos(
                math.radians(
                    fire_bearing
                    - float(wind_direction)
                )
            )

            result.at[index, "wind_alignment"] = (
                wind_alignment
            )

    return result

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

    for index, row in result.iterrows():
        candidates = obs[
            obs["valid_at"] == row["target_time"]
        ].copy()

        if candidates.empty:
            continue

        distances = []

        for _, monitor in candidates.iterrows():
            distance = haversine_distance_km(
                row["location_lat"],
                row["location_lon"],
                monitor["latitude"],
                monitor["longitude"],
            )

            distances.append(distance)

        candidates["distance_km"] = distances

        candidates = candidates[
            candidates["distance_km"] <= max_distance_km
        ]

        if candidates.empty:
            continue

        # Use the nearest eligible monitor.
        target = candidates.loc[
            candidates["distance_km"].idxmin()
        ]

        result.at[index, "target_pm25"] = (
            target["pm25"]
        )

        result.at[index, "target_source"] = (
            target["correction"]
        )

        result.at[index, "target_monitor_dist_km"] = (
            target["distance_km"]
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
    horizons: tuple[int, ...] = ALLOWED_HORIZONS,
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

    result = add_pm25_target(
        result,
        pm25_observations,
    )

    return result