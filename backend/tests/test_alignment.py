import pandas as pd
import pytest

from features.alignment import (
    add_fire_alignment_features,
    add_pm25_alignment_features,
    add_pm25_target,
    add_temporal_alignment_features,
    add_weather_alignment_features,
    build_feature_dataset,
    build_feature_times,
)


def test_build_feature_times_creates_expected_rows():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 38.5,
                "location_lon": -121.5,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    result = build_feature_times(
        forecast_points,
        issue_times,
    )

    assert len(result) == 5


def test_build_feature_times_calculates_target_time():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 38.5,
                "location_lon": -121.5,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    result = build_feature_times(
        forecast_points,
        issue_times,
    )

    six_hour_row = result[
        result["horizon_hours"] == 6
    ].iloc[0]

    assert six_hour_row["issue_time"] == pd.Timestamp(
        "2024-08-01 12:00:00",
        tz="UTC",
    )

    assert six_hour_row["target_time"] == pd.Timestamp(
        "2024-08-01 18:00:00",
        tz="UTC",
    )


def test_build_feature_times_uses_only_allowed_horizons():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 38.5,
                "location_lon": -121.5,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    result = build_feature_times(
        forecast_points,
        issue_times,
    )

    assert sorted(
        result["horizon_hours"].unique()
    ) == [1, 3, 6, 12, 24]

def test_add_temporal_alignment_features():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 38.5,
                "location_lon": -121.5,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
    )

    result = add_temporal_alignment_features(
        aligned,
    )

    assert "local_solar_hour" in result.columns
    assert "day_of_year" in result.columns
    assert "month" in result.columns
    assert "smoke_season" in result.columns

    assert result["month"].iloc[0] == 8
    assert result["day_of_year"].iloc[0] == 214
    assert bool(result["smoke_season"].iloc[0]) is True

def test_add_fire_alignment_features():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 0.0,
                "location_lon": 0.0,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
    )

    fire_detections = pd.DataFrame(
        [
            {
                "latitude": 0.5,
                "longitude": 0.0,
                "detected_at": pd.Timestamp(
                    "2024-08-01 10:00:00",
                    tz="UTC",
                ),
                "frp_mw": 100.0,
            },
            {
                "latitude": 1.0,
                "longitude": 0.0,
                "detected_at": pd.Timestamp(
                    "2024-08-01 11:00:00",
                    tz="UTC",
                ),
                "frp_mw": 200.0,
            },
        ]
    )

    result = add_fire_alignment_features(
        aligned,
        fire_detections,
    )

    assert "nearest_fire_dist_km" in result.columns
    assert "fire_bearing_deg" in result.columns
    assert "fire_bearing_sin" in result.columns
    assert "fire_bearing_cos" in result.columns
    assert "total_frp_200km" in result.columns
    assert "active_fire_count_200km" in result.columns

    assert result["active_fire_count_200km"].iloc[0] == 2

    assert (
        result["nearest_fire_dist_km"].iloc[0]
        < 60
    )

def test_add_fire_alignment_features_accepts_custom_lookback():
    aligned = build_feature_times(
        pd.DataFrame(
            [{
                "forecast_point_id": "FP-001",
                "location_lat": 0.0,
                "location_lon": 0.0,
            }]
        ),
        pd.Series([pd.Timestamp("2024-08-01 12:00:00", tz="UTC")]),
        horizons=(6,),
    )
    fire_detections = pd.DataFrame(
        [{
            "latitude": 0.5,
            "longitude": 0.0,
            "detected_at": pd.Timestamp("2024-07-31 00:00:00", tz="UTC"),
            "frp_mw": 100.0,
        }]
    )

    default_result = add_fire_alignment_features(
        aligned,
        fire_detections,
    )
    result = add_fire_alignment_features(
        aligned,
        fire_detections,
        lookback_hours=48.0,
    )

    assert default_result["active_fire_count_200km"].iloc[0] == 0
    assert result["active_fire_count_200km"].iloc[0] == 1


def test_add_fire_alignment_features_excludes_future_fire():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 0.0,
                "location_lon": 0.0,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
    )

    fire_detections = pd.DataFrame(
        [
            {
                "latitude": 0.5,
                "longitude": 0.0,
                "detected_at": pd.Timestamp(
                    "2024-08-01 13:00:00",
                    tz="UTC",
                ),
                "frp_mw": 500.0,
            }
        ]
    )

    result = add_fire_alignment_features(
        aligned,
        fire_detections,
    )

    assert (
        result["active_fire_count_200km"].iloc[0]
        == 0
    )

    assert (
        result["total_frp_200km"].iloc[0]
        == 0.0
    )

    assert (
        result["nearest_fire_dist_km"].iloc[0]
        == 9999.0
    )

