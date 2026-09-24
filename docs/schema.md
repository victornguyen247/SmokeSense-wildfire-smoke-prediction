# SmokeSense — Database Schema

**docs/schema.md** · PM-01 deliverable · Last updated: Phase 0

---

## Conventions

These conventions apply to every table and every column in this schema. Violations require a reviewer sign-off.

| Convention | Rule |
| --- | --- |
| **Timestamps** | All `TIMESTAMPTZ` columns are stored in **UTC**. No naive datetimes anywhere. The application layer normalizes every timestamp to UTC on ingest before any row is written. |
| **Two-timestamp pattern** | Wherever data has a "what time does this reading describe" vs "when did we receive it" distinction, both are recorded. `valid_at` = the time the reading describes. `received_at` / `issued_at` = when the connector fetched it. The difference is essential for honest backtesting. |
| **PM2.5 units** | All PM2.5 values are stored in **µg/m³**. Never AQI integers. |
| **PM2.5 correction** | Every PM2.5 column that could originate from PurpleAir must be accompanied by a `correction` enum column (`raw` \| `barkjohn`). Only `barkjohn`-corrected values may be used as ML training labels. Raw PurpleAir values over-report during heavy wildfire smoke (Barkjohn et al., 2022). |
| **Coordinate system** | All geometry columns use **GEOGRAPHY(POINT, 4326)** — WGS-84, the same system as GPS and every live API in this project. Never store lat/lon as bare floats in columns that will be used in spatial queries. |
| **Spatial indexes** | Every `GEOGRAPHY` column must have a **GiST index**. Alembic autogenerate does not create these automatically — add them by hand in the migration. |
| **Source IDs** | Every row ingested from an external API stores that API's own identifier in `external_id`. This enables idempotent re-ingestion and deduplication. |
| **Experimental label** | Every `forecasts` row carries `is_experimental = TRUE`. The product may never present model output as an official warning. (Proposal §5.3, §8) |
| **No raw archives in Postgres** | Raw API snapshots are written to `data/raw/` on disk (S3 in production). Postgres holds only normalized, validated rows. |
| **Primary keys** | UUIDs (`gen_random_uuid()`) for all tables. Avoids leaking row-count information through sequential integers in API responses. |

---

## Live Database (PostgreSQL + PostGIS)

### ERD (Entity Relationship Map)

```
locations ──────────────────────────────────────────────────┐
    │                                                        │
    │ 1:many                                                 │ 1:many
    ▼                                                        ▼
forecasts ──── FK ──► locations                          alerts
    │
    │ FK
    ▼
city_monthly_aggregates  (keyed by city TEXT, not FK)

monitors ──── 1:many ──► observations

fire_detections   (no FK — spatial relationship only)
weather_observations  (no FK — tied to a lat/lon grid point, not a location row)
weather_forecasts     (same)
```

---

### Table: `locations`

Tracked prediction points — the set of places the dashboard generates forecasts for. Seeded manually via `db/seed.py`. Changes infrequently.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK, default `gen_random_uuid()` |  |
| `name` | TEXT | NOT NULL | Human label, e.g. `"Sacramento, CA"` |
| `city` | TEXT | NOT NULL | Used to join to `city_monthly_aggregates` |
| `state` | TEXT | NOT NULL | Two-letter code, e.g. `"CA"` |
| `geom` | GEOGRAPHY(POINT, 4326) | NOT NULL | PostGIS point — lat/lon in WGS-84 |
| `active` | BOOLEAN | NOT NULL, default `TRUE` | Soft-disable without deleting |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `now()` | UTC |

**Indexes:**

- `PRIMARY KEY (id)`
- `UNIQUE (name)`
- `GiST (geom)` — spatial index for distance queries

---

### Table: `monitors`

EPA AirNow regulatory stations and PurpleAir low-cost sensors. Seeded from AirNow's monitor list and a one-time PurpleAir bounding-box query. Updated infrequently (new monitors added, inactive ones soft-disabled).

