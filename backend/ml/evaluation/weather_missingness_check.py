"""Does live weather missingness hurt baseline_v2? (analysis only; no model or data change)

    python -m ml.evaluation.weather_missingness_check [--out ../docs/ml/weather-missingness-check.json]

Live NWS data leaves precip_1h_mm and pressure_hpa missing more often than the NCEI rows
smokesense_v1 was built from. This re-runs baseline_v2's leave-one-group-out CV with the
shipped recipe (ml.models.xgb_v2, the setting in params.json): every fold is trained on
UNMASKED rows, as in production, and the features are masked only in the held-out fold at
prediction time, which is what serving would see. Scenarios:

  baseline  no masking (must reproduce docs/models/baseline_v2.md)
  A         precip_1h_mm and pressure_hpa NaN on every held-out row
  B         extra PRESENT values masked at random until each feature's missing rate reaches
            the live rate; one run per seed

Metrics are on persistence rows (where the residual model serves and the release rule is
computed). Missing values stay NaN; nothing is filled. The decision rule in CONFIG was set
before the results were seen.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from ml.datasets.load import BACKEND, load_dataset
from ml.evaluation.release import release, skills
from ml.feature_columns import FEATURES_V2, TARGET
from ml.features import add_derived
from ml.models import xgb_v2 as v2m
from ml.training.train_baseline_v2 import HORIZONS, exceedance

MODEL_DIR = BACKEND / "data" / "models" / "baseline_v2"
OUT = BACKEND.parent / "docs" / "ml" / "weather-missingness-check.json"

CONFIG = {
    "features": ["precip_1h_mm", "pressure_hpa"],
    # Missing rate of each feature in live NWS rows (first live run, 2026-10-23, PR #85).
    "live_missing_rate": {"precip_1h_mm": 0.87, "pressure_hpa": 0.60},
    "seeds": [0, 1, 2, 3, 4],
    "severe_from": 125.5,  # bias is reported on labels >= this (EPA "Very Unhealthy")
    # Scenario baseline must reproduce these (docs/models/baseline_v2.md, persistence rows).
    "expected_baseline": {
        "v2_pooled_mae": 11.40,
        "persistence_pooled_mae": 12.31,
        "tolerance": 0.005,
    },
    # Pre-set decision rule: the gap is harmless if, under scenario B, ALL hold.
    # MAE and F1 use the mean over seeds; the served horizons must match for every seed.
    "rule": {"max_mae_rise": 0.15, "max_f1_change": 0.01},
}


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


def missing_rates(frame: pd.DataFrame, columns: list[str]) -> dict[str, float]:
    return {c: float(frame[c].isna().mean()) for c in columns}


def extra_fraction(current: float, target: float) -> float:
    """Share of the PRESENT values to mask so the missing rate goes from current to target."""
    if target <= current or current >= 1.0:
        return 0.0
    return (target - current) / (1.0 - current)


def mask_present(
    frame: pd.DataFrame, column: str, fraction: float, seed: int
) -> pd.DataFrame:
    """A copy of frame with round(fraction x present) randomly chosen present values of column
    set to NaN. Deterministic for a seed; already-missing values and other columns are untouched."""
    out = frame.copy()
    present = np.flatnonzero(out[column].notna().to_numpy())
    k = int(round(min(max(fraction, 0.0), 1.0) * len(present)))
    if k:
        rng = np.random.default_rng(seed)
        chosen = rng.choice(present, size=k, replace=False)
        out.iloc[chosen, out.columns.get_loc(column)] = np.nan
    return out


def mask_to_rates(
    frame: pd.DataFrame,
    targets: dict[str, float],
    seed: int,
    current: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Mask each column's present values up to its target missing rate (current: measured rates)."""
    current = current or missing_rates(frame, list(targets))
    out = frame
    for i, (column, target) in enumerate(targets.items()):
        # One stream per (seed, column), so adding a column never changes another's mask.
        out = mask_present(
            out, column, extra_fraction(current[column], target), seed * 1000 + i
        )
    return out