def test_add_pm25_alignment_features():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 38.5,
                "location_lon": -121.5,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-02 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
    )

    pm25_history = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "issue_time": pd.Timestamp(
                    "2024-08-01 12:00:00",
                    tz="UTC",
                ),
                "pm25": 10.0,
            },
            {
                "forecast_point_id": "FP-001",
                "issue_time": pd.Timestamp(
                    "2024-08-02 06:00:00",
                    tz="UTC",
                ),
                "pm25": 20.0,
            },
            {
                "forecast_point_id": "FP-001",
                "issue_time": pd.Timestamp(
                    "2024-08-02 09:00:00",
                    tz="UTC",
                ),
                "pm25": 30.0,
            },
            {
                "forecast_point_id": "FP-001",
                "issue_time": pd.Timestamp(
                    "2024-08-02 11:00:00",
                    tz="UTC",
                ),
                "pm25": 40.0,
            },
        ]
    )

    result = add_pm25_alignment_features(
        aligned,
        pm25_history,
    )

    assert "pm25_lag_1h" in result.columns
    assert "pm25_lag_3h" in result.columns
    assert "pm25_lag_6h" in result.columns
    assert "pm25_lag_12h" in result.columns
    assert "pm25_lag_24h" in result.columns

def test_add_pm25_alignment_features_does_not_use_future_values():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 38.5,
                "location_lon": -121.5,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-02 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
    )

    pm25_history = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "issue_time": pd.Timestamp(
                    "2024-08-02 13:00:00",
                    tz="UTC",
                ),
                "pm25": 999.0,
            }
        ]
    )

    result = add_pm25_alignment_features(
        aligned,
        pm25_history,
    )

    assert result["pm25_lag_1h"].isna().all()
    assert result["pm25_lag_3h"].isna().all()
    assert result["pm25_lag_6h"].isna().all()
    assert result["pm25_lag_12h"].isna().all()
    assert result["pm25_lag_24h"].isna().all()

@pytest.mark.parametrize(
    ("wind_dir_deg", "expected_sin", "expected_cos", "expected_alignment"),
    [
        (90.0, 1.0, 0.0, 1.0),
        (270.0, -1.0, 0.0, -1.0),
        (0.0, 0.0, 1.0, 0.0),
    ],
    ids=["wind-toward-location", "wind-opposite", "wind-perpendicular"],
)
def test_add_weather_alignment_features(
    wind_dir_deg,
    expected_sin,
    expected_cos,
    expected_alignment,
):
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 0.0,
                "location_lon": 0.0,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
        horizons=(6,),
    )

    fire_detections = pd.DataFrame(
        [
            {
                "latitude": 0.0,
                "longitude": 0.5,
                "detected_at": pd.Timestamp(
                    "2024-08-01 10:00:00",
                    tz="UTC",
                ),
                "frp_mw": 100.0,
            }
        ]
    )

    aligned = add_fire_alignment_features(
        aligned,
        fire_detections,
    )

    # The fire is east of the forecast point, so the
    # point -> fire bearing should be 90 degrees.
    assert aligned["fire_bearing_deg"].iloc[0] == pytest.approx(
        90.0,
        abs=0.5,
    )

    point_weather_map = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "grid_id": "GRID-001",
            }
        ]
    )

    weather_forecasts = pd.DataFrame(
        [
            {
                "grid_id": "GRID-001",
                "issued_at": pd.Timestamp(
                    "2024-08-01 10:00:00",
                    tz="UTC",
                ),
                "valid_at": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "wind_speed_ms": 5.0,
                "wind_dir_deg": wind_dir_deg,
                "temp_c": 30.0,
                "rh_pct": 40.0,
                "precip_prob_pct": 10.0,
            }
        ]
    )

    result = add_weather_alignment_features(
        aligned,
        weather_forecasts,
        point_weather_map,
    )

    row = result.iloc[0]

    assert row["wind_speed_ms"] == 5.0
    assert row["temp_c"] == 30.0
    assert row["rh_pct"] == 40.0
    assert row["precip_prob_pct"] == 10.0

    assert row["wind_dir_sin"] == pytest.approx(expected_sin, abs=1e-6)
    assert row["wind_dir_cos"] == pytest.approx(expected_cos, abs=1e-6)

    # The fire bearing is east (90°). Same, opposite, and perpendicular
    # wind-from directions should produce +1, -1, and 0 respectively.
    assert row["wind_alignment"] == pytest.approx(
        expected_alignment,
        abs=1e-5,
    )

