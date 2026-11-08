"""ML-02 Method A pilot: forecast at monitors, then interpolate predictions.

Run from backend/ after copying into ml/training/train_method_a.py:
    python -m ml.training.train_method_a

Reproduces the chronological split from train_grid_native.py using the
IDW-LOO dataset as the reference timeline. Fits monitor-local history models
on the own-history dataset, then interpolates out-of-sample neighbor forecasts
at target monitor sites. Reports matched Method A vs Method B metrics.

WARNING: This PE-001 pilot has only two monitors. It is not a spatial
holdout, a full grid experiment, or evidence of cross-event generalization.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error

from features.pm25_idw import haversine_km, idw_average
from ml.feature_columns import FEATURES, TARGET
from ml.models.xgb import BASE_PARAMS, EARLY_STOPPING, N_ESTIMATORS

HORIZONS = (1, 3, 6, 12, 24)
KEY = ["forecast_point_id", "issue_time", "horizon_hours"]
POWER = 2.0
RADIUS_KM = 100.0
MAX_NEIGHBORS = 4


def matrix(df: pd.DataFrame) -> pd.DataFrame:
    x = df[FEATURES].copy()
    x["smoke_season"] = x["smoke_season"].astype("int8")
    return x.astype("float32")


def scores(frame: pd.DataFrame, column: str) -> dict:
    y = frame[TARGET].to_numpy(dtype=float)
    pred = frame[column].to_numpy(dtype=float)
    return {
        "mae": float(mean_absolute_error(y, pred)),
        "rmse": float(np.sqrt(mean_squared_error(y, pred))),
        "bias": float(np.mean(pred - y)),
    }


def require_unique(frame: pd.DataFrame, name: str) -> None:
    if frame.duplicated(KEY).any():
        raise ValueError(f"{name} has duplicate forecast keys")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--own", default="data/datasets/smokesense_v1/data.parquet")
    p.add_argument("--idw", default="data/datasets/smokesense_v1.1/data.parquet")
    p.add_argument("--method-b", default="data/models/ml02_grid_native_pe001/test_predictions.parquet")
    p.add_argument("--out", default="data/models/ml02_method_a_pe001")
    args = p.parse_args()

    own = pd.read_parquet(args.own)
    idw = pd.read_parquet(args.idw)
    method_b = pd.read_parquet(args.method_b)
    for name, frame in (("own", own), ("idw", idw), ("method B", method_b)):
        for col in ("issue_time", "target_time"):
            frame[col] = pd.to_datetime(frame[col], utc=True)
        require_unique(frame, name)

    required_own = set(FEATURES) | set(KEY) | {"target_time", TARGET, "location_lat", "location_lon"}
    required_b = set(KEY) | {"target_time", TARGET, "prediction_pm25"}
    if required_own - set(own) or required_own - set(idw):
        raise ValueError("Own/IDW dataset missing required columns")
    if required_b - set(method_b):
        raise ValueError("Method B prediction file missing required columns")

    # Check that source datasets have identical keys, labels and geometry.
    aligned = own[[*KEY, "target_time", TARGET, "location_lat", "location_lon"]].merge(
        idw[[*KEY, "target_time", TARGET, "location_lat", "location_lon"]],
        on=KEY, how="outer", indicator=True, suffixes=("_own", "_idw"), validate="one_to_one"
    )
    if not (aligned["_merge"] == "both").all():
        raise ValueError("Own and IDW datasets do not have identical forecast keys")
    for col in ("target_time", TARGET, "location_lat", "location_lon"):
        a, b = aligned[f"{col}_own"], aligned[f"{col}_idw"]
        equal = a.eq(b) if col == "target_time" else np.isclose(a.to_numpy(float), b.to_numpy(float), equal_nan=True)
        if not np.all(equal):
            raise ValueError(f"Own and IDW datasets disagree on {col}")

    # Use the EXACT Method B chronological cutoffs, determined from IDW data.
    times = np.sort(idw["issue_time"].unique())
    val_start = pd.Timestamp(times[int(len(times) * 0.70)])
    test_start = pd.Timestamp(times[int(len(times) * 0.85)])
    train = own[own["target_time"] < val_start]
    valid = own[(own["issue_time"] >= val_start) & (own["target_time"] < test_start)]
    test = own[own["issue_time"] >= test_start]

    # Check Method B test sample IDs and labels against this split.
    expected = idw[idw["issue_time"] >= test_start][[*KEY, "target_time", TARGET]]
    joined = method_b.merge(expected, on=KEY, how="outer", indicator=True, suffixes=("_b", "_idw"), validate="one_to_one")
    if not (joined["_merge"] == "both").all() or not (joined["target_time_b"] == joined["target_time_idw"]).all() or not np.allclose(joined[f"{TARGET}_b"], joined[f"{TARGET}_idw"]):
        raise ValueError("Method B predictions do not match the expected chronological test split")

    # Two coordinates per monitor are expected to remain fixed in this pilot.
    sites = own[["forecast_point_id", "location_lat", "location_lon"]].drop_duplicates()
    if sites["forecast_point_id"].duplicated().any():
        raise ValueError("Forecast point coordinates vary over time; revise spatial lookup")
    sites = sites.set_index("forecast_point_id")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    monitor_predictions = []
    training_details = {}
    for h in HORIZONS:
        tr = train[train["horizon_hours"] == h]
        va = valid[valid["horizon_hours"] == h]
        te = test[test["horizon_hours"] == h]
        if min(len(tr), len(va), len(te)) == 0:
            raise ValueError(f"Empty train/validation/test split at horizon {h}")
        booster = xgb.train(
            {**BASE_PARAMS, "max_depth": 4, "nthread": 4},
            xgb.DMatrix(matrix(tr), label=np.log1p(tr[TARGET].to_numpy(float))),
            num_boost_round=N_ESTIMATORS,
            evals=[(xgb.DMatrix(matrix(va), label=np.log1p(va[TARGET].to_numpy(float))), "validation")],
            early_stopping_rounds=EARLY_STOPPING,
            verbose_eval=False,
        )
        pred = np.clip(np.expm1(booster.predict(xgb.DMatrix(matrix(te)), iteration_range=(0, booster.best_iteration + 1))), 0, None)
        scored = te[[*KEY, "target_time", TARGET]].copy()
        scored["monitor_prediction"] = pred
        monitor_predictions.append(scored)
        booster.save_model(out / f"model_h{h}.json")
        training_details[str(h)] = {"n_train": len(tr), "n_validation": len(va), "n_test": len(te), "best_iteration": int(booster.best_iteration)}

    monitor_preds = pd.concat(monitor_predictions, ignore_index=True)
    monitor_preds.to_parquet(out / "monitor_test_predictions.parquet", index=False)

    # Each candidate neighbor MUST be forecast at the SAME issue time and horizon,
    # and MUST NOT be the target monitor. We never interpolate realized test labels.
    targets = idw[idw["issue_time"] >= test_start][[*KEY, "target_time", TARGET]].copy()
    by_time_h = {(ts, h): g for (ts, h), g in monitor_preds.groupby(["issue_time", "horizon_hours"], sort=False)}
    rows = []
    for point in targets.itertuples(index=False):
        candidates = by_time_h.get((point.issue_time, point.horizon_hours))
        neighbors = []
        if candidates is not None:
            tlat, tlon = sites.loc[point.forecast_point_id, ["location_lat", "location_lon"]]
            candidates = candidates[candidates["forecast_point_id"] != point.forecast_point_id]
            for cand in candidates.itertuples(index=False):
                slat, slon = sites.loc[cand.forecast_point_id, ["location_lat", "location_lon"]]
                dist = float(haversine_km(tlat, tlon, slat, slon))
                if np.isfinite(dist) and dist <= RADIUS_KM:
                    neighbors.append((dist, cand.forecast_point_id, float(cand.monitor_prediction)))
        neighbors.sort(key=lambda z: (z[0], z[1]))
        neighbors = neighbors[:MAX_NEIGHBORS]
        if neighbors:
            colocated = [v for d, _, v in neighbors if d == 0]
            estimated = float(np.mean(colocated)) if colocated else idw_average(
                [v for d, _, v in neighbors], [d for d, _, _ in neighbors], power=POWER
            )
        else:
            estimated = np.nan
        rows.append({
            "forecast_point_id": point.forecast_point_id,
            "issue_time": point.issue_time,
            "target_time": point.target_time,
            "horizon_hours": point.horizon_hours,
            TARGET: point.target_pm25,
            "method_a_prediction": estimated,
            "n_neighbors": len(neighbors),
        })

    pred_a = pd.DataFrame(rows)
    pred_a.to_parquet(out / "method_a_predictions.parquet", index=False)
    matched = pred_a.merge(
        method_b[[*KEY, "prediction_pm25"]].rename(columns={"prediction_pm25": "method_b_prediction"}),
        on=KEY, how="inner", validate="one_to_one"
    )
    if len(matched) != len(targets):
        raise ValueError("Method B missing some target rows")
    matched = matched.dropna(subset=["method_a_prediction", "method_b_prediction"])
    matched.to_parquet(out / "matched_predictions.parquet", index=False)
    metrics = {}
    for h in HORIZONS:
        m = matched[matched["horizon_hours"] == h]
        all_n = int((targets["horizon_hours"] == h).sum())
        if m.empty:
            metrics[str(h)] = {"n_matched": 0, "n_test_total": all_n}
            print(f"h{h}: no matched neighbor predictions")
            continue
        ma = scores(m, "method_a_prediction")
        mb = scores(m, "method_b_prediction")
        metrics[str(h)] = {"n_matched": int(len(m)), "n_test_total": all_n, "coverage_pct": float(100 * len(m) / all_n), "method_a": ma, "method_b": mb, "mae_improvement_b_pct": float(100 * (ma["mae"] - mb["mae"]) / ma["mae"]) if ma["mae"] > 0 else None}
        print(f"h{h}: n={len(m)}/{all_n}; A MAE={ma['mae']:.3f}; B MAE={mb['mae']:.3f}; B improvement={metrics[str(h)]['mae_improvement_b_pct']:.1f}%", flush=True)

    metadata = {
        "experiment": "Method A (monitor XGB -> IDW) vs Method B (IDW lag -> grid XGB), PE-001 pilot",
        "limitations": ["Only two monitors", "No spatial holdout", "No cross-event test", "Method A coverage limited by availability of own-history labeled monitor forecast rows"],
        "input_own": args.own, "input_idw": args.idw, "input_method_b": args.method_b,
        "split_validation_issue_start": val_start.isoformat(), "split_test_issue_start": test_start.isoformat(),
        "idw_power": POWER, "idw_radius_km": RADIUS_KM, "idw_k": MAX_NEIGHBORS,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "train_details": training_details,
        "metrics": metrics,
    }
    (out / "metrics.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Saved Method A outputs and matched comparison to {out}")


if __name__ == "__main__":
    main()
