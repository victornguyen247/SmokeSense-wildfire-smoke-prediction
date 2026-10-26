# Live ingestion (DATA-06)

Keeps a rolling ~72 h window of live California data in the database for features (GEO-03), map layers and the API. One job per source, each runnable on its own:

```bash
cd backend
python -m ingestion.live firms        # or airnow | nws | purpleair
python -m ingestion.live retention    # dry run; --delete to delete
python -m ingestion.live freshness    # the /meta `sources` array
LIVE_INGEST_SMOKE=1 python -m ingestion.live smoke firms airnow nws   # live calls, no writes, counts only
```

The same jobs are Celery tasks (`ingestion/tasks.py`) scheduled by beat (`ingestion/live/schedule.py`). Code lives in `ingestion/live/`; field decoding stays in `ingestion/connectors/`, shared with the DATA-03 batch.

## Sources

| Source | Task | `ingestion_runs.source` | Default cadence (env) | Window per run | Rate limit and retries |
|---|---|---|---|---|---|
| FIRMS VIIRS **SNPP NRT** only | `ingestion.live.firms` | `firms` | every 30 min (`LIVE_FIRMS_EVERY_MINUTES`) | California bbox + 200 km; 72 h on a first run, then from 24 h (`LIVE_FIRMS_OVERLAP_HOURS`) before the last success | 5,000 transactions / 10 min; one request per run. Retries 429 and 5xx. |
| AirNow hourly PM2.5 | `ingestion.live.airnow` | `airdata` | hourly at :25 (`LIVE_AIRNOW_MINUTE`) | California bbox; 72 h, then from 3 h (`LIVE_AIRNOW_OVERLAP_HOURS`) before the last success | 500 requests / hour; one request per run (more only if the record cap makes the connector bisect). **429 is not retried** (no data until the next hour); 5xx are. |
| NWS station observations | `ingestion.live.nws` | `nws_obs` | hourly at :05 (`LIVE_NWS_MINUTE`) | the 109 training stations; 72 h, then from 3 h (`LIVE_NWS_OVERLAP_HOURS`) before the last success | Unpublished; "retry after ~5 s". One station at a time, `LIVE_NWS_REQUEST_SPACING_S` (0.5 s) apart, ~2 pages per station on a backfill. Retries 429 and 5xx. Sends `NWS_USER_AGENT`. |
| PurpleAir (map layer only) | `ingestion.live.purpleair` | `purpleair` | **off by default**; set `LIVE_PURPLEAIR_EVERY_MINUTES` to schedule it | California bbox, sensors seen in the last hour (`LIVE_PURPLEAIR_MAX_AGE_S`) | Points per field per sensor; one `/v1/sensors` call per run, six fields. Retries 429 and 5xx. |
| Retention | `ingestion.live.retention` | (none) | daily 09:15 UTC (`LIVE_RETENTION_HOUR`, `LIVE_RETENTION_MINUTE`) | see below | |

There is no chaining between sources. Each beat entry is separate and has an `expires` equal to its interval, so a stalled worker doesn't pile up a backlog.

**Retries** (`ingestion/live/common.py`, `RetryTransport`): network errors and the statuses above are retried up to `LIVE_HTTP_ATTEMPTS` (3) times, with a 2 s, 4 s, … backoff (`LIVE_HTTP_BACKOFF_S`). A wait is never shorter than the server's `Retry-After`. A wait longer than `LIVE_HTTP_MAX_WAIT_S` (60 s) is not slept: that run fails and the next scheduled run tries again. The read timeout is `LIVE_HTTP_TIMEOUT_S` (120 s), because AirNow took 40–55 s even for a small box on 2026-10-23.

**Failures.** Every run writes one `ingestion_runs` row: `running` when it starts, then `success`, `partial` (NWS with some stations failing) or `failed`, with `rows_fetched`, `rows_written`, `watermark` (newest data timestamp) and a one-line `error`. A job never raises out of its task, so a failure is logged and recorded, and the next scheduled run is the retry. Because the lookback starts from the last *successful* run, a gap after failed runs is filled automatically.

**Keys.** Keys come from the environment / `backend/.env` (`app.core.config.settings`). They are never logged or printed. Errors pass through `safe_error`, which removes every configured key and the NWS contact before logging or storing. The FIRMS key is in the URL path and the AirNow key in the query, so `httpx` logging stays at WARNING (`tests/test_no_keys_in_logs.py`, `tests/test_live_jobs.py`).

## What each job stores

All live rows go through the batch normalizers (`normalize_firms_row`, `normalize_airnow_row`, `normalize_purpleair_row`), so a live row is built exactly like a historical one. Tests check this parity on the same raw sample. Re-running over the same window adds no rows: writes upsert on the natural key, and an unchanged row is not rewritten.

