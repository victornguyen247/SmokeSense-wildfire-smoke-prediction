"""Baseline v2: derived features, residual target, release rule, threshold tuning and inference."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ml.evaluation.release import release, skills
from ml.feature_columns import DERIVED, EXCLUDED, FEATURES, FEATURES_V2
from ml.features import add_derived
from ml.inference.predict_v2 import predict
from ml.models import xgb as v1m
from ml.models import xgb_v2 as v2m
from tests.test_ml_baseline import NEVER_FEATURES
from tests.test_ml_baseline import _frame as _v1_frame

LAGS = ["pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h", "pm25_lag_12h", "pm25_lag_24h"]


def _frame(n=400, seed=0):
    """v1's fixture with PM2.5 lags made non-negative, as stored PM2.5 is."""
    f = _v1_frame(n, seed)
    f[LAGS] = f[LAGS].abs() * 10
    f["target_pm25"] = np.clip(f["pm25_lag_1h"] * 1.2 + 2 + np.random.default_rng(seed).normal(size=n), 0, None)
    return f


def test_v2_features_exclude_labels_and_identifiers():
    assert not NEVER_FEATURES & set(FEATURES_V2)
    assert not set(FEATURES_V2) & set(EXCLUDED)
    assert FEATURES_V2 == [*FEATURES, *DERIVED] and len(set(FEATURES_V2)) == len(FEATURES_V2)


def test_add_derived_values_and_fallbacks():
    f = pd.DataFrame({"pm25_lag_1h": [10.0, np.nan, np.nan], "pm25_lag_3h": [4.0, 7.0, np.nan],
                      "pm25_lag_6h": [1.0, 2.0, 3.0], "pm25_lag_24h": [4.0, 1.0, np.nan]})
    d = add_derived(f)
    assert d["persistence"].tolist() == [10.0, 7.0, 3.0]
    assert d.loc[0, "trend_1_3"] == 6.0 and d.loc[0, "trend_1_6"] == 9.0
    assert d.loc[0, "ratio_1_24"] == pytest.approx(11 / 5)
    assert d.loc[1, ["trend_1_3", "trend_1_6", "ratio_1_24"]].isna().all()
    assert "persistence" not in f  # input untouched


def test_derived_features_identical_in_training_and_inference(monkeypatch):
    """predict() must hand the model exactly the matrix training builds (horizon 6 rows)."""
    frame = _frame(48)
    seen = []

    def fake_predict(booster, fr):
        seen.append(v2m.matrix(fr))
        return np.zeros(len(fr))

    from ml.inference import predict_v2 as pv2
    monkeypatch.setattr(v2m, "predict", fake_predict)
    monkeypatch.setattr(pv2, "_booster", lambda path: None)
    monkeypatch.setattr(pv2, "load_release", lambda d: {"6": {"serve": "v2", "threshold": 30.0}})
    pv2.predict(frame.drop(columns=["horizon_hours"]), horizon=6, model_dir="unused")
    train_matrix = v2m.matrix(add_derived(frame))
    assert len(seen) == 1
    pd.testing.assert_frame_equal(seen[0].reset_index(drop=True), train_matrix.reset_index(drop=True))


def test_residual_round_trip():
    y = np.array([0.0, 3.0, 35.5, 400.0])
    p = np.array([5.0, 3.0, 20.0, 150.0])
    assert np.allclose(v2m.from_residual(p, v2m.residual(y, p)), y)
    assert (v2m.from_residual(p, np.array([-50.0] * 4)) >= 0).all()  # clipped at 0


def test_group_weights_equalise_groups():
    g = np.array(["A"] * 6 + ["B"] * 2)
    w = v2m.group_weights(g, "group")
    assert w[:6].sum() == pytest.approx(w[6:].sum()) and w.mean() == pytest.approx(1.0)
    assert v2m.group_weights(g, "none") is None


