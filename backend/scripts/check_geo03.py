"""Read-only GEO-03 checks: real Parquet parity or synthetic compute timing.

Run from backend; see docs/geo03.md for commands and prerequisites.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from dataset_build.build_v1 import CONFIG  # noqa: E402
from features.alignment import ALLOWED_HORIZONS, build_input_features  # noqa: E402
from features.idw import interpolate_to_grid  # noqa: E402
from ingestion.batch.batch_ingest import load_pilot_events  # noqa: E402
from serving.geo import (  # noqa: E402
    INPUT_COLUMNS,
    build_monitor_features,
    interpolate_to_grid as interpolate_seeded_grid,
    load_monitor_points,
)


def parity(dataset: Path, samples: int) -> None:
    """Check sampled event/hours at all matching seeded v1 monitor points."""
    expected = pd.read_parquet(dataset, columns=[
        "forecast_point_id", "issue_time", "pilot_event_id", *INPUT_COLUMNS,
    ]).drop_duplicates(["pilot_event_id", "forecast_point_id", "issue_time"])
    events = {e.event_id: e for e in load_pilot_events(CONFIG)}
    groups = expected[["pilot_event_id", "issue_time"]].drop_duplicates().sort_values(
        ["pilot_event_id", "issue_time"])
    # Spread checks over the artifact instead of only the first event's hours.
    positions = np.linspace(0, len(groups) - 1, min(samples, len(groups)), dtype=int)
    groups = groups.iloc[positions]
    engine = create_engine(settings.database_url)
    checked = 0
    with engine.connect() as connection:
        identities = load_monitor_points(connection)[["forecast_point_id", "external_id"]]
        for group in groups.itertuples(index=False):
            actual = build_monitor_features(
                group.issue_time, connection=connection, fire_feed_available=True,
                row_scope="historical", event=events[group.pilot_event_id],
            ).merge(identities, on="forecast_point_id", validate="one_to_one")
            actual = actual.set_index("external_id")
            wanted = expected.loc[(expected.pilot_event_id == group.pilot_event_id)
                                  & (expected.issue_time == group.issue_time)].set_index("forecast_point_id")
            if not wanted.index.isin(actual.index).all():
                raise AssertionError("Parquet points missing from active seeded monitor features")
            for column in INPUT_COLUMNS:
                np.testing.assert_allclose(
                    actual.loc[wanted.index, column].to_numpy(dtype=float),
                    wanted[column].to_numpy(dtype=float), rtol=1e-6, atol=1e-6, equal_nan=True,
                    err_msg=f"{group.pilot_event_id} {group.issue_time} {column}",
                )
            checked += len(wanted)
    engine.dispose()
    if checked == 0:
        raise AssertionError("No Parquet rows checked")
    print(json.dumps({"parity_rows": checked, "event_hours": len(groups)}))


def benchmark() -> None:
    """Deterministic California-sized compute check, without DB/model I/O."""
    rng = np.random.default_rng(42)
    h = pd.Timestamp("2026-10-23T18:00Z")
    points = pd.DataFrame({"forecast_point_id": [f"m{i}" for i in range(129)],
                           "location_lat": rng.uniform(32.6, 42, 129),
                           "location_lon": rng.uniform(-124.4, -114.2, 129)})
    grid = pd.DataFrame({"forecast_point_id": [f"g{i}" for i in range(3000)],
                         "location_lat": rng.uniform(32.6, 42, 3000),
                         "location_lon": rng.uniform(-124.4, -114.2, 3000)})
    history = pd.DataFrame({"forecast_point_id": np.repeat(points.forecast_point_id, 24),
                            "issue_time": np.tile(pd.date_range(h - pd.Timedelta(hours=24), periods=24,
                                                                freq="h"), 129),
                            "pm25": rng.uniform(0, 100, 129 * 24)})
    fires = pd.DataFrame({"detected_at": h - pd.to_timedelta(rng.uniform(0, 72, 179), unit="h"),
                          "latitude": rng.uniform(32, 43, 179), "longitude": rng.uniform(-126, -112, 179),
                          "frp_mw": rng.uniform(1, 100, 179)})
    weather = pd.DataFrame({"station_id": np.repeat([f"K{i}" for i in range(107)], 72),
                            "valid_at": np.tile(pd.date_range(h - pd.Timedelta(hours=72), periods=72,
                                                              freq="h"), 107),
                            "latitude": np.repeat(rng.uniform(32.6, 42, 107), 72),
                            "longitude": np.repeat(rng.uniform(-124.4, -114.2, 107), 72),
                            "wind_speed_ms": 2., "wind_dir_deg": 270., "temp_c": 20., "rh_pct": 30.,
                            "pressure_hpa": np.nan, "precip_1h_mm": np.nan})
    started = perf_counter()
    features = build_input_features(points, pd.Series([h]), fires, history, weather, horizons=(1,))
    feature_seconds = perf_counter() - started
    predictions = pd.concat([pd.DataFrame({
        "forecast_point_id": points.forecast_point_id, "issued_at": h, "horizon_hours": horizon,
        "pm25_predicted": rng.uniform(0, 100, len(points)), "source": "v2", "model_key": "benchmark/1",
    }) for horizon in ALLOWED_HORIZONS], ignore_index=True)
    started = perf_counter()
    result = interpolate_to_grid(predictions, points, grid)
    idw_seconds = perf_counter() - started
    print(json.dumps({"synthetic": True, "monitors": len(features), "grid_cells": len(grid),
                      "horizons": len(ALLOWED_HORIZONS), "output_rows": len(result),
                      "feature_seconds": feature_seconds, "idw_seconds": idw_seconds,
                      "total_compute_seconds": feature_seconds + idw_seconds}, indent=2))


def benchmark_live(issued_at: str, model_key: str) -> None:
    """Measure the real seeded pipeline, including DB and cold model loading.

    Only predictions in memory and the registry's verified local cache are
    produced. No forecast writes, promotion, ingestion or retention jobs run.
    The CLI caller must independently confirm live feed/window availability.
    """
    try:
        from ml.inference.service import InferenceService
    except ModuleNotFoundError as exc:
        if exc.name != "ml.inference.service":
            raise
        raise RuntimeError("benchmark-live requires the ML-04 adapter from PR #92") from exc
    from mlops.registry import build_registry

    started = perf_counter()
    service = InferenceService.from_registry(build_registry(), model_key=model_key)
    model_seconds = perf_counter() - started
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            stage = perf_counter()
            features = build_monitor_features(
                issued_at, connection=connection, fire_feed_available=True,
            )
            if features.empty:
                raise RuntimeError("No eligible live monitor rows to benchmark")
            feature_seconds = perf_counter() - stage
            stage = perf_counter()
            monitor_forecasts = service.predict(features)
            inference_seconds = perf_counter() - stage
            stage = perf_counter()
            grid_forecasts = interpolate_seeded_grid(monitor_forecasts, connection=connection)
            interpolation_seconds = perf_counter() - stage
            if grid_forecasts.empty:
                raise RuntimeError("No covered grid forecasts to benchmark")
    finally:
        engine.dispose()
    total = perf_counter() - started
    print(json.dumps({
        "synthetic": False, "model_key": service.model_key, "monitors": len(features),
        "monitor_forecasts": len(monitor_forecasts), "grid_forecasts": len(grid_forecasts),
        "model_load_seconds": model_seconds, "feature_seconds": feature_seconds,
        "inference_seconds": inference_seconds, "interpolation_seconds": interpolation_seconds,
        "total_seconds": total, "under_two_minutes": total < 120,
    }, indent=2))
    if total >= 120:
        raise AssertionError("GEO-03 pipeline exceeded the two-minute runtime criterion")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("parity")
    check.add_argument("--dataset", type=Path, required=True)
    check.add_argument("--samples", type=int, default=5)
    commands.add_parser("benchmark")
    live = commands.add_parser("benchmark-live")
    live.add_argument("--issued-at", required=True, help="Top of a UTC hour in the retained live window")
    live.add_argument("--model-key", required=True, help="Explicit registry model key, e.g. baseline/v2")
    live.add_argument("--fire-feed-available", action="store_true", required=True,
                      help="Confirm a healthy fire feed with its full required lookback available")
    args = parser.parse_args()
    if args.command == "parity":
        if args.samples < 1:
            parser.error("--samples must be positive")
        parity(args.dataset, args.samples)
    elif args.command == "benchmark-live":
        benchmark_live(args.issued_at, args.model_key)
    else:
        benchmark()


if __name__ == "__main__":
    main()
