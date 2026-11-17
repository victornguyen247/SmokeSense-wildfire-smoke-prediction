"""ML-02 exploratory grid-native PM2.5 models for one pilot event.

Run from backend/:
    python -m ml.training.train_grid_native


This evaluation is chronological WITHIN one event, not spatial hold-out.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error

from ml.feature_columns import FEATURES, TARGET
from ml.models.xgb import BASE_PARAMS, EARLY_STOPPING, N_ESTIMATORS

from ml.training.ml02_common import matrix, chronological_boundaries

HORIZONS = (1, 3, 6, 12, 24)





def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/datasets/smokesense_v1.1/data.parquet")
    parser.add_argument("--out", default="data/models/ml02_grid_native_pe001")
    args = parser.parse_args()

    df = pd.read_parquet(args.data)
    required = set(FEATURES) | {TARGET, "issue_time", "target_time", "horizon_hours", "forecast_point_id", "group_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    df["issue_time"] = pd.to_datetime(df["issue_time"], utc=True)
    df["target_time"] = pd.to_datetime(df["target_time"], utc=True)
    if df[TARGET].isna().any():
        raise ValueError("Target contains nulls")
    # Split all forecast points and horizons on the same timestamps.
    val_start, test_start = chronological_boundaries(df)
    # A 24h target-time purge ensures no training labels enter the validation
    # issue-time period and no validation labels enter the test issue-time period.
    train = df[df["target_time"] < val_start]
    valid = df[(df["issue_time"] >= val_start) & (df["target_time"] < test_start)]
    test = df[df["issue_time"] >= test_start]
    if any(x.empty for x in (train, valid, test)):
        raise ValueError("One chronological split is empty")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    metrics = {}
    predictions = []
    for h in HORIZONS:
        tr = train[train["horizon_hours"] == h]
        va = valid[valid["horizon_hours"] == h]
        te = test[test["horizon_hours"] == h]
        if min(len(tr), len(va), len(te)) == 0:
            raise ValueError(f"Empty split for horizon {h}")
        dtr = xgb.DMatrix(matrix(tr), label=np.log1p(tr[TARGET].to_numpy(float)))
        dva = xgb.DMatrix(matrix(va), label=np.log1p(va[TARGET].to_numpy(float)))
        dte = xgb.DMatrix(matrix(te))
        params = {**BASE_PARAMS, "max_depth": 4, "nthread": 4}
        booster = xgb.train(
            params, dtr, num_boost_round=N_ESTIMATORS,
            evals=[(dva, "validation")], early_stopping_rounds=EARLY_STOPPING,
            verbose_eval=False,
        )
        pred = np.clip(np.expm1(booster.predict(dte, iteration_range=(0, booster.best_iteration + 1))), 0, None)
        y = te[TARGET].to_numpy(float)
        metrics[str(h)] = {
            "n_train": len(tr), "n_validation": len(va), "n_test": len(te),
            "mae": float(mean_absolute_error(y, pred)),
            "rmse": float(np.sqrt(mean_squared_error(y, pred))),
            "best_iteration": int(booster.best_iteration),
        }
        booster.save_model(out / f"model_h{h}.json")
        scored = te[["forecast_point_id", "issue_time", "target_time", "horizon_hours", TARGET]].copy()
        scored["prediction_pm25"] = pred
        predictions.append(scored)
        print(f"h{h}: {metrics[str(h)]}", flush=True)

    pd.concat(predictions, ignore_index=True).to_parquet(out / "test_predictions.parquet", index=False)
    summary = {
        "experiment": "ML-02 PE-001 chronological pilot; NOT spatial holdout or Method A/B comparison",
        "dataset": str(args.data), "created_at": datetime.now(timezone.utc).isoformat(),
        "train_target_before": val_start.isoformat(),
        "validation_issue_from": val_start.isoformat(),
        "validation_target_before": test_start.isoformat(),
        "test_issue_from": test_start.isoformat(),
        "feature_names": FEATURES,
        "metrics_by_horizon": metrics,
    }
    (out / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Saved results to {out}")


if __name__ == "__main__":
    main()
