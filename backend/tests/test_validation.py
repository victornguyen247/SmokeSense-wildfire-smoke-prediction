import pandas as pd
import pytest

from features.validation import validate_feature_dataset


def make_valid_dataset():
    return pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 38.5,
                "location_lon": -121.5,
                "issue_time": pd.Timestamp(
                    "2024-08-01 12:00:00",
                    tz="UTC",
                ),
                "target_time": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "pilot_event_id": "PE-001",
                "horizon_hours": 6,
                "target_pm25": 35.0,
                "target_source": "regulatory",
                "target_monitor_dist_km": 10.0,
                "nearest_fire_dist_km": 50.0,
                "fire_bearing_deg": 90.0,
                "fire_bearing_sin": 1.0,
                "fire_bearing_cos": 0.0,
                "total_frp_200km": 100.0,
                "active_fire_count_200km": 2,
                "wind_alignment": 1.0,
                "wind_speed_ms": 5.0,
                "wind_dir_sin": 1.0,
                "wind_dir_cos": 0.0,
                "temp_c": 30.0,
                "rh_pct": 40.0,
                "pressure_hpa": 1013.0,
                "precip_prob_pct": 10.0,
                "pm25_lag_1h": 20.0,
                "pm25_lag_3h": 18.0,
                "pm25_lag_6h": 17.0,
                "pm25_lag_12h": 15.0,
                "pm25_lag_24h": 12.0,
                "local_solar_hour": 5.0,
                "day_of_year": 214,
                "month": 8,
                "smoke_season": True,
            }
        ]
    )


def test_valid_feature_dataset():
    dataframe = make_valid_dataset()

    validate_feature_dataset(dataframe)


def test_validation_rejects_duplicate_rows():
    dataframe = make_valid_dataset()

    dataframe = pd.concat(
        [dataframe, dataframe],
        ignore_index=True,
    )

    with pytest.raises(ValueError):
        validate_feature_dataset(dataframe)


def test_validation_rejects_invalid_horizon():
    dataframe = make_valid_dataset()

    dataframe.loc[0, "horizon_hours"] = 2

    with pytest.raises(ValueError):
        validate_feature_dataset(dataframe)


def test_validation_rejects_wrong_target_time():
    dataframe = make_valid_dataset()

    dataframe.loc[0, "target_time"] = pd.Timestamp(
        "2024-08-01 19:00:00",
        tz="UTC",
    )

    with pytest.raises(ValueError):
        validate_feature_dataset(dataframe)


def test_validation_rejects_missing_target():
    dataframe = make_valid_dataset()

    dataframe.loc[0, "target_pm25"] = pd.NA

    with pytest.raises(ValueError):
        validate_feature_dataset(dataframe)


def test_validation_rejects_far_target_monitor():
    dataframe = make_valid_dataset()

    dataframe.loc[
        0,
        "target_monitor_dist_km",
    ] = 30.0

    with pytest.raises(ValueError):
        validate_feature_dataset(dataframe)