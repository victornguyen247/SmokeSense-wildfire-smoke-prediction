# Model card: baseline_v2 (persistence-anchored)

| | |
|---|---|
| Models | Per horizon: an XGBoost residual model on top of persistence (max_depth 4, no group weights), plus the v1 direct model as the fallback when persistence is missing |
| Serving | `release.json`: **1 h serves persistence; 3, 6, 12 and 24 h serve v2** |
| Data | `smokesense_v1` 1.0.0 (`docs/datasets/smokesense_v1.md`), sha256 `6799c405…` checked on load |
| Code | `backend/ml/`: `features.py` (derived features), `models/xgb_v2.py`, `evaluation/release.py`, `training/train_baseline_v2.py`, `inference/predict_v2.py`. The v1 code is unchanged. |
| Train | `cd backend && python -m ml.training.train_baseline_v2` (about 1.5 min; reads `data/models/baseline_v1/oof_predictions.parquet`) |
| Artifacts | `backend/data/models/baseline_v2/`, not in git: `model_h*.json` (residual), `fallback_h*.json` (v1 direct), `release.json`, `thresholds.json`, `features.json`, `params.json`, `metrics.json`, `oof_predictions.parquet`, `manifest.json` |
| Reproduce | `backend/scripts/reproduce_data04.sh` |
| Rules | `docs/data-decisions.md` #28–#31 |
| Previous | [`baseline_v1.md`](baseline_v1.md) |

## What changed from v1, and why

v1 lost to persistence on pooled data. When the 2020 group was held out, the direct log1p model under-predicted severe smoke (bias −188 µg/m³ on labels ≥ 125.5), because trees cannot extrapolate beyond their training range. v2 makes three changes:

