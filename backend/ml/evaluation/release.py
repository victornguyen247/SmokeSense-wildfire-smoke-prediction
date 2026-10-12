"""Release rule for per-horizon models (docs/data-decisions.md #31, fixed before the v2 results).

Per horizon, on out-of-fold rows where persistence exists:

    pooled_skill = 1 - MAE(model) / MAE(persistence)
    macro_skill  = 1 - mean_g MAE_g(model) / mean_g MAE_g(persistence)    (g = held-out group)

The horizon ships the model only if pooled_skill >= 0 AND macro_skill >= 0; otherwise it
serves persistence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def skills(frame: pd.DataFrame, model_col: str, target: str = "target_pm25", persistence_col: str = "persistence",
           group_col: str = "group_id") -> tuple[float, float]:
    rows = frame[frame[persistence_col].notna() & frame[model_col].notna()]
    err_m = (rows[model_col] - rows[target]).abs()
    err_p = (rows[persistence_col] - rows[target]).abs()
    pooled = 1 - err_m.mean() / err_p.mean()
    by_group = pd.DataFrame({"m": err_m, "p": err_p, "g": rows[group_col]}).groupby("g")[["m", "p"]].mean()
    macro = 1 - by_group["m"].mean() / by_group["p"].mean()
    return float(pooled), float(macro)


def release(frame: pd.DataFrame, model_col: str, model_name: str = "v2", horizons=(1, 3, 6, 12, 24)) -> dict:
    """{horizon: {"serve": model_name | "persistence", "pooled_skill", "macro_skill"}}."""
    out = {}
    for h in horizons:
        pooled, macro = skills(frame[frame["horizon_hours"] == h], model_col)
        ship = bool(np.isfinite(pooled) and np.isfinite(macro) and pooled >= 0 and macro >= 0)
        out[str(h)] = {"serve": model_name if ship else "persistence",
                       "pooled_skill": round(pooled, 4), "macro_skill": round(macro, 4)}
    return out
