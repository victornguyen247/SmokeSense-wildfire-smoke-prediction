# ML-01 baselines vs DATA-04 models on one split

This compares ML-01's baselines (PR #66, `backend/ml/notebooks/ML01_Baselines.ipynb`) with the DATA-04 models (`baseline_v1`, `baseline_v2`) on **the same rows**. It is analysis only: no model, dataset or serving change. The numbers are in [`ml01-vs-data04.json`](ml01-vs-data04.json), the code is `backend/ml/evaluation/ml01_vs_data04.py` (about 5 s), and the decision is #45.

## Method

- **Split (ML-01's).** Groups are ordered by first issue time. The first 9 train, the next 2 validate (G-PE-017, G-PE-009), and the last 2 test (G-PE-018, G-PE-004). That is 104,710 / 2,760 / 34,484 rows. The test rows are those with `pm25_lag_1h` present: **30,922**, about 6,180 per horizon.
- **ML-01 models.** These are his saved Decision Trees from release `ml01-baselines-v1.0.0`, loaded through his module `ml.inference.ml01_baselines`, plus his persistence (`pm25_lag_1h`). The ZIP's SHA-256 was checked against the release checksum before anything was extracted or loaded.
- **DATA-04 models.** XGBoost v1 (`ml.models.xgb`) and the v2 recipe (`ml.models.xgb_v2`) were trained with the shipped hyperparameters (`params.json`: depth 4; v2 without group weights, seed 42) on **ML-01's 9 training groups only**. Their early-stopping split also stays inside those groups. The validation and test groups are never used for training or tuning. NaNs stay NaN.
- **Metrics.** `ml.evaluation.metrics.scores`: MAE, RMSE, and precision, recall, F1, AUROC and AUPRC for ≥ 35.5 µg/m³. The alert threshold is fixed at 35.5 for every model, as in ML-01. Because the served v2 alerts at its tuned per-horizon cut-off (`release.json`), that row is shown separately. "Bias ≥ 125.5" is the mean error on labels ≥ 125.5 µg/m³, of which there are only 12–13 rows per horizon.

## Reproduction check: passed

His module and saved trees reproduce his published 6 h test numbers exactly. The script stops if they don't.

| 6 h, 6,193 rows | MAE | RMSE | F1 | AUROC |
|---|---|---|---|---|
| Persistence (published / got) | 5.792 / 5.792 | 17.776 / 17.776 | 0.293 / 0.293 | 0.784 / 0.784 |
| Decision Tree (published / got) | 7.012 / 7.012 | 16.890 / 16.890 | 0.321 / 0.321 | 0.760 / 0.760 |

The joblib files were pickled with scikit-learn 1.7.2, while the repo pins 1.6.0. Loading raises `InconsistentVersionWarning`, but the predictions still match exactly.

## Results by horizon (ML-01 test rows)

Thresholds are at 35.5 unless a cut-off is named.

### 1 h (6,188 rows; 136 ≥ 35.5; 13 ≥ 125.5)

| Model | MAE | RMSE | Precision | Recall | F1 | AUROC | AUPRC | Bias ≥ 125.5 |
|---|---|---|---|---|---|---|---|---|
| Persistence | 4.172 | 11.775 | 0.519 | 0.500 | 0.509 | 0.919 | 0.552 | −37.7 |
| Decision Tree (ML-01) | 4.319 | 11.786 | 0.534 | 0.522 | **0.528** | 0.922 | 0.540 | −57.4 |
| XGBoost v1 | **3.653** | 11.977 | 0.753 | 0.404 | 0.526 | 0.922 | 0.560 | −173.2 |
| v2 | 3.663 | **11.376** | 0.731 | 0.360 | 0.483 | **0.924** | **0.564** | −157.3 |
| v2 at shipped cut-off 35.5 (1 h serves persistence) | | | 0.731 | 0.360 | 0.483 | | | |

### 3 h (6,185 rows; 132 ≥ 35.5; 12 ≥ 125.5)

| Model | MAE | RMSE | Precision | Recall | F1 | AUROC | AUPRC | Bias ≥ 125.5 |
|---|---|---|---|---|---|---|---|---|
| Persistence | 5.111 | 15.278 | 0.405 | 0.402 | 0.403 | 0.860 | 0.401 | −118.8 |
| Decision Tree (ML-01) | 5.654 | 13.686 | 0.413 | 0.394 | 0.403 | 0.851 | 0.351 | −191.8 |
| XGBoost v1 | **4.124** | 13.478 | 0.903 | 0.212 | 0.344 | 0.867 | **0.433** | −219.3 |
| v2 | 4.234 | **12.944** | 0.702 | 0.250 | 0.369 | **0.869** | 0.424 | −188.4 |
| v2 at shipped cut-off 29.5 | | | 0.531 | 0.386 | **0.447** | | | |

### 6 h (6,193 rows; 135 ≥ 35.5; 12 ≥ 125.5)

| Model | MAE | RMSE | Precision | Recall | F1 | AUROC | AUPRC | Bias ≥ 125.5 |
|---|---|---|---|---|---|---|---|---|
| Persistence | 5.792 | 17.776 | 0.298 | 0.289 | 0.293 | 0.784 | 0.237 | −191.0 |
| Decision Tree (ML-01) | 7.012 | 16.890 | 0.351 | 0.296 | **0.321** | 0.760 | 0.217 | −211.5 |
| XGBoost v1 | **4.437** | 13.811 | 0.444 | 0.030 | 0.056 | **0.806** | 0.198 | −226.5 |
| v2 | 4.602 | **13.689** | 0.621 | 0.133 | 0.220 | 0.798 | **0.263** | −218.3 |
| v2 at shipped cut-off 25.5 | | | 0.386 | 0.252 | 0.305 | | | |

### 12 h (6,179 rows; 131 ≥ 35.5; 13 ≥ 125.5)

| Model | MAE | RMSE | Precision | Recall | F1 | AUROC | AUPRC | Bias ≥ 125.5 |
|---|---|---|---|---|---|---|---|---|
| Persistence | 6.312 | 20.275 | 0.213 | 0.206 | 0.209 | 0.730 | 0.145 | −242.4 |
| Decision Tree (ML-01) | 10.132 | 17.502 | 0.279 | 0.092 | 0.138 | 0.673 | 0.107 | −240.7 |
| XGBoost v1 | **4.580** | **15.185** | 0.091 | 0.008 | 0.014 | **0.811** | 0.132 | −249.8 |
| v2 | 4.826 | 15.396 | 0.304 | 0.053 | 0.091 | 0.785 | **0.163** | −249.2 |
| v2 at shipped cut-off 21.5 | | | 0.236 | 0.191 | **0.211** | | | |

### 24 h (6,177 rows; 134 ≥ 35.5; 13 ≥ 125.5)

| Model | MAE | RMSE | Precision | Recall | F1 | AUROC | AUPRC | Bias ≥ 125.5 |
|---|---|---|---|---|---|---|---|---|
| Persistence | 6.197 | 19.869 | 0.192 | 0.187 | 0.189 | 0.761 | 0.118 | −238.7 |
| Decision Tree (ML-01) | 10.232 | 18.047 | 0.184 | 0.216 | 0.199 | 0.743 | 0.115 | −236.7 |
| XGBoost v1 | 5.191 | **15.256** | 0.333 | 0.030 | 0.055 | **0.800** | **0.129** | −247.0 |
| v2 | **5.112** | 15.885 | 0.225 | 0.067 | 0.103 | 0.785 | 0.128 | −245.1 |
| v2 at shipped cut-off 20.0 | | | 0.178 | 0.246 | **0.207** | | | |

## Per test group

| Group | Test rows (lag 1 h present) | Share | 6 h rows / ≥ 35.5 / ≥ 125.5 |
|---|---|---|---|
| G-PE-004 | 29,252 | **94.6%** | 5,859 / 130 / 12 |
| G-PE-018 | 1,670 | 5.4% | 334 / 5 / 0 |

**MAE by horizon (1 / 3 / 6 / 12 / 24 h)**

| Model | G-PE-004 | G-PE-018 |
|---|---|---|
| Persistence | 4.17 / 5.09 / 5.78 / 6.32 / 6.30 | 4.13 / 5.52 / 5.93 / 6.14 / 4.35 |
| Decision Tree | 4.32 / 5.60 / 7.04 / 10.14 / 10.33 | 4.23 / 6.53 / 6.60 / 9.98 / 8.59 |
| XGBoost v1 | 3.66 / 4.11 / 4.44 / 4.62 / 5.21 | 3.54 / 4.39 / 4.45 / **3.93** / 4.87 |
| v2 | 3.67 / 4.22 / 4.60 / 4.86 / 5.18 | 3.55 / 4.57 / 4.62 / 4.32 / **3.92** |

**6 h, F1 at 35.5 / AUROC.**
- **G-PE-004:** persistence 0.305 / 0.804, Decision Tree 0.328 / 0.776, v1 0.058 / 0.820, v2 0.226 / 0.815. v2 at its shipped cut-off 25.5 reaches F1 0.312.
- **G-PE-018:** it has only 5 exceedances at 6 h, and **no model detects any** (F1 0 for all four). Its AUROC of 0.27–0.41 rests on 5 positives and means nothing. All its bias cells are empty: no label is ≥ 125.5.

## Features and interfaces

| | ML-01 Decision Tree (`ml.inference.ml01_baselines`) | XGBoost v1 (`FEATURES`, 23) | v2 (`FEATURES_V2`, 27) |
|---|---|---|---|
| **Inputs** | 8 raw: `pm25_lag_{1,3,6,12,24}h`, `temp_c`, `rh_pct`, `wind_speed_ms`, plus 3 engineered internally | all 8 of ML-01's raw inputs, plus fire (5), `wind_alignment`, `wind_dir_sin/cos`, `pressure_hpa`, `precip_1h_mm`, calendar (4) and `horizon_hours` | v1's 23 plus `persistence`, `trend_1_3`, `trend_1_6`, `ratio_1_24` (`ml.features.add_derived`) |
| **Only in ML-01** | `pm25_change_1_3` = lag1 − lag3 (**identical** to v2's `trend_1_3`); `pm25_change_3_6` = lag3 − lag6 (v2 has `trend_1_6` = lag1 − lag6 instead); `pm25_short_avg` = NaN-skipping mean of lags 1/3/6 (v2 has `persistence` = lag1, else lag3, else lag6) | | |
| **Not in ML-01** | | fire, wind direction and alignment, pressure, precipitation, calendar | the same, plus `persistence`, `trend_1_6`, `ratio_1_24` |
| **Missing values** | median imputation fitted on the training groups, inside the pickled pipeline, so a missing value looks like a typical one; persistence **raises** if `pm25_lag_1h` is missing | NaN kept; XGBoost learns a default branch | NaN kept; without lags 1/3/6 the v1 direct model is the fallback (`source = fallback`) |
| **Input contract** | DataFrame with the 8 raw columns, numeric, any order (selected by name); `horizon` argument; no `horizon_hours` column | `predict_v2.predict(frame, horizon)`: the 22 `FEATURES` other than `horizon_hours`, any order, cast to float32, `smoke_season` to int8 | same entry point |
| **Output** | numpy array, µg/m³, clipped at 0 | | DataFrame aligned with the input index: `pm25`, `exceeds` (per-horizon threshold), `source` (`v2`, `persistence` or `fallback`) |

**PM-03 serving contract (`docs/ml/serving-contract.md`).**
- **predict_v2** satisfies the 22-column input contract, the horizons, the derived features via `add_derived`, the `source` values, the per-horizon release rule and thresholds (`release.json`), and the artifact layout. What it lacks, `forecast_point_id`, `issued_at` and `model_key` on every output row, is ML-04's wrapper (#45).
- **The ML-01 tree** satisfies the horizons and output in µg/m³ ≥ 0. It would even accept a contract frame, since it selects only its 8 columns. It lacks `source`, a release rule and thresholds, a fallback when `pm25_lag_1h` is missing, a `model_key` / `model_versions` entry, the artifact layout, and the fire features the contract defines.

**The release ZIP** (`ml01-baselines-v1.0.0.zip`, SHA-256 `d7d22870…`) contains only `models/decision_tree_{1,3,6,12,24}h.joblib`, `model_metadata.json`, `validation_results.csv`, `test_results.csv` and `test_classification.csv`. There is **no** `release.json`, `features.json`, `params.json`, `metrics.json`, `manifest.json` or `SHA256SUMS`. The `.sha256` file has Windows line endings, so `sha256sum -c` / `shasum -c` fail on macOS; CI works because it runs on Linux with GNU `sha256sum`. To register it with PR #68's `registry.py` (`read_metadata`), it needs at least:

- a `release.json` with one entry per horizon (`serve`, `threshold`);
- a `features.json` with a `features` list.

`manifest.json` (`dataset.data_sha256`), `params.json` and `metrics.json` are optional but fill `training_data_hash`, `hyperparameters` and `backtest_metrics`. All can be derived from `model_metadata.json` and the CSVs. Registering pickles would also mean loading only from the trusted bucket and pinning scikit-learn to the version that wrote them (1.7.2, while the repo pins 1.6.0). The packaging script below generates all five (see **Registry packaging**).

## Findings

1. **ML-01 reproduces exactly**, through his own module and saved trees, despite the scikit-learn version gap. His conclusion holds: the Decision Tree does not beat persistence on MAE at any horizon on his test groups (6 h: 7.01 vs 5.79).
2. **On the same rows, the DATA-04 models beat both on MAE at every horizon** (6 h: v1 4.44, v2 4.60, persistence 5.79, tree 7.01), and in both test groups. The one exception is v1 at 24 h in G-PE-018 (4.87 vs persistence 4.35). They also have the best RMSE and AUROC at 3–24 h. This matches the direction of DATA-04's 13-fold leave-one-group-out CV. On these low-PM test groups, v1 is slightly ahead of v2 on MAE at 3–12 h: v2's anchor on the last reading costs a little when the air is mostly clean, as `baseline_v2.md` already notes for the smaller groups.
3. **At a fixed 35.5, v1 and v2 almost never alert at 6–24 h** (6 h F1: v1 0.056, v2 0.220). They predict the bulk well but under-predict exceedances. At the cut-offs it actually serves, v2 reaches F1 0.305 at 6 h, level with persistence (0.293) and the tree (0.321). Every model is far below severe readings (bias −190 to −250 µg/m³ on the 12–13 rows ≥ 125.5).
4. **This split is a thin test.** G-PE-004 holds 94.6% of the test rows; G-PE-018 has 5 exceedances at 6 h and none ≥ 125.5. ML-01's validation groups hold 21 exceedances at 6 h. Two held-out groups, both low-PM, cannot rank models on smoke events. DATA-04's 13 held-out groups, including the 2020 fires, are the better basis.
5. **Only `predict_v2` is ready for serving.** The ML-01 path is a pickled pipeline with no release rule, `source`, fallback or registry metadata.

## Recommendation

- **Poster.** Use one main table on DATA-04's 13-fold leave-one-group-out CV with Baseline A persistence, XGBoost v1 and v2 (served), all from the model cards.
- **Second table.** Add one labelled "single held-out split (ML-01's, 2 groups)" with all four models, the ML-01 Decision Tree as **Baseline B**. Its caveat: 2 low-PM test groups and 135 exceedances at 6 h.
- **Don't merge the two.** They are different splits.
- **Alerts.** Report F1 at the served cut-offs for v2.
- **ML-04.** ML-04 (#45) should wrap **`ml.inference.predict_v2.predict`** and add `forecast_point_id`, `issued_at` and `model_key`.
- **Keep the ML-01 tree as a documented baseline**, not a serving path. It can be held in PR #68's registry as a shadow-only reference (below); the scikit-learn pin is still unresolved.

## Registry packaging

`ml/tools/package_ml01_for_registry.py` (decision #46) turns the verified release into a model directory that PR #68's registry accepts, without retraining anything:

```bash
cd backend
python -m ml.tools.package_ml01_for_registry      # -> data/models/ml01_decision_tree/ (git-ignored)
```

- **Inputs** (no network): the extracted release (`data/models/ml01_baselines/`), the release ZIP and its `.sha256` (`data/release/ml01-baselines-v1.0.0.{zip,sha256}`), and `smokesense_v1`. It stops unless the ZIP's SHA-256 equals the checksum file (compared directly, so the Windows line endings don't matter) and every release file it reads is byte-identical to the ZIP member. Only then are the pickles loaded. It also stops unless the recomputed metrics equal ML-01's published CSVs (within 1e-4); they do, for validation MAE and every test metric.
- **Output:** the five `models/decision_tree_{1,3,6,12,24}h.joblib`, copied unchanged (the `models/` layout `ml.inference.ml01_baselines` loads from), plus generated JSON with sorted keys and no timestamps; a re-run gives the same bytes.
  - `features.json`: the fitted pipelines' column order (`feature_names_in_`), the 8 raw inputs and his 3 engineered features, with a note that `pm25_change_3_6` and `pm25_short_avg` are not in `ml.feature_columns` (`pm25_change_1_3` equals `trend_1_3`).
  - `params.json`: the hyperparameters chosen on validation (`model_metadata.json`; checked against the fitted trees).
  - `metrics.json`: MAE, RMSE, precision, recall, F1, AUROC and AUPRC at 35.5 per horizon, for persistence and the tree, on the validation (G-PE-017, G-PE-009) and test (G-PE-018, G-PE-004) groups.
  - `manifest.json`: `dataset.data_sha256` of `smokesense_v1`, the release tag, the ZIP's SHA-256, the joblib hashes, and scikit-learn 1.7.2 (saved with) vs 1.6.0 (repo pin).
  - `release.json`: baseline_v2's schema. `ml/evaluation/release.py` (decision #31) is applied to ML-01's **test split** (its two held-out groups, rows with `pm25_lag_1h`), with `basis` naming the split. Threshold 35.5 is provisional, as in ML-01.

| Horizon | serve | pooled skill | macro skill |
|---|---|---|---|
| 1 h | persistence | −0.035 | −0.030 |
| 3 h | persistence | −0.106 | −0.144 |
| 6 h | persistence | −0.211 | −0.164 |
| 12 h | persistence | −0.605 | −0.615 |
| 24 h | persistence | −0.651 | −0.775 |

The rule serves persistence at every horizon, which matches ML-01's own finding. These skills come from 2 held-out groups, not DATA-04's 13-fold CV, so they are not comparable with baseline_v2's `release.json`.

**Register it as shadow only.** It is Baseline B, a reference: never `promote` it. On the PR #68 branch:

```bash
python -m mlops.registry register data/models/ml01_decision_tree --name ml01_decision_tree \
    --version v1.0.0 --algorithm decision_tree --notes "ML-01 Baseline B reference; not for serving"
```

This was checked on 2026-10-26 against PR #68's code, a throwaway `*_test` database and a temporary local registry. The row is `shadow`, with the 11 features, threshold 35.5 at each horizon and the dataset hash. The stored archive's SHA-256 equals `artifact_sha256`, and `materialize` re-extracts all 10 files with identical hashes. Loading the pickles under the pinned scikit-learn 1.6.0 warns (`InconsistentVersionWarning`), but predictions reproduce ML-01's numbers. The pin should be resolved before anything other than a reference use.
