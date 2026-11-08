"""Exploratory ML-02 ablation: Fold 1, 12-hour Method B with vs without PM2.5 lags.

Run from backend/: python ablate_ml02_lags.py
Preserves all prior experiment outputs; this script does not write files.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb

import evaluate_ml02_rolling as rolling
from ml.feature_columns import FEATURES, TARGET
from ml.models.xgb import EARLY_STOPPING, N_ESTIMATORS

VALID_START = pd.Timestamp("2020-09-01", tz="UTC")
TEST_START = pd.Timestamp("2020-09-08", tz="UTC")
TEST_END = pd.Timestamp("2020-09-15", tz="UTC")
HORIZON = 12
THRESHOLD = 35.5


def design(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    x = frame[features].copy()
    if "smoke_season" in x:
        x["smoke_season"] = x["smoke_season"].astype("int8")
    return x.astype("float32")


def scores(y: np.ndarray, pred: np.ndarray) -> dict[str, float | int]:
    high = y >= THRESHOLD
    predicted_high = pred >= THRESHOLD
    n_high = int(high.sum())
    tp = int((high & predicted_high).sum())
    fp = int((~high & predicted_high).sum())
    return {
        "mae": round(float(np.mean(np.abs(pred - y))), 3),
        "rmse": round(float(np.sqrt(np.mean((pred - y) ** 2))), 3),
        "bias": round(float(np.mean(pred - y)), 3),
        "high_n": n_high,
        "tp": tp,
        "fp": fp,
        "recall": round(tp / n_high, 3) if n_high else float("nan"),
    }


def main() -> None:
    _, idw, _ = rolling.load_pair(
        "data/datasets/smokesense_v1/data.parquet",
        "data/datasets/smokesense_v1.1/data.parquet",
    )
    train, validation, test = rolling.partition(idw, VALID_START, TEST_START, TEST_END)
    train = train[train.horizon_hours == HORIZON]
    validation = validation[validation.horizon_hours == HORIZON]
    test = test[test.horizon_hours == HORIZON]
    if min(len(train), len(validation), len(test)) == 0:
        raise ValueError("One or more partitions are empty")

    full = list(FEATURES)
    without_lags = [col for col in full if not col.startswith("pm25_lag_")]
    print("Removed lag columns:", [c for c in full if c not in without_lags])
    print(f"Rows train={len(train)} validation={len(validation)} test={len(test)}")

    for name, columns in [("full", full), ("no_lags", without_lags)]:
        dtrain = xgb.DMatrix(design(train, columns), label=np.log1p(train[TARGET].to_numpy(float)))
        dvalid = xgb.DMatrix(design(validation, columns), label=np.log1p(validation[TARGET].to_numpy(float)))
        dtest = xgb.DMatrix(design(test, columns))
        model = xgb.train(
            rolling.PARAMS,
            dtrain,
            num_boost_round=N_ESTIMATORS,
            evals=[(dvalid, "validation")],
            early_stopping_rounds=EARLY_STOPPING,
            verbose_eval=False,
        )
        end = model.best_iteration + 1
        valid_pred = np.clip(np.expm1(model.predict(dvalid, iteration_range=(0, end))), 0, None)
        test_pred = np.clip(np.expm1(model.predict(dtest, iteration_range=(0, end))), 0, None)
        valid_scores = scores(validation[TARGET].to_numpy(float), valid_pred)
        test_scores = scores(test[TARGET].to_numpy(float), test_pred)
        print(f"\n{name}: best_iteration={model.best_iteration} (rounds={end})")
        print("  validation:", valid_scores)
        print("  test (exploratory only):", test_scores)


if __name__ == "__main__":
    main()
