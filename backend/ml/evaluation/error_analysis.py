
"""ML-03: Error analysis for SmokeSense PM2.5 forecasts.

Analyze existing predictions without retraining models.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.evaluation.metrics import UNHEALTHY_SG, scores


def summarize_groups(
    frame: pd.DataFrame,
    group_col: str,
    pred_col: str = "v2",
) -> pd.DataFrame:
    """Calculate prediction error metrics for each group."""

    required = {group_col, pred_col, "target_pm25"}
    missing = required - set(frame.columns)

    if missing:
        raise ValueError(
            f"Missing columns: {sorted(missing)}"
        )

    results = []

    for group, subset in frame.groupby(
        group_col,
        dropna=False,
        sort=True,
        observed=True,
    ):
        valid = subset.loc[
            subset[pred_col].notna()
            & subset["target_pm25"].notna()
        ]

        if valid.empty:
            continue

        y = valid["target_pm25"].to_numpy(dtype=float)
        p = valid[pred_col].to_numpy(dtype=float)

        metric = scores(y, p)

        error = p - y
        positive = y >= UNHEALTHY_SG

        results.append({
            "group": group,
            "n": int(len(valid)),
            "n_exceedance": int(positive.sum()),
            "prevalence": float(positive.mean()),
            "mae": metric["mae"],
            "rmse": metric["rmse"],
            "bias": float(np.mean(error)),
            "precision": metric["precision_35_5"],
            "recall": metric["recall_35_5"],
            "f1": metric["f1_35_5"],
        })

    return pd.DataFrame(results)


def analyze_ml02(
    path: str = (
        "data/models/ml02_method_a_pe001/"
        "matched_predictions.parquet"
    ),
) -> pd.DataFrame:
    """Compare ML-02 Method A and Method B across horizons."""

    df = pd.read_parquet(path)

    results = []

    for method, column in [
        ("Method A", "method_a_prediction"),
        ("Method B", "method_b_prediction"),
    ]:
        summary = summarize_groups(
            df,
            group_col="horizon_hours",
            pred_col=column,
        )

        summary.insert(0, "method", method)
        results.append(summary)

    return pd.concat(results, ignore_index=True)


def load_ml02_analysis_data(
    prediction_path: str = (
        "data/models/ml02_method_a_pe001/"
        "matched_predictions.parquet"
    ),
    dataset_path: str = (
        "data/datasets/smokesense_v1.1/data.parquet"
    ),
) -> pd.DataFrame:
    """Join ML-02 predictions with historical feature data."""

    predictions = pd.read_parquet(prediction_path)
    dataset = pd.read_parquet(dataset_path)

    key = [
        "forecast_point_id",
        "issue_time",
        "horizon_hours",
    ]

    features = [
        "nearest_fire_dist_km",
        "wind_alignment",
        "local_solar_hour",
        "pilot_event_id",
        "group_id",
    ]

    for frame in (predictions, dataset):
        frame["issue_time"] = pd.to_datetime(
            frame["issue_time"], utc=True
        )

        if frame.duplicated(key).any():
            raise ValueError(
                "Duplicate forecast keys detected"
            )

    result = predictions.merge(
        dataset[key + features],
        on=key,
        how="left",
        validate="one_to_one",
        indicator=True,
    )

    if not (result["_merge"] == "both").all():
        raise ValueError(
            "Unmatched ML-02 prediction rows"
        )

    return result.drop(columns="_merge")


def add_analysis_groups(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Create fire-distance, wind, and time-of-day categories."""

    df = frame.copy()

    # The dataset uses 9999 km as a no-nearby-fire
    # sentinel, so treat distances above 200 km
    # as a separate category.
    distance = df["nearest_fire_dist_km"].where(
        df["nearest_fire_dist_km"] <= 200
    )

    df["distance_group"] = pd.cut(
        distance,
        bins=[
            -float("inf"),
            25,
            50,
            100,
            200,
        ],
        labels=[
            "0-25",
            "25-50",
            "50-100",
            "100-200",
        ],
    ).astype("object").fillna("No nearby fire")

    # Wind alignment:
    # +1 = fire directly upwind of location
    # -1 = fire directly downwind of location
    df["wind_group"] = pd.cut(
        df["wind_alignment"],
        bins=[-1.01, -0.5, 0.5, 1.01],
        labels=[
            "Downwind",
            "Crosswind",
            "Upwind",
        ],
    ).astype("object").fillna("Missing")

    # Use the local solar hour at forecast issue time.
    df["time_group"] = pd.cut(
        df["local_solar_hour"] % 24,
        bins=[0, 6, 12, 18, 24],
        labels=[
            "00-06",
            "06-12",
            "12-18",
            "18-24",
        ],
        right=False,
        include_lowest=True,
    )

    return df