> **Proposal §2.1 note:** Regulatory PM2.5 monitors are spatially sparse (\~1,000–1,400 sites nationally). PurpleAir densifies coverage in fire-prone western US. Both live here, distinguished by `source`.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK |  |
| `external_id` | TEXT | NOT NULL | AQS site code (AirNow) or sensor index (PurpleAir). Used for dedup on re-ingestion. |
| `source` | ENUM(`airnow`, `purpleair`) | NOT NULL | Determines which connector writes to this row and whether correction is required |
| `name` | TEXT |  | Station name where available |
| `geom` | GEOGRAPHY(POINT, 4326) | NOT NULL | Station coordinates — used for distance-to-location feature |
| `elevation_m` | FLOAT |  | Optional terrain feature (proposal §6.2 stretch) |
| `active` | BOOLEAN | NOT NULL, default `TRUE` |  |
| `first_seen_at` | TIMESTAMPTZ | NOT NULL | UTC — when this monitor first appeared in ingestion |

**Indexes:**

- `PRIMARY KEY (id)`
- `UNIQUE (source, external_id)` — deduplication key
- `GiST (geom)`
- `INDEX (source, active)` — connector queries filter by both

---

### Table: `observations`

Rolling \~72-hour PM2.5 observation window. The primary live signal used as model input. **Trimmed** — rows older than 72 hours are deleted by a scheduled Celery task. Long-term history lives in the Parquet file, not here.

> **Proposal §2.1:** Sources are EPA AirNow (authoritative, sparse) and EPA-corrected PurpleAir (dense, requires Barkjohn correction). Both land in this table. The `correction` column distinguishes them for ML feature selection.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK |  |
| `monitor_id` | UUID | FK → monitors(id), NOT NULL |  |
| `valid_at` | TIMESTAMPTZ | NOT NULL | UTC — the time this reading describes |
| `received_at` | TIMESTAMPTZ | NOT NULL | UTC — when the connector fetched it from the API |
| `ingested_at` | TIMESTAMPTZ | NOT NULL, default `now()` | UTC — when this row was written to Postgres |
| `pm25` | FLOAT | NOT NULL | µg/m³ |
| `correction` | ENUM(`raw`, `barkjohn`) | NOT NULL | `raw` = uncorrected PurpleAir or regulatory value. `barkjohn` = EPA correction applied. **Only `barkjohn` values are used as ML labels.** |
| `aqi_category` | TEXT |  | Optional: `Good`, `Moderate`, `USG`, `Unhealthy`, `Very Unhealthy`, `Hazardous` — derived from `shared/aqi.py` thresholds |

**Indexes:**

- `PRIMARY KEY (id)`
- `UNIQUE (monitor_id, valid_at)` — prevents duplicate readings per station per hour
- `INDEX (valid_at DESC)` — ingestion and feature queries always filter by recent time
- `INDEX (monitor_id, valid_at DESC)` — lag-feature queries scan by monitor

**Retention:** Celery task deletes rows where `valid_at < NOW() - INTERVAL '72 hours'` on each ingestion cycle.

---

### Table: `fire_detections`

NASA FIRMS active-fire satellite detection points. Rolling \~72-hour window.

> **Proposal §2.1:** Sources are MODIS (from 2000) and VIIRS (S-NPP from 2012, NOAA-20 from 2018, NOAA-21 from 2024). US/Canada ultra-real-time detections can arrive within 60 seconds of satellite overpass.
> 
> **Proposal §12 risk note:** "Fire detections ≠ fire perimeter — satellite points can be noisy or intermittent. Keep detection-level data separate from incident/perimeter layers; aggregate carefully across time." Do not aggregate detections into a single "fire" row here — that is the feature engineering layer's job.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK |  |
| `external_id` | TEXT | NOT NULL | FIRMS detection identifier — for dedup |
| `geom` | GEOGRAPHY(POINT, 4326) | NOT NULL | Satellite detection point |
| `detected_at` | TIMESTAMPTZ | NOT NULL | UTC — satellite overpass time as reported by FIRMS |
| `received_at` | TIMESTAMPTZ | NOT NULL | UTC — when connector fetched this detection |
| `ingested_at` | TIMESTAMPTZ | NOT NULL, default `now()` | UTC |
| `sensor` | ENUM(`MODIS`, `VIIRS_SNPP`, `VIIRS_NOAA20`, `VIIRS_NOAA21`) | NOT NULL | Different sensors have different confidence scales and spatial resolution |
| `confidence` | TEXT | NOT NULL | Raw confidence value as returned by FIRMS — varies by sensor (`low`/`nominal`/`high` for VIIRS; 0–100 integer for MODIS). Store raw, interpret in feature engineering. |
| `frp` | FLOAT |  | Fire radiative power in megawatts (MW). Available from VIIRS; not always present for MODIS. Proxy for fire intensity. |
| `bright_t31` | FLOAT |  | Brightness temperature (Kelvin) — MODIS band 31. Additional intensity signal. |