def test_add_weather_alignment_features_excludes_future_forecast():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 38.5,
                "location_lon": -121.5,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
        horizons=(6,),
    )

    aligned["fire_bearing_deg"] = 90.0

    point_weather_map = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "grid_id": "GRID-001",
            }
        ]
    )

    weather_forecasts = pd.DataFrame(
        [
            {
                "grid_id": "GRID-001",
                # This forecast was issued AFTER the prediction.
                "issued_at": pd.Timestamp(
                    "2024-08-01 13:00:00",
                    tz="UTC",
                ),
                "valid_at": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "wind_speed_ms": 999.0,
                "wind_dir_deg": 90.0,
                "temp_c": 999.0,
                "rh_pct": 999.0,
                "precip_prob_pct": 999.0,
            }
        ]
    )

    result = add_weather_alignment_features(
        aligned,
        weather_forecasts,
        point_weather_map,
    )

    row = result.iloc[0]

    assert pd.isna(row["wind_speed_ms"])
    assert pd.isna(row["temp_c"])
    assert pd.isna(row["rh_pct"])
    assert pd.isna(row["precip_prob_pct"])

def test_add_pm25_target_selects_nearest_eligible_monitor():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 0.0,
                "location_lon": 0.0,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
        horizons=(6,),
    )

    observations = pd.DataFrame(
        [
            {
                "monitor_id": "MON-NEAR",
                "valid_at": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "pm25": 35.0,
                "correction": "regulatory",
                "qa_flag": "ok",
                "latitude": 0.1,
                "longitude": 0.0,
            },
            {
                "monitor_id": "MON-FAR",
                "valid_at": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "pm25": 80.0,
                "correction": "regulatory",
                "qa_flag": "ok",
                "latitude": 0.2,
                "longitude": 0.0,
            },
        ]
    )

    result = add_pm25_target(
        aligned,
        observations,
    )

    row = result.iloc[0]

    assert row["target_pm25"] == 35.0
    assert row["target_source"] == "regulatory"
    assert row["target_monitor_id"] == "MON-NEAR"
    assert row["target_monitor_dist_km"] < 25.0

def test_add_pm25_target_rejects_ineligible_observations():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 0.0,
                "location_lon": 0.0,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
        horizons=(6,),
    )

    observations = pd.DataFrame(
        [
            {
                "monitor_id": "MON-BAD-CORRECTION",
                "valid_at": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "pm25": 999.0,
                "correction": "purpleair_raw",
                "qa_flag": "ok",
                "latitude": 0.01,
                "longitude": 0.0,
            },
            {
                "monitor_id": "MON-BAD-QA",
                "valid_at": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "pm25": 888.0,
                "correction": "regulatory",
                "qa_flag": "bad",
                "latitude": 0.01,
                "longitude": 0.0,
            },
        ]
    )

    result = add_pm25_target(
        aligned,
        observations,
    )

    row = result.iloc[0]

    assert pd.isna(row["target_pm25"])
    assert pd.isna(row["target_source"])
    assert pd.isna(row["target_monitor_dist_km"])

def test_add_pm25_target_rejects_monitor_over_25km():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 0.0,
                "location_lon": 0.0,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    aligned = build_feature_times(
        forecast_points,
        issue_times,
        horizons=(6,),
    )

    observations = pd.DataFrame(
        [
            {
                "monitor_id": "MON-FAR",
                "valid_at": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "pm25": 100.0,
                "correction": "regulatory",
                "qa_flag": "ok",
                # ~55 km away
                "latitude": 0.5,
                "longitude": 0.0,
            }
        ]
    )

    result = add_pm25_target(
        aligned,
        observations,
    )

    assert pd.isna(
        result["target_pm25"].iloc[0]
    )

