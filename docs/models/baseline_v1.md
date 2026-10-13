# Model card: baseline_v1

| | |
|---|---|
| Models | XGBoost regressor, one per horizon (1, 3, 6, 12, 24 h), max_depth 4 |
| Data | `smokesense_v1` 1.0.0 (`docs/datasets/smokesense_v1.md`); the dataset's sha256 is checked on load |
| Code | `backend/ml/`: `feature_columns.py`, `models/`, `evaluation/metrics.py`, `training/train_baseline_v1.py`, `inference/predict.py` |
| Train | `cd backend && python -m ml.training.train_baseline_v1` (about 2 min on 12 cores) |
| Artifacts | `backend/data/models/baseline_v1/`, not in git: `model_h{1,3,6,12,24}.json`, `features.json`, `params.json`, `metrics.json`, `climatology.json`, `oof_predictions.parquet`, `manifest.json` (dataset sha256, git commit, library versions). `docs/ml.md` §7 places artifacts in `ml/artifacts/`; this follows the DATA-04 request instead. |
| Rules | `docs/data-decisions.md` #23–#27 |

**Status: not ready to replace persistence.** XGBoost beats persistence in 12 of 13 held-out groups and on the macro average over groups. Pooled over all rows, it loses, because it under-predicts severe smoke when the 2020 group is held out. Its recall at the ≥ 35.5 µg/m³ threshold is low. Details are under [Failure cases](#failure-cases).

## Features (#23)

There are 23 features, in `ml/feature_columns.py` (`FEATURES`):

| Kind | Columns |
|---|---|
| Fire (VIIRS SNPP, 200 km, last 72 h) | `nearest_fire_dist_km`, `fire_bearing_sin`, `fire_bearing_cos`, `total_frp_200km`, `active_fire_count_200km` |
| Weather (nearest NCEI station, latest report ≤ issue time, ≤ 3 h old) | `wind_alignment`, `wind_speed_ms`, `wind_dir_sin`, `wind_dir_cos`, `temp_c`, `rh_pct`, `pressure_hpa`, `precip_1h_mm` |
| PM2.5 lags (own monitor, before issue time) | `pm25_lag_1h`, `pm25_lag_3h`, `pm25_lag_6h`, `pm25_lag_12h`, `pm25_lag_24h` |
| Calendar | `day_of_year`, `month`, `smoke_season`, `local_solar_hour` |
| Horizon | `horizon_hours`, constant within each per-horizon model |

Missing values are left as NaN; XGBoost learns a default branch for them.

**Excluded columns.** `tests/test_ml_baseline.py` fails if any of these becomes a feature:

| Column | Why |
|---|---|
| `target_pm25`, `target_time` | The label and its timing. |
| `target_source`, `target_monitor_id`, `target_monitor_dist_km` | Label provenance, not known at issue time. |
| `forecast_point_id`, `location_lat`, `location_lon` | Would let the model memorise sites across events. |
| `event_ids`, `pilot_event_id`, `group_id` | Event and CV bookkeeping, unknown in live inference. |
| `event_tier` | Derived from the labels (max in-box peak). |
| `precip_prob_pct` | Always null: observed weather has no forecast probability. |
| `fire_bearing_deg` | Encoded as sin/cos instead, because it's circular. |
| `issue_time` | A timestamp; the calendar features carry its signal. |

## Target and training (#25)

- **Target:** `log1p(target_pm25)`. Predictions are `expm1(·)`, clipped at 0.
- **Base parameters:** eta 0.05, subsample 0.8, colsample_bytree 0.8, min_child_weight 5, `hist` tree method, seed 42.
- **Grid:** max_depth 4, 6 or 8. Each fit takes up to 800 trees, with early stopping (50 rounds) on an inner group split that holds out 25% of the training groups. It is then refitted on all training rows with the chosen number of trees.
- **Selection:** pooled out-of-fold MAE on all rows was 13.32 for depth 4, 13.78 for depth 6 and 14.01 for depth 8, so **depth 4** was chosen.
- **Not a clean nested estimate:** the same outer folds both choose the setting and score it, so read the CV numbers as nested-ish.
- **Final models:** refitted on all rows with depth 4, one per horizon.

## CV design (#26)

Leave-one-group-out on `group_id`: 13 folds. Each fold holds out every event whose window overlaps another's, so no labelled hour appears in both train and test.
- **Units:** all metrics are on raw µg/m³.
- **Skill:** `1 − MAE / MAE_persistence`.
- **AQI accuracy:** agreement in EPA 2024 PM2.5 category (0–9.0, 9.1–35.4, 35.5–55.4, 55.5–125.4, 125.5–225.4, > 225.4).
- **Threshold metrics:** precision, recall, F1, AUROC and AUPRC for PM2.5 ≥ 35.5 µg/m³.
- **Row sets:** "Persistence rows" (139,020, or 97.9% of rows) compares every model on the same rows. "All rows" (141,954) has no persistence prediction for 2.1% of rows.
- **Climatology** is fitted on each fold's training rows only.

## Results

### Pooled (persistence rows)

| Model | MAE | RMSE | R² | Skill | AQI acc. | Precision ≥ 35.5 | Recall ≥ 35.5 | F1 ≥ 35.5 | AUROC ≥ 35.5 |
|---|---|---|---|---|---|---|---|---|---|
| Persistence | **12.31** | **30.25** | **0.477** | 0 | **0.655** | 0.691 | **0.688** | **0.689** | **0.897** |
| Climatology | 19.43 | 44.67 | −0.140 | −0.578 | 0.324 | — | 0.000 | 0.000 | 0.291 |
| XGBoost d4 (log1p) | 13.48 | 37.63 | 0.191 | −0.095 | 0.643 | **0.822** | 0.317 | 0.458 | 0.893 |
| XGBoost d4 (raw target) | 13.92 | 35.05 | 0.298 | −0.130 | 0.548 | 0.681 | 0.555 | 0.612 | 0.896 |

On all rows, XGBoost d4 scores MAE 13.32, RMSE 37.29 and F1 0.455; the raw-target variant scores MAE 13.82 and F1 0.609; climatology scores MAE 19.24.

### Macro average over groups (persistence rows)

| Model | MAE | RMSE | R² | AQI acc. | F1 ≥ 35.5 |
|---|---|---|---|---|---|
| Persistence | 10.36 | 23.65 | −0.393 | **0.639** | **0.311** |
| Climatology | 11.39 | 23.60 | −0.096 | 0.402 | 0.000 |
| XGBoost d4 | **8.97** | **20.93** | **0.103** | 0.636 | 0.209 |
| XGBoost d4 raw | 10.30 | 21.35 | −0.029 | 0.538 | 0.282 |

### Per horizon (persistence rows): MAE / skill / F1 ≥ 35.5

| Horizon | Persistence | Climatology | XGBoost d4 | XGBoost d4 raw |
|---|---|---|---|---|
| 1 h | **7.58** / 0 / **0.826** | 19.34 / −1.553 / 0 | 9.86 / −0.301 / 0.772 | 9.24 / −0.220 / 0.804 |
| 3 h | **10.37** / 0 / **0.749** | 19.36 / −0.866 / 0 | 11.97 / −0.154 / 0.660 | 12.71 / −0.226 / 0.710 |
| 6 h | **12.82** / 0 / **0.683** | 19.37 / −0.511 / 0 | 14.30 / −0.116 / 0.249 | 14.23 / −0.110 / 0.649 |
| 12 h | 15.09 / 0 / **0.614** | 19.45 / −0.289 / 0 | **14.74** / **+0.023** / 0.253 | 15.06 / +0.002 / 0.546 |
| 24 h | **15.74** / 0 / **0.574** | 19.65 / −0.248 / 0 | 16.55 / −0.052 / 0.137 | 18.37 / −0.167 / 0.275 |

### Per tier (persistence rows): MAE / F1 ≥ 35.5

| Tier (rows, positives) | Persistence | Climatology | XGBoost d4 | XGBoost d4 raw |
|---|---|---|---|---|
| high (81,851, 16,771) | **12.50** / **0.758** | 23.50 / 0 | 15.64 / 0.475 | 15.16 / 0.667 |
| high-medium (38,195, 6,485) | 13.98 / **0.559** | 16.35 / 0 | **12.15** / 0.447 | 13.76 / 0.531 |
| medium-low (11,980, 662) | 8.53 / **0.338** | 9.04 / 0 | **7.36** / 0.199 | 9.69 / 0.307 |
| low (6,994, 174) | 7.46 / **0.134** | 6.44 / 0 | **5.85** / 0.022 | 7.51 / 0.106 |

### Per group (persistence rows)

| Held-out group | Rows | Positives ≥ 35.5 | MAE persistence | MAE climatology | MAE XGBoost d4 | Skill | F1 XGBoost |
|---|---|---|---|---|---|---|---|
| G-PE-001 (PE-001, 005, 007, 012, 013, 019) | 62,581 | 18,396 | 16.92 | 29.92 | 21.24 | **−0.255** | 0.453 |
| G-PE-002 (PE-002, 014) | 12,427 | 1,574 | 8.50 | 12.37 | 8.33 | +0.021 | 0.598 |
| G-PE-003 (PE-003, 008) | 9,633 | 2,288 | 16.20 | 19.73 | 13.42 | +0.171 | 0.524 |
| G-PE-004 | 30,410 | 660 | 5.51 | 9.09 | 4.36 | +0.209 | 0.220 |
| G-PE-006 | 3,315 | 344 | 16.08 | 14.02 | 12.22 | +0.240 | 0.267 |
| G-PE-009 | 2,400 | 89 | 10.50 | 8.66 | 8.21 | +0.218 | 0.140 |
| G-PE-010 | 10,065 | 403 | 8.04 | 8.51 | 6.78 | +0.156 | 0.214 |
| G-PE-011 | 1,675 | 183 | 9.48 | 9.82 | 8.62 | +0.091 | 0.190 |
| G-PE-015 | 720 | 10 | 5.94 | 4.74 | 4.42 | +0.257 | 0.000 |
| G-PE-016 | 1,626 | 75 | 8.39 | 6.98 | 7.22 | +0.140 | 0.026 |
| G-PE-017 | 360 | 29 | 16.69 | 13.48 | 13.07 | +0.217 | 0.000 |
| G-PE-018 | 1,675 | 25 | 5.21 | 6.45 | 4.14 | +0.205 | 0.000 |
| G-PE-020 | 2,133 | 16 | 7.15 | 4.37 | 4.66 | +0.349 | 0.087 |

## Feature importance (gain, mean over the five horizon models, top 15)

| # | Feature | Gain share |
|---|---|---|
| 1 | `pm25_lag_1h` | 0.393 |
| 2 | `pm25_lag_3h` | 0.196 |
| 3 | `pm25_lag_12h` | 0.079 |
| 4 | `active_fire_count_200km` | 0.051 |
| 5 | `pm25_lag_6h` | 0.047 |
| 6 | `total_frp_200km` | 0.025 |
| 7 | `day_of_year` | 0.020 |
| 8 | `wind_speed_ms` | 0.020 |
| 9 | `pm25_lag_24h` | 0.019 |
| 10 | `month` | 0.018 |
| 11 | `fire_bearing_cos` | 0.018 |
| 12 | `pressure_hpa` | 0.014 |
| 13 | `temp_c` | 0.014 |
| 14 | `smoke_season` | 0.013 |
| 15 | `local_solar_hour` | 0.012 |

## Failure cases

Worst three groups by skill against persistence:

1. **G-PE-001, the 2020 siege (skill −0.255, 44% of rows).**
   - Held out, it takes the whole extreme-smoke regime out of training. Its labels reach p99 277 and max 798 µg/m³ (Creek at Yosemite Village). The other 12 groups top out at p99 100.
   - Trees cannot extrapolate beyond the training range, and the log1p target compresses the high end further. On labels ≥ 125.5 the model is biased by −188 µg/m³ (MAE 188 vs 92 for persistence), and those 2,771 rows (4% of the group) cause 39% of its error.
   - Below 35.5 the model beats persistence even here (MAE 6.0 vs 9.3).
   - Excluding this group, pooled MAE is 7.13 for XGBoost vs 8.54 for persistence (skill +0.165).
2. **G-PE-002, Dixie + River (skill +0.021).** A single long-running site (Chico − East) where smoke builds and clears over days. XGBoost is level with persistence at 1 h (5.08 vs 5.20) and slightly worse at 24 h (13.5 vs 12.6).
3. **G-PE-011, Klamathon (skill +0.091).** A single site (Yreka) and only 1,675 rows. Few training rows resemble its plume, a single fire in the far north of the state.

**General pattern.** XGBoost has the best precision at ≥ 35.5 (0.82) but recall of only 0.32. It is conservative on smoke episodes, worst at 6–24 h, where F1 falls to 0.25 and below. The raw-target variant trades MAE for recall (F1 0.61). Ideas for v2:
- a recall-oriented objective: Tweedie or quantile loss, or sample weights on high PM2.5;
- a residual model on top of persistence;
- calibrating the threshold on predicted PM2.5 (AUROC is already 0.89).

## Caveats

These are inherited from the dataset card:
- Labels are AirNow preliminary data, not validated AQS.
- Red Bluff time offsets are applied. The Lone Pine and Tahoe City offsets are unverified (neither site is a forecast point in v1), and sites without an AQS counterpart, such as Morongo School, have unverified timing.
- No PurpleAir labels until v1.1.
- Fire features use VIIRS SNPP only.
- PE-008 starts without lags (Weaverville's dark 2018-07-30).
- The 2020 group dominates the row count. That is exactly why the pooled numbers above are driven by one fold.
- Weather is observed NCEI weather at issue time, not NWS forecasts.

## What live inference must supply

- **Columns:** `FEATURES`, with the same meanings and units, from `ml.feature_columns`. `predict(feature_frame, horizon)` in `ml/inference/predict.py` raises if any is missing and sets `horizon_hours` itself.
- **Fire:** VIIRS SNPP NRT detections (`VIIRS_SNPP_NRT`, the source the live FIRMS task requests). Use those within 200 km of the point and in the 72 h before the issue time, computed with `features.spatial` exactly as in training. Detections at or after the issue time must be excluded.
- **Weather:** NCEI-style observations from the station nearest the point, taking the latest report at or before the issue time and no older than 3 h. Calm winds have speed 0 and no direction.
- **PM2.5 lags:** the forecast point's own AirNow monitor at issue time − 1/3/6/12/24 h (RawConcentration, with the time-offset table applied, values in [−5, 0) clamped to 0). Missing lags stay NaN.
- **Calendar:** `day_of_year`, `month` and `smoke_season` from the issue time; `local_solar_hour` from the point's longitude.
- **Model version:** load an explicit model folder, never "the newest" (`docs/ml.md` §7).
