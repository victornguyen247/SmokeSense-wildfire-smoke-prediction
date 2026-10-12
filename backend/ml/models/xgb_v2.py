"""Baseline v2: persistence-anchored XGBoost per horizon (docs/data-decisions.md #28-30).

On rows with persistence, the model learns the residual r = log1p(y) - log1p(persistence);
the prediction is clip(expm1(log1p(persistence) + r_hat), 0). Rows without persistence
use the v1 direct log1p model. The number of trees comes from early stopping on the same
inner group split as v1; that split's predictions also tune the exceedance cut-off.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupShuffleSplit

from ml.feature_columns import FEATURES_V2, TARGET
from ml.models import xgb as v1

SEED = v1.SEED
BASE_PARAMS = v1.BASE_PARAMS
N_ESTIMATORS = v1.N_ESTIMATORS
EARLY_STOPPING = v1.EARLY_STOPPING
INNER_VALID_GROUPS = v1.INNER_VALID_GROUPS
GRID = [{"max_depth": d, "weights": w} for d in (4, 6) for w in ("none", "group")]
V1_FALLBACK = {"max_depth": 4}  # the v1 setting chosen in baseline_v1
THRESHOLD_GRID = np.round(np.arange(20.0, 50.0 + 1e-9, 0.5), 1)
UNHEALTHY_SG = 35.5


def name(setting: dict) -> str:
    return f"v2_d{setting['max_depth']}_{setting['weights']}"


def matrix(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame[FEATURES_V2].copy()
    x["smoke_season"] = x["smoke_season"].astype("int8")
    return x.astype("float32")


def residual(y, p) -> np.ndarray:
    return np.log1p(np.clip(np.asarray(y, float), 0, None)) - np.log1p(np.clip(np.asarray(p, float), 0, None))


def from_residual(p, r) -> np.ndarray:
    p = np.clip(np.asarray(p, float), 0, None)  # PM2.5 is stored >= 0; guard anyway
    return np.clip(np.expm1(np.log1p(p) + np.asarray(r, float)), 0, None)


def group_weights(groups: np.ndarray, scheme: str) -> np.ndarray | None:
    """None, or weights giving every group the same total weight (mean weight 1)."""
    if scheme == "none":
        return None
    labels, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    w = (len(groups) / len(labels)) / counts[inverse]
    return w.astype(float)


def fit(train: pd.DataFrame, setting: dict) -> tuple[xgb.Booster, int, tuple[np.ndarray, np.ndarray]]:
    """(residual booster refitted on all of train, n_trees, (y, prediction) on the inner validation groups).

    train must hold only rows with persistence.
    """
    params = {**BASE_PARAMS, "max_depth": setting["max_depth"]}
    y = train[TARGET].to_numpy(float)
    p = train["persistence"].to_numpy(float)
    r = residual(y, p)
    groups = train["group_id"].to_numpy()
    w = group_weights(groups, setting["weights"])
    n_trees, inner = N_ESTIMATORS, (np.array([]), np.array([]))
    if len(np.unique(groups)) > 1:
        split = GroupShuffleSplit(n_splits=1, test_size=INNER_VALID_GROUPS, random_state=SEED)
        tr, va = next(split.split(train, groups=groups))
        dtr = xgb.DMatrix(matrix(train.iloc[tr]), label=r[tr], weight=None if w is None else w[tr])
        dva = xgb.DMatrix(matrix(train.iloc[va]), label=r[va], weight=None if w is None else w[va])
        b = xgb.train(params, dtr, N_ESTIMATORS, evals=[(dva, "valid")], early_stopping_rounds=EARLY_STOPPING,
                      verbose_eval=False)
        n_trees = b.best_iteration + 1
        inner = (y[va], from_residual(p[va], b.predict(dva, iteration_range=(0, n_trees))))
    booster = xgb.train(params, xgb.DMatrix(matrix(train), label=r, weight=w), n_trees)
    return booster, n_trees, inner


def predict(booster: xgb.Booster, frame: pd.DataFrame) -> np.ndarray:
    """Residual model prediction in µg/m³; frame must have persistence (add_derived)."""
    return from_residual(frame["persistence"].to_numpy(float), booster.predict(xgb.DMatrix(matrix(frame))))


def tune_threshold(y, pred) -> float:
    """The cut-off in THRESHOLD_GRID with the best F1 for y >= 35.5 (ties: closest to 35.5)."""
    y, pred = np.asarray(y, float), np.asarray(pred, float)
    hit = y >= UNHEALTHY_SG
    if len(y) == 0 or not hit.any():
        return UNHEALTHY_SG
    best = (-1.0, 0.0, UNHEALTHY_SG)
    for t in THRESHOLD_GRID:
        alarm = pred >= t
        tp = int((hit & alarm).sum())
        f1 = 2 * tp / (int(hit.sum()) + int(alarm.sum())) if tp else 0.0
        key = (f1, -abs(t - UNHEALTHY_SG), float(t))
        if key > best:
            best = key
    return best[2]