def test_tune_threshold_picks_best_f1_in_range():
    y = np.array([10, 20, 40, 50, 60, 5])
    pred = np.array([12, 18, 30, 31, 45, 3])  # under-predicts the exceedances
    t = v2m.tune_threshold(y, pred)
    assert 20 <= t <= 50 and t <= 30  # catches all three exceedances without the 18
    assert v2m.tune_threshold([1, 2], [1, 2]) == 35.5  # no positives: keep the fixed cut-off


def _oof(model_err, pers_err, groups=("G1", "G2")):
    rows = []
    for g in groups:
        for i in range(10):
            rows.append({"horizon_hours": 6, "group_id": g, "target_pm25": 20.0,
                         "persistence": 20.0 + pers_err[g], "v2": 20.0 + model_err[g]})
    return pd.DataFrame(rows)


def test_release_rule_needs_pooled_and_macro_skill():
    # better in both groups -> ship
    assert release(_oof({"G1": 1, "G2": 1}, {"G1": 2, "G2": 2}), "v2", horizons=(6,))["6"]["serve"] == "v2"
    # worse everywhere -> persistence
    assert release(_oof({"G1": 3, "G2": 3}, {"G1": 2, "G2": 2}), "v2", horizons=(6,))["6"]["serve"] == "persistence"
    # equal MAE -> skill 0 -> ships (rule is >= 0)
    assert release(_oof({"G1": 2, "G2": 2}, {"G1": 2, "G2": 2}), "v2", horizons=(6,))["6"]["serve"] == "v2"
    pooled, macro = skills(_oof({"G1": 1, "G2": 4}, {"G1": 2, "G2": 2}), "v2")
    assert pooled == pytest.approx(1 - 2.5 / 2) and macro == pytest.approx(1 - 2.5 / 2)


def test_release_rule_rejects_pooled_win_with_macro_loss():
    # big group: model better; two small groups: model much worse -> pooled >= 0, macro < 0
    rows = []
    for g, n, me, pe in (("BIG", 100, 1.0, 2.0), ("S1", 5, 9.0, 1.0), ("S2", 5, 9.0, 1.0)):
        rows += [{"horizon_hours": 6, "group_id": g, "target_pm25": 20.0, "persistence": 20 + pe, "v2": 20 + me}] * n
    rel = release(pd.DataFrame(rows), "v2", horizons=(6,))["6"]
    assert rel["pooled_skill"] >= 0 and rel["macro_skill"] < 0 and rel["serve"] == "persistence"


@pytest.fixture
def model_dir(tmp_path):
    train = add_derived(_frame(400))
    has_p = train["persistence"].notna()
    booster, _, _ = v2m.fit(train[has_p], {"max_depth": 3, "weights": "none"})
    booster.save_model(tmp_path / "model_h6.json")
    fb, _ = v1m.fit(train, {"max_depth": 3})
    fb.save_model(tmp_path / "fallback_h6.json")
    (tmp_path / "release.json").write_text(json.dumps({"6": {"serve": "v2", "threshold": 30.0}}))
    return tmp_path


def test_predict_v2_follows_release_and_falls_back(model_dir):
    test = _frame(20, seed=1)
    test.loc[test.index[:3], ["pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h"]] = np.nan  # no persistence
    out = predict(test, horizon=6, model_dir=model_dir)
    assert list(out.columns) == ["pm25", "exceeds", "source"]
    assert out["source"].tolist()[:3] == ["fallback"] * 3 and set(out["source"][3:]) == {"v2"}
    assert out["pm25"].notna().all() and (out["pm25"] >= 0).all()
    assert (out["exceeds"] == (out["pm25"] >= 30.0)).all()


def test_predict_v2_serves_persistence_when_released_so(model_dir):
    (model_dir / "release.json").write_text(json.dumps({"6": {"serve": "persistence", "threshold": 35.5}}))
    from ml.inference import predict_v2 as pv2
    pv2.load_release.cache_clear()
    test = _frame(12, seed=2)
    out = predict(test, horizon=6, model_dir=model_dir)
    assert np.allclose(out["pm25"], add_derived(test)["persistence"].clip(lower=None))
    assert set(out["source"]) == {"persistence"}
    pv2.load_release.cache_clear()
