# SmokeSense ML-01: Baseline Modeling

## Overview

ML-01 evaluates baseline models for forecasting PM2.5
concentrations at 1, 3, 6, 12, and 24 hours.

The primary forecast horizon is 6 hours.

## Dataset

- Dataset: DATA-04 v1.0.0
- Records: 141,954
- Columns: 38
- Format: Parquet

Dataset release:
https://github.com/victornguyen247/SmokeSense-wildfire-smoke-prediction/releases/tag/data04-v1.0.0

Expected local dataset directory:
`backend/ml/data/processed/smokesense_v1/`

Required files:
- data.parquet
- manifest.json

The dataset is not included in Git.

## Baseline Models

### Baseline A: Persistence

Uses `pm25_lag_1h` as the forecast.

### Baseline B: Machine Learning

Experiments include:
- Linear Regression
- Ridge Regression
- Decision Tree Regression

Decision Tree hyperparameters were selected using
validation MAE.

Engineered features:
- pm25_change_1_3
- pm25_change_3_6
- pm25_short_avg

## Evaluation

The dataset was divided into temporally separated
and group-disjoint training, validation, and test sets.

Regression metrics:
- MAE
- RMSE

Classification metrics:
- Precision
- Recall
- F1
- AUROC
- AUPRC

The exceedance threshold of 35.5 ug/m3 is provisional.

### Six-hour held-out test results

| Metric | Persistence | Decision Tree |
|---|---:|---:|
| MAE | 5.792 | 7.012 |
| RMSE | 17.776 | 16.890 |
| F1 | 0.293 | 0.321 |
| AUROC | 0.784 | 0.760 |
| AUPRC | 0.237 | 0.217 |

Decision Tree improved validation MAE but did not
outperform Persistence on held-out test MAE.

## Inference

Module:
`backend/ml/inference/ml01_baselines.py`

Supported horizons: 1, 3, 6, 12, 24 hours.

Supported model types:
- persistence
- tree

Decision Tree inference requires saved Joblib artifacts.

Expected artifact directory:
`backend/data/models/ml01_baselines/models/`

Required artifacts:
- decision_tree_1h.joblib
- decision_tree_3h.joblib
- decision_tree_6h.joblib
- decision_tree_12h.joblib
- decision_tree_24h.joblib

These files are excluded from Git.

Model artifacts are published at:
https://github.com/victornguyen247/SmokeSense-wildfire-smoke-prediction/releases/tag/ml01-baselines-v1.0.0

Download ml01-baselines-v1.0.0.zip and its .sha256
checksum file. Verify the checksum, then extract
the ZIP into backend/data/models/ml01_baselines/.

Only load trusted Joblib model artifacts.

## Automated Tests

Run from the backend directory:

    python -m pytest tests/test_ml01_baselines.py -v

All 15 tests passed locally with model artifacts installed.

Artifact-dependent integration tests require the five trained Decision Tree Joblib files in backend/data/models/ml01_baselines/models/.

When these files are unavailable, the ten artifact-dependent tests are skipped. The five remaining tests continue to execute.

Model artifacts are published through GitHub Releases: https://github.com/victornguyen247/SmokeSense-wildfire-smoke-prediction/releases/tag/ml01-baselines-v1.0.0

Only load model artifacts from trusted sources.

## Limitations

- Only two event groups were used for validation.
- Elevated PM2.5 cases are relatively rare.
- The classification threshold is provisional.
- Model registry integration is not yet complete.
- Training-serving feature parity requires verification.
