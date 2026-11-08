
import numpy as np
import pytest


from features.pm25_idw import idw_average

import pandas as pd

from features.pm25_idw import compute_idw_lags

def test_idw_basic():
    values = [30, 50]
    distances = [10, 20]

    result = idw_average(values, distances, power=2)

    assert result == pytest.approx(34.0)


def test_idw_equal_distances():
    values = [20, 40]
    distances = [10, 10]

    result = idw_average(values, distances)

    assert result == pytest.approx(30.0)


def test_idw_missing_values():
    values = [30, np.nan]
    distances = [10, 20]

    result = idw_average(values, distances)

    assert result == pytest.approx(30.0)


def test_idw_no_valid_neighbors():
    result = idw_average(
        [np.nan],
        [10],
    )

    assert np.isnan(result)


def test_idw_invalid_power():
    with pytest.raises(ValueError):
        idw_average([30], [10], power=0)


def test_idw_lags_exclude_self_and_future():
    issue_time = pd.Timestamp("2020-09-10 12:00:00", tz="UTC")

    points = pd.DataFrame({
        "forecast_point_id": ["monitor_A"],
        "location_lat": [0.0],
        "location_lon": [0.0],
        "issue_time": [issue_time],
    })

    observations = pd.DataFrame({
        "monitor_id": [
            "monitor_A",
            "monitor_B",
            "monitor_B",
            "monitor_B",
        ],
        "valid_at": [
            issue_time - pd.Timedelta(hours=1),
            issue_time - pd.Timedelta(hours=1),
            issue_time,
            issue_time + pd.Timedelta(hours=1),
        ],
        "pm25": [999.0, 40.0, 80.0, 100.0],
        "latitude": [0.0, 0.0, 0.0, 0.0],
        "longitude": [0.0, 0.1, 0.1, 0.1],
    })

    result = compute_idw_lags(
        points,
        observations,
        max_radius_km=100.0,
    )

    # Must use monitor B's reading exactly one hour earlier.
    # Must not use monitor A's own value (999).
    assert result.loc[0, "pm25_lag_1h"] == pytest.approx(40.0)

    # No observations exist at these exact historical times.
    assert np.isnan(result.loc[0, "pm25_lag_3h"])
    assert np.isnan(result.loc[0, "pm25_lag_6h"])

    # Current and future observations must not enter the lag.
    assert result.loc[0, "pm25_lag_1h"] != 80.0
    assert result.loc[0, "pm25_lag_1h"] != 100.0


def test_idw_lags_radius_and_missing_neighbors():
    issue_time = pd.Timestamp("2020-09-10 12:00:00", tz="UTC")

    points = pd.DataFrame({
        "forecast_point_id": ["monitor_A"],
        "location_lat": [0.0],
        "location_lon": [0.0],
        "issue_time": [issue_time],
    })

    observations = pd.DataFrame({
        "monitor_id": ["monitor_B", "monitor_C"],
        "valid_at": [
            issue_time - pd.Timedelta(hours=1),
            issue_time - pd.Timedelta(hours=3),
        ],
        "pm25": [30.0, 100.0],
        "latitude": [0.0, 0.0],
        "longitude": [0.5, 2.0],
    })

    result = compute_idw_lags(
        points,
        observations,
        max_radius_km=100.0,
    )

    # Monitor B is approximately 56 km away.
    assert result.loc[0, "pm25_lag_1h"] == pytest.approx(30.0)

    # Monitor C is approximately 222 km away.
    assert np.isnan(result.loc[0, "pm25_lag_3h"])

    # No eligible historical observations at these timestamps.
    assert np.isnan(result.loc[0, "pm25_lag_6h"])
    assert np.isnan(result.loc[0, "pm25_lag_12h"])
    assert np.isnan(result.loc[0, "pm25_lag_24h"])


def test_idw_rejects_duplicate_observations():
    issue_time = pd.Timestamp("2020-09-10 12:00:00", tz="UTC")
    history_time = issue_time - pd.Timedelta(hours=1)

    points = pd.DataFrame({
        "forecast_point_id": ["monitor_A"],
        "location_lat": [0.0],
        "location_lon": [0.0],
        "issue_time": [issue_time],
    })

    observations = pd.DataFrame({
        "monitor_id": ["monitor_B", "monitor_B"],
        "valid_at": [history_time, history_time],
        "pm25": [30.0, 50.0],
        "latitude": [0.0, 0.0],
        "longitude": [0.5, 0.5],
    })

    with pytest.raises(ValueError, match="Duplicate observations"):
        compute_idw_lags(
            points,
            observations,
            max_radius_km=100.0,
        )