def test_build_feature_dataset():
    forecast_points = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "location_lat": 38.5,
                "location_lon": -121.5,
            }
        ]
    )

    issue_times = pd.Series(
        [
            pd.Timestamp(
                "2024-08-01 12:00:00",
                tz="UTC",
            )
        ]
    )

    fire_detections = pd.DataFrame(
        [
            {
                "latitude": 38.6,
                "longitude": -121.5,
                "detected_at": pd.Timestamp(
                    "2024-08-01 10:00:00",
                    tz="UTC",
                ),
                "frp_mw": 100.0,
            },
            {
                "latitude": 38.7,
                "longitude": -121.5,
                "detected_at": pd.Timestamp(
                    "2024-07-31 00:00:00",
                    tz="UTC",
                ),
                "frp_mw": 50.0,
            },
        ]
    )

    pm25_history = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "issue_time": pd.Timestamp(
                    "2024-08-01 11:00:00",
                    tz="UTC",
                ),
                "pm25": 20.0,
            },
        ]
    )

    point_weather_map = pd.DataFrame(
        [
            {
                "forecast_point_id": "FP-001",
                "grid_id": "GRID-001",
            }
        ]
    )

    weather_forecasts = pd.DataFrame(
        [
            {
                "grid_id": "GRID-001",
                "issued_at": pd.Timestamp(
                    "2024-08-01 10:00:00",
                    tz="UTC",
                ),
                "valid_at": pd.Timestamp(
                    "2024-08-01 13:00:00",
                    tz="UTC",
                ),
                "wind_speed_ms": 5.0,
                "wind_dir_deg": 90.0,
                "temp_c": 30.0,
                "rh_pct": 40.0,
                "precip_prob_pct": 10.0,
            },
            {
                "grid_id": "GRID-001",
                "issued_at": pd.Timestamp(
                    "2024-08-01 10:00:00",
                    tz="UTC",
                ),
                "valid_at": pd.Timestamp(
                    "2024-08-01 15:00:00",
                    tz="UTC",
                ),
                "wind_speed_ms": 6.0,
                "wind_dir_deg": 90.0,
                "temp_c": 31.0,
                "rh_pct": 39.0,
                "precip_prob_pct": 15.0,
            },
            {
                "grid_id": "GRID-001",
                "issued_at": pd.Timestamp(
                    "2024-08-01 10:00:00",
                    tz="UTC",
                ),
                "valid_at": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "wind_speed_ms": 7.0,
                "wind_dir_deg": 90.0,
                "temp_c": 32.0,
                "rh_pct": 38.0,
                "precip_prob_pct": 20.0,
            },
            {
                "grid_id": "GRID-001",
                "issued_at": pd.Timestamp(
                    "2024-08-01 10:00:00",
                    tz="UTC",
                ),
                "valid_at": pd.Timestamp(
                    "2024-08-01 00:00:00",
                    tz="UTC",
                ),
                "wind_speed_ms": 4.0,
                "wind_dir_deg": 90.0,
                "temp_c": 29.0,
                "rh_pct": 41.0,
                "precip_prob_pct": 5.0,
            },
            {
                "grid_id": "GRID-001",
                "issued_at": pd.Timestamp(
                    "2024-08-01 10:00:00",
                    tz="UTC",
                ),
                "valid_at": pd.Timestamp(
                    "2024-08-02 12:00:00",
                    tz="UTC",
                ),
                "wind_speed_ms": 8.0,
                "wind_dir_deg": 90.0,
                "temp_c": 33.0,
                "rh_pct": 35.0,
                "precip_prob_pct": 25.0,
            },
        ]
    )

    pm25_observations = pd.DataFrame(
        [
            {
                "monitor_id": "MON-001",
                "valid_at": pd.Timestamp(
                    "2024-08-01 18:00:00",
                    tz="UTC",
                ),
                "pm25": 35.0,
                "correction": "regulatory",
                "qa_flag": "ok",
                "latitude": 38.55,
                "longitude": -121.5,
            }
        ]
    )

    result = build_feature_dataset(
        forecast_points=forecast_points,
        issue_times=issue_times,
        fire_detections=fire_detections,
        pm25_history=pm25_history,
        weather_forecasts=weather_forecasts,
        point_weather_map=point_weather_map,
        pm25_observations=pm25_observations,
        horizons=(6,),
        lookback_hours=48.0,
    )

    assert len(result) == 1

    required_columns = {
        "forecast_point_id",
        "location_lat",
        "location_lon",
        "issue_time",
        "target_time",
        "horizon_hours",
        "local_solar_hour",
        "day_of_year",
        "month",
        "smoke_season",
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
        "precip_prob_pct",
        "target_pm25",
        "target_source",
        "target_monitor_dist_km",
    }

    assert required_columns.issubset(
        set(result.columns)
    )

    row = result.iloc[0]

    assert row["target_pm25"] == 35.0
    assert row["target_source"] == "regulatory"
    assert row["horizon_hours"] == 6
    assert row["active_fire_count_200km"] == 2