1. **Anchor on persistence (#28).** On rows with persistence, the model predicts the residual `r = log1p(y) − log1p(persistence)`. The prediction is `clip(expm1(log1p(persistence) + r̂), 0)`. A plume that is already at 400 µg/m³ now starts from 400, not from what the trees have seen. Rows without persistence (2.1%) use the v1 direct model.
2. **Derived trend features (#29).** `persistence`, `trend_1_3 = lag1 − lag3`, `trend_1_6 = lag1 − lag6` and `ratio_1_24 = (lag1 + 1) / (lag24 + 1)` are added. They are computed in one function, `ml.features.add_derived`, which both training and inference call.
3. **A tuned exceedance cut-off (#30).** In each outer fold, the cut-off between 20 and 50 µg/m³ (step 0.5) that maximises F1 for "≥ 35.5" on the inner-validation predictions is applied to that fold's test rows. The served threshold is the median of the 13 fold cut-offs.

**Grid** (depth 4 or 6, with or without equal total weight per group), by pooled out-of-fold MAE on all rows:

| Setting | MAE |
|---|---|
| **d4, no weights** | **11.29** |
| d6, no weights | 11.30 |
| d4, group-weighted | 12.09 |
| d6, group-weighted | 12.20 |

Group weights hurt: they give the low-PM2.5 groups as much pull as the 2020 group. The same outer folds both choose the setting and score it, so read the numbers as nested-ish.

## Results

Every model is scored with the same leave-one-group-out CV (13 folds) and the same metric code as v1. Persistence and climatology are identical to v1's.

### Pooled (persistence rows: 139,020)

| Model | MAE | RMSE | R² | Skill | AQI acc. | Precision ≥ 35.5 | Recall ≥ 35.5 | F1 ≥ 35.5 | AUROC |
|---|---|---|---|---|---|---|---|---|---|
| Persistence | 12.31 | 30.24 | 0.477 | 0 | 0.655 | 0.691 | **0.688** | **0.689** | 0.897 |
| Climatology | 19.43 | 44.67 | −0.140 | −0.578 | 0.324 | — | 0.000 | 0.000 | 0.291 |
| v1 (direct) | 13.48 | 37.63 | 0.191 | −0.095 | 0.643 | **0.822** | 0.317 | 0.458 | 0.893 |
| **v2 (anchored)** | **11.40** | **28.81** | **0.526** | **+0.074** | **0.664** | 0.793 | 0.562 | 0.658 | **0.905** |

On all 141,954 rows, the MAE is 11.29 for v2, 13.32 for v1 and 19.24 for climatology. Persistence doesn't exist for 2.1% of rows.

### Macro average over groups (persistence rows)

| Model | MAE | RMSE | R² | AQI acc. | F1 ≥ 35.5 | Macro skill |
|---|---|---|---|---|---|---|
| Persistence | 10.36 | 23.65 | −0.393 | 0.639 | **0.311** | 0 |
| Climatology | 11.39 | 23.60 | −0.096 | 0.402 | 0.000 | −0.100 |
| v1 | 8.97 | 20.93 | **0.103** | 0.636 | 0.209 | +0.133 |
| **v2** | **8.82** | **20.15** | 0.083 | **0.648** | 0.280 | **+0.148** |

### Per horizon (persistence rows): MAE / skill / F1 at 35.5

| Horizon | Persistence | v1 | v2 | v2 RMSE (persistence) | Served |
|---|---|---|---|---|---|
| 1 h | **7.58** / 0 / **0.826** | 9.86 / −0.301 / 0.772 | 8.01 / −0.057 / 0.813 | 20.51 (**18.97**) | persistence |
| 3 h | 10.37 / 0 / **0.749** | 11.97 / −0.154 / 0.660 | **9.87** / **+0.048** / 0.727 | **25.10** (25.28) | v2 |
| 6 h | 12.82 / 0 / **0.683** | 14.30 / −0.116 / 0.249 | **11.74** / **+0.084** / 0.656 | **29.64** (30.58) | v2 |
| 12 h | 15.09 / 0 / **0.614** | 14.74 / +0.023 / 0.253 | **13.07** / **+0.134** / 0.545 | **32.59** (35.57) | v2 |
| 24 h | 15.74 / 0 / **0.574** | 16.55 / −0.052 / 0.137 | **14.35** / **+0.088** / 0.513 | **34.07** (37.13) | v2 |

`docs/ml.md` §5 calls the 6 h horizon the realistic target: v2 improves MAE there by 8.4% and RMSE by 3.1% over persistence.

### Per tier (persistence rows): MAE / F1 at 35.5

| Tier | Persistence | v1 | v2 |
|---|---|---|---|
| high | 12.50 / **0.758** | 15.64 / 0.475 | **12.14** / 0.726 |
| high-medium | 13.98 / **0.559** | 12.15 / 0.447 | **11.98** / 0.523 |
| medium-low | 8.53 / **0.338** | **7.36** / 0.199 | 7.64 / 0.272 |
| low | 7.46 / **0.134** | **5.85** / 0.022 | 6.09 / 0.081 |

### Per group (persistence rows): MAE

| Held-out group | Persistence | Climatology | v1 | v2 | v1 skill | v2 skill | v2 F1 |
|---|---|---|---|---|---|---|---|
| G-PE-001 (2020: PE-001, 005, 007, 012, 013, 019) | 16.92 | 29.92 | 21.24 | **16.45** | −0.255 | **+0.028** | 0.696 |
| G-PE-002 (PE-002, 014) | 8.50 | 12.37 | 8.33 | **7.75** | +0.021 | **+0.089** | 0.655 |
| G-PE-003 (PE-003, 008) | 16.20 | 19.73 | **13.42** | 13.98 | +0.171 | +0.137 | 0.616 |
| G-PE-004 | 5.51 | 9.09 | **4.36** | 4.54 | +0.209 | +0.176 | 0.288 |
| G-PE-006 | 16.08 | 14.02 | **12.22** | 12.72 | +0.240 | +0.209 | 0.355 |
| G-PE-009 | 10.50 | 8.66 | **8.21** | 8.35 | +0.218 | +0.204 | 0.171 |
| G-PE-010 | 8.04 | 8.51 | **6.78** | 7.14 | +0.156 | +0.112 | 0.236 |
| G-PE-011 | 9.48 | 9.82 | 8.62 | **8.50** | +0.091 | +0.104 | 0.396 |
| G-PE-015 | 5.94 | 4.74 | **4.42** | 4.63 | +0.257 | +0.220 | 0.000 |
| G-PE-016 | 8.39 | **6.98** | 7.22 | 7.26 | +0.140 | +0.135 | 0.168 |
| G-PE-017 | 16.69 | 13.48 | **13.07** | 13.87 | +0.217 | +0.169 | 0.000 |
| G-PE-018 | 5.21 | 6.45 | **4.14** | 4.16 | +0.205 | +0.202 | 0.000 |
| G-PE-020 | 7.15 | **4.37** | 4.66 | 5.31 | +0.349 | +0.257 | 0.061 |

v2 beats persistence in all 13 groups. It gives back a little of v1's edge in the smaller, cleaner groups: the anchor pulls the prediction toward the last reading, which is a slightly worse bet when the air is clearing.

### The 2020 group by reading band (G-PE-001, persistence rows)

| Label band | Rows | Persistence MAE | v1 MAE | v2 MAE | Mean bias (persistence / v1 / v2) |
|---|---|---|---|---|---|
| < 35.5 | 44,185 | 9.29 | **6.00** | 6.66 | +4.1 / −1.8 / +0.3 |
| 35.5–125.4 | 15,625 | **25.20** | 34.83 | 25.56 | −3.6 / −34.5 / −20.7 |
| ≥ 125.5 | 2,771 | **92.00** | 187.60 | 121.14 | **−48.8 / −187.6 / −116.3** |

v2 roughly halves v1's error on severe smoke but is still worse than persistence there. The residual learned from the other groups pulls extreme readings back toward the levels it has seen.

### Exceedance (≥ 35.5): fixed vs tuned cut-off

| | Fixed 35.5: P / R / F1 | Tuned cut-off: P / R / F1 |
|---|---|---|
| Pooled | 0.793 / 0.559 / 0.655 | 0.654 / **0.719** / **0.685** |
| 1 h | 0.873 / 0.759 / 0.812 | 0.822 / 0.825 / **0.824** |
| 3 h | 0.827 / 0.646 / 0.725 | 0.777 / 0.727 / **0.751** |
| 6 h | 0.777 / 0.564 / 0.654 | 0.682 / 0.690 / **0.686** |
| 12 h | 0.756 / 0.423 / 0.542 | 0.572 / 0.679 / **0.621** |
| 24 h | 0.685 / 0.404 / 0.509 | 0.498 / 0.673 / **0.573** |
| Macro over groups (F1) | 0.279 | 0.299 |

Precision and recall are pooled over all rows. The served thresholds (median fold cut-off) are 31.5, 29.5, 25.5, 21.5 and 20.0 µg/m³ for 1, 3, 6, 12 and 24 h. Because 1 h serves persistence, it uses the fixed 35.5. Tuning trades precision for recall. With tuned thresholds v2 is level with persistence's F1 at 6 h (0.686 vs 0.683), but not beyond it, and it still trails at 1 h. **At 24 h, 7 of the 13 fold cut-offs hit the grid floor of 20.0.** The best cut-off there is probably lower: v2 under-predicts at long horizons, and the grid limits the fix.

## Release decision (#31)

The rule was fixed before the results. Per horizon, ship v2 only if its MAE skill against persistence is ≥ 0 both pooled and macro over groups (`ml/evaluation/release.py`); otherwise serve persistence.

| Horizon | Pooled skill | Macro skill | Serves | Exceedance threshold |
|---|---|---|---|---|
| 1 h | −0.057 | +0.061 | **persistence** | 35.5 |
| 3 h | +0.048 | +0.136 | **v2** | 29.5 |
| 6 h | +0.084 | +0.175 | **v2** | 25.5 |
| 12 h | +0.134 | +0.230 | **v2** | 21.5 |
| 24 h | +0.088 | +0.110 | **v2** | 20.0 |

## Feature importance (gain, residual models, mean over horizons, top 15)

| # | Feature | Gain share |
|---|---|---|
| 1 | `persistence` | 0.280 |
| 2 | `trend_1_6` | 0.098 |
| 3 | `pm25_lag_1h` | 0.092 |
| 4 | `active_fire_count_200km` | 0.050 |
| 5 | `trend_1_3` | 0.044 |
| 6 | `total_frp_200km` | 0.042 |
| 7 | `ratio_1_24` | 0.042 |
| 8 | `pm25_lag_12h` | 0.032 |
| 9 | `temp_c` | 0.031 |
| 10 | `day_of_year` | 0.031 |
| 11 | `wind_speed_ms` | 0.030 |
| 12 | `month` | 0.023 |
| 13 | `pm25_lag_3h` | 0.022 |
| 14 | `pm25_lag_6h` | 0.020 |
| 15 | `local_solar_hour` | 0.020 |

The residual models are small: 17–51 trees after early stopping. Most of the work is done by the anchor; the trees learn when to pull the last reading up or down, from the trend and the fire activity.

## Remaining failure cases

- **Severe smoke is still under-predicted.** On the 2020 group's ≥ 125.5 hours, v2's bias is −116 µg/m³ (persistence −49). A held-out regime more extreme than anything in training still can't be learned from the other groups.
- **1 h stays with persistence.** The last reading is very hard to beat one hour out, and the release rule keeps persistence there.
- **Long-horizon exceedance.** At 12–24 h, F1 at the fixed 35.5 is 0.51–0.54; the tuned cut-offs reach 0.57–0.62, and the 24 h cut-off is limited by the grid floor.
- **Clean low-smoke groups.** v2 is a little worse than v1 in 10 of 13 groups (e.g. G-PE-020: 5.31 vs 4.66), though still better than persistence everywhere.
- **Ideas for v3:** let the cut-off grid go below 20; try a quantile or Tweedie loss for the tail; add fire-to-point transport features (wind-aligned upwind FRP); add PurpleAir labels (v1.1) for density near the fire.

## Caveats

The caveats from the [dataset card](../datasets/smokesense_v1.md) all apply:
- Labels are AirNow preliminary data.
- Red Bluff offsets are applied. The Lone Pine and Tahoe City offsets are unverified, and sites without an AQS counterpart have unverified timing.
- No PurpleAir labels.
- Fire features use SNPP only.
- PE-008 starts without lags.
- The 2020 group dominates the row count.
- Leave-one-group-out is the intended CV.
- Weather is observed NCEI weather at issue time.

## What live inference must supply

The same as v1 ([baseline_v1.md](baseline_v1.md#what-live-inference-must-supply)):
- the `FEATURES` columns, with the same meanings and units;
- VIIRS SNPP NRT detections, 200 km / 72 h, strictly before issue time;
- NCEI-style observed weather from the nearest station, at most 3 h old;
- the point's own AirNow PM2.5 lags at −1/3/6/12/24 h, with time offsets applied and negatives clamped.

Do not compute the derived features yourself. `ml.inference.predict_v2.predict(frame, horizon, model_dir)` adds them with `add_derived`, follows `release.json` and returns `pm25`, `exceeds` (against the horizon's threshold) and `source` (`v2`, `persistence` or `fallback`). Load an explicit model folder, never "the newest".
