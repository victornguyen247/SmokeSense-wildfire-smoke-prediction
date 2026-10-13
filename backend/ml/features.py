"""Derived model features shared by training and inference (docs/data-decisions.md #29).

add_derived is the only place these are computed; ml.training.train_baseline_v2 and
ml.inference.predict_v2 both call it, so training and serving cannot drift apart.
"""
from __future__ import annotations

import pandas as pd


def persistence(frame: pd.DataFrame) -> pd.Series:
    """The last observed PM2.5: pm25_lag_1h, else lag_3h, else lag_6h; NaN if none."""
    return frame["pm25_lag_1h"].fillna(frame["pm25_lag_3h"]).fillna(frame["pm25_lag_6h"]).astype(float)


def add_derived(frame: pd.DataFrame) -> pd.DataFrame:
    """A copy of frame with persistence, trend_1_3, trend_1_6 and ratio_1_24 added."""
    out = frame.copy()
    lag1, lag3, lag6, lag24 = (out[f"pm25_lag_{h}h"].astype(float) for h in (1, 3, 6, 24))
    out["persistence"] = persistence(out)
    out["trend_1_3"] = lag1 - lag3
    out["trend_1_6"] = lag1 - lag6
    out["ratio_1_24"] = (lag1 + 1) / (lag24 + 1)
    return out
