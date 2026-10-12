"""Load a baseline v1 model and predict PM2.5 (µg/m³) for one horizon.

    from ml.inference.predict import predict
    pm25 = predict(feature_frame, horizon=6)                    # default: data/models/baseline_v1
    pm25 = predict(feature_frame, horizon=6, model_dir=path)

feature_frame must hold every column in ml.feature_columns.FEATURES (extra columns are
ignored); live inference has to supply them the same way the dataset does (see
docs/models/baseline_v1.md, "What live inference must supply").
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from ml.datasets.load import BACKEND
from ml.feature_columns import FEATURES
from ml.models import xgb as xgbm

DEFAULT_MODEL_DIR = BACKEND / "data" / "models" / "baseline_v1"
HORIZONS = (1, 3, 6, 12, 24)


@lru_cache(maxsize=16)
def load_model(model_dir: str, horizon: int) -> xgb.Booster:
    path = Path(model_dir) / f"model_h{horizon}.json"
    if not path.exists():
        raise FileNotFoundError(f"no model for horizon {horizon} h in {model_dir}")
    booster = xgb.Booster()
    booster.load_model(path)
    if booster.feature_names and list(booster.feature_names) != FEATURES:
        raise ValueError(f"{path} was trained on {booster.feature_names}, expected {FEATURES}")
    return booster


def predict(feature_frame: pd.DataFrame, horizon: int, model_dir: Path | str = DEFAULT_MODEL_DIR) -> np.ndarray:
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {HORIZONS}, got {horizon}")
    missing = [c for c in FEATURES if c not in feature_frame.columns]
    if missing:
        raise ValueError(f"feature_frame is missing model features: {missing}")
    frame = feature_frame.assign(horizon_hours=horizon)
    return xgbm.predict(load_model(str(model_dir), horizon), frame)
