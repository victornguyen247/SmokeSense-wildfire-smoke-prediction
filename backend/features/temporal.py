"""Temporal feature calculations for GEO-01."""

from __future__ import annotations

import pandas as pd


def add_temporal_features(
    dataframe: pd.DataFrame,
    timestamp_column: str = "issue_time",
) -> pd.DataFrame:
    """
    Add leakage-free calendar and solar-time features.

    The input timestamp must represent the feature issue time.
    Timestamps are normalized to UTC.
    """
    result = dataframe.copy()

    timestamps = pd.to_datetime(
        result[timestamp_column],
        utc=True,
    )

    result["day_of_year"] = timestamps.dt.dayofyear
    result["month"] = timestamps.dt.month

    # Smoke season is June through October.
    result["smoke_season"] = timestamps.dt.month.isin(
        [6, 7, 8, 9, 10]
    )

    # Calculate approximate local solar hour from longitude.
    #
    # 15 degrees of longitude corresponds to approximately
    # one hour of solar time.
    #
    # UTC hour + longitude / 15 gives solar time.
    # Modulo 24 keeps the result between 0 and <24.
    if "location_lon" in result.columns:
        utc_hour = (
            timestamps.dt.hour
            + timestamps.dt.minute / 60.0
            + timestamps.dt.second / 3600.0
        )

        result["local_solar_hour"] = (
            utc_hour + result["location_lon"] / 15.0
        ) % 24.0

    return result


def add_lagged_pm25(
    dataframe: pd.DataFrame,
    group_column: str = "forecast_point_id",
    timestamp_column: str = "issue_time",
    pm25_column: str = "pm25",
) -> pd.DataFrame:
    """
    Add time-aware historical PM2.5 lag features.

    Each lag uses the exact timestamp
    issue_time - lag_hours within the same forecast point.

    Missing timestamps remain NaN instead of falling back to
    the previous available row.
    """
    result = dataframe.copy()

    result[timestamp_column] = pd.to_datetime(
        result[timestamp_column],
        utc=True,
    )

    # Preserve the original row order so callers receive
    # their data in the same order they provided.
    result["_original_order"] = range(len(result))

    lookup = result[
        [
            group_column,
            timestamp_column,
            pm25_column,
        ]
    ].copy()

    for lag_hours in (1, 3, 6, 12, 24):
        lag_column = f"pm25_lag_{lag_hours}h"

        lagged = lookup.copy()
        lagged[timestamp_column] = (
            lagged[timestamp_column]
            + pd.Timedelta(hours=lag_hours)
        )
        lagged = lagged.rename(
            columns={
                pm25_column: lag_column,
            }
        )

        result = result.merge(
            lagged[
                [
                    group_column,
                    timestamp_column,
                    lag_column,
                ]
            ],
            on=[
                group_column,
                timestamp_column,
            ],
            how="left",
            sort=False,
        )

    result = result.sort_values(
        "_original_order"
    ).drop(
        columns="_original_order"
    ).reset_index(drop=True)

    return result


def add_recent_fire_activity(
    feature_times: pd.DataFrame,
    fire_detections: pd.DataFrame,
    timestamp_column: str = "issue_time",
) -> pd.DataFrame:
    """
    Add historical fire activity available before each issue time.

    Fire detections at or after the issue time are excluded to prevent
    future leakage.

    This helper is retained for basic temporal fire activity.
    The final GEO-01 Parquet features also require spatial fire
    aggregation within 200 km.
    """
    result = feature_times.copy()

    result[timestamp_column] = pd.to_datetime(
        result[timestamp_column],
        utc=True,
    )

    fires = fire_detections.copy()

    fires["detected_at"] = pd.to_datetime(
        fires["detected_at"],
        utc=True,
    )

    result["recent_fire_count_1h"] = 0
    result["recent_fire_count_6h"] = 0
    result["recent_fire_count_24h"] = 0
    result["recent_fire_frp_6h"] = 0.0

    for index, row in result.iterrows():
        issue_time = row[timestamp_column]

        # IMPORTANT:
        # Only fires detected BEFORE the issue time are allowed.
        previous_fires = fires[
            fires["detected_at"] < issue_time
        ]

        fires_1h = previous_fires[
            previous_fires["detected_at"]
            >= issue_time - pd.Timedelta(hours=1)
        ]

        fires_6h = previous_fires[
            previous_fires["detected_at"]
            >= issue_time - pd.Timedelta(hours=6)
        ]

        fires_24h = previous_fires[
            previous_fires["detected_at"]
            >= issue_time - pd.Timedelta(hours=24)
        ]

        result.at[index, "recent_fire_count_1h"] = len(
            fires_1h
        )

        result.at[index, "recent_fire_count_6h"] = len(
            fires_6h
        )

        result.at[index, "recent_fire_count_24h"] = len(
            fires_24h
        )

        result.at[index, "recent_fire_frp_6h"] = (
            fires_6h["frp_mw"].fillna(0).sum()
        )

    return result