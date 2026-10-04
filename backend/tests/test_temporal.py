import pandas as pd
import pytest

from features.temporal import (
    add_lagged_pm25,
    add_recent_fire_activity,
    add_temporal_features,
)
from features.spatial import nearest_previous_fire_features


def test_add_temporal_features():
    dataframe = pd.DataFrame(
        {
            "issue_time": [
                "2026-09-25 14:30:00+00:00",
            ],
            "location_lon": [-96.8],
        }
    )

    result = add_temporal_features(dataframe)

    assert result.loc[0, "day_of_year"] == 268
    assert result.loc[0, "month"] == 9
    assert result.loc[0, "smoke_season"]

    # 14:30 UTC + (-96.8 / 15) hours
    expected_solar_hour = (
        14.5 - (96.8 / 15.0)
    ) % 24

    assert result.loc[0, "local_solar_hour"] == pytest.approx(
        expected_solar_hour
    )


def test_temporal_features_smoke_season():
    dataframe = pd.DataFrame(
        {
            "issue_time": [
                "2026-05-15 12:00:00+00:00",
                "2026-06-15 12:00:00+00:00",
                "2026-10-15 12:00:00+00:00",
                "2026-11-15 12:00:00+00:00",
            ],
            "location_lon": [0.0, 0.0, 0.0, 0.0],
        }
    )

    result = add_temporal_features(dataframe)

    assert bool(result.loc[0, "smoke_season"]) is False
    assert bool(result.loc[1, "smoke_season"]) is True
    assert bool(result.loc[2, "smoke_season"]) is True
    assert bool(result.loc[3, "smoke_season"]) is False


def test_add_lagged_pm25_uses_previous_values():
    dataframe = pd.DataFrame(
        {
            "forecast_point_id": ["A"] * 25,
            "issue_time": pd.date_range(
                "2026-09-25 00:00:00+00:00",
                periods=25,
                freq="h",
            ),
            "pm25": list(range(1, 26)),
        }
    )

    result = add_lagged_pm25(dataframe)

    row_24 = result[
        result["issue_time"]
        == pd.Timestamp("2026-09-26 00:00:00+00:00")
    ].iloc[0]

    assert row_24["pm25_lag_1h"] == 24.0
    assert row_24["pm25_lag_3h"] == 22.0
    assert row_24["pm25_lag_6h"] == 19.0
    assert row_24["pm25_lag_12h"] == 13.0
    assert row_24["pm25_lag_24h"] == 1.0


def test_lagged_pm25_does_not_use_future_values():
    dataframe = pd.DataFrame(
        {
            "forecast_point_id": ["A", "A", "A"],
            "issue_time": [
                "2026-09-25 10:00:00+00:00",
                "2026-09-25 11:00:00+00:00",
                "2026-09-25 12:00:00+00:00",
            ],
            "pm25": [5.0, 6.0, 999.0],
        }
    )

    result = add_lagged_pm25(dataframe)

    row_11 = result[
        result["issue_time"]
        == pd.Timestamp("2026-09-25 11:00:00+00:00")
    ].iloc[0]

    # The 12:00 value of 999 must not appear in
    # the 11:00 features.
    assert row_11["pm25_lag_1h"] == 5.0

def test_lagged_pm25_requires_exact_timestamp():
    dataframe = pd.DataFrame(
        {
            "forecast_point_id": ["A"] * 3,
            "issue_time": [
                "2026-09-25 10:00:00+00:00",
                "2026-09-25 11:00:00+00:00",
                "2026-09-25 13:00:00+00:00",
            ],
            "pm25": [5.0, 6.0, 8.0],
        }
    )

    result = add_lagged_pm25(dataframe)

    row_13 = result[
        result["issue_time"]
        == pd.Timestamp(
            "2026-09-25 13:00:00+00:00"
        )
    ].iloc[0]

    # 12:00 does not exist, so the 1-hour lag
    # must not incorrectly use the 11:00 row.
    assert pd.isna(row_13["pm25_lag_1h"])

    # 10:00 exists exactly 3 hours earlier.
    assert row_13["pm25_lag_3h"] == 5.0


def test_lagged_pm25_is_separated_by_location():
    dataframe = pd.DataFrame(
        {
            "forecast_point_id": [
                "A",
                "A",
                "B",
                "B",
            ],
            "issue_time": [
                "2026-09-25 10:00:00+00:00",
                "2026-09-25 11:00:00+00:00",
                "2026-09-25 10:00:00+00:00",
                "2026-09-25 11:00:00+00:00",
            ],
            "pm25": [5.0, 6.0, 20.0, 21.0],
        }
    )

    result = add_lagged_pm25(dataframe)

    row_b = result[
        (result["forecast_point_id"] == "B")
        & (
            result["issue_time"]
            == pd.Timestamp("2026-09-25 11:00:00+00:00")
        )
    ].iloc[0]

    assert row_b["pm25_lag_1h"] == 20.0