| Table | Natural key | Live writer | Notes |
|---|---|---|---|
| `fire_detections` | (`satellite`, acquisition time, latitude, longitude), backed by the unique (`satellite`, `external_id`, `detected_at`) | FIRMS | `product = 'NRT'`, `satellite = 'VIIRS_SNPP'`. First write wins. |
| `observations` + `monitors` | (`monitor_id`, `valid_at`) | AirNow, PurpleAir | AirNow: `correction = 'regulatory'`, `data_status = 'preliminary'`; a changed value (late revision) updates the row. PurpleAir: `purpleair_barkjohn` / `purpleair_raw`. |
| `weather_observations` | (`station_id`, `valid_at`) | NWS | METAR reports only (below). |

### AirNow

`RawConcentration` (never the NowCast `Value`), AQS code normalized to 9 characters, per-site time offsets (`airnow_time_offsets.py`, incl. Red Bluff), `-999` and values below −5 dropped, [−5, 0) clamped to 0. This is the same cleaning training used. Only permanent monitors (`monitorType=0`) with `in_california_scope(aqs_code)` (decision #17) are kept.

### NWS

`connectors/nws.py` maps NWS fields to the NCEI-derived columns, following the serving contract's table. Units are read from each value's `unitCode`. Calm wind gives a null direction. RH comes from temperature and dew point (not `relativeHumidity`). Pressure is `seaLevelPressure` (not `barometricPressure`), null when it is ≤ 800 hPa. Precipitation is `precipitationLastHour`, and missing stays null. A value that fails QC (MADIS `X`, `B`, `Q`) is dropped and the row's `qc_flag` is set to `suspect`.

Only METAR reports are stored, meaning observations that carry `rawMessage` or the `precipitationLastHour` group. The 5-minute ASOS readings NWS also serves are skipped: they have no sea-level pressure or precipitation, and NCEI's hourly data (training) does not contain them. Every METAR time is stored as reported, with no resampling, and GEO-03 applies the "latest report within 3 h" rule.

**Watch:** on the first live run (9,150 METAR rows, 2026-10-23), `pressure_hpa` was null in 60% of rows and `precip_1h_mm` in 87%. Over the `smokesense_v1` dataset rows (the training data), they are missing in 53.9% and 58.7% respectively, measured in PR #86. NWS sends `precipitationLastHour` as null when no precipitation group was reported, and it stays null as the serving contract requires, but the null rate is above training. This is the "NWS precipitation" gap the serving contract already lists, for ML-04 shadow evaluation to track. docs/ml/weather-missingness-check.md (PR #86) shows baseline_v2 is insensitive to this gap.

**Stations** (`connectors/nws_stations.py`): the 114 distinct `weather_observations.station_id` values of the DATA-03 batch. 109 exist on api.weather.gov under the same ICAO id (checked 2026-10-23). These 5 have **no NWS station** and are not substituted:

| Training id | Where | Training rows |
|---|---|---|
| KCQT | Los Angeles Downtown/USC | 456 (2018-11 to 2022-06) |
| KEKA | Eureka | 425 (2020-08 to 2020-11) |
| KGXA | near Victorville (34.564, −117.675) | 262 (2023-07) |
| SFD | San Francisco Downtown, no ICAO | 2 |
| STO | Sacramento, no ICAO | 1 |

A point whose nearest training station is one of these uses its next-nearest station with a report, which is the same nearest-station rule training applied.

On the first live run (2026-10-23), 107 of the 109 reported. KLHM (Lincoln) and KMYV (Marysville) exist on NWS but had no observations in the last 72 h; they stay in the list and fill in when their feed returns.

### PurpleAir

**Off by default** (decision #44): the team decided the live map layer does not need it. It is not scheduled and not reported in `/meta` until `LIVE_PURPLEAIR_EVERY_MINUTES` is set, but the task and `python -m ingestion.live purpleair` still work when run explicitly. Map layer only. It is not a model input (decision #12), and `tests/test_live_purpleair.py` fails if a PurpleAir column enters `FEATURES` / `FEATURES_V2`. Each run makes one `/v1/sensors` call for outdoor sensors in the California box, requesting `latitude, longitude, last_seen, humidity, pm2.5_cf_1_a, pm2.5_cf_1_b`. Readings get A/B channel QA and then the EPA U.S.-wide correction: Barkjohn et al. 2021, `PM2.5 = 0.524·cf1 − 0.0862·RH + 5.75`, https://doi.org/10.5194/amt-14-4617-2021. The value is the sensor's current reading, stored under the hour it falls in, and a later run in the same hour replaces it. It is not an hourly average.

**Cost:** each run is **one statewide request**, about (sensors returned) × 6 points. The first live run (2026-10-23) returned 7,095 sensors for about **42.6k points**. Cost therefore scales with the cadence, not with the number of grid cells or forecast points: every 120 min is about 0.5M points a day, and every 30 min about 2M. Check the balance before enabling it.

The historical PurpleAir pull for training labels (v1.1, `ingestion/batch/batch_ingest.py` and `connectors/purpleair.py`, per-sensor history capped by `PURPLEAIR_MAX_SENSORS`) is separate and is not affected by this setting.

## Live vs historical rows, and retention

`observations`, `fire_detections` and `weather_observations` also hold the DATA-03 pilot-event rows that `smokesense_v1` is built from. Those must never be deleted. Migration `0006` adds `ingestion_run_id` to the three tables. Live jobs set it to their run's id, and batch rows keep NULL.

- **Retention** deletes rows older than `LIVE_RETENTION_HOURS` (72) **only where `ingestion_run_id IS NOT NULL`**. A historical row is never deleted, whatever its date. It also closes orphaned runs: a run still `running` after 6 hours (its worker stopped mid-run) is marked `failed` with error `abandoned (worker stopped)`. It then prunes `ingestion_runs` older than 90 days, and creates daily partitions three days ahead (eight for `weather_forecasts`) so live rows land in their own partition rather than DEFAULT.
- It is a **dry run by default**: it reports counts only. Set `LIVE_RETENTION_DELETE=1` (or run `retention --delete`) to delete.
- Rows are deleted, not partitions dropped, because a daily partition can also hold historical rows.
- Live upserts never modify a row whose `ingestion_run_id` is NULL.
- The `smokesense_v1` build (`dataset_build/build_v1.py`) reads only rows with `ingestion_run_id IS NULL`: its query functions take `row_scope` (`"historical"` by default, `"live"` for GEO-03 features from live rows, or `"any"`). This was checked on 2026-10-25: the DATA-03 release dump was restored into a throwaway database, live rows were added through the live jobs from the test fixtures, and `scripts/reproduce_data04.sh` reproduced the dataset byte for byte. Before the filter, those live rows changed the dataset's sha256.

## Freshness (`/api/v1/meta` → `sources`)

`ingestion.live.freshness.source_freshness(session)` returns the `sources` array of the Meta schema (`SourceFreshness`, `docs/api/openapi.yaml`), computed from `ingestion_runs`. It needs no extra table, and API-01's meta service can return it as is.

| Field | From |
|---|---|
| `source` | `airnow` (runs as `airdata`), `purpleair` (only when enabled), `firms`, `nws_obs` |
| `last_success_at` | `finished_at` of the newest `success` or `partial` run |
| `latest_data_at` | newest `watermark` of those runs |
| `age_minutes` | now − `latest_data_at` |
| `stale` | no successful run, or the last one finished more than `stale_after_minutes` ago |

Thresholds, set with `FRESHNESS_STALE_AFTER_MINUTES_<SOURCE>`, default to about two missed runs: AirNow 150, NWS 150, FIRMS 90. A disabled source is left out of `sources` (the schema sets no minimum), so PurpleAir, off by default, is not reported and never shows as stale. When enabled, its default threshold follows the cadence: two runs plus 30 min. `stale` follows the job, not the data age, because a healthy FIRMS feed can go hours without a detection.

## Deploying

- **Set `LIVE_RETENTION_DELETE=1` on the deployed worker.** Without it retention only counts rows and nothing is ever deleted, so the live tables grow until the free Neon database is full. Leave it unset locally, where a dry run is the safe default.
- **Set `NWS_USER_AGENT` to the app name and a real contact**, e.g. `SmokeSense (team-inbox@yourdomain)`. NWS uses it to warn before blocking traffic, and the job refuses any value without an `@` or containing `example.com`.
- **Keys:** `FIRMS_MAP_KEY`, `AIRNOW_API_KEY` and `PURPLEAIR_API_KEY` in the worker's environment. A missing key fails only that source's runs.
- **PurpleAir is off by default.** Leave `LIVE_PURPLEAIR_EVERY_MINUTES` unset (or `0`); setting it to e.g. 120 costs about 0.5M points a day.
- **No always-on worker?** Every job is a plain command, so cron (or a scheduled GitHub Actions workflow) can run them directly from `backend/` with the same environment. Example crontab (UTC) matching the beat defaults:

  ```cron
  */30 * * * *  python -m ingestion.live firms
  25 * * * *    python -m ingestion.live airnow
  5 * * * *     python -m ingestion.live nws
  15 9 * * *    python -m ingestion.live retention
  ```

  Retention from cron still needs `LIVE_RETENTION_DELETE=1` (or `retention --delete`). Each command exits 1 when its run failed, and the run is recorded in `ingestion_runs` either way.

## Running locally

```bash
# worker and beat as separate processes (from backend/)
celery -A ingestion.tasks worker --loglevel=info
celery -A ingestion.tasks beat --loglevel=info
```

On macOS, start the worker with `--pool=threads`. The default prefork pool under macOS's spawn start method fails before any task code runs (`ValueError: not enough values to unpack`), and an embedded `worker --beat` fails to start. Linux and Docker are not affected.

Memory: a task holds one source's records at a time. NWS goes one station at a time, and writes are chunked by 1,000 rows. Nothing in `ingestion/` imports `ml/`, `xgboost` or `pandas` (`tests/test_live_jobs.py`).

## Tests

All tests use fixtures; none touches the network. The upsert, retention and freshness tests need Postgres: set `TEST_DATABASE_URL` to a database whose name ends in `_test`. It is dropped, recreated and migrated to head for each session. CI's backend job runs a PostGIS service for this. Without the variable, those tests are skipped.

```bash
TEST_DATABASE_URL=postgresql+psycopg://smokesense:smokesense@localhost:5433/smokesense_test pytest tests/test_live_*.py
```
