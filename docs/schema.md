# SmokeSense — Database Schema

**docs/schema.md** · PM-01 deliverable · Revised after peer review

---

## Conventions

These apply to every table and column. Violations require reviewer sign-off.

| Convention | Rule |
| --- | --- |
| **Timestamps** | All `TIMESTAMPTZ` columns are **UTC**. No naive datetimes anywhere. `normalize.py` coerces every value before any row is written. |
| **Two-timestamp pattern** | `valid_at` = the time the data describes. `received_at` / `issued_at` = when the connector fetched it. Both are always stored where the distinction exists. |
| **PM2.5 units** | Always **µg/m³**. Never AQI integers. |
| **PM2.5 correction** | Three-value enum: `regulatory` (AirNow — always label-eligible), `purpleair_raw` (never a label), `purpleair_barkjohn` (EPA-corrected — label-eligible). Only `regulatory` or `purpleair_barkjohn` rows with `qa_flag = 'ok'` may be used as ML training labels or for verification. |
| **Coordinate system** | `GEOGRAPHY(POINT, 4326)` — WGS-84. Never bare lat/lon floats for spatial queries. |
| **Spatial indexes** | Every `GEOGRAPHY` column has a **GiST index**. Alembic autogenerate misses these — add by hand in the migration. |
| **Source IDs** | Every externally ingested row stores the provider's own identifier in `external_id` for idempotent deduplication. |
| **Experimental label** | Every `forecasts` row carries `is_experimental = TRUE`, enforced as a CHECK constraint. Never present model output as an official warning. |
| **No raw archives in Postgres** | Raw API snapshots go to `data/raw/` on disk (S3 in production). Postgres holds only normalized, validated rows. |
| **Primary keys** | **UUIDv7** (time-ordered, non-guessable) for all tables. Better B-tree performance on high-insert time-series tables than random v4. Generate in application layer until PostgreSQL 18 is available. |
| **Value lists** | `TEXT + CHECK` constraints instead of Postgres ENUMs. ENUMs are difficult to evolve in Alembic (can't remove values; adding has transaction caveats). Sensor/satellite lists grow as new platforms launch. |
| **Stored AQI categories** | Never stored on rows — computed at read time using `shared/aqi.py`. EPA revised PM2.5 AQI breakpoints in 2024 (Good/Moderate cutoff moved from 12.0 to 9.0 µg/m³); stored categories go stale. |
| **Soft-delete** | Reference rows are never hard-deleted. Set `active = FALSE` instead. |
| **Invariants** | Enforced by CHECK constraints in the DB, not only in docs. Code paths that skip validation can't corrupt data. |

---

## Retention Policy

The daily job order is strict: **(1) build `monitor_daily_pm25`, (2) run `forecast_verifications`, (3) drop old partitions.** Reversing steps 1 and 3 loses that day's data before it is saved.

| Table | Retention | Mechanism |
| --- | --- | --- |
| `observations` | \~72 h (4 daily partitions) | Drop partition |
| `fire_detections` | 7 days (8 daily partitions) | Drop partition |
| `weather_observations` | \~72 h | Drop partition |
| `weather_forecasts` | 3 days | Drop partition |
| `forecasts` | 30 days | Celery DELETE |
| `ingestion_runs` | 90 days | Celery DELETE |
| `forecast_points` (ad-hoc) | Deactivated after 90 days without requests | Celery UPDATE |
| Everything else | Forever | — |

Partitioned tables use `pg_partman` for daily range partitioning on `valid_at` / `detected_at`. Dropping a partition is instant and leaves no bloat — a `DELETE WHERE valid_at < now() - interval` on a hot table causes constant dead tuples and autovacuum churn.

---

## Live Database (PostgreSQL + PostGIS)

### ERD Summary

```
cities ──────────────────────────────────────────────────────────────┐
  │ 1:many                                                           │ 1:many
  ▼                                                                  ▼
forecast_points ──── 1:many ──► forecasts ──── FK ──► model_versions
  │                                │
  │ via point_weather_map          │ 1:many
  ▼                                ▼
weather_observations          forecast_verifications
weather_forecasts (via grid)
  │
forecast_points ──── 1:many ──► alerts

monitors ──── city_id FK ──► cities
  │ 1:many
  ▼
observations ──── (aggregated to) ──► monitor_daily_pm25
                                           │
                                           ▼
                                  city_monthly_aggregates ──── city_id FK ──► cities

fire_detections   (no FK — spatial relationship resolved in features/)
ingestion_runs    (standalone audit log)
model_versions    (standalone reference)
zip_codes         (lookup, FK to forecast_points once requested)
```

---

## 1. Reference Tables

---

### `cities`

City records used for the History view and as the stable join key replacing fragile `city TEXT` joins. Resolves the "St. vs Saint" and duplicate-city-name-across-states problems.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | TEXT | PK | UUIDv7 |
| `name` | TEXT | NOT NULL | e.g. `Sacramento` |
| `state` | TEXT | NOT NULL, CHECK (length = 2) | Two-letter code |
| `timezone` | TEXT | NOT NULL | IANA zone e.g. `America/Los_Angeles` — used for local-day averages and local solar hour feature |
| `geom` | GEOGRAPHY(POINT,4326) |  | City centre, optional, for map display |

**Indexes:** `PRIMARY KEY (id)`, `UNIQUE (name, state)`, `GiST (geom)`

---

### `zip_codes`

ZIP lookup loaded once from the Census ZCTA Gazetteer file. Maps ZIP code searches on the dashboard to a `forecast_point_id`.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `zcta` | TEXT | PK | Census ZCTA — PO-box-only ZIPs have none |
| `state` | TEXT | NOT NULL |  |
| `geom` | GEOGRAPHY(POINT,4326) |  | Centroid — can be 20+ km from a house in large rural ZIPs |
| `area_km2` | FLOAT |  | UI warns when ZIP is large |
| `forecast_point_id` | TEXT | FK → forecast_points(id), nullable | NULL until first requested |

**Indexes:** `PRIMARY KEY (zcta)`, `GiST (geom)`

---

### `forecast_points`

Every place the system can forecast for. Replaces `locations`. Supports city centres, ZIP centroids, H3 grid cells, and ad-hoc user points. The model only needs lat/lon — any point works.

User locations are snapped to an H3 cell (resolution 7, \~5 km²) so neighbours share a forecast and exact home locations are never stored.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | TEXT | PK | UUIDv7 |
| `kind` | TEXT | NOT NULL, CHECK IN ('city','zip','grid_cell','adhoc') |  |
| `label` | TEXT | NOT NULL | Display name: `"Sacramento, CA"`, `"95814"`, H3 cell id |
| `h3_cell` | TEXT |  | H3 cell identifier at resolution 7 |
| `city_id` | TEXT | FK → cities(id), nullable | NULL for rural points with no associated city |
| `geom` | GEOGRAPHY(POINT,4326) | NOT NULL | The point the model predicts for |
| `timezone` | TEXT | NOT NULL | IANA zone — used for local solar hour feature and display |
| `always_forecast` | BOOLEAN | NOT NULL, DEFAULT TRUE | TRUE = forecast every cycle. FALSE = only while users keep requesting it |
| `last_requested_at` | TIMESTAMPTZ |  | UTC — inference skips non-always points not requested in 7 days |
| `active` | BOOLEAN | NOT NULL, DEFAULT TRUE | Soft-disable flag |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | UTC |

**Indexes:** `PRIMARY KEY (id)`, `GiST (geom)`, `INDEX (city_id)`, `INDEX (always_forecast, last_requested_at)`

---

### `monitors`

Air quality stations — AirNow regulatory and PurpleAir low-cost sensors. Each physical station has one row. Readings link back here via `monitor_id` in `observations`. If a sensor moves >500 m, the old row is deactivated and a new row is inserted.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | TEXT | PK | UUIDv7 |
| `source` | TEXT | NOT NULL, CHECK IN ('airnow','purpleair') |  |
| `external_id` | TEXT | NOT NULL | AQS site code (AirNow) or `sensor_index` (PurpleAir) — dedup key |
| `name` | TEXT |  | Station name |
| `city_id` | TEXT | FK → cities(id), nullable | Which city this monitor counts toward in the History view |
| `location_type` | TEXT | NOT NULL, CHECK IN ('outdoor','indoor') | **Only `outdoor` sensors are used.** Indoor PurpleAir sensors read lower during smoke events and corrupt labels. Filter to `outdoor` at seed time. |
| `geom` | GEOGRAPHY(POINT,4326) | NOT NULL | Station coordinates — used for distance-to-point feature |
| `elevation_m` | FLOAT |  | Optional terrain feature |
| `active` | BOOLEAN | NOT NULL, DEFAULT TRUE | FALSE = retired or moved |
| `first_seen_at` | TIMESTAMPTZ | NOT NULL | UTC — when first seen at this location |
| `last_seen_at` | TIMESTAMPTZ |  | UTC — last time data arrived; used to detect dead sensors |

**Indexes:** `PRIMARY KEY (id)`, `UNIQUE (source, external_id)`, `GiST (geom)`, `INDEX (source, active, location_type)`

---

## 2. Live Time-Series Tables (Partitioned)

All tables in this section use **daily range partitioning** on their primary time column via `pg_partman`. Old partitions are dropped by the daily Celery job *after* rollups are built.

---

### `observations`

Hourly PM2.5 readings — one row per monitor per hour. Rolling \~72-hour window. The primary live PM2.5 signal used as model input and for real-time validation.

PurpleAir raw channel values (`pm25_cf1_a`, `pm25_cf1_b`) are stored so the Barkjohn correction can be rerun if EPA updates the formula. The corrected value goes in `pm25`.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `monitor_id` | TEXT | NOT NULL, FK → monitors(id) |  |
| `valid_at` | TIMESTAMPTZ | NOT NULL | UTC — start of the hour this reading averages. **Partition key.** |
| `received_at` | TIMESTAMPTZ | NOT NULL | UTC — when connector fetched it |
| `ingested_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | UTC — when row was written |
| `pm25` | FLOAT | NOT NULL, CHECK (pm25 >= 0) | µg/m³ — corrected value for PurpleAir, raw regulatory value for AirNow |
| `correction` | TEXT | NOT NULL, CHECK IN ('regulatory','purpleair_raw','purpleair_barkjohn') | Only `regulatory` or `purpleair_barkjohn` rows with `qa_flag = 'ok'` are label-eligible |
| `pm25_cf1_a` | FLOAT | CHECK (pm25_cf1_a >= 0) | PurpleAir channel A raw — stored for correction recompute |
| `pm25_cf1_b` | FLOAT | CHECK (pm25_cf1_b >= 0) | PurpleAir channel B raw |
| `rh_pct` | FLOAT | CHECK (rh_pct BETWEEN 0 AND 100) | Humidity at sensor — input to Barkjohn correction |
| `qa_flag` | TEXT |  | Quality flag: `ok`, `suspect`, `invalid`. Only `ok` rows are label-eligible. |
| `data_status` | TEXT | CHECK IN ('preliminary','validated') | `preliminary` = real-time AQS value. `validated` = final quality-assured value. |

**Primary Key:** `(monitor_id, valid_at)` — replaces UUID PK; this is the natural unique key and avoids a second index.

**Indexes:** `INDEX (valid_at DESC)` (partition pruning + rolling window trim), `GiST` index on monitors.geom handles spatial queries via join.

**Nullability note:** `pm25_cf1_a`, `pm25_cf1_b`, `rh_pct` are nullable — they are only populated for PurpleAir rows. AirNow rows leave them NULL.

---

### `fire_detections`

NASA FIRMS satellite hotspot detections. **A detection is a point, not a fire perimeter.** Aggregating detections into fire incidents happens in `features/`, not here. Detections can be noisy and superseded — the `product` column tracks whether a detection is live (URT/NRT) or archive-quality (SP), which matters for train/serve consistency.

FIRMS CSV/API rows carry no stable per-detection identifier, so `external_id` is synthesised as a hash of `(satellite, lat, lon, acq_date, acq_time)`.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | TEXT | PK | UUIDv7 |
| `external_id` | TEXT | NOT NULL | Hash of satellite+lat+lon+time — dedup key |
| `satellite` | TEXT | NOT NULL, CHECK IN ('MODIS_Terra','MODIS_Aqua','VIIRS_SNPP','VIIRS_NOAA20','VIIRS_NOAA21') | Splits MODIS Terra and Aqua, which have different overpass times |
| `product` | TEXT | NOT NULL, CHECK IN ('URT','RT','NRT','SP') | URT/RT/NRT = live. SP = archive (standard processing). Training uses SP; live inference sees NRT/URT. Track skew. |
| `geom` | GEOGRAPHY(POINT,4326) | NOT NULL | Pixel centre. **Partition key** (on `detected_at`). |
| `detected_at` | TIMESTAMPTZ | NOT NULL | UTC — satellite overpass time. **Partition key.** |
| `received_at` | TIMESTAMPTZ | NOT NULL | UTC — when connector fetched it |
| `ingested_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | UTC |
| `confidence_raw` | TEXT | NOT NULL | As returned by FIRMS: 0–100 integer (MODIS) or `l`/`n`/`h` (VIIRS). Store raw. |
| `confidence_level` | TEXT | NOT NULL, CHECK IN ('low','nominal','high') | Normalised — used in feature engineering |
| `frp_mw` | FLOAT | CHECK (frp_mw >= 0) | Fire radiative power in MW — proxy for intensity |
| `bright_t31_k` | FLOAT |  | Brightness temperature (K) — MODIS band 31 |
| `scan_km` | FLOAT | CHECK (scan_km > 0) | Pixel width in km |
| `track_km` | FLOAT | CHECK (track_km > 0) | Pixel height in km |
| `daynight` | TEXT | CHECK IN ('D','N') | Day or night overpass |

**Indexes:** `PRIMARY KEY (id)`, `UNIQUE (satellite, external_id)`, `GiST (geom)`, `INDEX (detected_at DESC)`

---

### `weather_observations`

Measured surface weather from NWS stations. One row per station per observation time.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `station_id` | TEXT | NOT NULL | NWS station identifier, e.g. `KSAC` |
| `valid_at` | TIMESTAMPTZ | NOT NULL | UTC — observation time. **Partition key.** |
| `received_at` | TIMESTAMPTZ | NOT NULL | UTC |
| `geom` | GEOGRAPHY(POINT,4326) | NOT NULL | Station coordinates |
| `wind_speed_ms` | FLOAT | CHECK (wind_speed_ms >= 0) | m/s |
| `wind_dir_deg` | FLOAT | CHECK (wind_dir_deg BETWEEN 0 AND 360) | Direction wind blows FROM. 0° = north. |
| `temp_c` | FLOAT |  | °C |
| `rh_pct` | FLOAT | CHECK (rh_pct BETWEEN 0 AND 100) | % |
| `pressure_hpa` | FLOAT | CHECK (pressure_hpa > 800) | hPa |
| `precip_1h_mm` | FLOAT | CHECK (precip_1h_mm >= 0) | mm |
| `qc_flag` | TEXT |  | NWS quality code. Values other than `V` (verified) or `C` (coerced) need review before use as features. |

**Primary Key:** `(station_id, valid_at)`

**Indexes:** `INDEX (valid_at DESC)`, `GiST (geom)`

---

### `weather_forecasts`

NWS hourly point forecasts. Kept separate from observations because `issued_at ≠ valid_at` — a forecast issued at 08:00 describes 20:00. For a given `valid_at` there will be multiple rows issued at different times (8h-ahead, 6h-ahead, 2h-ahead); the ML pipeline uses the most recent `issued_at` for that valid time.

NWS forecasts are keyed to a **grid cell** (e.g. `STO/41,68`), not a station. Wind speed comes as strings like "10 to 15 mph" — store the midpoint in m/s. Wind direction comes as compass text (NW) — store as degrees.

`weather_forecasts` cannot FK to `weather_observations` because the forecast is created before the observation exists.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `grid_id` | TEXT | NOT NULL | NWS grid, e.g. `STO/41,68` |
| `issued_at` | TIMESTAMPTZ | NOT NULL | UTC — when NWS issued this forecast |
| `valid_at` | TIMESTAMPTZ | NOT NULL | UTC — the future hour it describes. **Partition key.** |
| `received_at` | TIMESTAMPTZ | NOT NULL | UTC |
| `wind_speed_ms` | FLOAT | CHECK (wind_speed_ms >= 0) | Midpoint of NWS range string, converted to m/s |
| `wind_dir_deg` | FLOAT | CHECK (wind_dir_deg BETWEEN 0 AND 360) | Compass text converted to degrees |
| `temp_c` | FLOAT |  | °C |
| `rh_pct` | FLOAT | CHECK (rh_pct BETWEEN 0 AND 100) | % |
| `precip_prob_pct` | FLOAT | CHECK (precip_prob_pct BETWEEN 0 AND 100) | Rain probability |

**Primary Key:** `(grid_id, issued_at, valid_at)`

**Indexes:** `INDEX (valid_at DESC, issued_at DESC)`

---

### `point_weather_map`

Precomputed link from each `forecast_point` to its nearest NWS station and grid cell. Computed once at seed time and updated when new points are added. Eliminates spatial joins at inference time — inference reads this table to know which station and grid to use for each point.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `forecast_point_id` | TEXT | PK, FK → forecast_points(id) | One row per point |
| `station_id` | TEXT | NOT NULL | Nearest NWS station |
| `station_dist_km` | FLOAT | NOT NULL, CHECK > 0 | Distance in km — large values mean less reliable weather data |
| `grid_id` | TEXT | NOT NULL | NWS forecast grid containing the point |
| `computed_at` | TIMESTAMPTZ | NOT NULL | UTC — when this mapping was computed |

---

## 3. Durable Rollups

These tables are built **before** observations are trimmed and kept indefinitely. They are the only way to support multi-year City Air Quality History, since the live pipeline only starts collecting on launch day — past years must be backfilled from EPA AQS archival downloads.

---

### `monitor_daily_pm25`

Daily average PM2.5 per monitor. Built by the daily Celery job before partition drops. Backfilled from EPA AQS for historical years. `city_monthly_aggregates` reads from here, not from `observations`.

A day is considered complete when `hours_reported >= 18` (EPA convention for a valid daily average).

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `monitor_id` | TEXT | NOT NULL, FK → monitors(id) |  |
| `local_date` | DATE | NOT NULL | Day in the monitor's local time zone (EPA convention) |
| `correction` | TEXT | NOT NULL, CHECK IN ('regulatory','purpleair_barkjohn') | `purpleair_raw` is never rolled up |
| `mean_pm25` | FLOAT | NOT NULL, CHECK >= 0 | Daily mean µg/m³ |
| `max_pm25` | FLOAT | CHECK >= 0 | Highest hourly reading |
| `hours_reported` | INT | NOT NULL, CHECK BETWEEN 0 AND 24 | Hours with valid data this day |
| `computed_at` | TIMESTAMPTZ | NOT NULL | UTC |

**Primary Key:** `(monitor_id, local_date, correction)`

**Indexes:** `INDEX (local_date DESC)`, `INDEX (monitor_id, local_date DESC)`

---

### `city_monthly_aggregates`

Monthly PM2.5 statistics for the City Air Quality History view. Rebuilt monthly from `monitor_daily_pm25`. This is **descriptive history, not a forecast** — label it clearly in the UI.

`aqi_table_version` records which EPA breakpoint table was used when computing `unhealthy_days`, so stale values can be identified if EPA revises thresholds again.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | TEXT | PK | UUIDv7 |
| `city_id` | TEXT | NOT NULL, FK → cities(id) | FK replaces fragile `city TEXT` join |
| `year_month` | DATE | NOT NULL | First day of month, UTC e.g. `2023-07-01` |
| `source_scope` | TEXT | NOT NULL, CHECK IN ('regulatory','all_corrected') | `regulatory` = AirNow only (default — comparable across years). `all_corrected` = AirNow + Barkjohn-corrected PurpleAir (denser but only reliable post-2020). |
| `avg_pm25` | FLOAT | CHECK >= 0 | Monthly mean of daily averages, µg/m³ |
| `max_pm25` | FLOAT | CHECK >= 0 | Peak daily average |
| `p95_pm25` | FLOAT | CHECK >= 0 | 95th percentile of daily averages — less affected by single-sensor spikes |
| `unhealthy_days` | INT | CHECK >= 0 | Days where daily average PM2.5 exceeded **35.4 µg/m³** (top of USG, AQI 100; EPA 2024 table) |
| `data_coverage_pct` | FLOAT | CHECK BETWEEN 0 AND 100 | % of days with complete data (≥18 hours reported). Shown as coverage label in UI. |
| `monitor_count` | INT | CHECK > 0 | Monitors contributing this month |
| `aqi_table_version` | TEXT | NOT NULL | e.g. `epa-2024` — breakpoint table used for `unhealthy_days` |
| `computed_at` | TIMESTAMPTZ | NOT NULL | UTC — when last rebuilt |

**Indexes:** `PRIMARY KEY (id)`, `UNIQUE (city_id, year_month, source_scope)`, `INDEX (city_id, year_month DESC)`

---

## 4. Models and Predictions

---

### `model_versions`

One row per trained model. The model file lives in S3; this table holds metadata and the S3 location. The model is never updated in place — retraining creates a new version row.

To promote a model: set the old `production` row to `retired` and the new `shadow` row to `production` in a single transaction. Inference loads the row where `status = 'production'`.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `model_key` | TEXT | PK | `<model_name>/<version>` e.g. `pm25-forecaster/v1.2.0`. Matches the S3 folder. |
| `model_name` | TEXT | NOT NULL | Model family e.g. `pm25-forecaster` |
| `version` | TEXT | NOT NULL | Semantic version e.g. `v1.2.0` |
| `algorithm` | TEXT | NOT NULL | e.g. `xgboost` |
| `artifact_uri` | TEXT | NOT NULL | S3 path to model file |
| `artifact_sha256` | TEXT | NOT NULL | File checksum — inference verifies before loading |
| `hyperparameters` | JSONB |  | e.g. `{"n_estimators": 500, "max_depth": 6}` |
| `feature_list` | JSONB | NOT NULL | Ordered array of feature names the model expects — must match the Parquet contract |
| `training_data_uri` | TEXT |  | S3 path of the Parquet training snapshot |
| `training_data_hash` | TEXT |  | Hash of that snapshot — reproducibility audit |
| `backtest_metrics` | JSONB |  | MAE/RMSE per horizon and per pilot event |
| `status` | TEXT | NOT NULL, CHECK IN ('shadow','production','retired') | Max one `production` row per `model_name` — enforced by partial unique index |
| `notes` | TEXT |  | Free text: what changed in this version |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | UTC |
| `status_changed_at` | TIMESTAMPTZ |  | UTC — last status change |

**Indexes:** `PRIMARY KEY (model_key)`, `UNIQUE (model_name, version)`, `PARTIAL UNIQUE INDEX one_production ON model_versions (model_name) WHERE status = 'production'`

---

### `forecasts`

ML model output. The primary table the dashboard reads. Written only by `ml/inference` after each ingestion cycle. Never populated by an external API connector.

The `UNIQUE (forecast_point_id, model_key, issued_at, horizon_hours)` key allows a shadow model to run alongside the production model — `is_shadow = TRUE` rows are never shown to users or used for alerts.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | TEXT | PK | UUIDv7 |
| `forecast_point_id` | TEXT | NOT NULL, FK → forecast_points(id) | Renamed from `location_id` |
| `model_key` | TEXT | NOT NULL, FK → model_versions(model_key) | Replaces free-text `model_version` |
| `issued_at` | TIMESTAMPTZ | NOT NULL | UTC — when predicted. Features use only data available at this time. |
| `horizon_hours` | INT | NOT NULL, CHECK IN (1,3,6,12,24) |  |
| `target_time` | TIMESTAMPTZ | NOT NULL, CHECK (target_time = issued_at + make_interval(hours => horizon_hours)) | DB-enforced — can't drift |
| `pm25_predicted` | FLOAT | NOT NULL, CHECK >= 0 | µg/m³ |
| `pm25_lower` | FLOAT | CHECK >= 0 | Lower bound of prediction interval (stretch goal) |
| `pm25_upper` | FLOAT | CHECK >= 0 | Upper bound |
| `nearest_monitor_dist_km` | FLOAT | CHECK > 0 | UI shows lower confidence when large (e.g. >25 km). Copied from `point_weather_map` at write time. |
| `is_shadow` | BOOLEAN | NOT NULL, DEFAULT FALSE | TRUE = test model run. Never shown to users or used for alerts. |
| `is_experimental` | BOOLEAN | NOT NULL, DEFAULT TRUE, CHECK (is_experimental) | Always TRUE — DB rejects FALSE. |
| `feature_snapshot` | JSONB |  | Top 5–10 feature values for the "Why?" panel. Written once, read per forecast. |

**Indexes:** `PRIMARY KEY (id)`, `UNIQUE (forecast_point_id, model_key, issued_at, horizon_hours)`, `INDEX (forecast_point_id, issued_at DESC)` (dashboard: latest forecasts for this point), `INDEX (target_time)` (alert check: forecasts for the next 6 hours)

**Retention:** 30 days via Celery DELETE. Long enough to verify live accuracy (key capstone demo: "how accurate was the model last week?").

---

### `forecast_verifications`

Each forecast compared to what actually happened, once `target_time` passes. Values are **copied from the forecast row** so this table survives the 30-day forecast trim. The accuracy record lives here permanently.

Only verify when a monitor exists within 25 km — farther monitors produce misleading verification scores.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | TEXT | PK | UUIDv7 |
| `forecast_id` | TEXT |  | Original forecast id — may be NULL after 30-day trim |
| `forecast_point_id` | TEXT | NOT NULL | Copied from forecast |
| `model_key` | TEXT | NOT NULL | Copied from forecast |
| `horizon_hours` | INT | NOT NULL | Copied |
| `issued_at` | TIMESTAMPTZ | NOT NULL | Copied |
| `target_time` | TIMESTAMPTZ | NOT NULL | Copied |
| `pm25_predicted` | FLOAT | NOT NULL | What the model said |
| `pm25_observed` | FLOAT | NOT NULL, CHECK >= 0 | What was measured at `target_time` |
| `label_correction` | TEXT | NOT NULL | `regulatory` or `purpleair_barkjohn` — which monitor type provided the observed value |
| `label_monitor_dist_km` | FLOAT | NOT NULL | Distance to that monitor — filter to ≤25 km |
| `verified_at` | TIMESTAMPTZ | NOT NULL | UTC |

**Indexes:** `PRIMARY KEY (id)`, `INDEX (model_key, horizon_hours, target_time DESC)` (accuracy queries: MAE by model and horizon), `INDEX (forecast_point_id, target_time DESC)`

---

### `alerts`

Predicted threshold exceedances stored as **episodes**, not per-cycle rows. One open row exists per (point, severity) combination. It is updated each inference cycle while the exceedance continues and resolved when the forecast drops below the threshold.

This solves alert spam — without episodes, every hourly inference cycle creates a new alert row for the same ongoing smoke event.

The `forecast_id` FK is **nullable with `ON DELETE SET NULL`** — this is the fix for the critical FK-vs-retention conflict. When the 30-day forecast trim runs, `latest_forecast_id` becomes NULL; the alert row and its episode history are preserved. The trigger facts (`pm25_threshold`, `peak_pm25_predicted`, `horizon_hours`, `model_key`) are copied onto the alert at creation and never rely on the forecast row surviving.

A partial unique index enforces at most one open alert per point per severity.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | TEXT | PK | UUIDv7 |
| `forecast_point_id` | TEXT | NOT NULL, FK → forecast_points(id) |  |
| `severity` | TEXT | NOT NULL, CHECK IN ('moderate','unhealthy_sensitive','unhealthy','very_unhealthy','hazardous') | Thresholds from `shared/aqi.py` |
| `status` | TEXT | NOT NULL, CHECK IN ('open','resolved') | Episode state |
| `first_triggered_at` | TIMESTAMPTZ | NOT NULL | UTC — start of episode |
| `last_seen_at` | TIMESTAMPTZ | NOT NULL | UTC — last cycle where exceedance was still predicted |
| `resolved_at` | TIMESTAMPTZ |  | UTC — when forecast dropped back below threshold |
| `pm25_threshold` | FLOAT | NOT NULL | µg/m³ value crossed — copied at creation so meaning never changes if thresholds update |
| `aqi_table_version` | TEXT | NOT NULL | e.g. `epa-2024` — which breakpoint table was used |
| `peak_pm25_predicted` | FLOAT |  | Worst predicted value during this episode |
| `peak_target_time` | TIMESTAMPTZ |  | When the peak is predicted to occur |
| `horizon_hours` | INT |  | Horizon of the peak forecast |
| `model_key` | TEXT | NOT NULL | Model that raised the alert — copied at creation |
| `latest_forecast_id` | TEXT | FK → forecasts(id), nullable, ON DELETE SET NULL | Latest supporting forecast. NULL after 30-day trim — alert survives. |
| `is_experimental` | BOOLEAN | NOT NULL, DEFAULT TRUE, CHECK (is_experimental) | Always TRUE — alert is based on model prediction, not an official reading |

**Indexes:** `PRIMARY KEY (id)`, `PARTIAL UNIQUE INDEX one_open_alert ON alerts (forecast_point_id, severity) WHERE status = 'open'`, `INDEX (forecast_point_id, first_triggered_at DESC)`, `INDEX (latest_forecast_id)`

---

## 5. Operations

---

### `ingestion_runs`

One row per Celery ingestion job run. Powers the "data last updated X minutes ago" badge on the dashboard and makes debugging failed runs straightforward. `watermark` is the newest data timestamp seen in that run — dashboard freshness = `now() - max(watermark) WHERE status = 'success'`.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | TEXT | PK | UUIDv7 |
| `source` | TEXT | NOT NULL, CHECK IN ('firms','nws_obs','nws_fcst','airdata','purpleair') | Which connector ran |
| `started_at` | TIMESTAMPTZ | NOT NULL | UTC |
| `finished_at` | TIMESTAMPTZ |  | UTC — NULL while running |
| `status` | TEXT | NOT NULL, CHECK IN ('running','success','partial','failed') |  |
| `rows_fetched` | INT | CHECK >= 0 | Rows returned by the external API |
| `rows_written` | INT | CHECK >= 0 | Rows saved after validation |
| `watermark` | TIMESTAMPTZ |  | Newest data timestamp seen this run |
| `raw_path` | TEXT |  | Path to raw API response archive in `data/raw/` or S3 |
| `error` | TEXT |  | Error summary for failed runs — never expose raw stack traces externally |

**Indexes:** `PRIMARY KEY (id)`, `INDEX (source, started_at DESC)`, `INDEX (status, started_at DESC)`

**Retention:** 90 days via Celery DELETE.

---

## Parquet Training Set

Parquet files live in `data/processed/` and are read by `pd.read_parquet()` during training. They are **immutable snapshots** — running training twice on the same file produces the same result. Never queried by the web server.

### How rows are generated

Each row represents one **(forecast_point, issue_time, horizon_hours)** prediction moment from a pilot event window. All features are computed relative to **`issue_time`** (the moment the model would have made a prediction), never `target_time`. This prevents look-ahead leakage — see leakage rules below.

### Leakage rules (critical)

**`issue_time` is the reference point for all features.** `target_time = issue_time + horizon_hours`. Any feature that uses data from after `issue_time` leaks future information into training and inflates metrics.

- PM2.5 lags are relative to `issue_time`, not `target_time`. `pm25_lag_1h` = PM2.5 one hour before `issue_time`.
- Fire features (distance, FRP, bearing) are computed from detections available at `issue_time`.
- Weather must use **NWS forecast values issued before `issue_time`** for the `valid_at = target_time` slot — not observed weather at `target_time`. In training, use archived NWS forecast files, not observed weather at the target hour.

### Column contract

All columns below must be present with exactly these names and dtypes. Adding columns is fine; renaming or removing requires a schema migration note and ML owner sign-off.

| Column | dtype | Units | Notes |
| --- | --- | --- | --- |
| `forecast_point_id` | str | — | Matches `forecast_points.id`. Identifier only — not a model input. |
| `location_lat` | float32 | decimal degrees | WGS-84 |
| `location_lon` | float32 | decimal degrees | WGS-84 |
| `issue_time` | datetime64\[UTC\] | — | When the model "makes" the prediction. All lags and fire features are relative to this. |
| `target_time` | datetime64\[UTC\] | — | `issue_time + horizon_hours`. The hour being predicted. |
| `pilot_event_id` | str | — | Which fire event this row belongs to (from `pilot-events.md`). Used for grouped train/test split. |
| `horizon_hours` | int8 | — | 1, 3, 6, 12, or 24 |
| **Target variable** |  |  |  |
| `target_pm25` | float32 | µg/m³ | EPA Barkjohn-corrected or regulatory PM2.5 at `target_time`. Only `regulatory` or `purpleair_barkjohn` with `qa_flag = 'ok'`. Rows with no eligible monitor must be dropped. |
| `target_source` | str | — | `regulatory` or `purpleair_barkjohn` — audit trail for which monitor provided the label |
| `target_monitor_dist_km` | float32 | km | Distance from `forecast_point` to the monitor that provided the label. Filter out rows >25 km for weak labels. |
| **Fire features** (relative to `issue_time`) |  |  |  |
| `nearest_fire_dist_km` | float32 | km | Distance to nearest FIRMS detection available at `issue_time` |
| `fire_bearing_deg` | float32 | degrees | Direction from point to nearest fire (0° = north) |
| `fire_bearing_sin` | float32 | — | `sin(fire_bearing_deg)` — encode circular variable |
| `fire_bearing_cos` | float32 | — | `cos(fire_bearing_deg)` |
| `total_frp_200km` | float32 | MW | FRP-weighted, distance-decayed sum over all fires within 200 km at `issue_time` — better than nearest-only |
| `active_fire_count_200km` | int16 | count | FIRMS detection count within 200 km at `issue_time` |
| **Wind alignment** |  |  |  |
| `wind_alignment` | float32 | — | `cos(fire_bearing_deg - wind_dir_deg)`. +1 = wind from fire toward point. −1 = opposite. Computed from NWS **forecast** wind at `target_time`, not observed. |
| `wind_speed_ms` | float32 | m/s | NWS forecast value valid at `target_time` |
| `wind_dir_sin` | float32 | — | `sin(wind_dir_deg)` — encode circular variable |
| `wind_dir_cos` | float32 | — | `cos(wind_dir_deg)` |
| `temp_c` | float32 | °C | NWS forecast at `target_time` |
| `rh_pct` | float32 | % | NWS forecast at `target_time` |
| `pressure_hpa` | float32 | hPa |  |
| `precip_prob_pct` | float32 | % | NWS forecast probability |
| **PM2.5 lags** (all relative to `issue_time`) |  |  |  |
| `pm25_lag_1h` | float32 | µg/m³ | PM2.5 at `issue_time - 1h`. Barkjohn-corrected or regulatory. |
| `pm25_lag_3h` | float32 | µg/m³ |  |
| `pm25_lag_6h` | float32 | µg/m³ |  |
| `pm25_lag_12h` | float32 | µg/m³ |  |
| `pm25_lag_24h` | float32 | µg/m³ |  |
| **Temporal features** |  |  |  |
| `local_solar_hour` | float32 | 0–24 | Solar hour at the forecast point's longitude — better proxy for diurnal mixing than UTC hour across time zones |
| `day_of_year` | int16 | 1–366 | Seasonal signal |
| `month` | int8 | 1–12 |  |
| `smoke_season` | bool | — | TRUE if month in \[6,7,8,9,10\] |

### Null / missing value policy

| Condition | Action |
| --- | --- |
| `target_pm25` is NULL | **Drop row** — no label, no training row |
| `target_monitor_dist_km` > 25 km | **Drop row** — label too far to be meaningful |
| Fire features during periods with no nearby detections | **Fill with sentinels** defined in `features/README.md` (e.g. `nearest_fire_dist_km = 9999.0`, `total_frp_200km = 0.0`) |
| Weather features missing | **Flag and review** — do not forward-fill silently |

### Train / test split rule

**Split by `pilot_event_id` (grouped split), never randomly.** Adjacent hourly rows within the same event are highly correlated — a random split leaks future observations into training and produces inflated metrics. Each complete pilot event goes entirely into train, validation, or test — never split across sets.

---

## Open Questions (remaining after peer review)

| # | Question | Owner | Impact |
| --- | --- | --- | --- |
| 1 | What is the H3 resolution for `h3_cell`? Resolution 7 (\~5 km²) is proposed — confirm with geospatial engineer. | Geo + Backend | Affects `forecast_points` granularity and user privacy |
| 2 | PurpleAir bounding box for seeding: western US only, or all 50 states? Keep configurable in `config.py`. | Data engineer | Affects `monitors` seed size and ingestion cost |
| 3 | `feature_snapshot` in `forecasts`: confirmed as JSONB storing top 5–10 features only. No further action needed. | Resolved | — |
| 4 | `city_monthly_aggregates` `source_scope`: default to `regulatory` only (comparable across years). Optional `all_corrected` series with its own coverage label. | Resolved | — |
| 5 | Fire detection retention: confirmed 7 days (cheap, small rows). Historical event playback uses archived pilot event data, not the live window. | Resolved | — |