def test_recent_fire_activity_uses_only_previous_fires():
    feature_times = pd.DataFrame(
        {
            "issue_time": [
                "2026-09-25 12:00:00+00:00",
            ],
        }
    )

    fire_detections = pd.DataFrame(
        {
            "detected_at": [
                "2026-09-25 11:30:00+00:00",
                "2026-09-25 12:00:00+00:00",
                "2026-09-25 12:30:00+00:00",
            ],
            "frp_mw": [10.0, 20.0, 30.0],
        }
    )

    result = add_recent_fire_activity(
        feature_times,
        fire_detections,
    )

    row = result.iloc[0]

    assert row["recent_fire_count_1h"] == 1
    assert row["recent_fire_count_6h"] == 1
    assert row["recent_fire_count_24h"] == 1
    assert row["recent_fire_frp_6h"] == 10.0


def test_recent_fire_activity_uses_correct_time_windows():
    feature_times = pd.DataFrame(
        {
            "issue_time": [
                "2026-09-25 12:00:00+00:00",
            ],
        }
    )

    fire_detections = pd.DataFrame(
        {
            "detected_at": [
                "2026-09-25 11:30:00+00:00",
                "2026-09-25 08:00:00+00:00",
                "2026-09-24 11:00:00+00:00",
            ],
            "frp_mw": [10.0, 20.0, 30.0],
        }
    )

    result = add_recent_fire_activity(
        feature_times,
        fire_detections,
    )

    row = result.iloc[0]

    assert row["recent_fire_count_1h"] == 1
    assert row["recent_fire_count_6h"] == 2
    assert row["recent_fire_count_24h"] == 2
    assert row["recent_fire_frp_6h"] == 30.0


def test_recent_fire_activity_excludes_fire_at_feature_timestamp():
    feature_times = pd.DataFrame(
        {
            "issue_time": [
                "2026-09-25 12:00:00+00:00",
            ],
        }
    )

    fire_detections = pd.DataFrame(
        {
            "detected_at": [
                "2026-09-25 12:00:00+00:00",
            ],
            "frp_mw": [50.0],
        }
    )

    result = add_recent_fire_activity(
        feature_times,
        fire_detections,
    )

    row = result.iloc[0]

    assert row["recent_fire_count_1h"] == 0
    assert row["recent_fire_count_6h"] == 0
    assert row["recent_fire_count_24h"] == 0
    assert row["recent_fire_frp_6h"] == 0.0


def test_nearest_previous_fire():
    fire_detections = pd.DataFrame(
        {
            "detected_at": pd.to_datetime(
                [
                    "2026-09-25 10:00:00+00:00",
                    "2026-09-25 11:00:00+00:00",
                ]
            ),
            "latitude": [
                0.0,
                10.0,
            ],
            "longitude": [
                1.0,
                10.0,
            ],
            "frp_mw": [
                25.0,
                50.0,
            ],
        }
    )

    result = nearest_previous_fire_features(
        location_latitude=0.0,
        location_longitude=0.0,
        timestamp=pd.Timestamp(
            "2026-09-25 12:00:00+00:00"
        ),
        fire_detections=fire_detections,
    )

    assert result["fire_distance_km"] == pytest.approx(
        111.2,
        abs=0.5,
    )

    assert result["fire_bearing_deg"] == pytest.approx(
        90.0
    )

    assert result["fire_frp_mw"] == 25.0


def test_nearest_previous_fire_ignores_future_fire():
    fire_detections = pd.DataFrame(
        {
            "detected_at": pd.to_datetime(
                [
                    "2026-09-25 13:00:00+00:00",
                ]
            ),
            "latitude": [0.0],
            "longitude": [1.0],
            "frp_mw": [100.0],
        }
    )

    result = nearest_previous_fire_features(
        location_latitude=0.0,
        location_longitude=0.0,
        timestamp=pd.Timestamp(
            "2026-09-25 12:00:00+00:00"
        ),
        fire_detections=fire_detections,
    )

    assert result["fire_distance_km"] is None
    assert result["fire_bearing_deg"] is None
    assert result["fire_frp_mw"] is None

def test_lagged_pm25_prefers_real_observation_over_placeholder():
    dataframe = pd.DataFrame({
        "forecast_point_id": ["A", "A", "A"],
        "issue_time": [
            "2026-09-25 10:00:00+00:00",
            "2026-09-25 10:00:00+00:00",
            "2026-09-25 11:00:00+00:00",
        ],
        "pm25": [25.0, None, 30.0],
    })

    result = add_lagged_pm25(dataframe)

    row_11 = result[
        result["issue_time"] == pd.Timestamp("2026-09-25 11:00:00+00:00")
    ].iloc[0]

    assert row_11["pm25_lag_1h"] == 25.0