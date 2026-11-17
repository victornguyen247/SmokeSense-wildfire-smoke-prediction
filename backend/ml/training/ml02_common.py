"""Shared feature preparation and chronological splitting for ML-02."""

import numpy as np
import pandas as pd

from ml.feature_columns import FEATURES


def matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Prepare the feature matrix for XGBoost."""
    x = frame[FEATURES].copy()
    x["smoke_season"] = x["smoke_season"].astype("int8")
    return x.astype("float32")


def chronological_boundaries(
    frame: pd.DataFrame,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Calculate the 70%/85% chronological evaluation boundaries."""
    times = np.sort(frame["issue_time"].unique())

    if len(times) < 100:
        raise ValueError(
            "Not enough distinct issue times for chronological evaluation"
        )

    val_start = pd.Timestamp(times[int(len(times) * 0.70)])
    test_start = pd.Timestamp(times[int(len(times) * 0.85)])

    return val_start, test_start