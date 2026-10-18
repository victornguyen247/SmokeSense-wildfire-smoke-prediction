
"""Tests for SmokeSense ML-01 baseline inference."""

import numpy as np
import pandas as pd
import pytest

from ml.inference.ml01_baselines import (
    HORIZONS,
    MODEL_FEATURES,
    add_engineered_features,
    load_model,
    predict,
)


@pytest.fixture
def sample_features():
    return pd.DataFrame({
        "pm25_lag_1h": [10.0, 20.0, 30.0],
        "pm25_lag_3h": [8.0, 22.0, 28.0],
        "pm25_lag_6h": [7.0, 25.0, 25.0],
        "pm25_lag_12h": [6.0, 24.0, 23.0],
        "pm25_lag_24h": [5.0, 18.0, 20.0],
        "temp_c": [25.0, 30.0, 20.0],
        "rh_pct": [40.0, 50.0, 60.0],
        "wind_speed_ms": [2.0, 4.0, 6.0],
    })


def test_persistence_predictions(sample_features):
    predictions = predict(
        sample_features,
        horizon=6,
        model_type="persistence",
    )

    np.testing.assert_allclose(
        predictions,
        [10.0, 20.0, 30.0],
    )


def test_feature_engineering(sample_features):
    result = add_engineered_features(sample_features)

    assert result["pm25_change_1_3"].iloc[0] == 2.0
    assert result["pm25_change_3_6"].iloc[0] == 1.0

    assert result["pm25_short_avg"].iloc[0] == pytest.approx(
        (10.0 + 8.0 + 7.0) / 3
    )


@pytest.mark.parametrize("horizon", HORIZONS)
def test_tree_predictions(horizon, sample_features):
    predictions = predict(
        sample_features,
        horizon=horizon,
        model_type="tree",
    )

    assert len(predictions) == len(sample_features)
    assert np.isfinite(predictions).all()
    assert (predictions >= 0).all()


def test_invalid_horizon(sample_features):
    with pytest.raises(ValueError, match="Unsupported horizon"):
        predict(
            sample_features,
            horizon=7,
            model_type="tree",
        )


def test_missing_feature(sample_features):
    invalid = sample_features.drop(columns=["pm25_lag_1h"])

    with pytest.raises(ValueError, match="Missing features"):
        predict(
            invalid,
            horizon=6,
            model_type="tree",
        )


def test_invalid_model_type(sample_features):
    with pytest.raises(ValueError, match="Unknown model type"):
        predict(
            sample_features,
            horizon=6,
            model_type="unknown",
        )


@pytest.mark.parametrize("horizon", HORIZONS)
def test_saved_pipeline_consistency(horizon, sample_features):
    model = load_model(horizon)

    processed = add_engineered_features(sample_features)

    direct_predictions = np.maximum(
        model.predict(processed[MODEL_FEATURES]), 0
    )

    module_predictions = predict(
        sample_features,
        horizon=horizon,
        model_type="tree",
    )

    np.testing.assert_allclose(
        direct_predictions,
        module_predictions,
        rtol=1e-10,
        atol=1e-10,
    )