**Indexes:**

- `PRIMARY KEY (id)`
- `UNIQUE (sensor, external_id)` — deduplication key
- `GiST (geom)` — spatial index for `ST_DWithin` queries ("fires within 300km of this location")
- `INDEX (detected_at DESC)` — rolling window trim and feature queries

**Retention:** Same 72-hour trim policy as `observations`.

---

### Table: `weather_observations`

Current NWS surface observations. Keyed to a grid point, not a `locations` row. Different from `weather_forecasts`, as it only captures current data.

> **Proposal §2.1:** NOAA/NWS provides wind speed/direction, temp, humidity, pressure, precipitation. Wind direction relative to a fire is one of the most important ML features (proposal §6.2 "wind alignment").

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK |  |
| `station_id` | TEXT | NOT NULL | NWS station identifier, e.g. `KSAC` |
| `geom` | GEOGRAPHY(POINT, 4326) | NOT NULL | Station coordinates |
| `valid_at` | TIMESTAMPTZ | NOT NULL | UTC — observation time |
| `received_at` | TIMESTAMPTZ | NOT NULL | UTC — when fetched |
| `wind_speed_ms` | FLOAT |  | m/s |
| `wind_dir_deg` | FLOAT |  | Meteorological degrees — 0° = wind FROM north, 90° = wind FROM east |
| `temp_c` | FLOAT |  | Celsius |
| `rh_pct` | FLOAT |  | Relative humidity, 0–100 |
| `pressure_hpa` | FLOAT |  | hPa |
| `precip_1h_mm` | FLOAT |  | 1-hour precipitation accumulation, mm |

**Indexes:**

- `PRIMARY KEY (id)`
- `UNIQUE (station_id, valid_at)`
- `GiST (geom)`
- `INDEX (valid_at DESC)`

---

### Table: `weather_forecasts`

Hourly NWS point forecast. Separate from observations because a forecast issued now describes conditions 6 hours from now.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK |  |
| `station_id` | TEXT | NOT NULL | NWS grid point or station |
| `geom` | GEOGRAPHY(POINT, 4326) | NOT NULL |  |
| `issued_at` | TIMESTAMPTZ | NOT NULL | UTC — when NWS issued this forecast |
| `valid_at` | TIMESTAMPTZ | NOT NULL | UTC — the future time this forecast describes |
| `wind_speed_ms` | FLOAT |  |  |
| `wind_dir_deg` | FLOAT |  |  |
| `temp_c` | FLOAT |  |  |
| `rh_pct` | FLOAT |  |  |
| `precip_prob_pct` | FLOAT |  | Precipitation probability 0–100 |

**Indexes:**

- `PRIMARY KEY (id)`
- `UNIQUE (station_id, issued_at, valid_at)`
- `GiST (geom)`
- `INDEX (valid_at DESC)`

---

### Table: `forecasts`

ML model output. The primary table the web server reads to serve the dashboard. Written exclusively by `ml/inference` after each ingestion cycle.

> **Proposal §8:** Forecast card shows predicted PM2.5 for 1/3/6/12/24 hours. Predictions must be clearly labeled as experimental (§5.3, §8). `model_version` enables audit when the model is retrained.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK |  |
| `location_id` | UUID | FK → locations(id), NOT NULL |  |
| `issued_at` | TIMESTAMPTZ | NOT NULL | UTC — when this forecast was computed |
| `target_time` | TIMESTAMPTZ | NOT NULL | UTC — the future time being predicted |
| `horizon_hours` | INT | NOT NULL | One of: `1`, `3`, `6`, `12`, `24` (proposal §5.1) |
| `pm25_predicted` | FLOAT | NOT NULL | µg/m³ — model point estimate |
| `pm25_lower` | FLOAT |  | Lower bound of confidence interval (stretch goal §14) |
| `pm25_upper` | FLOAT |  | Upper bound of confidence interval |
| `aqi_category_predicted` | TEXT |  | Derived from `shared/aqi.py` — never hardcoded here |
| `model_version` | TEXT | NOT NULL | e.g. `"xgb-v1.0"` — audit trail for retraining |
| `is_experimental` | BOOLEAN | NOT NULL, default `TRUE` | Product requirement — must always be `TRUE`. UI uses this flag to display the "experimental, not an official warning" disclaimer. |
| `feature_snapshot` | JSONB |  | Optional: key input feature values at prediction time — supports the "Why?" panel (proposal §8) |

