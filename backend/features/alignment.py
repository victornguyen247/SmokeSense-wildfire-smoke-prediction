
"""Feature-row alignment helpers for GEO-01 and ML-02."""

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
WEATHER_MAX_AGE_HOURS = 3


def build_feature_times(
    forecast_points: pd.DataFrame,
    issue_times: pd.Series,
    horizons: tuple[int, ...] = ALLOWED_HORIZONS,
) -> pd.DataFrame:
    """
    Create one feature row for each forecast point, issue time,
    and forecast horizon.

    target_time is always calculated from issue_time.
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

    result["issue_time"] = pd.to_datetime(
        result["issue_time"], utc=True
    )
    result["target_time"] = (
        result["issue_time"]
        + pd.to_timedelta(result["horizon_hours"], unit="h")
    )

    return result


def add_temporal_alignment_features(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add calendar and solar-time features from issue_time.
    """
    return add_temporal_features(
        dataframe,
        timestamp_column="issue_time",
    )


def add_fire_alignment_features(
    dataframe: pd.DataFrame,
    fire_detections: pd.DataFrame,
    lookback_hours: float = 72.0,
) -> pd.DataFrame:
    """
    Add spatial fire features using detections before issue_time.
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
    lag_mode: str = "own",
    pm25_observations: pd.DataFrame | None = None,
    idw_power: float = 2.0,
    idw_max_radius_km: float = 100.0,
    idw_k: int = 4,
) -> pd.DataFrame:
    """
    Add historical PM2.5 lag features.

    Modes:
        own:
            Original own-monitor historical readings.

        idw-loo:
            Inverse-distance-weighted readings from other
            monitors, excluding the forecast monitor.

    The default own mode preserves the original DATA-04 logic.
    """
    if lag_mode not in ("own", "idw-loo"):
        raise ValueError(
            f"Unknown PM2.5 lag mode: {lag_mode!r}"
        )

    if lag_mode == "idw-loo":
        if pm25_observations is None:
            raise ValueError(
                "pm25_observations is required "
                "for lag_mode='idw-loo'"
            )

        from features.pm25_idw import compute_idw_lags

        # Match the original regulatory AirNow lag source.
        observations = pm25_observations.copy()

        if "correction" in observations.columns:
            observations = observations.loc[
                observations["correction"] == "regulatory"
            ].copy()

        return compute_idw_lags(
            dataframe,
            observations,
            power=idw_power,
            max_radius_km=idw_max_radius_km,
            k=idw_k,
        )

    # Original DATA-04 own-monitor implementation.
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

    # Calculate lags only once per unique point and issue time.
    prediction_times = result[
        ["forecast_point_id", "issue_time"]
    ].drop_duplicates()

    combined = pd.concat(
        [
            history,
            prediction_times.assign(pm25=float("nan")),
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

    lag_values = combined[
        ["forecast_point_id", "issue_time"] + lag_columns
    ].drop_duplicates(
        ["forecast_point_id", "issue_time"]
    )

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
    weather_observations: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add weather from the nearest NCEI observation station.

    Use the latest observation at or before issue_time,
    no older than WEATHER_MAX_AGE_HOURS.
    """
    result = dataframe.copy()

    required_feature_columns = {
        "forecast_point_id",
        "location_lat",
        "location_lon",
        "issue_time",
        "fire_bearing_deg",
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
        "station_id",
        "latitude",
        "longitude",
        "valid_at",
        "wind_speed_ms",
        "wind_dir_deg",
        "temp_c",
        "rh_pct",
        "pressure_hpa",
        "precip_1h_mm",
    }

    missing = (
        required_weather_columns
        - set(weather_observations.columns)
    )

    if missing:
        raise ValueError(
            f"Missing weather-observation columns: {sorted(missing)}"
        )

    result["issue_time"] = pd.to_datetime(
        result["issue_time"],
        utc=True,
    )

    weather = weather_observations.copy()
    weather["valid_at"] = pd.to_datetime(
        weather["valid_at"], utc=True
    )

    feature_columns = [
        "wind_alignment",
        "wind_speed_ms",
        "wind_dir_sin",
        "wind_dir_cos",
        "temp_c",
        "rh_pct",
        "pressure_hpa",
        "precip_1h_mm",
        "precip_prob_pct",
    ]

    result = result.reset_index(drop=True).copy()
    result = result.drop(
        columns=feature_columns, errors="ignore"
    )
    result["_row_id"] = np.arange(len(result))
    result[feature_columns] = pd.NA

    station_locations = (
        weather[
            ["station_id", "latitude", "longitude"]
        ]
        .dropna()
        .drop_duplicates("station_id", keep="first")
        .reset_index(drop=True)
    )

    if not result.empty and not station_locations.empty:
        point_locations = result[
            [
                "forecast_point_id",
                "location_lat",
                "location_lon",
            ]
        ].drop_duplicates("forecast_point_id")

        station_map_rows = []

        for point in point_locations.itertuples(index=False):
            point_lat = pd.to_numeric(
                point.location_lat, errors="coerce"
            )
            point_lon = pd.to_numeric(
                point.location_lon, errors="coerce"
            )

            if pd.isna(point_lat) or pd.isna(point_lon):
                continue

            station_lats = np.radians(
                station_locations["latitude"].to_numpy(
                    dtype=float
                )
            )
            station_lons = np.radians(
                station_locations["longitude"].to_numpy(
                    dtype=float
                )
            )

            latitude = np.radians(float(point_lat))
            longitude = np.radians(float(point_lon))

            delta_lat = station_lats - latitude
            delta_lon = station_lons - longitude

            haversine_a = (
                np.sin(delta_lat / 2) ** 2
                + np.cos(latitude)
                * np.cos(station_lats)
                * np.sin(delta_lon / 2) ** 2
            )

            distances = (
                2
                * 6371.008
                * np.arctan2(
                    np.sqrt(haversine_a),
                    np.sqrt(1 - haversine_a),
                )
            )

            nearest_position = int(np.argmin(distances))

            station_map_rows.append(
                {
                    "forecast_point_id": point.forecast_point_id,
                    "station_id": station_locations.iloc[
                        nearest_position
                    ]["station_id"],
                }
            )

        station_map = pd.DataFrame(
            station_map_rows,
            columns=["forecast_point_id", "station_id"],
        )

        if not station_map.empty:
            result = result.merge(
                station_map,
                on="forecast_point_id",
                how="left",
                validate="many_to_one",
            )

            candidates = result.dropna(
                subset=["station_id", "issue_time"]
            ).drop(
                columns=feature_columns
            ).copy()

            weather_for_join = weather[
                [
                    "station_id",
                    "valid_at",
                    "wind_speed_ms",
                    "wind_dir_deg",
                    "temp_c",
                    "rh_pct",
                    "pressure_hpa",
                    "precip_1h_mm",
                ]
            ].dropna(
                subset=["station_id", "valid_at"]
            )

            if (
                not candidates.empty
                and not weather_for_join.empty
            ):
                matched = pd.merge_asof(
                    candidates.sort_values(
                        "issue_time", kind="mergesort"
                    ),
                    weather_for_join.sort_values(
                        "valid_at", kind="mergesort"
                    ),
                    left_on="issue_time",
                    right_on="valid_at",
                    by="station_id",
                    direction="backward",
                    allow_exact_matches=True,
                    tolerance=pd.Timedelta(
                        hours=WEATHER_MAX_AGE_HOURS
                    ),
                ).set_index("_row_id")

                row_ids = matched.index

                wind_direction = pd.to_numeric(
                    matched["wind_dir_deg"],
                    errors="coerce",
                )

                radians = np.radians(wind_direction)

                result.loc[
                    row_ids, "wind_dir_sin"
                ] = np.sin(radians)

                result.loc[
                    row_ids, "wind_dir_cos"
                ] = np.cos(radians)

                for column in (
                    "wind_speed_ms",
                    "temp_c",
                    "rh_pct",
                    "pressure_hpa",
                    "precip_1h_mm",
                ):
                    result.loc[
                        row_ids, column
                    ] = matched[column]

                # Meteorological FROM convention.
                bearing = pd.to_numeric(
                    matched["fire_bearing_deg"],
                    errors="coerce",
                )

                result.loc[
                    row_ids, "wind_alignment"
                ] = np.cos(
                    np.radians(
                        bearing - wind_direction
                    )
                )

    return result.drop(
        columns=["_row_id", "station_id"],
        errors="ignore",
    ).reset_index(drop=True)


