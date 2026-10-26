"""ml.evaluation.weather_missingness_check: the masking helper and the unmasked baseline path."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.evaluation import weather_missingness_check as wmc
from ml.feature_columns import FEATURES, TARGET
from ml.features import add_derived
from ml.models import xgb_v2 as v2m
from ml.training import train_baseline_v2 as train_v2

COLS = ["precip_1h_mm", "pressure_hpa"]


def weather_frame(
    n: int = 20_000, missing: float = 0.587, seed: int = 7
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {
            "precip_1h_mm": rng.gamma(1.0, 1.0, n),
            "pressure_hpa": rng.normal(1010, 5, n),
            "temp_c": rng.normal(25, 5, n),
        }
    )
    frame.loc[rng.random(n) < missing, "precip_1h_mm"] = np.nan
    frame.loc[rng.random(n) < 0.539, "pressure_hpa"] = np.nan
    return frame


def test_masking_is_seeded_and_deterministic():
    frame = weather_frame()
    a = wmc.mask_to_rates(frame, {"precip_1h_mm": 0.87, "pressure_hpa": 0.60}, seed=3)
    b = wmc.mask_to_rates(frame, {"precip_1h_mm": 0.87, "pressure_hpa": 0.60}, seed=3)
    c = wmc.mask_to_rates(frame, {"precip_1h_mm": 0.87, "pressure_hpa": 0.60}, seed=4)
    pd.testing.assert_frame_equal(a, b)
    assert not a["precip_1h_mm"].isna().equals(c["precip_1h_mm"].isna())


def test_only_present_values_are_masked_and_values_are_never_changed():
    frame = weather_frame()
    out = wmc.mask_present(frame, "precip_1h_mm", 0.5, seed=1)
    was_missing = frame["precip_1h_mm"].isna()
    assert out.loc[was_missing, "precip_1h_mm"].isna().all()
    kept = out["precip_1h_mm"].notna()
    assert (out.loc[kept, "precip_1h_mm"] == frame.loc[kept, "precip_1h_mm"]).all()
    newly = out["precip_1h_mm"].isna() & ~was_missing
    assert newly.sum() == round(0.5 * (~was_missing).sum())
    assert frame["precip_1h_mm"].isna().equals(was_missing)  # input left as it was


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_achieved_rate_is_within_half_a_point_of_target(seed):
    frame = weather_frame()
    targets = {"precip_1h_mm": 0.87, "pressure_hpa": 0.60}
    rates = wmc.missing_rates(wmc.mask_to_rates(frame, targets, seed), COLS)
    for column, target in targets.items():
        assert abs(rates[column] - target) <= 0.005


def test_other_columns_are_never_touched():
    frame = weather_frame()
    out = wmc.mask_to_rates(frame, {"precip_1h_mm": 0.95}, seed=0)
    pd.testing.assert_frame_equal(
        out[["pressure_hpa", "temp_c"]], frame[["pressure_hpa", "temp_c"]]
    )


def test_target_at_or_below_current_masks_nothing():
    frame = weather_frame()
    current = wmc.missing_rates(frame, COLS)
    assert wmc.extra_fraction(current["precip_1h_mm"], 0.30) == 0.0
    assert wmc.extra_fraction(1.0, 1.0) == 0.0
    out = wmc.mask_to_rates(
        frame, {"precip_1h_mm": 0.30, "pressure_hpa": current["pressure_hpa"]}, 0
    )
    pd.testing.assert_frame_equal(out, frame)


def test_extra_fraction_formula():
    assert wmc.extra_fraction(0.5, 0.75) == pytest.approx(0.5)
    assert wmc.extra_fraction(0.0, 0.2) == pytest.approx(0.2)


def tiny_dataset(seed: int = 0) -> pd.DataFrame:
    """Four groups x five horizons of random rows, shaped like smokesense_v1 for v2."""
    rng = np.random.default_rng(seed)
    n = 4 * 5 * 30
    frame = pd.DataFrame(
        {f: rng.normal(10, 3, n) for f in FEATURES if f != "horizon_hours"}
    )
    frame["smoke_season"] = rng.random(n) < 0.5
    frame["group_id"] = np.repeat([f"G{i}" for i in range(4)], 5 * 30)
    frame["horizon_hours"] = np.tile(np.repeat(train_v2.HORIZONS, 30), 4)
    frame.loc[rng.random(n) < 0.1, ["pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h"]] = (
        np.nan
    )
    frame.loc[rng.random(n) < 0.5, "precip_1h_mm"] = np.nan
    frame[TARGET] = np.abs(frame["pm25_lag_24h"] + rng.normal(0, 2, n))
    return add_derived(frame)


def test_unmasked_baseline_matches_the_training_cross_validation(monkeypatch):
    """No masking reproduces train_baseline_v2.cross_validate's out-of-fold v2 predictions."""
    df = tiny_dataset()
    setting = {"max_depth": 4, "weights": "none"}

    ours = wmc.oof_predictions(df, setting, {"baseline": df})

    monkeypatch.setattr(v2m, "GRID", [setting])
    oof = df[["group_id", "horizon_hours", TARGET, "persistence"]].copy()
    oof["v1"] = 0.0  # fallback rows; not compared
    train_v2.cross_validate(df, oof)
    theirs = oof.loc[ours.index, v2m.name(setting)]

    np.testing.assert_allclose(
        ours["baseline"].to_numpy(), theirs.to_numpy(), rtol=0, atol=1e-6
    )
    assert ours.index.equals(df.index[df["persistence"].notna()])
