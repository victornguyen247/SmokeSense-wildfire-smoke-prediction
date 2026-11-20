
"""Unit tests for ML-03 error analysis."""

import numpy as np
import pandas as pd
import pytest

from ml.evaluation.error_analysis import (
    summarize_groups,
    add_analysis_groups,
    load_ml02_analysis_data,
    load_served_thresholds,
    detection_scores,
)


def test_group_summary():
    df = pd.DataFrame({
        "group_id": ["A", "A", "B", "B"],
        "target_pm25": [10, 40, 50, 20],
        "v2": [12, 38, 20, 36],
    })

    result = summarize_groups(df, "group_id")

    assert len(result) == 2

    a = result[result["group"] == "A"].iloc[0]
    b = result[result["group"] == "B"].iloc[0]

    assert a["n"] == 2
    assert a["mae"] == pytest.approx(2.0)
    assert a["bias"] == pytest.approx(0.0)
    assert a["recall"] == pytest.approx(1.0)

    assert b["n"] == 2
    assert b["mae"] == pytest.approx(23.0)
    assert b["bias"] == pytest.approx(-7.0)
    assert b["recall"] == pytest.approx(0.0)


def test_missing_predictions():
    df = pd.DataFrame({
        "group_id": ["A", "A", "A"],
        "target_pm25": [10, 40, 50],
        "v2": [12, np.nan, 45],
    })

    result = summarize_groups(df, "group_id")

    assert result.iloc[0]["n"] == 2
    assert result.iloc[0]["mae"] == pytest.approx(3.5)


def test_missing_required_column():
    df = pd.DataFrame({
        "group_id": ["A"],
        "target_pm25": [40],
    })

    with pytest.raises(ValueError, match="Missing columns"):
        summarize_groups(df, "group_id")


def test_missing_group_value():
    df = pd.DataFrame({
        "group_id": ["A", None],
        "target_pm25": [40, 20],
        "v2": [38, 18],
    })

    result = summarize_groups(df, "group_id")

    assert result["n"].sum() == 2
    assert len(result) == 2


def test_ml02_join_preserves_matching_rows(tmp_path):
    """ML-02 predictions must match environmental data one-to-one."""
    key = {
        "forecast_point_id": "monitor-001",
        "issue_time": pd.Timestamp("2020-08-16T00:00:00Z"),
        "horizon_hours": 6,
    }

    predictions = pd.DataFrame([
        {
            **key,
            "target_pm25": 40.0,
            "method_a_prediction": 25.0,
            "method_b_prediction": 28.0,
        }
    ])

    dataset = pd.DataFrame([
        {
            **key,
            "nearest_fire_dist_km": 15.0,
            "wind_alignment": 0.8,
            "local_solar_hour": 12.0,
            "pilot_event_id": "PE-001",
            "group_id": "G-PE-001",
        }
    ])

    prediction_path = tmp_path / "predictions.parquet"
    dataset_path = tmp_path / "dataset.parquet"

    predictions.to_parquet(prediction_path, index=False)
    dataset.to_parquet(dataset_path, index=False)

    result = load_ml02_analysis_data(
        str(prediction_path),
        str(dataset_path),
    )

    assert len(result) == 1
    assert result.iloc[0]["nearest_fire_dist_km"] == 15.0
    assert result.iloc[0]["pilot_event_id"] == "PE-001"


def test_environmental_group_boundaries():
    """Check distance, wind, and issue-time grouping."""
    frame = pd.DataFrame({
        "nearest_fire_dist_km": [15.0, 75.0, 9999.0],
        "wind_alignment": [0.8, -0.8, float("nan")],
        "local_solar_hour": [2.0, 14.0, 20.0],
    })

    result = add_analysis_groups(frame)

    assert result["distance_group"].tolist() == [
        "0-25",
        "50-100",
        "No nearby fire",
    ]

    assert result["wind_group"].tolist() == [
        "Upwind",
        "Downwind",
        "Missing",
    ]

    assert result["time_group"].astype(str).tolist() == [
        "00-06",
        "12-18",
        "18-24",
    ]


def test_served_threshold_recall():
    # Observed exceedance cut-off remains 35.5, only the alarm moves.
    y = np.array([10.0, 40.0, 50.0, 20.0])
    p = np.array([12.0, 30.0, 37.0, 26.0])
    fixed = detection_scores(y, p, 35.5)
    served = detection_scores(y, p, 25.5)
    assert fixed["recall"] == pytest.approx(0.5)
    assert served["recall"] == pytest.approx(1.0)
    assert served["precision"] == pytest.approx(2 / 3)


def test_served_cutoff_read_from_release(tmp_path):
    release = tmp_path / "release.json"
    release.write_text('{"1": {"threshold": 35.5}, "6": {"threshold": 25.5}}')
    assert load_served_thresholds(release) == {1: 35.5, 6: 25.5}


def test_group_summary_reports_both_cutoffs():
    df = pd.DataFrame({
        "group_id": ["A", "A", "A"],
        "target_pm25": [40.0, 50.0, 10.0],
        "v2": [30.0, 40.0, 12.0],
    })
    r = summarize_groups(df, "group_id", prediction_threshold=25.5).iloc[0]
    assert r["recall"] == pytest.approx(0.5)
    assert r["served_recall"] == pytest.approx(1.0)
    assert r["prediction_threshold"] == pytest.approx(25.5)