def add_pm25_target(
    dataframe: pd.DataFrame,
    observations: pd.DataFrame,
    max_distance_km: float = 25.0,
) -> pd.DataFrame:
    """
    Attach the PM2.5 training target for each prediction row.

    Only observations matching target_time are eligible.

    Eligible observations:
        - regulatory
        - purpleair_barkjohn with qa_flag == ok

    The nearest eligible monitor within max_distance_km
    supplies the target.
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

    obs = obs[
        (obs["correction"] == "regulatory")
        | (
            (obs["correction"] == "purpleair_barkjohn")
            & (obs["qa_flag"] == "ok")
        )
    ].copy()

    result["target_pm25"] = pd.NA
    result["target_source"] = pd.NA
    result["target_monitor_dist_km"] = pd.NA
    result["target_monitor_id"] = pd.NA

    observations_by_time = {
        timestamp: group
        for timestamp, group in obs.groupby(
            "valid_at", sort=False
        )
    }

    for index, row in result.iterrows():
        candidates = observations_by_time.get(
            row["target_time"]
        )

        if candidates is None or candidates.empty:
            continue

        lat1 = np.radians(
            float(row["location_lat"])
        )
        lat2 = np.radians(
            candidates["latitude"].to_numpy(
                dtype=float
            )
        )

        delta_lat = lat2 - lat1
        delta_lon = np.radians(
            candidates["longitude"].to_numpy(
                dtype=float
            ) - float(row["location_lon"])
        )

        a = (
            np.sin(delta_lat / 2) ** 2
            + np.cos(lat1)
            * np.cos(lat2)
            * np.sin(delta_lon / 2) ** 2
        )

        distances = (
            2
            * 6371.008
            * np.arctan2(
                np.sqrt(a),
                np.sqrt(1 - a),
            )
        )

        eligible = np.flatnonzero(
            distances <= max_distance_km
        )

        if not len(eligible):
            continue

        nearest_position = eligible[
            np.argmin(distances[eligible])
        ]

        target = candidates.iloc[nearest_position]

        result.at[
            index, "target_pm25"
        ] = target["pm25"]

        result.at[
            index, "target_source"
        ] = target["correction"]

        result.at[
            index, "target_monitor_dist_km"
        ] = distances[nearest_position]

        result.at[
            index, "target_monitor_id"
        ] = target["monitor_id"]

    return result

def build_input_features(
    forecast_points: pd.DataFrame,
    issue_times: pd.Series,
    fire_detections: pd.DataFrame,
    pm25_history: pd.DataFrame,
    weather_observations: pd.DataFrame,
    horizons: tuple[int, ...] = ALLOWED_HORIZONS,
    lookback_hours: float = 72.0,
    lag_mode: str = "own",
    pm25_observations: pd.DataFrame | None = None,
    idw_power: float = 2.0,
    idw_max_radius_km: float = 100.0,
    idw_k: int = 4,
) -> pd.DataFrame:
    """Shared training/serving features; retain rows without future labels."""
    result = build_feature_times(forecast_points, issue_times, horizons=horizons)
    result = add_temporal_alignment_features(result)
    result = add_fire_alignment_features(result, fire_detections, lookback_hours=lookback_hours)
    result = add_pm25_alignment_features(
    result,
    pm25_history,
    lag_mode=lag_mode,
    pm25_observations=pm25_observations,
    idw_power=idw_power,
    idw_max_radius_km=idw_max_radius_km,
    idw_k=idw_k,
)
    return add_weather_alignment_features(result, weather_observations)


def build_feature_dataset(
    forecast_points: pd.DataFrame,
    issue_times: pd.Series,
    fire_detections: pd.DataFrame,
    pm25_history: pd.DataFrame,
    weather_observations: pd.DataFrame,
    pm25_observations: pd.DataFrame,
    pilot_event_id: str | None = None,
    horizons: tuple[int, ...] = ALLOWED_HORIZONS,
    lookback_hours: float = 72.0,
    lag_mode: str = "own",
    idw_power: float = 2.0,
    idw_max_radius_km: float = 100.0,
    idw_k: int = 4,
) -> pd.DataFrame:
    """
    Build the complete GEO-01 feature dataset.

    Pipeline:
        1. Align prediction rows.
        2. Add temporal features.
        3. Add fire features.
        4. Add PM2.5 lag features.
        5. Add weather features.
        6. Add target labels.

    ML-02:
        lag_mode="idw-loo" generates PM2.5 lags using
        neighboring monitors rather than the target's own
        history.

    The default mode remains "own".
    """

    result = build_input_features(
        forecast_points=forecast_points,
        issue_times=issue_times,
        fire_detections=fire_detections,
        pm25_history=pm25_history,
        weather_observations=weather_observations,
        horizons=horizons,
        lookback_hours=lookback_hours,
        lag_mode=lag_mode,
        pm25_observations=pm25_observations,
        idw_power=idw_power,
        idw_max_radius_km=idw_max_radius_km,
        idw_k=idw_k,
    )


    result = add_pm25_target(
        result,
        pm25_observations,
    )

    if pilot_event_id is not None:
        result["pilot_event_id"] = pilot_event_id
    else:
        result["pilot_event_id"] = pd.NA

    result = result.dropna(
        subset=["target_pm25"]
    ).reset_index(drop=True)

    from features.validation import (
        validate_feature_dataset,
    )

    validate_feature_dataset(result)

    return result
