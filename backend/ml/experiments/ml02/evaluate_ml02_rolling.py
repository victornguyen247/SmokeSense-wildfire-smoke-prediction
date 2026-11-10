"""ML-02 exploratory expanding-window PE-001 comparison (Method A vs B).

Run in backend/: python evaluate_ml02_rolling.py
Requires smokesense_v1 (own-history) and smokesense_v1.1 (IDW-LOO).

Pre-specified chronological test windows with an immediately preceding validation
week and a target-time purge before each boundary. Both methods use identical
XGBoost parameters and forecast horizons. Does NOT overwrite existing models.
These are exploratory within-event splits, NOT spatial or cross-event holdouts.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from features.pm25_idw import haversine_km, idw_average
from ml.feature_columns import FEATURES, TARGET
from ml.models.xgb import BASE_PARAMS, EARLY_STOPPING, N_ESTIMATORS

KEY = ["forecast_point_id", "issue_time", "horizon_hours"]
HORIZONS = (1, 3, 6, 12, 24)
# Exploratory test windows selected during analysis.
TEST_STARTS = ("2020-09-08", "2020-09-22", "2020-10-06", "2020-10-27")
VALID_DAYS = 7
TEST_DAYS = 7
RADIUS_KM = 100.0
POWER = 2.0
K = 4
PARAMS = {**BASE_PARAMS, "max_depth": 4, "nthread": 4}


def mat(df: pd.DataFrame) -> pd.DataFrame:
    x = df[FEATURES].copy()
    x["smoke_season"] = x["smoke_season"].astype("int8")
    return x.astype("float32")


def fit_predict(train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame):
    dtr = xgb.DMatrix(mat(train), label=np.log1p(train[TARGET].to_numpy(float)))
    dva = xgb.DMatrix(mat(valid), label=np.log1p(valid[TARGET].to_numpy(float)))
    model = xgb.train(PARAMS, dtr, num_boost_round=N_ESTIMATORS,
                      evals=[(dva, "validation")], early_stopping_rounds=EARLY_STOPPING,
                      verbose_eval=False)
    values = np.clip(np.expm1(model.predict(
        xgb.DMatrix(mat(test)), iteration_range=(0, model.best_iteration + 1))), 0, None)
    return values, int(model.best_iteration)


def load_pair(own_path, idw_path):
    own, idw = pd.read_parquet(own_path), pd.read_parquet(idw_path)
    for name, frame in (("own", own), ("idw", idw)):
        necessary = set(FEATURES) | set(KEY) | {"target_time", TARGET, "location_lat", "location_lon"}
        if necessary - set(frame):
            raise ValueError(f"{name} dataset lacks {sorted(necessary - set(frame))}")
        frame["issue_time"] = pd.to_datetime(frame["issue_time"], utc=True)
        frame["target_time"] = pd.to_datetime(frame["target_time"], utc=True)
        if frame.duplicated(KEY).any() or frame[TARGET].isna().any():
            raise ValueError(f"{name}: duplicate keys or missing target")
    cols = [*KEY, "target_time", TARGET, "location_lat", "location_lon"]
    cmp = own[cols].merge(idw[cols], on=KEY, how="outer", validate="one_to_one",
                          suffixes=("_own", "_idw"), indicator=True)
    if not cmp["_merge"].eq("both").all():
        raise ValueError("Own-history and IDW dataset forecast keys differ")
    for col in ("target_time", TARGET, "location_lat", "location_lon"):
        a, b = cmp[f"{col}_own"], cmp[f"{col}_idw"]
        eq = a.eq(b) if col == "target_time" else np.isclose(a.to_numpy(float), b.to_numpy(float), equal_nan=True)
        if not np.all(eq):
            raise ValueError(f"Own-history and IDW differ on {col}")
    coords = own[["forecast_point_id", "location_lat", "location_lon"]].drop_duplicates()
    if coords["forecast_point_id"].duplicated().any():
        raise ValueError("Forecast locations vary over time; adjust site lookup")
    sites = coords.set_index("forecast_point_id")
    return own, idw, sites


def partition(frame, validation_start, test_start, test_end):
    train = frame[frame["target_time"] < validation_start]
    valid = frame[(frame["issue_time"] >= validation_start) & (frame["target_time"] < test_start)]
    test = frame[(frame["issue_time"] >= test_start) & (frame["issue_time"] < test_end)]
    return train, valid, test


def method_a_interpolate(targets, monitor_pred, sites):
    lookup = {(ts, h): grp for (ts, h), grp in monitor_pred.groupby(["issue_time", "horizon_hours"], sort=False)}
    out = []
    for p in targets.itertuples(index=False):
        cands = lookup.get((p.issue_time, p.horizon_hours))
        near = []
        if cands is not None:
            lat, lon = sites.loc[p.forecast_point_id, ["location_lat", "location_lon"]]
            for c in cands.itertuples(index=False):
                if c.forecast_point_id == p.forecast_point_id:
                    continue
                slat, slon = sites.loc[c.forecast_point_id, ["location_lat", "location_lon"]]
                dist = float(haversine_km(lat, lon, slat, slon))
                if np.isfinite(dist) and dist <= RADIUS_KM:
                    near.append((dist, c.forecast_point_id, float(c.monitor_prediction)))
        near.sort(key=lambda v: (v[0], v[1]))
        near = near[:K]
        coloc = [v for d, _, v in near if d == 0]
        pred = (float(np.mean(coloc)) if coloc else
                idw_average([v for _, _, v in near], [d for d, _, _ in near], power=POWER) if near else np.nan)
        out.append((*[getattr(p, x) for x in KEY], pred, len(near)))
    return pd.DataFrame(out, columns=[*KEY, "method_a_prediction", "n_neighbors"])


def score(df, col):
    error = df[col].to_numpy(float) - df[TARGET].to_numpy(float)
    return {"mae": float(np.mean(np.abs(error))), "rmse": float(np.sqrt(np.mean(error**2))),
            "bias": float(np.mean(error))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--own", default="data/datasets/smokesense_v1/data.parquet")
    parser.add_argument("--idw", default="data/datasets/smokesense_v1.1/data.parquet")
    parser.add_argument("--out", default="data/models/ml02_rolling_pe001")
    args = parser.parse_args()
    own, idw, sites = load_pair(args.own, args.idw)
    out_dir = Path(args.out)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"Output directory already contains files: {out_dir}. Choose a new --out path.")
    out_dir.mkdir(parents=True, exist_ok=True)

    all_predictions = []
    report = []
    for fold_no, start in enumerate(TEST_STARTS, 1):
        ts = pd.Timestamp(start, tz="UTC")
        vs = ts - pd.Timedelta(days=VALID_DAYS)
        te = ts + pd.Timedelta(days=TEST_DAYS)
        own_tr, own_va, own_te = partition(own, vs, ts, te)
        idw_tr, idw_va, idw_te = partition(idw, vs, ts, te)
        for h in HORIZONS:
            a_tr = own_tr[own_tr.horizon_hours == h]
            a_va = own_va[own_va.horizon_hours == h]
            a_te = own_te[own_te.horizon_hours == h]
            b_tr = idw_tr[idw_tr.horizon_hours == h]
            b_va = idw_va[idw_va.horizon_hours == h]
            b_te = idw_te[idw_te.horizon_hours == h]
            if any(len(x) == 0 for x in (a_tr, a_va, a_te, b_tr, b_va, b_te)):
                raise ValueError(f"Empty split: fold={fold_no}, horizon={h}")
            pa, a_iter = fit_predict(a_tr, a_va, a_te)
            pb, b_iter = fit_predict(b_tr, b_va, b_te)
            monitor_pred = a_te[KEY].copy()
            monitor_pred["monitor_prediction"] = pa
            a = method_a_interpolate(b_te[KEY], monitor_pred, sites)
            b = b_te[[*KEY, TARGET, "target_time"]].copy()
            b["method_b_prediction"] = pb
            m = b.merge(a, on=KEY, how="left", validate="one_to_one")
            m["fold"] = fold_no
            m["test_start"] = start
            m = m.dropna(subset=["method_a_prediction", "method_b_prediction"])
            if m.empty:
                print(f"fold {fold_no} h{h}: no matched samples")
                continue
            all_predictions.append(m)
            sa, sb = score(m, "method_a_prediction"), score(m, "method_b_prediction")
            info = {"fold": fold_no, "test_start": start, "horizon": h, "n_matched": len(m),
                    "n_test": len(b_te), "n_train": len(b_tr), "n_validation": len(b_va),
                    "a_best_iteration": a_iter, "b_best_iteration": b_iter,
                    "a_mae": sa["mae"], "b_mae": sb["mae"], "a_rmse": sa["rmse"],
                    "b_rmse": sb["rmse"], "a_bias": sa["bias"], "b_bias": sb["bias"],
                    "exceedance_n": int((m[TARGET] >= 35.5).sum())}
            report.append(info)
            print(f"fold {fold_no} ({start}) h{h}: n={len(m)}/{len(b_te)} "
                  f"MAE A={sa['mae']:.3f} B={sb['mae']:.3f} "
                  f"exceedances={info['exceedance_n']}", flush=True)
    if not all_predictions:
        raise ValueError("No matched predictions across rolling folds")
    preds = pd.concat(all_predictions, ignore_index=True)
    preds.to_parquet(out_dir / "matched_predictions.parquet", index=False)
    pd.DataFrame(report).to_csv(out_dir / "fold_metrics.csv", index=False)
    summary = []
    for h, grp in preds.groupby("horizon_hours"):
        sa, sb = score(grp, "method_a_prediction"), score(grp, "method_b_prediction")
        summary.append({"horizon": int(h), "n": len(grp), "mae_a": sa["mae"],
                        "mae_b": sb["mae"], "mae_a_minus_b": sa["mae"]-sb["mae"],
                        "rmse_a": sa["rmse"], "rmse_b": sb["rmse"],
                        "bias_a": sa["bias"], "bias_b": sb["bias"],
                        "exceedance_n": int((grp[TARGET] >= 35.5).sum())})
    pooled = pd.DataFrame(summary).sort_values("horizon")
    pooled.to_csv(out_dir / "pooled_metrics.csv", index=False)
    print("\nPooled matched results:\n" + pooled.round(3).to_string(index=False), flush=True)
    metadata = {"experiment": "Exploratory expanding-window Method A vs B, PE-001",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "test_starts": TEST_STARTS, "valid_days": VALID_DAYS, "test_days": TEST_DAYS,
                "split_rule": "train target_time < validation_start; validation issue_time >= validation_start and target_time < test_start; test issue_time in [test_start, test_end)",
                "model_params": PARAMS, "early_stopping_rounds": EARLY_STOPPING,
                "idw": {"power": POWER, "radius_km": RADIUS_KM, "max_neighbors": K},
                "limitations": ["Only two monitoring locations", "Only PE-001", "No independent spatial holdout",
                                "Windows chosen after exploratory test inspection; results are exploratory", "No statistical uncertainty estimated"],
                "files": ["matched_predictions.parquet", "fold_metrics.csv", "pooled_metrics.csv"]}
    (out_dir / "experiment.json").write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    print(f"Saved to {out_dir}")


if __name__ == "__main__":
    main()
