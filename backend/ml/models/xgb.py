"""XGBoost per-horizon regressor (docs/data-decisions.md #25).

Trained on log1p(pm25) by default; predictions are expm1 and clipped at 0. The number of
trees is chosen by early stopping on an inner group split of the training groups, then the
model is refitted on all training rows with that many trees.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupShuffleSplit

from ml.feature_columns import FEATURES, TARGET

SEED = 42
BASE_PARAMS = {"eta": 0.05, "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 5,
               "objective": "reg:squarederror", "tree_method": "hist", "seed": SEED, "nthread": -1}
GRID = [{"max_depth": d} for d in (4, 6, 8)]
N_ESTIMATORS = 800
EARLY_STOPPING = 50
INNER_VALID_GROUPS = 0.25  # share of training groups held out for early stopping


def matrix(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame[FEATURES].copy()
    x["smoke_season"] = x["smoke_season"].astype("int8")
    return x.astype("float32")


def _fwd(y, log_target):
    return np.log1p(np.clip(y, 0, None)) if log_target else y


def _inv(p, log_target):
    return np.clip(np.expm1(p) if log_target else p, 0, None)


def fit(train: pd.DataFrame, params: dict, log_target: bool = True) -> tuple[xgb.Booster, int]:
    """(booster refitted on all of train, number of trees chosen on the inner group split)."""
    p = {**BASE_PARAMS, **params}
    y = _fwd(train[TARGET].to_numpy(float), log_target)
    groups = train["group_id"].to_numpy()
    n_trees = N_ESTIMATORS
    if len(np.unique(groups)) > 1:
        split = GroupShuffleSplit(n_splits=1, test_size=INNER_VALID_GROUPS, random_state=SEED)
        tr, va = next(split.split(train, groups=groups))
        dtr = xgb.DMatrix(matrix(train.iloc[tr]), label=y[tr])
        dva = xgb.DMatrix(matrix(train.iloc[va]), label=y[va])
        b = xgb.train(p, dtr, N_ESTIMATORS, evals=[(dva, "valid")], early_stopping_rounds=EARLY_STOPPING,
                      verbose_eval=False)
        n_trees = b.best_iteration + 1
    booster = xgb.train(p, xgb.DMatrix(matrix(train), label=y), n_trees)
    return booster, n_trees


def predict(booster: xgb.Booster, frame: pd.DataFrame, log_target: bool = True) -> np.ndarray:
    return _inv(booster.predict(xgb.DMatrix(matrix(frame))), log_target)