def mask_all(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    out[columns] = np.nan
    return out


# ---------------------------------------------------------------------------
# Out-of-fold predictions: train unmasked, predict each scenario's frame
# ---------------------------------------------------------------------------


def oof_predictions(
    df: pd.DataFrame, setting: dict, scenarios: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """v2 residual-model predictions on persistence rows, one column per scenario.

    df is the unmasked data (training); each scenario frame has df's index and holds the
    features the held-out fold is predicted from. Folds and fit are those of
    train_baseline_v2.cross_validate.
    """
    has_p = df["persistence"].notna()
    out = pd.DataFrame(index=df.index[has_p])
    for name in scenarios:
        out[name] = np.nan
    for g in sorted(df["group_id"].unique()):
        for h in HORIZONS:
            train = df[(df["group_id"] != g) & (df["horizon_hours"] == h) & has_p]
            test_idx = df.index[
                (df["group_id"] == g) & (df["horizon_hours"] == h) & has_p
            ]
            if not len(test_idx):
                continue
            booster, _, _ = v2m.fit(train, setting)
            for name, frame in scenarios.items():
                out.loc[test_idx, name] = v2m.predict(booster, frame.loc[test_idx])
    return out


# ---------------------------------------------------------------------------
# Evaluation (existing metric and release code)
# ---------------------------------------------------------------------------


def evaluate(
    rows: pd.DataFrame, pred: str, thresholds: dict[str, float], severe_from: float
) -> dict:
    """Per horizon: MAE (v2, persistence), skill (pooled, macro), F1 at the shipped cut-off,
    bias on severe labels; plus the horizons the release rule would serve."""
    served = release(rows, pred)
    out = {
        "by_horizon": {},
        "served": sorted(int(h) for h, r in served.items() if r["serve"] == "v2"),
    }
    for h in HORIZONS:
        d = rows[rows["horizon_hours"] == h]
        pooled, macro = skills(d, pred)
        severe = d[d[TARGET] >= severe_from]
        out["by_horizon"][str(h)] = {
            "n": int(len(d)),
            "v2_mae": float((d[pred] - d[TARGET]).abs().mean()),
            "persistence_mae": float((d["persistence"] - d[TARGET]).abs().mean()),
            "skill_pooled": pooled,
            "skill_macro": macro,
            "f1_shipped_cutoff": exceedance(d[TARGET], d[pred] >= thresholds[str(h)])[
                "f1"
            ],
            "severe_n": int(len(severe)),
            "severe_bias": float((severe[pred] - severe[TARGET]).mean())
            if len(severe)
            else float("nan"),
            "serve": served[str(h)]["serve"],
        }
    out["pooled"] = {
        "v2_mae": float((rows[pred] - rows[TARGET]).abs().mean()),
        "persistence_mae": float((rows["persistence"] - rows[TARGET]).abs().mean()),
    }
    return out


def summarize_seeds(runs: list[dict]) -> dict:
    """Mean and standard deviation over seeds of every per-horizon number."""
    out = {"by_horizon": {}, "served_per_seed": [r["served"] for r in runs]}
    for h in map(str, HORIZONS):
        out["by_horizon"][h] = {}
        for k, v in runs[0]["by_horizon"][h].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals = np.array([r["by_horizon"][h][k] for r in runs], float)
                out["by_horizon"][h][k] = {
                    "mean": float(np.mean(vals)),
                    "std": float(np.std(vals)),
                }
    return out


def verdict(baseline: dict, b: dict, rule: dict) -> dict:
    """The pre-set decision rule (CONFIG["rule"]) applied to scenario B."""
    checks = {}
    for h in map(str, HORIZONS):
        base, mean = baseline["by_horizon"][h], b["by_horizon"][h]
        checks[f"mae_rise_h{h}"] = (
            mean["v2_mae"]["mean"] - base["v2_mae"] <= rule["max_mae_rise"]
        )
        checks[f"f1_change_h{h}"] = (
            abs(mean["f1_shipped_cutoff"]["mean"] - base["f1_shipped_cutoff"])
            <= rule["max_f1_change"]
        )
    checks["served_unchanged_every_seed"] = all(
        s == baseline["served"] for s in b["served_per_seed"]
    )
    return {"harmless": all(checks.values()), "checks": checks}


def importance_ranks(model_dir: Path, features: list[str]) -> dict:
    """Gain share and rank (1 = most important) of features in the shipped residual models."""
    per_h = {}
    for h in HORIZONS:
        b = xgb.Booster()
        b.load_model(str(model_dir / f"model_h{h}.json"))
        gain = b.get_score(importance_type="gain")
        total = sum(gain.values()) or 1.0
        per_h[h] = {f: gain.get(f, 0.0) / total for f in FEATURES_V2}
    mean = {f: float(np.mean([per_h[h][f] for h in HORIZONS])) for f in FEATURES_V2}
    order = sorted(FEATURES_V2, key=lambda f: -mean[f])
    return {
        f: {
            "gain_share_mean": mean[f],
            "rank_mean": order.index(f) + 1,
            "rank_by_horizon": {
                str(h): sorted(FEATURES_V2, key=lambda x: -per_h[h][x]).index(f) + 1
                for h in HORIZONS
            },
        }
        for f in features
    } | {"_n_features": len(FEATURES_V2)}


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    t0 = time.time()
    cfg = CONFIG
    np.random.seed(v2m.SEED)

    df, _ = load_dataset()
    df = add_derived(df)
    setting = json.loads((MODEL_DIR / "params.json").read_text())["chosen"]
    thresholds = {
        h: r["threshold"]
        for h, r in json.loads((MODEL_DIR / "release.json").read_text()).items()
    }
    feats, targets = cfg["features"], cfg["live_missing_rate"]

    measured = missing_rates(df, feats)
    by_group = {g: missing_rates(d, feats) for g, d in df.groupby("group_id")}
    fractions = {c: extra_fraction(measured[c], targets[c]) for c in feats}
    print(
        f"measured missing rates: {measured}; extra fraction of present values to mask: {fractions}"
    )

    scenarios = {"baseline": df, "A": mask_all(df, feats)}
    achieved = {}
    for seed in cfg["seeds"]:
        frame = mask_to_rates(df, targets, seed, current=measured)
        scenarios[f"B_seed{seed}"] = frame
        achieved[seed] = missing_rates(frame, feats)

    print(
        f"training {df['group_id'].nunique()} folds x {len(HORIZONS)} horizons ({setting}) ...",
        flush=True,
    )
    preds = oof_predictions(df, setting, scenarios)
    rows = df.loc[
        preds.index, ["group_id", "horizon_hours", TARGET, "persistence"]
    ].join(preds)

    results = {
        name: evaluate(rows, name, thresholds, cfg["severe_from"])
        for name in ("baseline", "A")
    }
    b_runs = [
        evaluate(rows, f"B_seed{s}", thresholds, cfg["severe_from"])
        for s in cfg["seeds"]
    ]
    results["B"] = summarize_seeds(b_runs)

    exp, got = cfg["expected_baseline"], results["baseline"]["pooled"]
    shipped = pd.read_parquet(MODEL_DIR / "oof_predictions.parquet")
    max_diff = float((shipped.loc[preds.index, "v2"] - preds["baseline"]).abs().max())
    reproduced = (
        abs(round(got["v2_mae"], 2) - exp["v2_pooled_mae"]) <= exp["tolerance"]
        and abs(round(got["persistence_mae"], 2) - exp["persistence_pooled_mae"])
        <= exp["tolerance"]
    )
    print(
        f"baseline pooled MAE v2 {got['v2_mae']:.4f} / persistence {got['persistence_mae']:.4f} "
        f"(expected {exp['v2_pooled_mae']} / {exp['persistence_pooled_mae']}); "
        f"max |diff| vs shipped OOF {max_diff:.2e}"
    )
    if not reproduced:
        print(
            "STOP: the baseline does not reproduce docs/models/baseline_v2.md",
            file=sys.stderr,
        )
        return 1

    decision = verdict(results["baseline"], results["B"], cfg["rule"])
    report = {
        "config": cfg,
        "setting": setting,
        "shipped_thresholds": thresholds,
        "rows_evaluated": int(len(rows)),
        "measured_missing_rate": measured,
        "measured_missing_rate_by_group": by_group,
        "extra_fraction_masked": fractions,
        "achieved_missing_rate_B": {str(k): v for k, v in achieved.items()},
        "baseline_reproduced": {"pooled": got, "max_abs_diff_vs_shipped_oof": max_diff},
        "results": results,
        "importance": importance_ranks(MODEL_DIR, feats),
        "verdict": decision,
        "runtime_seconds": round(time.time() - t0),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1, default=float) + "\n")

    for h in map(str, HORIZONS):
        base, a, b = (results[k]["by_horizon"][h] for k in ("baseline", "A", "B"))
        print(
            f"h{h:>2}: MAE base {base['v2_mae']:.3f}  A {a['v2_mae']:.3f}  B {b['v2_mae']['mean']:.3f}"
            f"±{b['v2_mae']['std']:.3f}  | F1 base {base['f1_shipped_cutoff']:.3f}  A {a['f1_shipped_cutoff']:.3f}"
            f"  B {b['f1_shipped_cutoff']['mean']:.3f}"
        )
    print(
        f"served: baseline {results['baseline']['served']}, A {results['A']['served']}, "
        f"B {results['B']['served_per_seed']}"
    )
    print(
        f"VERDICT: the live weather missingness gap is {'HARMLESS' if decision['harmless'] else 'NOT harmless'} "
        f"({sum(decision['checks'].values())}/{len(decision['checks'])} checks pass); "
        f"{report['runtime_seconds']}s; wrote {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
