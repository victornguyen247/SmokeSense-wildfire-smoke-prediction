"""Train and evaluate the baseline v1 models (docs/data-decisions.md #23-27).

    python -m ml.training.train_baseline_v1 [--out data/models/baseline_v1]

1. Load smokesense_v1 and check its sha256 against the manifest.
2. Leave-one-group-out CV on group_id: persistence, climatology (fitted on the training
   folds), and XGBoost per horizon for each grid setting (log1p target).
3. Choose the setting with the lowest pooled out-of-fold MAE across the outer folds. The
   outer folds both choose and score it, so the CV numbers are "nested-ish", not a clean
   nested estimate. Also score the chosen setting on the raw target, for comparison.
4. Refit the chosen setting on all rows, one model per horizon; write models, feature list,
   params, metrics, out-of-fold predictions and a manifest (dataset sha256, git commit).
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost

from ml.datasets.load import BACKEND, SMOKESENSE_V1, load_dataset
from ml.evaluation.metrics import breakdown
from ml.feature_columns import EXCLUDED, FEATURES, TARGET
from ml.models import xgb as xgbm
from ml.models.baselines import Climatology, persistence

OUT = BACKEND / "data" / "models" / "baseline_v1"
HORIZONS = (1, 3, 6, 12, 24)
KEEP = ["forecast_point_id", "issue_time", "horizon_hours", "pilot_event_id", "event_tier", "group_id", TARGET]


def col(setting: dict) -> str:
    return f"xgb_d{setting['max_depth']}"


def git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=BACKEND,
                               capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def cross_validate(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    oof = df[KEEP].copy()
    oof["persistence"] = persistence(df)
    for c in ["climatology", *[col(s) for s in xgbm.GRID]]:
        oof[c] = np.nan
    trees = {col(s): {} for s in xgbm.GRID}
    for g in sorted(df["group_id"].unique()):
        t = time.time()
        train, test = df[df["group_id"] != g], df[df["group_id"] == g]
        oof.loc[test.index, "climatology"] = Climatology().fit(train).predict(test).to_numpy()
        for h in HORIZONS:
            tr, te = train[train["horizon_hours"] == h], test[test["horizon_hours"] == h]
            if te.empty:
                continue
            for s in xgbm.GRID:
                booster, n = xgbm.fit(tr, s)
                oof.loc[te.index, col(s)] = xgbm.predict(booster, te)
                trees[col(s)][f"{g}|h{h}"] = n
        print(f"  fold {g}: {len(test):,} test rows ({time.time() - t:.0f}s)", flush=True)
    return oof, trees


def raw_variant(df: pd.DataFrame, oof: pd.DataFrame, setting: dict) -> str:
    name = f"{col(setting)}_raw"
    oof[name] = np.nan
    for g in sorted(df["group_id"].unique()):
        train, test = df[df["group_id"] != g], df[df["group_id"] == g]
        for h in HORIZONS:
            tr, te = train[train["horizon_hours"] == h], test[test["horizon_hours"] == h]
            if not te.empty:
                booster, _ = xgbm.fit(tr, setting, log_target=False)
                oof.loc[te.index, name] = xgbm.predict(booster, te, log_target=False)
    return name


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(SMOKESENSE_V1))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    t0 = time.time()
    np.random.seed(xgbm.SEED)

    df, data_manifest = load_dataset(Path(args.data))
    print(f"loaded {len(df):,} rows, {df['group_id'].nunique()} groups (sha256 ok)", flush=True)

    print("outer CV (leave-one-group-out):", flush=True)
    oof, trees = cross_validate(df)
    selection = {col(s): float(np.abs(oof[col(s)] - oof[TARGET]).mean()) for s in xgbm.GRID}
    best = min(xgbm.GRID, key=lambda s: selection[col(s)])
    print(f"pooled out-of-fold MAE by setting: {selection} -> {col(best)}", flush=True)
    raw = raw_variant(df, oof, best)

    metrics = breakdown(oof, ["persistence", "climatology", col(best), raw])
    metrics["grid_pooled_mae_all_rows"] = selection
    metrics["persistence_coverage"] = float(oof["persistence"].notna().mean())

    print("final models (all rows):", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    final_trees, importance = {}, {}
    for h in HORIZONS:
        booster, n = xgbm.fit(df[df["horizon_hours"] == h], best)
        booster.save_model(out / f"model_h{h}.json")
        final_trees[h] = n
        gain = booster.get_score(importance_type="gain")
        total = sum(gain.values()) or 1.0
        importance[h] = {f: gain.get(f, 0.0) / total for f in FEATURES}
    mean_gain = {f: float(np.mean([importance[h][f] for h in HORIZONS])) for f in FEATURES}

    climatology = Climatology().fit(df)
    (out / "climatology.json").write_text(json.dumps(climatology.to_dict(), indent=1))
    (out / "features.json").write_text(json.dumps({"features": FEATURES, "excluded": EXCLUDED}, indent=1))
    params = {"base": xgbm.BASE_PARAMS, "chosen": best, "grid": xgbm.GRID, "n_estimators_max": xgbm.N_ESTIMATORS,
              "early_stopping_rounds": xgbm.EARLY_STOPPING, "inner_valid_groups": xgbm.INNER_VALID_GROUPS,
              "target_transform": "log1p (predictions expm1, clipped at 0)", "seed": xgbm.SEED,
              "final_trees_per_horizon": final_trees, "cv_trees": trees}
    (out / "params.json").write_text(json.dumps(params, indent=1))
    metrics["gain_importance_mean_over_horizons"] = dict(sorted(mean_gain.items(), key=lambda kv: -kv[1]))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=float))
    oof.to_parquet(out / "oof_predictions.parquet", index=False)
    manifest = {
        "model": "baseline_v1", "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_seconds": round(time.time() - t0), "git_commit": git_commit(),
        "dataset": {"name": data_manifest["name"], "version": data_manifest["version"],
                    "data_sha256": data_manifest["data_sha256"],
                    "pilot_events_sha256": data_manifest["pilot_events_sha256"]},
        "rows": int(len(df)), "groups": sorted(df["group_id"].unique()), "cv": "leave-one-group-out on group_id",
        "chosen": col(best), "files": sorted(p.name for p in out.iterdir()),
        "versions": {"python": platform.python_version(), "xgboost": xgboost.__version__,
                     "sklearn": sklearn.__version__, "pandas": pd.__version__},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {out} ({manifest['train_seconds']}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
