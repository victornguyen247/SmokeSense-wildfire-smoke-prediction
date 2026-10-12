"""Regression and threshold metrics on raw PM2.5 (µg/m³) (docs/data-decisions.md #26)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

UNHEALTHY_SG = 35.5  # EPA 2024: "Unhealthy for Sensitive Groups" starts at 35.5 µg/m³ (24 h)
# EPA 2024 AQI PM2.5 category upper bounds: Good 0-9.0, Moderate 9.1-35.4, USG 35.5-55.4,
# Unhealthy 55.5-125.4, Very Unhealthy 125.5-225.4, Hazardous > 225.4.
AQI_UPPER = np.array([9.0, 35.4, 55.4, 125.4, 225.4])


def aqi_category(pm25) -> np.ndarray:
    """0..5 per EPA 2024 PM2.5 breakpoints; values are truncated to 0.1 first, as EPA does."""
    x = np.floor(np.asarray(pm25, dtype=float) * 10) / 10
    return np.searchsorted(AQI_UPPER, x, side="left")


def scores(y_true, y_pred) -> dict:
    y, p = np.asarray(y_true, float), np.asarray(y_pred, float)
    ok = ~np.isnan(p)
    y, p = y[ok], p[ok]
    if len(y) == 0:
        return {"n": 0}
    err = p - y
    ss_tot = float(((y - y.mean()) ** 2).sum())
    hit, alarm = y >= UNHEALTHY_SG, p >= UNHEALTHY_SG
    tp, fp, fn = int((hit & alarm).sum()), int((~hit & alarm).sum()), int((hit & ~alarm).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if tp else (0.0 if tp + fp + fn else float("nan"))
    both = hit.any() and (~hit).any()
    return {
        "n": int(len(y)),
        "mae": float(np.abs(err).mean()),
        "rmse": float(np.sqrt((err ** 2).mean())),
        "r2": float(1 - (err ** 2).sum() / ss_tot) if ss_tot else float("nan"),
        "aqi_accuracy": float((aqi_category(y) == aqi_category(p)).mean()),
        "precision_35_5": prec, "recall_35_5": rec, "f1_35_5": f1,
        "auroc_35_5": float(roc_auc_score(hit, p)) if both else float("nan"),
        "auprc_35_5": float(average_precision_score(hit, p)) if both else float("nan"),
        "positives_35_5": int(hit.sum()),
    }


def breakdown(frame: pd.DataFrame, pred_cols: list[str], persistence_col: str = "persistence") -> dict:
    """Pooled, macro-over-groups, per horizon, per tier and per group, for each prediction column.

    Two row sets: "persistence_rows" (rows where persistence exists; every model compared on
    the same rows, with skill = 1 - MAE / MAE_persistence) and "all_rows".
    """
    out = {}
    have = frame[persistence_col].notna()
    for name, rows in (("persistence_rows", frame[have]), ("all_rows", frame)):
        res = {}
        for col in pred_cols:
            if name == "all_rows" and col == persistence_col:
                continue
            pooled = scores(rows["target_pm25"], rows[col])
            by = {key: {str(k): scores(g["target_pm25"], g[col]) for k, g in rows.groupby(key, sort=True)}
                  for key in ("horizon_hours", "event_tier", "group_id")}
            groups = by["group_id"].values()
            macro = {m: float(np.nanmean([g[m] for g in groups if g.get("n")]))
                     for m in ("mae", "rmse", "r2", "aqi_accuracy", "f1_35_5")}
            res[col] = {"pooled": pooled, "macro_groups": macro, **{f"by_{k}": v for k, v in by.items()}}
        if name == "persistence_rows":
            base = res[persistence_col]
            for col in pred_cols:
                r = res[col]
                r["pooled"]["skill"] = 1 - r["pooled"]["mae"] / base["pooled"]["mae"]
                for key in ("by_horizon_hours", "by_event_tier", "by_group_id"):
                    for k, s in r[key].items():
                        b = base[key][k]
                        s["skill"] = 1 - s["mae"] / b["mae"] if b.get("n") and b["mae"] else float("nan")
        res["_rows"] = int(len(rows))
        out[name] = res
    return out
