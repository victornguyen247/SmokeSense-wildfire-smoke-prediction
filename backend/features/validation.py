"""Validation helpers for the GEO-01 Parquet contract."""

from __future__ import annotations

import pandas as pd


ALLOWED_HORIZONS = {1, 3, 6, 12, 24}

REQUIRED_COLUMNS = {
    "forecast_point_id",
    "location_lat",
    "location_lon",
    "issue_time",
    "target_time",
    "pilot_event_id",
    "horizon_hours",
    "target_pm25",
    "target_source",
    "target_monitor_dist_km",
    "nearest_fire_dist_km",
    "fire_bearing_deg",
    "fire_bearing_sin",
    "fire_bearing_cos",
    "total_frp_200km",
    "active_fire_count_200km",
    "wind_alignment",
    "wind_speed_ms",
    "wind_dir_sin",
    "wind_dir_cos",
    "temp_c",
    "rh_pct",
    "pressure_hpa",
    "precip_prob_pct",
    "pm25_lag_1h",
    "pm25_lag_3h",
    "pm25_lag_6h",
    "pm25_lag_12h",
    "pm25_lag_24h",
    "local_solar_hour",
    "day_of_year",
    "month",
    "smoke_season",
}


def validate_feature_dataset(
    dataframe: pd.DataFrame,
) -> None:
    """
    Validate a GEO-01 feature dataset against the Parquet contract.

    Raises ValueError when a contract requirement is violated.
    """

    missing = REQUIRED_COLUMNS - set(dataframe.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    if dataframe.empty:
        raise ValueError(
            "Feature dataset is empty."
        )

    if dataframe[
        [
            "forecast_point_id",
            "issue_time",
            "horizon_hours",
        ]
    ].duplicated().any():
        raise ValueError(
            "Duplicate forecast-point prediction rows found."
        )

    horizons = set(
        dataframe["horizon_hours"].dropna().unique()
    )

    invalid_horizons = horizons - ALLOWED_HORIZONS

    if invalid_horizons:
        raise ValueError(
            f"Invalid forecast horizons: "
            f"{sorted(invalid_horizons)}"
        )

    issue_times = pd.to_datetime(
        dataframe["issue_time"],
        utc=True,
    )

    target_times = pd.to_datetime(
        dataframe["target_time"],
        utc=True,
    )

    expected_target_times = (
        issue_times
        + pd.to_timedelta(
            dataframe["horizon_hours"],
            unit="h",
        )
    )

    if not target_times.equals(
        expected_target_times
    ):
        raise ValueError(
            "target_time does not match "
            "issue_time + horizon_hours."
        )

    if dataframe["target_pm25"].isna().any():
        raise ValueError(
            "Rows with missing target_pm25 found."
        )

    invalid_sources = set(
        dataframe["target_source"].dropna().unique()
    ) - {
        "regulatory",
        "purpleair_barkjohn",
    }

    if invalid_sources:
        raise ValueError(
            f"Invalid target sources: "
            f"{sorted(invalid_sources)}"
        )

    if (
        dataframe["target_monitor_dist_km"]
        > 25.0
    ).any():
        raise ValueError(
            "Target monitor exceeds 25 km."
        )

    if (
        dataframe["nearest_fire_dist_km"]
        < 0
    ).any():
        raise ValueError(
            "Negative fire distance found."
        )

    if (
        dataframe["nearest_fire_dist_km"]
        .replace(9999.0, pd.NA)
        .dropna()
        > 200.0
    ).any():
        raise ValueError(
            "Nearby fire distance exceeds 200 km."
        )

    if (
        dataframe["active_fire_count_200km"]
        < 0
    ).any():
        raise ValueError(
            "Negative fire count found."
        )

    if (
        dataframe["local_solar_hour"]
        .dropna()
        < 0
    ).any() or (
        dataframe["local_solar_hour"]
        .dropna()
        >= 24
    ).any():
        raise ValueError(
            "local_solar_hour must be in [0, 24)."
        )