
"""Generate ML-03 cross-event poster figures."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path("data/release/ml03_analysis")
OUTPUT = Path("../docs/ml/figures")
OUTPUT.mkdir(parents=True, exist_ok=True)

MODELS = {
    "Persistence": "persistence",
    "Baseline v2": "v2",
}


def load(group):
    """Read model summaries for one grouping dimension."""
    return {
        label: pd.read_csv(ROOT / f"{group}_{column}.csv")
        for label, column in MODELS.items()
    }


def grouped_plot(group, order, metric, ylabel, filename):
    """Compare both methods on the same categories."""
    results = load(group)
    x = np.arange(len(order))
    width = 0.36

    fig, ax = plt.subplots(figsize=(10, 5.5))

    for offset, (name, df) in zip(
        [-width / 2, width / 2],
        results.items(),
    ):
        values = df.set_index("group").reindex(order)[metric]
        ax.bar(
            x + offset,
            values,
            width,
            label=name,
        )

    ax.set_xticks(x, order)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)

    if metric == "recall":
        ax.set_ylim(0, 1)

    fig.tight_layout()
    fig.savefig(OUTPUT / filename, dpi=220)
    plt.close(fig)
    print("Saved:", OUTPUT / filename)


def event_bias_plot():
    """Show signed six-hour error across wildfire events."""
    results = load("pilot_event_id")
    baseline = results["Baseline v2"].sort_values("group")
    persistence = results["Persistence"].set_index("group")

    events = baseline["group"].tolist()
    x = np.arange(len(events))
    width = 0.38

    fig, ax = plt.subplots(figsize=(13, 5.5))

    ax.bar(
        x - width / 2,
        persistence.loc[events, "bias"],
        width,
        label="Persistence",
    )
    ax.bar(
        x + width / 2,
        baseline["bias"],
        width,
        label="Baseline v2",
    )

    ax.axhline(0, linewidth=1)
    ax.set_xticks(x, events, rotation=60, ha="right")
    ax.set_ylabel("Mean prediction error (µg/m³)")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)

    fig.tight_layout()
    path = OUTPUT / "ml03_event_bias.png"
    fig.savefig(path, dpi=220)
    plt.close(fig)
    print("Saved:", path)


def main():
    grouped_plot(
        "distance_group",
        ["0-25", "25-50", "50-100",
         "100-200", "No nearby fire"],
        "recall",
        "Recall at 35.5 µg/m³",
        "ml03_distance_recall.png",
    )

    grouped_plot(
        "wind_group",
        ["Downwind", "Crosswind", "Upwind", "Missing"],
        "mae",
        "MAE (µg/m³)",
        "ml03_wind_mae.png",
    )

    grouped_plot(
        "time_group",
        ["00-06", "06-12", "12-18", "18-24"],
        "recall",
        "Recall at 35.5 µg/m³",
        "ml03_time_recall.png",
    )

    event_bias_plot()


if __name__ == "__main__":
    main()
