
"""ML-03: Full cross-event environmental error analysis."""

from pathlib import Path

import pandas as pd

from ml.evaluation.error_analysis import (
    add_analysis_groups,
    summarize_groups,
    load_served_thresholds,
)

DATASET = Path("data/datasets/smokesense_v1/data.parquet")
PREDICTIONS = Path("data/models/baseline_v2/oof_predictions.parquet")
RELEASE = Path("data/models/baseline_v2/release.json")
OUTPUT = Path("data/release/ml03_analysis")

KEY = [
    "forecast_point_id",
    "issue_time",
    "horizon_hours",
]

FEATURES = [
    "nearest_fire_dist_km",
    "wind_alignment",
    "local_solar_hour",
]


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    predictions = pd.read_parquet(PREDICTIONS)
    dataset = pd.read_parquet(DATASET)
    served_thresholds = load_served_thresholds(RELEASE)

    # Normalize timestamps before joining.
    for frame in (predictions, dataset):
        frame["issue_time"] = pd.to_datetime(
            frame["issue_time"], utc=True
        )

        if frame.duplicated(KEY).any():
            raise ValueError("Duplicate prediction keys detected")

    # Join predictions to environmental features.
    merged = predictions.merge(
        dataset[KEY + FEATURES],
        on=KEY,
        how="left",
        validate="one_to_one",
        indicator=True,
    )

    if not (merged["_merge"] == "both").all():
        raise ValueError("Unmatched prediction rows")

    merged = merged.drop(columns="_merge")

    # Retain paired rows for fair comparison.
    merged = merged.dropna(
        subset=["target_pm25", "persistence", "v2"]
    )

    merged = add_analysis_groups(merged)

    # Primary analysis: six-hour forecasts.
    six_hour = merged.loc[
        merged["horizon_hours"] == 6
    ].copy()

    print("Six-hour rows:", len(six_hour))
    print(
        "Events:",
        six_hour["pilot_event_id"].nunique(),
    )

    for group_col in [
        "distance_group",
        "wind_group",
        "time_group",
        "pilot_event_id",
    ]:
        for model in ["persistence", "v2"]:
            result = summarize_groups(
                six_hour,
                group_col=group_col,
                pred_col=model,
                prediction_threshold=(
                    served_thresholds[6] if model == "v2" else 35.5
                ),
            )

            filename = f"{group_col}_{model}.csv"

            result.to_csv(
                OUTPUT / filename,
                index=False,
            )

            print(f"\n{group_col} / {model}")
            print(
                result[
                    [
                        "group",
                        "n",
                        "n_exceedance",
                        "mae",
                        "bias",
                        "recall",
                        "served_recall",
                        "f1",
                        "served_f1",
                    ]
                ].to_string(index=False)
            )

    print("\nAnalysis saved to:", OUTPUT)


if __name__ == "__main__":
    main()
