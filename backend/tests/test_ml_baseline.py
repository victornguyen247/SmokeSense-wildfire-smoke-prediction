"""Baseline v1: feature contract, baselines, metrics and inference (no DB, no real data)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.evaluation.metrics import aqi_category, scores
from ml.feature_columns import EXCLUDED, FEATURES
from ml.inference.predict import predict
from ml.models import xgb as xgbm
from ml.models.baselines import Climatology, persistence

# Written out here, not imported, so editing ml.feature_columns cannot quietly allow them.
NEVER_FEATURES = {
    "target_pm25", "target_time", "target_source", "target_monitor_id", "target_monitor_dist_km",
    "forecast_point_id", "location_lat", "location_lon", "event_ids", "pilot_event_id", "event_tier",
    "group_id", "precip_prob_pct",
}


def test_excluded_columns_are_never_features():
    leaked = NEVER_FEATURES & set(FEATURES)
    assert not leaked, f"label/identifier columns used as features: {sorted(leaked)}"
    assert NEVER_FEATURES <= set(EXCLUDED)
    assert not set(FEATURES) & set(EXCLUDED)
    assert len(FEATURES) == len(set(FEATURES))


def test_features_exist_in_the_dataset_contract():
    from features.validation import REQUIRED_COLUMNS
    assert set(FEATURES) <= REQUIRED_COLUMNS


def _frame(n=400, seed=0):
    rng = np.random.default_rng(seed)
    f = pd.DataFrame({c: rng.normal(size=n) for c in FEATURES})
    f["smoke_season"] = rng.integers(0, 2, n).astype(bool)
    f["local_solar_hour"] = rng.uniform(0, 24, n)
    f["horizon_hours"] = 6
    f["target_pm25"] = np.clip(10 + 8 * f["pm25_lag_1h"] + rng.normal(size=n), 0, None)
    f["group_id"] = np.repeat(["G-A", "G-B", "G-C", "G-D"], n // 4)
    return f


def test_persistence_falls_back_through_lags():
    f = pd.DataFrame({"pm25_lag_1h": [1.0, np.nan, np.nan, np.nan], "pm25_lag_3h": [2.0, 3.0, np.nan, np.nan],
                      "pm25_lag_6h": [4.0, 5.0, 6.0, np.nan]})
    assert persistence(f).tolist()[:3] == [1.0, 3.0, 6.0]
    assert np.isnan(persistence(f).iloc[3])


def test_climatology_uses_training_medians_by_horizon_and_solar_hour():
    train = pd.DataFrame({"horizon_hours": [1, 1, 1, 6], "local_solar_hour": [3.2, 3.9, 4.5, 3.0],
                          "target_pm25": [10.0, 20.0, 100.0, 7.0]})
    clim = Climatology().fit(train)
    test = pd.DataFrame({"horizon_hours": [1, 1, 6, 6], "local_solar_hour": [3.5, 4.0, 3.1, 9.0]})
    assert clim.predict(test).tolist() == [15.0, 100.0, 7.0, 7.0]  # last: unseen hour -> horizon median


@pytest.mark.parametrize("pm25, cat", [(0, 0), (9.0, 0), (9.05, 0), (9.1, 1), (35.4, 1), (35.5, 2),
                                       (55.5, 3), (125.5, 4), (225.5, 5)])
def test_aqi_categories_follow_epa_2024(pm25, cat):
    assert aqi_category([pm25])[0] == cat


def test_scores_threshold_metrics():
    s = scores([10, 40, 50, 20], [12, 38, 20, 36])
    assert s["n"] == 4 and s["mae"] == pytest.approx((2 + 2 + 30 + 16) / 4)
    assert (s["precision_35_5"], s["recall_35_5"]) == (0.5, 0.5)


def test_saved_model_predicts_with_feature_columns(tmp_path):
    train = _frame()
    booster, n_trees = xgbm.fit(train, {"max_depth": 3})
    assert 1 <= n_trees <= xgbm.N_ESTIMATORS
    booster.save_model(tmp_path / "model_h6.json")

    test = _frame(20, seed=1)
    p = predict(test[FEATURES[::-1] + ["target_pm25"]], horizon=6, model_dir=tmp_path)  # order and extras ignored
    assert p.shape == (20,) and (p >= 0).all()
    assert np.corrcoef(p, test["target_pm25"])[0, 1] > 0.8

    with pytest.raises(ValueError, match="missing model features"):
        predict(test.drop(columns=["pm25_lag_1h"]), horizon=6, model_dir=tmp_path)
    with pytest.raises(ValueError, match="horizon"):
        predict(test, horizon=2, model_dir=tmp_path)
