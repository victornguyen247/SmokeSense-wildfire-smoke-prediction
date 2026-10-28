"""ml/inference/service.py: the PM-03 model interface over predict_v2 (ML-04, #45)."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ml.datasets.load import BACKEND
from ml.feature_columns import FEATURES, FEATURES_V2
from ml.features import add_derived
from ml.inference import predict_v2
from ml.inference.service import (
    FORECAST_COLUMNS,
    HORIZONS,
    FeatureFrameError,
    InferenceService,
    ModelDirError,
)
from ml.models import xgb as v1m
from ml.models import xgb_v2 as v2m
from tests.test_ml_baseline_v2 import _frame as _train_frame

INPUTS = [c for c in FEATURES if c != "horizon_hours"]
ISSUED = pd.Timestamp("2026-10-13T18:00:00Z")
# The real count of Stage A monitor points is not seeded yet (no kind='monitor' rows in
# forecast_points); 129 is the planning figure.
CA_MONITOR_POINTS = 129
REAL_DIRS = [BACKEND / "data" / "models" / "packaged" / "baseline_v2",
             BACKEND / "data" / "models" / "baseline_v2"]  # fmt: skip
REAL_DIR = next((d for d in REAL_DIRS if (d / "release.json").is_file()), None)


def features(n: int = 12, seed: int = 1) -> pd.DataFrame:
    """A Stage A input frame: keys plus the 22 input columns, in features.json order."""
    f = _train_frame(-(-n // 4) * 4, seed)[INPUTS].head(n)  # its groups need n % 4 == 0
    keys = pd.DataFrame({"forecast_point_id": [f"fp-{i}" for i in range(n)],
                         "issued_at": ISSUED})  # fmt: skip
    return pd.concat([keys, f.reset_index(drop=True)], axis=1)


def write_model_dir(path, serve: dict[int, str]):
    """Tiny boosters for every horizon (one fit reused), features.json and release.json."""
    path.mkdir(parents=True, exist_ok=True)
    train = add_derived(_train_frame(400))
    residual, _, _ = v2m.fit(
        train[train["persistence"].notna()], {"max_depth": 3, "weights": "none"}
    )
    direct, _ = v1m.fit(train, {"max_depth": 3})
    for h in HORIZONS:
        residual.save_model(path / f"model_h{h}.json")
        direct.save_model(path / f"fallback_h{h}.json")
    (path / "features.json").write_text(json.dumps({"features": FEATURES_V2}))
    release = {str(h): {"serve": serve[h], "threshold": 35.5} for h in HORIZONS}
    (path / "release.json").write_text(json.dumps(release))
    return path


@pytest.fixture(scope="module")
def dirs(tmp_path_factory):
    root = tmp_path_factory.mktemp("models")
    v2 = write_model_dir(
        root / "v2", {h: "persistence" if h == 1 else "v2" for h in HORIZONS}
    )
    v1 = write_model_dir(root / "v1", {h: "persistence" for h in HORIZONS})
    return {"baseline/v2": v2, "baseline/v1": v1}


@pytest.fixture
def svc(dirs):
    return InferenceService.from_dir(dirs["baseline/v2"], "baseline/v2")


# --------------------------------------------------------------------------- input checks


def test_input_columns_come_from_features_json(svc):
    assert list(svc.input_columns) == INPUTS
    assert (
        json.loads((BACKEND.parent / "docs/ml/features.json").read_text())[
            "input_columns"
        ]
        == INPUTS
    )


def test_missing_columns_are_named(svc):
    with pytest.raises(
        FeatureFrameError, match=r"missing columns: \['temp_c', 'pm25_lag_6h'\]"
    ):
        svc.predict(features().drop(columns=["temp_c", "pm25_lag_6h"]))
    with pytest.raises(FeatureFrameError, match="forecast_point_id"):
        svc.predict(features().drop(columns=["forecast_point_id"]))


def test_misordered_columns_are_named(svc):
    cols = features().columns.tolist()
    i, j = cols.index("temp_c"), cols.index("rh_pct")
    cols[i], cols[j] = cols[j], cols[i]
    with pytest.raises(
        FeatureFrameError,
        match="rh_pct \\(expected temp_c\\).*temp_c \\(expected rh_pct\\)",
    ):
        svc.predict(features()[cols])


def test_extra_columns_are_dropped_with_a_warning(svc, caplog):
    f = features()
    f.insert(5, "location_lat", 38.5)
    f["persistence"] = (
        999.0  # derived columns are recomputed, never taken from the caller
    )
    with caplog.at_level(logging.WARNING, logger="ml.inference.service"):
        out = svc.predict(f)
    assert "location_lat" in caplog.text and "persistence" in caplog.text
    pd.testing.assert_frame_equal(out, svc.predict(features()))


def test_duplicate_columns_and_naive_issue_time_are_rejected(svc):
    f = features()
    with pytest.raises(FeatureFrameError, match="duplicate"):
        svc.predict(pd.concat([f, f[["temp_c"]]], axis=1))
    with pytest.raises(FeatureFrameError, match="timezone-aware"):
        svc.predict(f.assign(issued_at=ISSUED.tz_localize(None)))


# --------------------------------------------------------------------------- output


def test_output_schema_and_target_time(svc):
    f = features(7)
    out = svc.predict(f)
    assert list(out.columns) == FORECAST_COLUMNS
    assert len(out) == 7 * len(HORIZONS)
    assert sorted(out["horizon_hours"].unique()) == list(HORIZONS)
    per_point = out.groupby("forecast_point_id")["horizon_hours"].apply(sorted)
    assert per_point.tolist() == [list(HORIZONS)] * 7
    assert (out["issued_at"] == ISSUED).all() and str(out["issued_at"].dt.tz) == "UTC"
    assert (
        out["target_time"]
        == out["issued_at"] + pd.to_timedelta(out["horizon_hours"], unit="h")
    ).all()
    assert set(out["model_key"]) == {"baseline/v2"}
    assert set(out["source"]) <= {"v2", "persistence", "fallback"}
    assert (out["pm25_predicted"] >= 0).all()


def test_issued_at_is_converted_to_utc(svc):
    out = svc.predict(
        features(2).assign(issued_at=ISSUED.tz_convert("America/Los_Angeles"))
    )
    assert (out["issued_at"] == ISSUED).all() and str(out["issued_at"].dt.tz) == "UTC"


def test_negative_predictions_are_clipped_to_zero(svc, monkeypatch):
    def negative(frame, horizon, model_dir):
        return pd.DataFrame(
            {"pm25": -3.0, "exceeds": False, "source": "v2"}, index=frame.index
        )

    monkeypatch.setattr(predict_v2, "predict", negative)
    assert (svc.predict(features(3))["pm25_predicted"] == 0.0).all()


def test_nan_predictions_are_not_returned(svc, monkeypatch):
    real = predict_v2.predict

    def nan_at_6(frame, horizon, model_dir):
        out = real(frame, horizon, model_dir)
        return out.assign(pm25=np.nan) if horizon == 6 else out

    monkeypatch.setattr(predict_v2, "predict", nan_at_6)
    out = svc.predict(features(4))
    assert len(out) == 4 * 4 and 6 not in set(out["horizon_hours"])


def test_persistence_served_horizon_returns_the_lag(svc):
    f = features(6)
    f.loc[1, "pm25_lag_1h"] = np.nan  # persistence falls back to lag 3 h
    f.loc[2, ["pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h"]] = np.nan  # no persistence
    out = svc.predict(f).set_index(["horizon_hours", "forecast_point_id"])
    h1 = out.loc[1]
    want = f.set_index("forecast_point_id")["pm25_lag_1h"].fillna(
        f.set_index("forecast_point_id")["pm25_lag_3h"]
    )
    for fp in ("fp-0", "fp-1", "fp-3"):
        assert h1.loc[fp, "source"] == "persistence"
        assert h1.loc[fp, "pm25_predicted"] == pytest.approx(want[fp])
    assert h1.loc["fp-2", "source"] == "fallback"
    assert set(out.loc[6]["source"]) == {"v2", "fallback"}


def test_matches_predict_v2_horizon_by_horizon(svc):
    f = features(10)
    out = svc.predict(f)
    for h in HORIZONS:
        direct = predict_v2.predict(f[INPUTS], h, svc.model_dir)
        got = out[out["horizon_hours"] == h]
        assert np.allclose(got["pm25_predicted"], direct["pm25"].clip(lower=0))
        assert got["source"].tolist() == direct["source"].tolist()


# --------------------------------------------------------------------------- loading


class FakeRegistry:
    """The three mlops.registry.Registry methods the adapter uses."""

    def __init__(self, dirs: dict, production: str):
        self.dirs, self.production = dirs, production

    def get(self, model_key):
        return SimpleNamespace(model_key=model_key)

    def materialize(self, version):
        return self.dirs[version.model_key]

    def load_production(self, name):
        assert name == self.production.split("/")[0]
        return self.get(self.production), self.dirs[self.production]


def test_model_key_swap_changes_only_the_key(dirs):
    reg = FakeRegistry(dirs, production="baseline/v2")
    f = features(8)
    a = InferenceService.from_registry(reg, name="baseline").predict(f)
    b = InferenceService.from_registry(reg, model_key="baseline/v1").predict(f)
    assert set(a["model_key"]) == {"baseline/v2"} and set(b["model_key"]) == {
        "baseline/v1"
    }
    assert list(a.columns) == list(b.columns) == FORECAST_COLUMNS
    assert "v2" in set(a["source"]) and "v2" not in set(
        b["source"]
    )  # v1 serves persistence
    reg.production = "baseline/v1"  # a promote / rollback
    c = InferenceService.from_registry(reg, name="baseline").predict(f)
    pd.testing.assert_frame_equal(b, c)


def test_from_registry_needs_exactly_one_selector(dirs):
    reg = FakeRegistry(dirs, production="baseline/v2")
    for kwargs in ({}, {"name": "baseline", "model_key": "baseline/v2"}):
        with pytest.raises(ValueError, match="exactly one"):
            InferenceService.from_registry(reg, **kwargs)


def test_unservable_model_dirs_are_refused(tmp_path):
    bad = write_model_dir(
        tmp_path / "bad", {h: "v1" if h == 12 else "persistence" for h in HORIZONS}
    )
    with pytest.raises(ModelDirError, match="12 h serves 'v1'"):
        InferenceService.from_dir(bad, "baseline/bad")
    gone = write_model_dir(tmp_path / "gone", {h: "v2" for h in HORIZONS})
    (gone / "model_h3.json").unlink()
    with pytest.raises(ModelDirError, match="model_h3.json"):
        InferenceService.from_dir(gone, "baseline/gone")


def test_no_training_or_app_imports_at_inference():
    code = ("import sys, ml.inference.service as s; "
            "bad = [m for m in sys.modules if m.split('.')[0] in ('app', 'mlops', 'dataset_build') "
            "or m.startswith(('ml.training', 'ml.evaluation', 'ml.tools'))]; "
            "print(bad); sys.exit(1 if bad else 0)")  # fmt: skip
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


# --------------------------------------------------------------------------- real artifacts


@pytest.mark.skipif(REAL_DIR is None, reason="baseline_v2 artifacts not present")
def test_all_ca_monitor_points_predict_in_under_10s():
    f = features(CA_MONITOR_POINTS, seed=3)
    f[
        ["pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h", "pm25_lag_12h", "pm25_lag_24h"]
    ] *= 3
    predict_v2.load_release.cache_clear()
    predict_v2._booster.cache_clear()  # time a cold start: boosters load inside the window
    start = time.perf_counter()
    svc = InferenceService.from_dir(REAL_DIR, "baseline/v2")
    out = svc.predict(f)
    elapsed = time.perf_counter() - start
    assert len(out) == CA_MONITOR_POINTS * len(HORIZONS)
    assert elapsed < 10, f"{elapsed:.2f}s"
    served = json.loads((REAL_DIR / "release.json").read_text())
    for h in HORIZONS:
        assert set(out.loc[out["horizon_hours"] == h, "source"]) == {
            served[str(h)]["serve"]
        }
    print(f"{CA_MONITOR_POINTS} points x {len(HORIZONS)} horizons: {elapsed:.3f}s")
