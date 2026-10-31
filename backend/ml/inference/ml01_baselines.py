
"""SmokeSense ML-01 experimental baseline inference."""

from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


HORIZONS = (1, 3, 6, 12, 24)

RAW_FEATURES = [
    "pm25_lag_1h",
    "pm25_lag_3h",
    "pm25_lag_6h",
    "pm25_lag_12h",
    "pm25_lag_24h",
    "temp_c",
    "rh_pct",
    "wind_speed_ms",
]

ENGINEERED_FEATURES = [
    "pm25_change_1_3",
    "pm25_change_3_6",
    "pm25_short_avg",
]

MODEL_FEATURES = RAW_FEATURES + ENGINEERED_FEATURES

# backend/ml/inference/ml01_baselines.py
# parents[2] points to backend/
DEFAULT_ARTIFACT_DIR = (
    Path(__file__).resolve().parents[2]
    / "data" / "models" / "ml01_baselines"
)


def validate_input(frame, horizon):
    """Validate raw input columns and forecast horizon."""
    if horizon not in HORIZONS:
        raise ValueError(f"Unsupported horizon: {horizon}")

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame")

    if frame.empty:
        raise ValueError("Input DataFrame is empty")

    missing = [
        feature for feature in RAW_FEATURES
        if feature not in frame.columns
    ]

    if missing:
        raise ValueError(f"Missing features: {missing}")

    # Ensure the model receives numeric or missing values.
    for feature in RAW_FEATURES:
        if not pd.api.types.is_numeric_dtype(frame[feature]):
            raise TypeError(f"Non-numeric feature: {feature}")


def add_engineered_features(frame):
    """Reproduce the feature engineering used in ML-01."""
    result = frame.copy()

    result["pm25_change_1_3"] = (
        result["pm25_lag_1h"] - result["pm25_lag_3h"]
    )

    result["pm25_change_3_6"] = (
        result["pm25_lag_3h"] - result["pm25_lag_6h"]
    )

    result["pm25_short_avg"] = result[
        ["pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h"]
    ].mean(axis=1)

    return result


@lru_cache(maxsize=10)
def load_model(horizon, artifact_dir=None):
    """Load a trusted, previously trained ML-01 artifact."""
    if horizon not in HORIZONS:
        raise ValueError(f"Unsupported horizon: {horizon}")

    root = (
        Path(artifact_dir)
        if artifact_dir is not None
        else DEFAULT_ARTIFACT_DIR
    )

    model_path = (
        root / "models" / f"decision_tree_{horizon}h.joblib"
    )

    if not model_path.is_file():
        raise FileNotFoundError(
            f"Model artifact not found: {model_path}"
        )

    # Never load untrusted Joblib files.
    return joblib.load(model_path)


def predict(frame, horizon, model_type="tree", artifact_dir=None):
    """
    Predict PM2.5 concentration in micrograms per cubic meter.

    Returns a numpy array with one prediction per input row.
    """
    validate_input(frame, horizon)

    if model_type == "persistence":
        # This matches the notebook's experimental definition.
        values = frame["pm25_lag_1h"].to_numpy(dtype=float)

        if not np.isfinite(values).all():
            raise ValueError(
                "Persistence requires a valid pm25_lag_1h"
            )

        return np.maximum(values, 0)

    if model_type == "tree":
        processed = add_engineered_features(frame)

        model = load_model(
            horizon,
            str(Path(artifact_dir).resolve())
            if artifact_dir is not None else None,
        )

        predictions = np.asarray(
            model.predict(processed[MODEL_FEATURES]),
            dtype=float,
        )

        if not np.isfinite(predictions).all():
            raise ValueError("Model returned invalid predictions")

        return np.maximum(predictions, 0)

    raise ValueError(f"Unknown model type: {model_type}")
