
"""ML-03: Reproducible diagnostic figures."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from ml.evaluation.metrics import UNHEALTHY_SG


def plot_ml02_six_hour(
    input_path="data/models/ml02_method_a_pe001/matched_predictions.parquet",
    output_path="../docs/ml/figures/ml02_six_hour_predictions.png",
):
    """Plot actual and predicted PM2.5 at the six-hour horizon."""

    df = pd.read_parquet(input_path)
    df = df[df["horizon_hours"] == 6].copy()
    df["target_time"] = pd.to_datetime(df["target_time"], utc=True)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    monitors = sorted(df["forecast_point_id"].unique())

    fig, axes = plt.subplots(
        len(monitors),
        1,
        figsize=(12, 4 * len(monitors)),
        sharex=True,
        squeeze=False,
    )

    for ax, monitor in zip(axes.flat, monitors):
        subset = df[
            df["forecast_point_id"] == monitor
        ].sort_values("target_time")

        ax.plot(
            subset["target_time"],
            subset["target_pm25"],
            label="Actual PM2.5",
            linewidth=1.8,
        )
        ax.plot(
            subset["target_time"],
            subset["method_a_prediction"],
            label="Method A",
            linewidth=1.2,
        )
        ax.plot(
            subset["target_time"],
            subset["method_b_prediction"],
            label="Method B",
            linewidth=1.2,
        )

        ax.axhline(
            UNHEALTHY_SG,
            color="red",
            linestyle="--",
            label="35.5 threshold",
        )

        ax.set_title(f"Monitor: {monitor}")
        ax.set_ylabel("PM2.5 (µg/m³)")
        ax.grid(alpha=0.25)
        ax.legend()

    axes[-1, 0].set_xlabel("Target time (UTC)")
    fig.suptitle(
        "SmokeSense ML-02: Six-Hour PM2.5 Predictions",
        fontsize=15,
    )
    fig.tight_layout()
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved figure: {output}")


if __name__ == "__main__":
    plot_ml02_six_hour()