**Indexes:**

- `PRIMARY KEY (id)`
- `UNIQUE (location_id, issued_at, horizon_hours)` — one forecast per location per issue time per horizon
- `INDEX (location_id, issued_at DESC)` — dashboard query: "latest forecasts for this location"
- `INDEX (target_time)` — alert query: "all forecasts for the next 6 hours"

---

### Table: `city_monthly_aggregates`

Precomputed monthly PM2.5 statistics per city. Powers the City Air Quality History view (proposal §5.2, §8). Rebuilt monthly by a scheduled Celery task — not written by connectors.

> **Proposal §5.2:** Shows multi-year PM2.5 trend, seasonal smoke pattern, count of unhealthy-AQI days per year, with clear data-coverage labeling. Must be presented as **descriptive history, not a forecast**.

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK |  |
| `city` | TEXT | NOT NULL | Matches `locations.city` |
| `state` | TEXT | NOT NULL |  |
| `year_month` | DATE | NOT NULL | First day of the month, UTC — e.g. `2023-07-01` |
| `avg_pm25` | FLOAT |  | Monthly mean µg/m³ across all monitors in the city |
| `max_pm25` | FLOAT |  | Peak reading in the month |
| `p95_pm25` | FLOAT |  | 95th percentile — less affected by single-sensor spikes than max |
| `unhealthy_days` | INT |  | Days where daily average PM2.5 exceeded **35 µg/m³** (EPA 24-hour NAAQS standard; corresponds to AQI 100). Threshold sourced from `shared/aqi.py`. |
| `data_coverage_pct` | FLOAT |  | % of hourly slots with ≥1 reading — used for the "coverage labeling" requirement in proposal §5.2 |
| `monitor_count` | INT |  | Number of monitors contributing data this month |
| `computed_at` | TIMESTAMPTZ | NOT NULL | UTC — when this aggregate was last rebuilt |

**Indexes:**

- `PRIMARY KEY (id)`
- `UNIQUE (city, state, year_month)`
- `INDEX (city, state, year_month DESC)` — history view query

---

### Table: `alerts`

Threshold-exceedance records generated when a forecast crosses an AQI risk level. Thresholds are defined in `shared/aqi.py`

> **Proposal §8:** "Alert workflow for threshold exceedance, clearly labeled as a model prediction rather than an official warning."

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK |  |
| `location_id` | UUID | FK → locations(id), NOT NULL |  |
| `forecast_id` | UUID | FK → forecasts(id), NOT NULL | The specific forecast row that triggered this alert |
| `severity` | ENUM(`moderate`, `unhealthy_sensitive`, `unhealthy`, `very_unhealthy`, `hazardous`) | NOT NULL | Maps to AQI breakpoints in `shared/aqi.py` |
| `pm25_threshold` | FLOAT | NOT NULL | The µg/m³ value that was crossed — stored so alert meaning doesn't change if thresholds are updated later |
| `triggered_at` | TIMESTAMPTZ | NOT NULL | UTC |
| `acknowledged_at` | TIMESTAMPTZ |  | UTC — nullable; set when a user dismisses the alert |
| `is_experimental` | BOOLEAN | NOT NULL, default `TRUE` | Mirrors `forecasts.is_experimental` — alert is based on a model prediction, not an official reading |

**Indexes:**

- `PRIMARY KEY (id)`
- `INDEX (location_id, triggered_at DESC)`
- `INDEX (forecast_id)`

---

## Retention and Maintenance Schedule

| Table | Retention | Who trims |
| --- | --- | --- |
| `observations` | Rolling 72 hours | Celery task, each ingestion cycle |
| `fire_detections` | Rolling 72 hours (pending answer to Open Question #5) | Celery task |
| `weather_observations` | Rolling 72 hours | Celery task |
| `weather_forecasts` | Trim issued forecasts older than 48 hours | Celery task |
| `forecasts` | Rolling 48 hours (older forecasts superseded by newer runs) | Celery task |
| `alerts` | Keep indefinitely (small table, audit value) | Never trimmed |
| `city_monthly_aggregates` | Keep indefinitely; rebuild entire city window monthly | Celery monthly task |
| `locations` / `monitors` | Never trimmed — soft-disable with `active = FALSE` | Manual |