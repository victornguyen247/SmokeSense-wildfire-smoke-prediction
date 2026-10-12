"""Train and evaluate baseline v2, persistence-anchored (docs/data-decisions.md #28-31).

    python -m ml.training.train_baseline_v2 [--data ...] [--v1 data/models/baseline_v1] [--out data/models/baseline_v2]

1. Load smokesense_v1 (sha256 checked), add the derived features (ml.features.add_derived),
   and join v1's out-of-fold predictions (v1 model and climatology) by row key.
2. Leave-one-group-out CV on group_id. Per fold and horizon, for each grid setting: fit the
   residual model on training rows with persistence; rows without persistence take v1's
   prediction (the v1 direct model is the fallback); tune the exceedance cut-off on the
   inner validation split and apply it to the fold's test rows.
3. Choose the setting with the lowest pooled out-of-fold MAE (the outer folds both choose and
   score it: nested-ish). Apply the release rule (ml/evaluation/release.py) per horizon.
4. Refit the chosen setting on all rows per horizon, plus the v1 direct fallback; write models,
   release.json, thresholds (median of the fold cut-offs), metrics, OOF predictions, manifest.
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

from ml.datasets.load import BACKEND, SMOKESENSE_V1, load_dataset, sha256
from ml.evaluation.metrics import UNHEALTHY_SG, breakdown
from ml.evaluation.release import release
from ml.feature_columns import EXCLUDED, FEATURES, FEATURES_V2, TARGET
from ml.features import add_derived
from ml.models import xgb as v1m
from ml.models import xgb_v2 as v2m

V1_DIR = BACKEND / "data" / "models" / "baseline_v1"
OUT = BACKEND / "data" / "models" / "baseline_v2"
HORIZONS = (1, 3, 6, 12, 24)
KEY = ["forecast_point_id", "issue_time", "horizon_hours"]
KEEP = [*KEY, "pilot_event_id", "event_tier", "group_id", TARGET, "persistence"]
BANDS = [("< 35.5", 0.0, 35.5), ("35.5-125.4", 35.5, 125.5), (">= 125.5", 125.5, np.inf)]
GROUP_2020 = "G-PE-001"


def git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=BACKEND,
                               capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def exceedance(y, flag) -> dict:
    hit, alarm = np.asarray(y, float) >= UNHEALTHY_SG, np.asarray(flag, bool)
    tp, fp, fn = int((hit & alarm).sum()), int((~hit & alarm).sum()), int((hit & ~alarm).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return {"precision": prec, "recall": rec, "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else float("nan")}


def cross_validate(df: pd.DataFrame, oof: pd.DataFrame) -> dict:
    has_p = df["persistence"].notna()
    cut_offs = {v2m.name(s): {} for s in v2m.GRID}
    for s in v2m.GRID:
        oof[v2m.name(s)] = oof["v1"]  # rows without persistence keep the v1 fallback prediction
        oof[v2m.name(s) + "_flag"] = False
    for g in sorted(df["group_id"].unique()):
        t0 = time.time()
        for h in HORIZONS:
            train = df[(df["group_id"] != g) & (df["horizon_hours"] == h) & has_p]
            test = df[(df["group_id"] == g) & (df["horizon_hours"] == h)]
            if test.empty:
                continue
            test_p = test[test["persistence"].notna()]
            for s in v2m.GRID:
                col = v2m.name(s)
                booster, _, (yv, pv) = v2m.fit(train, s)
                t = v2m.tune_threshold(yv, pv)
                cut_offs[col][f"{g}|h{h}"] = t
                if len(test_p):
                    oof.loc[test_p.index, col] = v2m.predict(booster, test_p)
                oof.loc[test.index, col + "_flag"] = oof.loc[test.index, col] >= t
        print(f"  fold {g}: {(df['group_id'] == g).sum():,} test rows ({time.time() - t0:.0f}s)", flush=True)
    return cut_offs


def band_table(oof: pd.DataFrame, cols: list[str]) -> dict:
    rows = oof[(oof["group_id"] == GROUP_2020) & oof["persistence"].notna()]
    out = {}
    for label, lo, hi in BANDS:
        b = rows[(rows[TARGET] >= lo) & (rows[TARGET] < hi)]
        out[label] = {"n": int(len(b)), **{c: {"mae": float((b[c] - b[TARGET]).abs().mean()),
                                               "bias": float((b[c] - b[TARGET]).mean())} for c in cols}}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(SMOKESENSE_V1))
    ap.add_argument("--v1", default=str(V1_DIR), help="baseline_v1 folder (its oof_predictions.parquet)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    t_start = time.time()
    np.random.seed(v2m.SEED)

    df, data_manifest = load_dataset(Path(args.data))
    df = add_derived(df)
    v1_oof = pd.read_parquet(Path(args.v1) / "oof_predictions.parquet")[[*KEY, "climatology", "xgb_d4"]]
    df = df.merge(v1_oof.rename(columns={"xgb_d4": "v1"}), on=KEY, how="left", validate="one_to_one")
    if df["v1"].isna().any():
        raise SystemExit("v1 out-of-fold predictions do not cover every row; retrain baseline_v1 first")
    print(f"loaded {len(df):,} rows (sha256 ok); persistence on {df['persistence'].notna().mean():.1%}", flush=True)

    oof = df[[*KEEP, "climatology", "v1"]].copy()
    print("outer CV (leave-one-group-out):", flush=True)
    cut_offs = cross_validate(df, oof)
    selection = {v2m.name(s): float((oof[v2m.name(s)] - oof[TARGET]).abs().mean()) for s in v2m.GRID}
    best = min(v2m.GRID, key=lambda s: selection[v2m.name(s)])
    col = v2m.name(best)
    print(f"pooled out-of-fold MAE by setting: {selection} -> {col}", flush=True)
    oof["v2"], oof["v2_flag"] = oof[col], oof[col + "_flag"]

    metrics = breakdown(oof, ["persistence", "climatology", "v1", "v2"])
    metrics["grid_pooled_mae_all_rows"] = selection
    metrics["chosen"] = col
    metrics["persistence_coverage"] = float(oof["persistence"].notna().mean())
    metrics["band_2020_group"] = band_table(oof, ["persistence", "v1", "v2"])
    fixed = {"pooled": exceedance(oof[TARGET], oof["v2"] >= UNHEALTHY_SG),
             "by_horizon": {str(h): exceedance(d[TARGET], d["v2"] >= UNHEALTHY_SG)
                            for h, d in oof.groupby("horizon_hours")}}
    tuned = {"pooled": exceedance(oof[TARGET], oof["v2_flag"]),
             "by_horizon": {str(h): exceedance(d[TARGET], d["v2_flag"]) for h, d in oof.groupby("horizon_hours")}}
    metrics["v2_exceedance"] = {"fixed_35_5": fixed, "tuned": tuned,
                                "macro_groups_f1": {"fixed_35_5": float(np.nanmean([exceedance(d[TARGET], d["v2"] >= UNHEALTHY_SG)["f1"] for _, d in oof.groupby("group_id")])),
                                                    "tuned": float(np.nanmean([exceedance(d[TARGET], d["v2_flag"])["f1"] for _, d in oof.groupby("group_id")]))}}
    thresholds = {str(h): float(np.median([t for k, t in cut_offs[col].items() if k.endswith(f"|h{h}")]))
                  for h in HORIZONS}
    rel = release(oof, "v2")
    for h in rel:
        rel[h]["threshold"] = thresholds[h] if rel[h]["serve"] == "v2" else UNHEALTHY_SG
    print(f"release: {json.dumps(rel)}", flush=True)

    print("final models (all rows):", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    trees, importance = {}, {}
    for h in HORIZONS:
        dh = df[df["horizon_hours"] == h]
        booster, n, _ = v2m.fit(dh[dh["persistence"].notna()], best)
        booster.save_model(out / f"model_h{h}.json")
        fb, n_fb = v1m.fit(dh, v2m.V1_FALLBACK)
        fb.save_model(out / f"fallback_h{h}.json")
        trees[h] = {"residual": n, "fallback": n_fb}
        gain = booster.get_score(importance_type="gain")
        total = sum(gain.values()) or 1.0
        importance[h] = {f: gain.get(f, 0.0) / total for f in FEATURES_V2}
    metrics["gain_importance_mean_over_horizons"] = dict(sorted(
        {f: float(np.mean([importance[h][f] for h in HORIZONS])) for f in FEATURES_V2}.items(), key=lambda kv: -kv[1]))

    (out / "release.json").write_text(json.dumps(rel, indent=1))
    (out / "thresholds.json").write_text(json.dumps({"per_horizon": thresholds, "fold_cut_offs": cut_offs[col]},
                                                    indent=1))
    (out / "features.json").write_text(json.dumps({"features": FEATURES_V2, "fallback_features": FEATURES,
                                                   "excluded": EXCLUDED}, indent=1))
    params = {"base": v2m.BASE_PARAMS, "chosen": best, "grid": v2m.GRID, "fallback": v2m.V1_FALLBACK,
              "target": "log1p(y) - log1p(persistence); fallback log1p(y)", "n_estimators_max": v2m.N_ESTIMATORS,
              "early_stopping_rounds": v2m.EARLY_STOPPING, "inner_valid_groups": v2m.INNER_VALID_GROUPS,
              "threshold_grid": [float(v2m.THRESHOLD_GRID[0]), float(v2m.THRESHOLD_GRID[-1]), 0.5],
              "seed": v2m.SEED, "final_trees_per_horizon": trees}
    (out / "params.json").write_text(json.dumps(params, indent=1))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=float))
    oof.to_parquet(out / "oof_predictions.parquet", index=False)
    manifest = {
        "model": "baseline_v2", "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_seconds": round(time.time() - t_start), "git_commit": git_commit(),
        "dataset": {k: data_manifest[k] for k in ("name", "version", "data_sha256", "pilot_events_sha256")},
        "v1_oof_sha256": sha256(Path(args.v1) / "oof_predictions.parquet"),
        "rows": int(len(df)), "cv": "leave-one-group-out on group_id", "chosen": col,
        "files": sorted(p.name for p in out.iterdir()),
        "versions": {"python": platform.python_version(), "xgboost": xgboost.__version__,
                     "sklearn": sklearn.__version__, "pandas": pd.__version__},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {out} ({manifest['train_seconds']}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
