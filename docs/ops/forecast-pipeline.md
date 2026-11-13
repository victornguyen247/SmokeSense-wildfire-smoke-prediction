# Hourly forecast pipeline (OPS-04)

Every hour at `PIPELINE_MINUTE` (default :45 UTC, the serving contract's H+45 cutoff, after AirNow at :25 and NWS at :05) beat
runs `pipeline.hourly`, which opens a `pipeline_runs` row for the current hour and
starts a Celery chain, one task per stage:

```
check_ingest -> features -> predict -> interpolate -> finish
```

| Stage | Does | Writes |
| --- | --- | --- |
| `check_ingest` | Fails if AirNow has not run recently (`app.repositories.freshness`). Stale NWS or a missing H-1 reading only log a warning (lag/weather features become null per the serving contract) | nothing |
| `features` | One feature row per active monitor point | a Parquet frame in `PIPELINE_WORK_DIR/<run id>/` |
| `predict` | Stage A: forecasts at every monitor for the 5 horizons | `forecasts` (upsert) |
| `interpolate` | Stage B: IDW of those onto grid cells (`serving.geo`) | `forecasts` (upsert, `source = 'idw'`) |
| `finish` | Marks the run `success`; trims `forecasts` (grid cells keep only the newest run, monitor points 30 days); prunes runs over 90 days and old work files | `pipeline_runs`, `forecasts` |

Run it without a worker: `cd backend && python -m pipeline [ISO issued_at]` (exit code 1 if the run failed).
Re-run a past hour through the task: `pipeline.hourly` with `issued_at="2026-11-06T14:00:00Z"`.

## Guarantees

- **Retryable per stage.** Each stage is its own task with `PIPELINE_STAGE_RETRIES` (2) retries
  and exponential backoff (`PIPELINE_RETRY_BACKOFF_S`, 20 s, capped at 3 min). Stages hand over
  through the database or a Parquet file, so a retry never re-runs an earlier stage.
  Worst case for a run that fails everywhere is about 4 stages x (3 attempts + backoff), well under 10 minutes.
- **Re-running an hour overwrites.** Writes are `INSERT .. ON CONFLICT (forecast_point_id, model_key,
  issued_at, horizon_hours) DO UPDATE`. Only `pipeline_runs` gains a row.
- **Failure keeps the last good forecast.** Nothing is deleted on failure. When a stage has used up
  its retries, `pipeline.fail` sets the run to `failed`, stores `<stage>: <error>` and logs one
  ERROR line (`pipeline run <id> FAILED at <stage> ...`). That log line is the alert.
- **Stale flag.** `pipeline.status.forecast_status(session)` returns the `/meta` fields
  `model_key`, `latest_issued_at`, `forecast_age_minutes`, `forecast_stale_after_minutes`,
  `forecast_stale`, from the newest *successful* run. `forecast_stale` is true once that run's
  `issued_at` is older than `PIPELINE_STALE_AFTER_MINUTES` (150, about two missed hours) or
  there is none. The API's `/meta` must merge it in (API-03, #56).
- **Retention only on success.** `finish` deletes old grid rows and 30-day-old monitor rows, so a failed run never removes the last good forecast. `alerts.latest_forecast_id` is `ON DELETE SET NULL`.
- **Switching the production model** mid-hour leaves both models' rows for that hour (the upsert key includes `model_key`). Readers must use the `model_key` of the newest successful `pipeline_runs` row.
- **Crashed runs.** `start_run` closes any run still `running` after 30 minutes as `failed` (`abandoned`) with an ERROR line, so a killed worker does not leave a silent row.
- **Not atomic across stages.** If `interpolate` fails after `predict` succeeded, the new hour's
  monitor rows are in `forecasts`, but the API keeps serving the newest *successful* run's cycle
  (`pipeline_runs`), so clients never see a half-written hour; `/meta` reports stale.

## Stub -> real is configuration

| Variable | Values | Default |
| --- | --- | --- |
| `PIPELINE_FEATURES_STAGE` | `stub` (newest reading per monitor), `real` (`serving.geo.build_monitor_features`, skips the cycle if FIRMS is stale) | `stub` |
| `PIPELINE_PREDICT_STAGE` | `stub` (persistence at all horizons, model `stub-persistence/v0`), `real` (registry production model via `InferenceService`), or `package.module:callable` | `stub` |
| `PIPELINE_INTERPOLATE_STAGE` | `real` (`serving.geo.interpolate_to_grid`) | `real` |

A custom stage is `fn(StageContext) -> StageResult` (`pipeline/stages.py`). The `stub` model gets a
`shadow` row in `model_versions` (the `forecasts.model_key` foreign key needs one); its forecasts are
written with `is_shadow = false`. The API serves only a production model, so after a stub run
`/forecast/*` returns 503 `forecast_unavailable`: to test serving locally, use
`PIPELINE_PREDICT_STAGE=real` or `make seed-fake`.

`PIPELINE_PREDICT_STAGE=real` serves the registry's production version of `PIPELINE_MODEL_NAME`
(default `baseline`) through ML-04's `InferenceService` (`ml.inference.service`), so `baseline/v2`
once promoted (docs/mlops/registry.md). It needs the full feature frame, so set
`PIPELINE_FEATURES_STAGE=real` with it; the run fails at `predict` with a missing-columns error otherwise.
The registry comes from `REGISTRY_*` settings (`mlops.registry.build_registry`).

To go live: register and promote the model, then set

```
PIPELINE_FEATURES_STAGE=real
PIPELINE_PREDICT_STAGE=real
```
