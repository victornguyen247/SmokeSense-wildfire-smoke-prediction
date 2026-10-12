"""Baseline v2 inference: follows release.json per horizon (docs/data-decisions.md #28-31).

    from ml.inference.predict_v2 import predict
    out = predict(feature_frame, horizon=6)        # default model_dir: data/models/baseline_v2

Returns a DataFrame aligned with feature_frame:
    pm25     predicted PM2.5 (µg/m³)
    exceeds  pm25 >= the horizon's threshold (release.json; 35.5 where persistence is served)
    source   "v2" (residual model), "persistence", or "fallback" (v1 direct model, used when
             persistence is missing)

feature_frame needs ml.feature_columns.FEATURES; the derived features are added here with
ml.features.add_derived, exactly as in training.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from ml.datasets.load import BACKEND
from ml.feature_columns import FEATURES
from ml.features import add_derived
from ml.models import xgb as v1m
from ml.models import xgb_v2 as v2m

DEFAULT_MODEL_DIR = BACKEND / "data" / "models" / "baseline_v2"
HORIZONS = (1, 3, 6, 12, 24)


@lru_cache(maxsize=32)
def _booster(path: str) -> xgb.Booster:
    if not Path(path).exists():
        raise FileNotFoundError(path)
    b = xgb.Booster()
    b.load_model(path)
    return b


@lru_cache(maxsize=8)
def load_release(model_dir: str) -> dict:
    return json.loads((Path(model_dir) / "release.json").read_text())


def predict(feature_frame: pd.DataFrame, horizon: int, model_dir: Path | str = DEFAULT_MODEL_DIR) -> pd.DataFrame:
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {HORIZONS}, got {horizon}")
    missing = [c for c in FEATURES if c != "horizon_hours" and c not in feature_frame.columns]  # set below
    if missing:
        raise ValueError(f"feature_frame is missing model features: {missing}")
    model_dir = str(model_dir)
    rule = load_release(model_dir)[str(horizon)]
    frame = add_derived(feature_frame.assign(horizon_hours=horizon))
    has_p = frame["persistence"].notna().to_numpy()

    pm25 = np.full(len(frame), np.nan)
    source = np.where(has_p, rule["serve"], "fallback").astype(object)
    if has_p.any():
        if rule["serve"] == "v2":
            pm25[has_p] = v2m.predict(_booster(f"{model_dir}/model_h{horizon}.json"), frame[has_p])
        else:
            pm25[has_p] = frame.loc[has_p, "persistence"].to_numpy(float)
    if (~has_p).any():
        pm25[~has_p] = v1m.predict(_booster(f"{model_dir}/fallback_h{horizon}.json"), frame[~has_p])
    return pd.DataFrame({"pm25": pm25, "exceeds": pm25 >= float(rule["threshold"]), "source": source},
                        index=feature_frame.index)
