# Data Sources

SmokeSense combines four kinds of public U.S. data: active fires, weather, air quality (regulatory + low-cost sensors), and an operational smoke-forecast benchmark. This document is the reference for what each source provides, how to access it, and the gotchas.

All ingestion connectors live in `backend/ingestion/connectors/`. Every source's timestamps are normalized to **UTC** on the way in.

**Verifying access:** each source has a credential smoke test in `backend/ingestion/connectors/validate_<source>.py`. Run them after filling in `backend/.env` — see [§8 Validating credentials](#8-validating-credentials).

> **Two dates to know.** The details below were verified against the live APIs on **2026-09-20**.
> - AirNow retires its legacy zip/lat-long web services on **2026-09-30**. We already target the replacements — see [§3](#3-air-quality-regulatory--epa-airnow--airdata).
> - FIRMS near-real-time data only reaches back ~3 months. Historical training data needs the standard-processing products — see [§1](#1-active-fires--nasa-firms).

---

## 1. Active fires — NASA FIRMS

- **Provides:** satellite active-fire detections — latitude/longitude, detection time, sensor, confidence, and fire radiative power where available.
- **Sensors:** MODIS (long history), VIIRS (S-NPP, NOAA-20, NOAA-21) for higher resolution, plus LANDSAT and GOES products.
- **Role:** the primary live fire signal and the source of historical fire events.

### Access

| | |
|---|---|
| **Base URL** | `https://firms.modaps.eosdis.nasa.gov/api/` |
| **Auth** | `MAP_KEY` embedded **in the URL path** (not a header, not a query param) |
| **Get a key** | <https://firms.modaps.eosdis.nasa.gov/api/map_key/> — free, issued instantly by email |
| **Env var** | `FIRMS_MAP_KEY` |
| **Rate limit** | **5,000 transactions per 10-minute rolling window.** Large queries count as more than one transaction. |
| **Key status** | `https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?MAP_KEY=<key>` returns your current transaction count |

**Area endpoint** (what we use):

```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{day_range}[/{start_date}]
```

Bounding-box order is **west, south, east, north**. CONUS is `-125,24,-66.5,49.5`.

### Gotchas

- **Do not use the country endpoint for the USA.** FIRMS documents `/api/country/` as unreliable for large countries (USA, Canada, China, Russia) — the polygon is complex enough that the query times out. Use the area endpoint with a bounding box.
- **`day_range` is 1–5.** Anything larger returns `Invalid day range. Expects [1..5].` as a plain-text body under HTTP 200.
- **`day_range=1` means "the current UTC day so far"**, which is routinely *empty* in the early UTC hours and looks exactly like a broken key. Our validation script uses `2` for this reason.
- **An invalid MAP_KEY returns HTTP 200** with an error sentence in the body instead of CSV. Status code alone never proves the key works — inspect the body.
- These are *detections* (points), not fire *perimeters*. They are noisy and intermittent; keep detection-level data separate from any incident/perimeter data and aggregate carefully over time.

### NRT vs. SP — this shapes our training set

`https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/{MAP_KEY}/all` returns the window each product covers. As of 2026-09-20:

| Product | Coverage | Use |
|---|---|---|
| `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT` | 2026-07-01 → today | Live signal |
| `VIIRS_NOAA21_NRT` | 2024-01-17 → today | Live signal |
| `MODIS_NRT` | 2026-07-01 → today | Live signal |
| `GOES_NRT` | 2022-08-09 → today | Geostationary, high temporal resolution |
| `MODIS_SP` | 2000-11-01 → 2026-06-30 | **History** |
| `VIIRS_SNPP_SP` | 2012-01-20 → 2026-06-30 | **History** |
| `VIIRS_NOAA20_SP` | 2018-04-01 → 2026-06-30 | **History** |

**The near-real-time archive is a rolling ~3-month window.** Anything older must come from the standard-processing (`_SP`) products, which lag roughly 2–3 months behind today. Plan any backfill around that seam — you cannot train on years of `_NRT` data.

### Terms & attribution

FIRMS data is open and free. NASA asks for acknowledgement in publications and products:

> We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management System (FIRMS) (<https://earthdata.nasa.gov/firms>), part of NASA's Earth Observing System Data and Information System (EOSDIS).

---

## 2. Weather — NOAA / National Weather Service

- **Provides:** current observations and point-based hourly forecasts — wind speed/direction, temperature, humidity, pressure, precipitation.
- **Role:** the driver of smoke transport and dispersion. Wind direction relative to a fire is one of our most important features.

### Access

| | |
|---|---|
| **Base URL** | `https://api.weather.gov` |
| **Auth** | **No API key.** A descriptive `User-Agent` header is required instead. |
| **Env var** | `NWS_USER_AGENT` |
| **Rate limit** | Not published. Exceeding it returns an error that may be retried after ~5 seconds. Cache aggressively. |
| **Format** | GeoJSON by default; send `Accept: application/geo+json` |

**User-Agent format.** NWS asks for an application identifier *and* a contact address, so they can warn you before blocking traffic:

```
SmokeSense (dev@smokesense.local)
```

Use an address someone actually reads — NWS uses it to warn you before blocking traffic.

A bare email works, but the app-name form is what the docs ask for. Our validation script rejects a value with no `@` in it. It also rejects anything containing **`example.com`**, which is the natural first guess: that domain is one of the placeholder markers in `_common.py`, there to catch an `.env` copied from `.env.example` and never filled in.

**Point forecasts take two calls.** `/points/{lat},{lon}` resolves a coordinate to a forecast grid and returns URLs in `properties`:

- `forecast` — 12-hour periods, ~7 days
- `forecastHourly` — hourly periods, ~7 days
- `forecastGridData` — raw grid values

Cache the `/points` result (grids change rarely) but re-check periodically, as the docs advise.

### Gotchas

- US-only. A coordinate outside NWS coverage returns a `/points` response with no `forecast` URL.
- For **historical** weather, `api.weather.gov` is not the right tool — NOAA NCEI provides the climate/weather archive.

### Terms & attribution

Public U.S. Government data — open, free for any purpose, no usage fees and no attribution requirement stated.

---

## 3. Air quality (regulatory) — EPA AirNow / AirData

- **Provides:** PM2.5 and other pollutants from regulatory monitors, reporting-area metadata, NowCast AQI values and categories.
- **Role:** the **target variable** (what we predict) and live validation, plus the City Air Quality History view.

### ⚠️ Service migration — legacy endpoints retire 2026-09-30

AirNow released six replacement web services in June 2026 and retires six older ones on **2026-09-30**. Our connectors target the replacements. Three differences will bite anyone porting old sample code:

| | Legacy (retiring) | Current |
|---|---|---|
| Observations by zip | `/aq/observation/zipCode/current/` | `/aq/observation/current/ziplatLong` |
| Key parameter | `API_KEY` | `api_key` (lowercase) |
| `distance` param | accepted | **removed** — each reporting area has a fixed search radius |
| Response fields | `ParameterName`, `AQI`, `Category.Name`, `Latitude`, `Longitude` | `parameterName`, `nowcastAQI`, `aqiCategoryName` — **and no lat/lon at all** |

Losing `Latitude`/`Longitude` matters: monitor coordinates now have to come from reporting-area metadata or the monitoring-site services.

### Access

| | |
|---|---|
| **Base URL** | `https://www.airnowapi.org/aq` — **always https**; the API 301-redirects http, which would send the key over the wire in plaintext first |
| **Auth** | `api_key` query parameter |
| **Get a key** | <https://docs.airnowapi.org/account/request/> — free, email confirmation |
| **Env var** | `AIRNOW_API_KEY` |
| **Rate limit** | **500 requests per hour** for most endpoints. Over the limit you get no data until the next hour. Limits are **not adjustable**. |

Current services we care about:

- `/observation/current/ziplatLong` — by `zipCode`, or by `latitude` + `longitude`
- `/observation/current/racode` — by reporting-area code
- `/observation/historical/state` — historical by state
- `/aq/dailydata/` — daily observations by monitoring site, bounding box

### Gotchas

- **Errors arrive under HTTP 200.** AirNow reports problems as `{"WebServiceError":[{"Message":"..."}]}` with a 2xx status. Always check for that envelope.
- `hourObserved` labels an hour by its **end**: `23:00` means the period 22:00–22:59, local to the reporting area. `localTimeZone` is an abbreviation (`PDT`) that Python cannot parse directly.
- Observations for the previous hour post **10–30 minutes past the hour**.
- Regulatory monitors are spatially **sparse** (~1,000–1,400 sites nationally) — not enough label density on their own in fire-prone areas, which is why we add PurpleAir below.

### Terms & attribution — [EPA AirNow Data Exchange Guidelines](https://www.airnowapi.org/docs/DataUseGuidelines.pdf)

These are real obligations, and several of them constrain our UI, not just our ingestion:

1. **AirNow data are preliminary.** They are "not fully verified or validated… subject to change." They must not be used to support regulation, ascertain trends, or act as guidance. Validated regulatory data lives in EPA's Air Quality System (AQS).
2. **Products must say so.** "If observational data are used for analyses, displayed on web pages, or used for other programs or products, the analysis results, displays, or products must indicate that these data are preliminary." → the dashboard and City History view need a visible "preliminary data" notice.
3. **Credit the agency first**, then EPA AirNow. The owners of the data are the federal/state/local/tribal air quality agencies — the `reportingAgency` field names them. Agency list: <https://www.airnow.gov/partners/>
4. **Do not alter values.** Air quality data, forecast values, and advisory statements "should not be altered in any way and should be disseminated as received." Our *predictions* are clearly our own model output and must be labelled distinctly from reported AirNow observations.
5. **Use the official AQI colors** when displaying AQI values, per EPA's AQI Technical Assistance Document.
6. The API is "designed for end-user queries of specific areas, not for automated database population through loops of multiple requests." Cache; do not hammer it.
7. EPA asks that users notify them when products rely on these data, and return a signed acknowledgement form to `dmc@airnowtech.org`.

---

## 4. Air quality (low-cost) — PurpleAir

- **Provides:** dense PM2.5 from low-cost sensors, coordinates, timestamps, humidity/temperature.
- **Role:** fills in label density in fire-prone regions where regulatory monitors are sparse.

### Access

| | |
|---|---|
| **Base URL** | `https://api.purpleair.com/v1` |
| **Auth** | `X-API-Key` **request header** |
| **Get a key** | <https://develop.purpleair.com/> — request a **READ** key |
| **Env var** | `PURPLEAIR_API_KEY` |
| **Rate limit** | **Points-based billing**, not a request count — see below |

**Read vs. write keys are different.** A write key authenticates fine and then fails with **403** on `/v1/sensors`. If you get a 403 with a valid-looking key, you probably have the wrong kind.

**Sensors endpoint:**

```
GET /v1/sensors?fields=<csv>&location_type=0&nwlng=&nwlat=&selng=&selat=&max_age=
```

- `fields` is **required**.
- `location_type`: `0` = outside, `1` = inside. Only outdoor sensors are useful to us.
- Bounding box: `nwlng`/`nwlat` = north-west corner, `selng`/`selat` = south-east corner.
- `max_age` (seconds) drops sensors that have not reported recently.
- Response is **columnar**: a `fields` list plus a `data` array of positional rows. Zip them before use.

### Cost & rate limits

PurpleAir bills **points per field per sensor**, so a query's cost scales with how many fields you ask for. Per their [API Use Guidelines](https://community.purpleair.com/t/api-use-guidelines/1589):

- Request only the fields you need; per-field costs are on the pricing tab at <https://develop.purpleair.com/>.
- Sensors report every **two minutes** — polling faster than once a minute is wasted spend.
- Use `modified_since` to fetch only changed data.
- Do not re-query slow-moving metadata (name, coordinates, hardware, firmware).
- Space requests evenly rather than bursting.
- Large historical pulls across thousands of sensors: **contact PurpleAir** rather than looping the API.
- Running afoul of these can cost you API access outright.
- Sensor owners can query their own sensors for free.

### Critical: correct before training

Raw PurpleAir readings **over-report** during heavy wildfire smoke — exactly the regime we care about. Apply the **EPA (Barkjohn) correction** before use, the same correction EPA applies for the AirNow Fire and Smoke Map. **Never train on raw uncorrected PurpleAir data.**

*(Not yet implemented — tracked separately from the credential work in DATA-01.)*

### Terms & attribution

- [Data License](https://www.purpleair.com/license) and [Data Attribution](https://www.purpleair.com/attribution).
- API and database use requires a **link back to purpleair.com** plus **text attribution**; PurpleAir publishes logo files and an attribution PDF for format guidance.
- Attribution applies to any use of PurpleAir visual data or the API — including our dashboard.

---

## 5. Benchmark — NOAA HRRR-Smoke

- **Provides:** an operational U.S. smoke-concentration forecast (cycles extend to 48 hours).
- **Access:** NOAA HRRR-Smoke products. No key; distributed as gridded model output rather than a JSON API.
- **Role:** an **external benchmark** to compare against — *not* part of our core algorithm. We are not reproducing it; we compare our student-built forecast to it where fields can be aligned.

---

## 6. Summary table

| Data | Source | Base URL | Auth | Key / env var | Rate limit |
|---|---|---|---|---|---|
| Active fires | NASA FIRMS | `firms.modaps.eosdis.nasa.gov/api/` | key in URL path | `FIRMS_MAP_KEY` | 5,000 / 10 min |
| Weather | NOAA / NWS | `api.weather.gov` | `User-Agent` header | `NWS_USER_AGENT` | unpublished; cache |
| Air quality (regulatory) | EPA AirNow | `www.airnowapi.org/aq` | `api_key` query param | `AIRNOW_API_KEY` | 500 / hour |
| Air quality (low-cost) | PurpleAir | `api.purpleair.com/v1` | `X-API-Key` header | `PURPLEAIR_API_KEY` | points-based |
| Smoke benchmark | NOAA HRRR-Smoke | — | none | — | — |

---

## 7. Ingestion rules

Live APIs change, rate-limit, and occasionally go down. Every connector should:

- **Cache** source data and store **raw snapshots**, so a demo or a training run doesn't depend on a live call succeeding.
- **Retry with backoff** on transient failures.
- **Validate** fields on the way in and record source timestamps + identifiers, so we can audit exactly what was available at prediction time.
- **Normalize timestamps to UTC** — always.
- **Never trust the status code alone.** Both FIRMS and AirNow report failures under HTTP 200.

Keys never get committed. Add each key to `backend/.env.example` with a blank placeholder when you introduce a connector, so teammates know it's required.

---

## 8. Validating credentials

Each source has a standalone smoke test that loads `backend/.env`, makes one live call, prints the status code and a readable sample, and exits non-zero with a fixable message if anything is wrong.

```bash
cd backend
cp .env.example .env        # then fill in the four keys

python -m ingestion.connectors.validate_firms
python -m ingestion.connectors.validate_nws
python -m ingestion.connectors.validate_airnow
python -m ingestion.connectors.validate_purpleair
```

Inside Docker, substitute `docker compose exec backend python -m ingestion.connectors.validate_firms`.

These scripts prove connectivity only — they build no connector state and write nothing to the database. They mask credentials in all output, so their logs are safe to paste into an issue.
