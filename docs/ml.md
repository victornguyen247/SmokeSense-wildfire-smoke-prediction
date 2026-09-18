# Machine Learning Workflow

This document covers how we build, evaluate, and ship the PM2.5 forecasting model. It's written so that anyone on the team — not just the ML engineer — can read a model PR and understand whether it's sound.

For where ML sits in the system, see [architecture.md](architecture.md).

---

## 1. The one rule that matters most: split by time, never randomly

This system predicts the **future**. Every evaluation must simulate that: train on the past, test on a later period the model has never seen.

- **Always use time-based train / validation / test splits.** Train on earlier dates, validate and test on later dates.
- **Never randomly shuffle observations into splits.** A random split lets the model see 3 p.m. when it's being tested on 2 p.m. of the same day — it learns from the future. The result is a great-looking score that collapses in production.
- **Use event-based holdout too:** hold out several complete wildfire events so at least some events are entirely unseen during training. Average error hides how the model does on the events that actually matter.

If you see a `train_test_split(..., shuffle=True)` in a model PR, that's a bug, not a style choice. Call it out.

---

## 2. Folder structure (`backend/ml/`)

```
ml/
  datasets/       assemble the training dataset; define time-based + event splits
  models/         model definitions: baselines, xgboost, advanced
  training/       training scripts + experiment configs
  evaluation/     metrics: MAE/RMSE, threshold detection, calibration
  inference/      load_model() + predict() — imported by app/services
  artifacts/      trained model binaries + manifest (git-ignored)
  notebooks/      exploratory only
```

`ml/` and `features/` must never import from `app/` — inference has to run without the web server. See the dependency rule in [backend.md](backend.md).

---

## 3. Notebooks are exploratory only

Notebooks are for exploring data and trying ideas — not for anything the system depends on. Once a piece of code matters (a feature calculation, a training step, an evaluation metric), **promote it out of the notebook** into `features/`, `ml/training/`, or `ml/evaluation/` where it can be imported, tested, and reviewed.

Nothing in `app/` or the ingestion worker may import from `notebooks/`.

---

## 4. Modeling strategy: staged, simplest first

Build in tiers so we always have a working system, even if the fancy model disappoints.

| Tier | Model | Purpose |
|---|---|---|
| Baseline A | Persistence (last observed PM2.5 carries forward) | The bar to beat. If ML can't beat "nothing changes," it isn't adding value. |
| Baseline B | Weather + lag features, linear or simple tree | Separates weather effects from fire-specific signal. |
| Primary | Gradient-boosted trees (XGBoost / LightGBM) | The MVP model: fast to train, handles nonlinear interactions, explainable. |
| Advanced | Temporal model (LSTM / transformer) | **Only** if it robustly beats the primary model. Experimental, not a dependency. |
| Benchmark | NOAA HRRR-Smoke, where comparable | External reference point for discussion. |

**Start with gradient-boosted trees.** In a three-month project, a model that trains in minutes and whose feature importances you can explain is worth far more than a deep model you can't debug. Deep sequence models are a stretch goal, never the thing the demo depends on.

---

## 5. Evaluation

Report, at minimum:

- **MAE and RMSE** for the PM2.5 point forecast, **broken down by horizon** (1 / 3 / 6 / 12 / 24 h). Performance varies a lot across horizons — a single averaged number hides this.
- **Threshold-exceedance detection:** precision, recall, F1, and AUROC/AUPRC for "will this location cross the unhealthy PM2.5 line?" This is the headline result — being right about *danger* matters more than shaving a microgram off the average.
- **Calibration:** if we report confidence, is it honest? A "70%" should be right about 70% of the time.
- **Breakdowns** by distance from fire and wind alignment — the model will behave very differently up- vs downwind.

Always compare against **persistence** and **weather-only** baselines, and against HRRR-Smoke where the data can be aligned.

### What counts as success
Persistence is very hard to beat at the 1-hour horizon. The realistic, winnable target is the **6-hour horizon**, where a statistically significant single-digit-percent RMSE improvement over persistence is a real result. Frame success as: meaningful improvement over persistence at 6 hours, plus better detection of unhealthy events without an unacceptable false-alarm rate. Set the exact number after the first baseline run, not before.

---

## 6. Reproducibility

- **Fix random seeds** in training and record them.
- **Version the dataset:** record which date range and sources produced a training set, so a result can be reproduced.
- **Log every experiment:** what changed, the split used, and the resulting metrics. A shared experiment log (even a markdown table or a lightweight tracker) beats memory.
- A model result that can't be reproduced doesn't count as a result.

---

## 7. Model artifacts and the registry

- Trained binaries go in `ml/artifacts/` and are **git-ignored** — never commit large model files.
- Alongside each artifact, record a small **manifest**: model version, training date range, feature set, split used, and headline metrics.
- `ml/inference/load_model()` loads a specified version. The API always loads an explicit version, never "whatever's newest," so we know exactly what's serving predictions.

---

## 8. What the model must never claim

SmokeSense produces **experimental forecasts**, not medical or official guidance. The ML output feeds a product that must:

- label predictions as model estimates, not warnings,
- express uncertainty rather than a single confident number where possible,
- defer to official AQI/health guidance for what the numbers *mean* for people.

Keep that framing intact from the model output through the API to the UI.
