# Data Sources

SmokeSense combines four kinds of public U.S. data: active fires, weather, air quality (regulatory + low-cost sensors), and an operational smoke-forecast benchmark. This document is the reference for what each source provides, how to access it, and the gotchas.

All ingestion connectors live in `backend/ingestion/connectors/`. Every source's timestamps are normalized to **UTC** on the way in.

---

## 1. Active fires — NASA FIRMS

- **Provides:** satellite active-fire detections — latitude/longitude, detection time, sensor, confidence, and fire radiative power where available.
- **Sensors:** MODIS (long history), VIIRS (S-NPP, NOAA-20, NOAA-21) for higher resolution.
- **Access:** FIRMS US/Canada API. Requires a free **MAP_KEY** → `FIRMS_MAP_KEY` in `backend/.env`.
- **Latency:** real-time service within ~60 minutes of overpass; ultra-real-time can be under a minute for parts of the US/Canada.
- **Role:** the primary live fire signal and the source of historical fire events.
- **Note:** these are *detections* (points), not fire *perimeters*. They can be noisy or intermittent — keep detection-level data separate from any incident/perimeter data and aggregate carefully over time.

---

## 2. Weather — NOAA / National Weather Service

- **Provides:** current observations and point-based hourly forecasts — wind speed/direction, temperature, humidity, pressure, precipitation.
- **Access:** NWS API (`api.weather.gov`). **No API key**, but it requires a descriptive **User-Agent** identifying our app and a contact → `NWS_USER_AGENT` in `backend/.env`.
- **Role:** the driver of smoke transport and dispersion. Wind direction relative to a fire is one of our most important features.
- **Historical:** for historical weather, NOAA NCEI provides climate/weather data access.

---

## 3. Air quality (regulatory) — EPA AirNow / AirData

- **Provides:** PM2.5 from regulatory monitors, station coordinates, timestamps, AQI-derived labels.
- **Access:** AirNow API for current/forecast (requires `AIRNOW_API_KEY`); EPA AirData for historical monitoring data.
- **Role:** the **target variable** (what we predict) and live validation, plus the City Air Quality History view.
- **Note:** regulatory monitors are spatially **sparse** (~1,000–1,400 sites nationally). Not enough label density on their own in fire-prone areas — which is why we add PurpleAir below.

---

## 4. Air quality (low-cost) — PurpleAir

- **Provides:** dense PM2.5 from low-cost sensors, coordinates, timestamps.
- **Access:** PurpleAir API → `PURPLEAIR_API_KEY` in `backend/.env`.
- **Role:** fills in label density in fire-prone regions where regulatory monitors are sparse.
- **Critical note:** raw PurpleAir readings **over-report** during heavy wildfire smoke. Apply the **EPA (Barkjohn) correction** before use — the same correction EPA uses for the AirNow Fire and Smoke Map. Never train on raw uncorrected PurpleAir data.

---

## 5. Benchmark — NOAA HRRR-Smoke

- **Provides:** an operational U.S. smoke-concentration forecast (cycles extend to 48 hours).
- **Access:** NOAA HRRR-Smoke products.
- **Role:** an **external benchmark** to compare against — *not* part of our core algorithm. We are not reproducing it; we compare our student-built forecast to it where fields can be aligned.

---

## 6. Summary table

| Data | Source | Key needed | Role |
|---|---|---|---|
| Active fires | NASA FIRMS | `FIRMS_MAP_KEY` | Primary live fire signal + history |
| Weather | NOAA / NWS | User-Agent only | Smoke transport driver |
| Air quality (regulatory) | EPA AirNow / AirData | `AIRNOW_API_KEY` | Target variable + validation + history |
| Air quality (low-cost) | PurpleAir (EPA-corrected) | `PURPLEAIR_API_KEY` | Label density in fire-prone areas |
| Smoke benchmark | NOAA HRRR-Smoke | — | Comparison only |

---

## 7. Ingestion rules

Live APIs change, rate-limit, and occasionally go down. Every connector should:

- **Cache** source data and store **raw snapshots**, so a demo or a training run doesn't depend on a live call succeeding.
- **Retry with backoff** on transient failures.
- **Validate** fields on the way in and record source timestamps + identifiers, so we can audit exactly what was available at prediction time.
- **Normalize timestamps to UTC** — always.

Keys never get committed. Add each key to `backend/.env.example` with a placeholder when you introduce a connector, so teammates know it's required.
