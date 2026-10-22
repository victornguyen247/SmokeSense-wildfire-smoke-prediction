# SmokeSense API (v1, MVP)

The yet to be agreed contract between the frontend and backend (PM-02). Both sides build against it, so neither waits on the other.

| File | What it is |
|---|---|
| [`api/openapi.yaml`](api/openapi.yaml) | OpenAPI 3.1 spec: every endpoint, parameter, response and error |
| [`api/fixtures/*.json`](api/fixtures/) | One realistic response per endpoint (Park Fire, see [Fixtures](#fixtures)) |
| [`api/validate.py`](api/validate.py) | Validates the spec, then every fixture against it. Runs in CI (`api-spec` job) |
| [`api/gen_fixtures.py`](api/gen_fixtures.py) | Generates the fixtures. CI reruns it and fails if the output differs from the committed fixtures |

Forecast semantics come from the PM-03 serving contract ([`ml/serving-contract.md`](ml/serving-contract.md)): the model runs at AirNow monitors (Stage A), and grid cells are interpolated from them (Stage B). The grid is GEO-02's ([`backend/docs/forecast_grid.md`](../backend/docs/forecast_grid.md)).

## Endpoints

| Endpoint | Returns | Format |
|---|---|---|
| `GET /api/v1/grid/cells?bbox=` | Grid cell polygons. Static: fetch once and cache | GeoJSON |
| `GET /api/v1/forecast/grid?bbox=` | Interpolated forecast per grid cell, all horizons, keyed by cell `id` | JSON |
| `GET /api/v1/forecast/point?lat=&lon=` or `?zip=` | The location's cell forecast for all horizons, plus the nearest monitor's forecast and distance | JSON |
| `GET /api/v1/forecast/monitors?bbox=` | Model forecasts at AirNow monitors, all horizons | GeoJSON |
| `GET /api/v1/fires/active?bbox=` | VIIRS SNPP fire detections, last 72 h | GeoJSON |
| `GET /api/v1/observations/pm25/latest?bbox=` | Latest reading per outdoor sensor, at most 2 h old | GeoJSON |
| `GET /api/v1/meta` | Active model, latest forecast cycle, per-source freshness, display thresholds, AQI legend | JSON |
| `GET /health`, `GET /api/v1/health` | Liveness | JSON |

Alerts and city history are Phase 4 and not in this version.

## Conventions

### Versioning

- Everything is under `/api/v1`. `/health` also stays at the root for existing deploy checks.
- Within v1, changes are additive only: new endpoints, new optional parameters, new response fields, new enum values. Clients must ignore fields they don't know.
- Removing or renaming a field, or changing a type or meaning, needs `/api/v2`.
- Response schemas are strict (`additionalProperties: false`) so fixtures can't drift. Adding a field means updating the spec and the fixtures in the same PR.

### Time

- Every timestamp is **ISO-8601 in UTC with a `Z` suffix**: `2024-07-27T18:00:00Z`. Never local time and never an offset. The spec enforces this.
- `issued_at` is the top of the UTC hour the forecast cycle was issued for. `target_time = issued_at + horizon_hours`.
- Horizons are always `1, 3, 6, 12, 24` hours.
- The frontend converts to local time for display (California: `America/Los_Angeles`).

### Units and rounding

| Quantity | Unit | Rounding |
|---|---|---|
| PM2.5 (`pm25`) | µg/m³ | **truncated** to 0.1 (see [AQI categories](#aqi-categories)) |
| Distances (`*_km`) | km, great-circle | rounded to 0.1 |
| Fire radiative power (`frp_mw`) | MW | rounded to 0.1 |
| Coordinates | WGS84 decimal degrees | 5 decimals (~1 m) |

Units are fixed by field name and never sent per value.

### Coordinates and `bbox`

- GeoJSON coordinates are `[lon, lat]`. Non-GeoJSON objects use `{"lat": …, "lon": …}`.
- `bbox` is `minLon,minLat,maxLon,maxLat`, the GeoJSON order. Example: `-122.95,39.40,-121.50,40.10`.
- `bbox` is optional everywhere and defaults to all of California. It is clipped to California, and the clipped value is echoed back where relevant. A bbox or point entirely outside California returns 404 `out_of_scope`.

### IDs

- `forecast_point_id` (and `id` on grid cells) is `forecast_points.id`, an **opaque string**: compare it, never parse it or assume it is a UUID.
- Grid cell ids come from GEO-02, e.g. `grid-ca-epsg3310-12500m-r+000015-c-000013-p00`. The same id is used by `/grid/cells`, `/forecast/grid` and `/forecast/point`.

### CORS

The API allows the frontend origins listed in the `CORS_ALLOWED_ORIGINS` env var (comma-separated): local dev (`http://localhost:5173`), staging and production. Only `GET` is allowed, and no credentials. The default is the two local dev origins (`localhost` and `127.0.0.1`); add staging and production in that environment's `.env`.

### Errors

Every error, from every endpoint, has the same body:

```json
{ "code": "out_of_scope", "message": "Point (45.52, -122.68) is outside California; SmokeSense only forecasts for California." }
```

`code` is stable and meant for code to check. `message` is for people and may change.

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid_query` | Missing or conflicting parameters, e.g. both `lat`/`lon` and `zip`, or `lat` without `lon` |
| 400 | `invalid_bbox` | `bbox` is malformed, or min > max |
| 404 | `out_of_scope` | Location or bbox is outside California |
| 404 | `zip_not_found` | No ZCTA for that ZIP (e.g. a PO-box-only ZIP) |
| 404 | `not_found` | Unknown route |
| 503 | `forecast_unavailable` | No forecast cycle exists yet |
| 500 | `internal_error` | Unexpected failure. The message never contains a stack trace |

Parameter validation errors are **400, not 422**. FastAPI's default is `422 {"detail": [...]}`, so the backend must register exception handlers for `RequestValidationError`, `HTTPException` and unhandled exceptions that return this shape. See [`error_invalid_query.json`](api/fixtures/error_invalid_query.json). `validate.py` checks that every 4xx/5xx response in the spec uses this one `Error` schema.

### How a forecast was made: `method` and `source`

Every forecast value says how it was produced:

| `method` | `source` | Meaning | UI |
|---|---|---|---|
| `model` | `persistence` | At a monitor: the last reading carried forward (the 1 h horizon serves persistence) | normal |
| `model` | `v2` | At a monitor: baseline_v2 | normal |
| `model` | `fallback` | At a monitor with no reading in the last 6 h: the v1 model on weather and fire only | **lower confidence** |
| `interpolated` | `idw` | At a grid cell: inverse-distance-weighted mean of up to 4 monitors within 50 km | lower confidence when `nearest_monitor_dist_km > 25` |

- `method` is enough for most UI logic. `source` adds detail, mainly to flag `fallback`.
- Observations use `provider` (`airnow` / `purpleair`) for the sensor network, so the word `source` only ever means how a forecast was made.
- Every forecast carries `issued_at`, `model_key` and `nearest_monitor_dist_km` (0 at a monitor). `issued_at` and `model_key` are on the response; `nearest_monitor_dist_km` is on each value.
- For a cell, `nearest_monitor_dist_km` is the distance from the cell centroid to the nearest monitor Stage B used: `v2` or `persistence` only, because `fallback` monitors never feed a cell. It is NOT NULL in `forecasts` (PM-03).
- Shadow-model forecasts are never returned.
- **Cells with no forecast.** A grid cell has no forecast when no eligible monitor is within 50 km.
  - `/forecast/grid` leaves those cells out of that horizon; draw them as "no data".
  - `/forecast/point` returns 200 with `cell.has_forecast: false`, `cell.no_forecast_reason: "no_monitor_within_50km"`, `cell.nearest_monitor_dist_km` (with no 50 km limit) and the nearest monitor's own forecast. See [`forecast_point_no_forecast.json`](api/fixtures/forecast_point_no_forecast.json).
- No prediction intervals (`pm25_lower` / `pm25_upper`) and no alert flags (`exceeds`) in v1.

### Display thresholds and labels

`/meta` returns every threshold and label the UI needs, so no screen hard-codes them:

| Field | Value | Use |
|---|---|---|
| `low_confidence_dist_km` | 25 | Show a cell forecast as lower confidence above this `nearest_monitor_dist_km` |
| `max_interpolation_dist_km` | 50 | Stage B radius; beyond it a cell has no forecast |
| `forecast_stale_after_minutes`, `sources[].stale_after_minutes` | provisional | Stale badges; `forecast_stale` and `sources[].stale` are already computed |
| `aqi_category_label` | `AQI category (hourly PM2.5)` | Label for `aqi_category` on every screen |
| `aqi_categories` | the table below | Legend |

### AQI categories

- `aqi_category` is computed at read time from `pm25` with `backend/shared/aqi.py`. It is never stored.
- Responses carry `aqi_table_version` (currently `epa-2024`), so a future EPA revision is visible.
- The PM2.5 value is **truncated to 0.1 µg/m³** before the breakpoints are applied, as EPA and AirNow do (9.05 is Good and 35.46 is Moderate; rounding would put both one category too high). `pm25` is returned truncated too, so the number and the color always agree and a client can recompute the category from the table. Both bounds below are inclusive.
- `/meta` returns the same table as `aqi_categories`; use it for the legend instead of hard-coding it.

| `key` | Label | Color | PM2.5 µg/m³ |
|---|---|---|---|
| `good` | Good | `#00E400` | 0.0 – 9.0 |
| `moderate` | Moderate | `#FFFF00` | 9.1 – 35.4 |
| `unhealthy_sensitive` | Unhealthy for Sensitive Groups | `#FF7E00` | 35.5 – 55.4 |
| `unhealthy` | Unhealthy | `#FF0000` | 55.5 – 125.4 |
| `very_unhealthy` | Very Unhealthy | `#8F3F97` | 125.5 – 225.4 |
| `hazardous` | Hazardous | `#7E0023` | ≥ 225.5 |

The category comes from an **hourly** value, while the official AQI uses 24 h or NowCast averages. The UI should label it with `aqi_category_label` ("AQI category (hourly PM2.5)") and must not show a numeric AQI; v1 doesn't return one.

## Endpoint rules

### `/grid/cells` and `/forecast/grid`: geometry once, values per cycle

The grid is GEO-02's: about 3,000 squares of 12.5 km in California Albers (EPSG:3310), clipped to the state boundary. A square cut by the coastline becomes several cells (`-p00`, `-p01`, …).

- `/grid/cells` returns one GeoJSON Polygon per cell (`forecast_points.cell_geom`, WGS84), with only `id` in `properties`. The grid only changes when GEO-02 is regenerated, which changes `grid_key`. The response is sent with `Cache-Control: public, max-age=86400` and an `ETag`. The frontend fetches it once and refetches only when `/meta` `grid_key` differs from the cached one.
- `/forecast/grid` returns no geometry: per horizon, a list of `{id, pm25, aqi_category, nearest_monitor_dist_km}`. All five horizons come in one response, so the horizon slider is a client-side swap (e.g. `setFeatureState` keyed by `id`).
- A cell from `/grid/cells` that is missing from a horizon has no forecast at that horizon; draw it as "no data".
- `method` / `source` (always `interpolated` / `idw`) are sent once on the response.

| | Cells | Raw JSON | gzip |
|---|---|---|---|
| Fixture `/grid/cells` (Clear Lake NF → Paradise) | 77 | 18.9 KB | 1.9 KB |
| Fixture `/forecast/grid`, 5 horizons | 62 with a forecast | 40.4 KB | 2.3 KB |
| Whole California `/grid/cells`, once | ~3,000 | ~0.75 MB, more with coastline vertices | ~0.15 MB (estimated) |
| Whole California `/forecast/grid`, upper bound | ~3,000 × 5 | ~2 MB | ~0.25 MB (estimated) |

- Measured on compact JSON: ~245 bytes per cell polygon, ~130 bytes per cell per horizon.
- The `/forecast/grid` figure is an upper bound. Cells with no monitor within 50 km are left out, so the real count is lower.
- The server must send `Content-Encoding: gzip` (or brotli).

### `/forecast/point`

- Pass **either** `lat` + `lon` **or** `zip`.
- The location snaps to the grid cell that covers it (GEO-02's `lookup_grid_forecast_point`). That cell's forecast is returned for all horizons, ordered 1, 3, 6, 12, 24.
- A ZIP resolves to its Census ZCTA centroid. `query.zip_area_km2` is returned so the UI can warn that a large ZIP's centroid may be far from the user.
- No forecast point is ever created by a request.
- **The two distances are intentionally different.**
  - The cell's distances (`cell.nearest_monitor_dist_km`, `cell.forecasts[].nearest_monitor_dist_km`) are from the **cell centroid** to the nearest monitor Stage B can use (`v2` or `persistence`). They say how well-supported the cell forecast is.
  - `nearest_monitor` is the **physically nearest** monitor to the **query location**, of any source, and `distance_km` is measured from the query location. It's what the user sees as "the closest station".
  - So `nearest_monitor` can be closer than any distance in `cell`. Near Weaverville it is a `fallback` monitor that no cell uses.
- `nearest_monitor.forecasts[].source` can be `fallback`; show the lower-confidence badge for it.

### `/forecast/monitors`

- AirNow monitors that are Stage A forecast points (outdoor, in California, with a reading in the last 24 h).
- Each feature has `forecasts`, one per horizon, ordered 1, 3, 6, 12, 24. `nearest_monitor_dist_km` is always 0.
- Monitors are identified by `forecast_point_id` (opaque string). `aqs_code` (9 characters) and `name` are for display.

### `/fires/active`

- Raw FIRMS **VIIRS SNPP** detections, one feature per satellite pixel, with `detected_at` in `[window_start, window_end)`.
- **72 h window and VIIRS SNPP only, the same as the model's fire features.** v1 ingests no other satellite (PM-03, DATA-06 #52), so `satellite` is always `VIIRS_SNPP`. Adding a satellite later is a new enum value, which is additive.
- **All confidence levels are returned.** `confidence` is normalized to `low` / `nominal` / `high`, and **`low` must be shown as low confidence** (e.g. a hollow or faded marker). `confidence_raw` keeps FIRMS's own VIIRS value (`l` / `n` / `h`).
- FIRMS NRT detections arrive up to a few hours after the overpass, so the newest detections can be several hours old even when ingestion is healthy.

### `/observations/pm25/latest`

One feature per sensor: its most recent hourly reading, if `valid_at` is **at most 2 h** before `generated_at`. Only these readings are included:

| `provider` | Included readings |
|---|---|
| `airnow` | `correction = regulatory` |
| `purpleair` | `correction = purpleair_barkjohn` **and** `qa_flag = ok` (raw PurpleAir values are never returned) |
| both | outdoor sensors only (`location_type = outdoor`) |

`station_code` is the AQS code for AirNow and the `sensor_index` for PurpleAir.

### `/meta`

- The active production `model_key`, the newest `issued_at` and how old it is, `grid_key`, the [display thresholds and labels](#display-thresholds-and-labels), the AQI legend, and freshness per source (`airnow`, `purpleair`, `firms`, `nws_obs`).
- Freshness is `generated_at − latest_data_at`, where `latest_data_at` is the newest data timestamp ingested (`ingestion_runs.watermark`). `last_success_at` is when ingestion last succeeded. When FIRMS has no new overpasses, the latter can be recent while the former is hours old.
- `mock_mode` is true when the API serves the fixtures instead of real data (API-01 `MOCK_MODE=true`). The frontend shows a "Demo data" badge when either this or its own mock mode (`VITE_USE_MOCKS`) is on. It is true in `meta.json`, so a server that returns the fixtures as-is reports it automatically.
- **Provisional:** the stale thresholds (`stale_after_minutes`, `forecast_stale_after_minutes`) aren't decided yet. The values in the fixture are placeholders, but they are already served from `/meta`, so the UI won't change when they are decided.

## Fixtures

Every fixture shows the same moment: **the Park Fire (PE-004, Butte and Tehama counties), cycle `issued_at = 2024-07-27T18:00:00Z`, requested at 18:40Z**, with `model_key = baseline_v2/1.0.0`.

- **Monitors:** the 7 AirNow sites are real (codes and locations from `backend/dataset_build/airnow_sites.csv`). Their PM2.5 values are realistic but invented.
- **Grid cells:** real GEO-02 squares (12.5 km, EPSG:3310, ids in GEO-02's format) for `bbox=-122.95,39.40,-121.50,40.10`. The area is inland, so no cell is clipped.
- **Grid and point forecasts:** generated from those monitor values with the PM-03 rules (k = 4, 50 km, `1/d²`, 1 km floor), for all five horizons.
- **Fire detections:** VIIRS SNPP only, placed around the fire's area and its north-east spread in those days, at realistic SNPP overpass times. Individual detections are invented.
- **PurpleAir sensors, monitor forecast-point ids and all UUIDs** are illustrative.
- **Showcases:**
  - a `fallback` monitor (Weaverville), which never feeds a grid cell
  - grid cells with no forecast (the western edge of the fixture bbox)
  - a point with no forecast ([`forecast_point_no_forecast.json`](api/fixtures/forecast_point_no_forecast.json), Mendocino National Forest: the cell centroid is 60.0 km from the nearest usable monitor and the query point is 61.3 km from the nearest monitor)
  - low-confidence fire detections
  - a stale source in `/meta` (`nws_obs`)
  - the error shape ([`error_out_of_scope.json`](api/fixtures/error_out_of_scope.json) 404, [`error_invalid_query.json`](api/fixtures/error_invalid_query.json) 400)

To change the scenario, edit `gen_fixtures.py` and rerun it (`python docs/api/gen_fixtures.py`, which writes to `docs/api/fixtures` by default). Don't hand-edit the JSON: CI regenerates the fixtures and fails if they differ.

## Validating locally

```bash
pip install -r docs/api/requirements.txt
python docs/api/validate.py
python docs/api/gen_fixtures.py /tmp/fixtures && diff -r /tmp/fixtures docs/api/fixtures
```

`validate.py` fails if the spec is invalid, a fixture doesn't match its response schema, a fixture isn't listed in `validate.py`, an endpoint has no 200 fixture, or an error response doesn't use the `Error` schema. When you add or change an endpoint, update `openapi.yaml`, `gen_fixtures.py`, the regenerated fixtures and the `FIXTURES` map in `validate.py` in the same PR.

## Backend (API-01)

The FastAPI app in `backend/app` implements this contract.

- **The spec is served as-is.** `/openapi.json` and `/docs` serve `openapi.yaml`, not a schema generated from the code. `docker compose up backend` mounts `docs/api` read-only for this.
- **Errors.** Every error, including FastAPI's own (validation, unknown route, unhandled exception), is returned in the shared `Error` shape, and 500s keep their CORS headers.

## Open items

| Item | Owner | Status |
|---|---|---|
| Stale thresholds per source, and forecast age | TBD | Undecided; fields in place and served from `/meta`, values provisional |
| `airnow` is not yet an ingestion source in `ingestion_runs` | DATA | Needed before `/meta` can report AirNow freshness |
| `backend/shared/aqi.py` is empty | TBD | The table above is the spec for it (truncate to 0.1) |
| Grid ids, `cell_geom` and the point lookup | GEO-02 (#65) | This contract follows #65; review requested there |
| Staging and production origins for `CORS_ALLOWED_ORIGINS` | OPS-03 | Waiting on the staging URL |
| `docs/api` in the production backend image | OPS-03 | The image is built from `backend/` only; compose mounts `docs/api` for dev |
| Attribution text (AirNow, FIRMS, PurpleAir, NWS) | TBD | Not in v1 of this contract yet |
