"""ML-01 baselines vs the DATA-04 models on ML-01's split (analysis only; nothing is retrained
for serving and no artifact is changed).

    python -m ml.evaluation.ml01_vs_data04 [--out ../docs/ml/ml01-vs-data04.json]

ML-01 (PR #66) split smokesense_v1 chronologically by event group: the first 9 groups (by first
issue time) train, the next 2 validate, the last 2 test, and its test rows are those with
pm25_lag_1h present. This script

1. reproduces ML-01's 6 h test numbers with ML-01's own inference module and saved Decision
   Trees (ml.inference.ml01_baselines; release ml01-baselines-v1.0.0), and stops if they differ;
2. trains XGBoost v1 (ml.models.xgb) and the v2 recipe (ml.models.xgb_v2) on ML-01's 9 training
   groups only, with the shipped hyperparameters (data/models/baseline_v{1,2}/params.json), and
   scores all four models on the same ML-01 test rows with ml.evaluation.metrics.scores.

The validation groups are not used: the shipped hyperparameters need no selection, and the test
groups are never seen in training. Missing values stay NaN for XGBoost.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ml.datasets.load import BACKEND, load_dataset
from ml.evaluation.metrics import scores
from ml.feature_columns import FEATURES, FEATURES_V2, TARGET
from ml.features import add_derived
from ml.inference import ml01_baselines as ml01
from ml.models import xgb as v1m
from ml.models import xgb_v2 as v2m
from ml.training.train_baseline_v2 import exceedance

MODELS = BACKEND / "data" / "models"
OUT = BACKEND.parent / "docs" / "ml" / "ml01-vs-data04.json"
HORIZONS = (1, 3, 6, 12, 24)

CONFIG = {
    # ML-01's chronological group split (notebook section 3.4), checked against the data.
    "train_groups": [
        "G-PE-006",
        "G-PE-016",
        "G-PE-011",
        "G-PE-003",
        "G-PE-010",
        "G-PE-020",
        "G-PE-001",
        "G-PE-002",
        "G-PE-015",
    ],
    "val_groups": ["G-PE-017", "G-PE-009"],
    "test_groups": ["G-PE-018", "G-PE-004"],
    "split_rows": {"train": 104_710, "val": 2_760, "test": 34_484},  # rows of any lag
    "eligible": "pm25_lag_1h present",  # ML-01's test rows
    "threshold": 35.5,  # exceedance, fixed for every model (as ML-01)
    "severe_from": 125.5,  # bias is reported on labels >= this
    "seed": v1m.SEED,  # the shipped seed (42); xgb_v2 uses the same
    # ML-01's published 6 h test results (README_ML01.md); step 1 must reproduce them.
    "ml01_6h": {
        "persistence": {
            "mae": 5.792,
            "rmse": 17.776,
            "f1_35_5": 0.293,
            "auroc_35_5": 0.784,
        },
        "tree": {"mae": 7.012, "rmse": 16.890, "f1_35_5": 0.321},
    },
    "tolerance": 0.0005,
}
METRICS = (
    "mae",
    "rmse",
    "precision_35_5",
    "recall_35_5",
    "f1_35_5",
    "auroc_35_5",
    "auprc_35_5",
)


def chronological_groups(df: pd.DataFrame) -> list[str]:
    """Groups ordered by first issue time, as ML-01 orders them."""
    return df.groupby("group_id")["issue_time"].min().sort_values().index.tolist()


def ml01_split(
    df: pd.DataFrame, n_train: int = 9, n_val: int = 2
) -> dict[str, list[str]]:
    order = chronological_groups(df)
    return {
        "train": order[:n_train],
        "val": order[n_train : n_train + n_val],
        "test": order[n_train + n_val :],
    }


def predictions(
    train: pd.DataFrame, test: pd.DataFrame, v1_setting: dict, v2_setting: dict
) -> dict:
    """{model: {horizon: predictions on test rows of that horizon}}; test rows have pm25_lag_1h."""
    out: dict[str, dict[int, np.ndarray]] = {
        m: {} for m in ("persistence", "decision_tree", "xgb_v1", "v2")
    }
    for h in HORIZONS:
        tr, te = train[train["horizon_hours"] == h], test[test["horizon_hours"] == h]
        out["persistence"][h] = ml01.predict(te, h, "persistence")
        out["decision_tree"][h] = ml01.predict(te, h, "tree")
        booster, _ = v1m.fit(tr, v1_setting)  # v1 trains on every row of the horizon
        out["xgb_v1"][h] = v1m.predict(booster, te)
        residual, _, _ = v2m.fit(tr[tr["persistence"].notna()], v2_setting)
        out["v2"][h] = v2m.predict(residual, te)  # every eligible row has persistence
    return out


def evaluate(
    test: pd.DataFrame, preds: dict, severe_from: float, v2_cutoffs: dict[str, float]
) -> dict:
    """Per horizon and model: ml.evaluation.metrics.scores (at 35.5) plus bias on severe labels.

    v2 also gets precision/recall/F1 at its shipped per-horizon alert cut-off (release.json),
    which is how the served model raises alerts; every other number uses the fixed 35.5.
    """
    out = {}
    for h in HORIZONS:
        te = test[test["horizon_hours"] == h]
        y = te[TARGET].to_numpy(float)
        severe = y >= severe_from
        out[str(h)] = {
            "rows": int(len(te)),
            "positives_35_5": int((y >= 35.5).sum()),
            "severe_rows": int(severe.sum()),
            "models": {},
        }
        for model, by_h in preds.items():
            p = np.asarray(by_h[h], float)
            s = scores(y, p)
            out[str(h)]["models"][model] = {
                **{k: s[k] for k in METRICS},
                "severe_bias": float((p[severe] - y[severe]).mean())
                if severe.any()
                else None,
            }
        p2 = np.asarray(preds["v2"][h], float)
        out[str(h)]["v2_at_shipped_cutoff"] = {
            "cutoff": v2_cutoffs[str(h)],
            **exceedance(y, p2 >= v2_cutoffs[str(h)]),
        }
    return out


def feature_comparison() -> dict:
    ml01_inputs = list(ml01.MODEL_FEATURES)
    return {
        "ml01_model_features": ml01_inputs,
        "ml01_raw_inputs": list(ml01.RAW_FEATURES),
        "in_both": [f for f in ml01_inputs if f in FEATURES_V2],
        "ml01_only": [f for f in ml01_inputs if f not in FEATURES_V2],
        "features_v1_only": [f for f in FEATURES if f not in ml01_inputs],
        "features_v2_only": [f for f in FEATURES_V2 if f not in ml01_inputs],
    }


def check_reproduction(result: dict, expected: dict, tol: float) -> list[str]:
    """Differences from ML-01's published 6 h numbers (empty when reproduced)."""
    got = result["6"]["models"]
    names = {"persistence": "persistence", "tree": "decision_tree"}
    return [
        f"{m} {k}: {got[names[m]][k]:.4f} != {v}"
        for m, want in expected.items()
        for k, v in want.items()
        if abs(round(got[names[m]][k], 3) - v) > tol
    ]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    t0 = time.time()
    cfg = CONFIG
    np.random.seed(cfg["seed"])

    df, manifest = load_dataset()
    df = add_derived(df)
    split = ml01_split(df)
    for part in ("train", "val", "test"):
        if split[part] != cfg[f"{part}_groups"]:
            print(
                f"STOP: {part} groups {split[part]} != {cfg[f'{part}_groups']}",
                file=sys.stderr,
            )
            return 1
    rows = {part: int(df["group_id"].isin(split[part]).sum()) for part in split}
    if rows != cfg["split_rows"]:
        print(f"STOP: split rows {rows} != {cfg['split_rows']}", file=sys.stderr)
        return 1

    train = df[df["group_id"].isin(split["train"])]
    test = df[df["group_id"].isin(split["test"]) & df["pm25_lag_1h"].notna()]
    v1_setting = json.loads((MODELS / "baseline_v1" / "params.json").read_text())[
        "chosen"
    ]
    v2_setting = json.loads((MODELS / "baseline_v2" / "params.json").read_text())[
        "chosen"
    ]

    print(
        f"split {rows}; test rows with pm25_lag_1h: {len(test):,}; training v1 {v1_setting} and "
        f"v2 {v2_setting} on {len(split['train'])} groups ...",
        flush=True,
    )
    preds = predictions(train, test, v1_setting, v2_setting)
    cutoffs = {
        h: r["threshold"]
        for h, r in json.loads(
            (MODELS / "baseline_v2" / "release.json").read_text()
        ).items()
    }
    pooled = evaluate(test, preds, cfg["severe_from"], cutoffs)

    diffs = check_reproduction(pooled, cfg["ml01_6h"], cfg["tolerance"])
    if diffs:
        print(
            "STOP: ML-01's 6 h test results do not reproduce: " + "; ".join(diffs),
            file=sys.stderr,
        )
        return 1

    by_group = {}
    for g in split["test"]:
        mask = (test["group_id"] == g).to_numpy()
        sub = test[mask]
        group_preds = {
            m: {
                h: by_h[h][mask[test["horizon_hours"].to_numpy() == h]]
                for h in HORIZONS
            }
            for m, by_h in preds.items()
        }
        by_group[g] = {
            "rows": int(len(sub)),
            "share_of_test_rows": float(len(sub) / len(test)),
            "by_horizon": evaluate(sub, group_preds, cfg["severe_from"], cutoffs),
        }

    report = {
        "config": cfg,
        "dataset_sha256": manifest["data_sha256"],
        "split": split,
        "split_rows": rows,
        "test_rows_eligible": int(len(test)),
        "settings": {"xgb_v1": v1_setting, "v2": v2_setting},
        "reproduction_6h": {
            "reproduced": True,
            "published": cfg["ml01_6h"],
            "got": {
                m: {
                    k: pooled["6"]["models"][m][k]
                    for k in ("mae", "rmse", "f1_35_5", "auroc_35_5")
                }
                for m in ("persistence", "decision_tree")
            },
        },
        "by_horizon": pooled,
        "by_test_group": by_group,
        "features": feature_comparison(),
        "runtime_seconds": round(time.time() - t0),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1, default=float) + "\n")

    for h in map(str, HORIZONS):
        line = ", ".join(
            f"{m} {r['mae']:.3f}/{r['f1_35_5']:.3f}"
            for m, r in pooled[h]["models"].items()
        )
        print(f"h{h:>2} ({pooled[h]['rows']} rows) MAE/F1: {line}")
    print(f"reproduced ML-01 6 h: yes; {report['runtime_seconds']}s; wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
