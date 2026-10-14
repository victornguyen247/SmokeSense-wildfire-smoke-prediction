# SmokeSense API (v1, MVP)

The yet to be agreed contract between the frontend and backend (PM-02). Both sides build against it, so neither waits on the other.

| File | What it is |
|---|---|
| [`api/openapi.yaml`](api/openapi.yaml) | OpenAPI 3.1 spec: every endpoint, parameter, response and error |
| [`api/fixtures/*.json`](api/fixtures/) | One realistic response per endpoint (Park Fire, see [Fixtures](#fixtures)) |
| [`api/validate.py`](api/validate.py) | Validates the spec, then every fixture against it. Runs in CI (`api-spec` job) |
| [`api/gen_fixtures.py`](api/gen_fixtures.py) | Regenerates the fixtures (needs `h3`). Not run in CI |

Forecast semantics come from the PM-03 serving contract ([`ml/serving-contract.md`](ml/serving-contract.md)): the model runs at AirNow monitors (Stage A), and grid cells are interpolated from them (Stage B).

## Endpoints

| Endpoint | Returns | Format |
|---|---|---|
| `GET /api/v1/forecast/grid?horizon=&bbox=` | Interpolated forecast per H3 cell, one horizon. `bbox` required | GeoJSON |
| `GET /api/v1/forecast/point?lat=&lon=` or `?zip=` | The location's cell forecast for all horizons, plus the nearest monitor's forecast and distance | JSON |
| `GET /api/v1/forecast/monitors?horizon=&bbox=` | Model forecasts at AirNow monitors, one horizon | GeoJSON |
| `GET /api/v1/fires/active?bbox=` | Satellite fire detections, last 72 h | GeoJSON |
| `GET /api/v1/observations/pm25/latest?bbox=` | Latest reading per outdoor sensor, at most 2 h old | GeoJSON |
| `GET /api/v1/meta` | Active model, latest forecast cycle, per-source freshness, AQI legend | JSON |
| `GET /health`, `GET /api/v1/health` | Liveness | JSON |

Alerts and city history are Phase 4 and not in this version.

## Conventions

### Versioning

- Everything is under `/api/v1`. `/health` also stays at the root for existing deploy checks.
- Within v1, changes are additive only: new endpoints, new optional parameters, new response fields. Clients must ignore fields they don't know.
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
| PM2.5 (`pm25`) | µg/m³ | 0.1 |
| Distances (`*_km`) | km, great-circle | 0.1 |
| Fire radiative power (`frp_mw`) | MW | 0.1 |
| Coordinates | WGS84 decimal degrees | 5 decimals (~1 m) |

Units are fixed by field name and never sent per value.

### Coordinates and `bbox`

- GeoJSON coordinates are `[lon, lat]`. Non-GeoJSON objects use `{"lat": …, "lon": …}`.
- `bbox` is `minLon,minLat,maxLon,maxLat`, the GeoJSON order. Example: `-122.20,39.60,-121.60,39.68`.
- `bbox` is clipped to California, and the clipped value is echoed back where relevant. A bbox or point entirely outside California returns 404 `out_of_scope`.
- `bbox` is optional everywhere except `/forecast/grid`, and defaults to all of California.

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
| 400 | `too_many_cells` | The grid request would return more than 100,000 cells |
| 404 | `out_of_scope` | Location or bbox is outside California |
| 404 | `zip_not_found` | No ZCTA for that ZIP (e.g. a PO-box-only ZIP) |
| 404 | `not_found` | Unknown route |
| 503 | `forecast_unavailable` | No forecast cycle exists yet |
| 500 | `internal_error` | Unexpected failure. The message never contains a stack trace |

Parameter validation errors are **400, not 422**. FastAPI's default is `422 {"detail": [...]}`, so the backend must register exception handlers for `RequestValidationError`, `HTTPException` and unhandled exceptions that return this shape.

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
- Every forecast carries `issued_at`, `model_key` and `nearest_monitor_dist_km` (0 at a monitor). In GeoJSON collections, `issued_at` and `model_key` are on the collection and `nearest_monitor_dist_km` is on each feature.
- Shadow-model forecasts are never returned.
- **Cells with no forecast.** A grid cell has no forecast when no eligible monitor is within 50 km.
  - `/forecast/grid` leaves those cells out; draw them as "no data".
  - `/forecast/point` returns 200 with `cell.has_forecast: false`, `cell.no_forecast_reason: "no_monitor_within_50km"` and the nearest monitor's own forecast. See [`forecast_point_no_forecast.json`](api/fixtures/forecast_point_no_forecast.json).
- No prediction intervals (`pm25_lower` / `pm25_upper`) and no alert flags (`exceeds`) in v1.

### AQI categories

- `aqi_category` is computed at read time from `pm25` with `backend/shared/aqi.py`. It is never stored.
- Responses carry `aqi_table_version` (currently `epa-2024`), so a future EPA revision is visible.
- The category is computed from `pm25` **as returned** (rounded to 0.1), so the number and the color always agree and a client can recompute it from the table. Both bounds below are inclusive.
- `/meta` returns the same table as `aqi_categories`; use it for the legend instead of hard-coding it.

| `key` | Label | Color | PM2.5 µg/m³ |
|---|---|---|---|
| `good` | Good | `#00E400` | 0.0 – 9.0 |
| `moderate` | Moderate | `#FFFF00` | 9.1 – 35.4 |
| `unhealthy_sensitive` | Unhealthy for Sensitive Groups | `#FF7E00` | 35.5 – 55.4 |
| `unhealthy` | Unhealthy | `#FF0000` | 55.5 – 125.4 |
| `very_unhealthy` | Very Unhealthy | `#8F3F97` | 125.5 – 225.4 |
| `hazardous` | Hazardous | `#7E0023` | ≥ 225.5 |

The category comes from an **hourly** value, while the official AQI uses 24 h or NowCast averages. The UI should label it "AQI category (hourly PM2.5)" and must not show a numeric AQI; v1 doesn't return one.

## Endpoint rules

### `/forecast/grid`: payload size

- One GeoJSON Point per H3 resolution-7 cell (~5 km²), at the cell centroid. Polygons are not sent.
- The frontend draws each hexagon from `h3_cell`, e.g. with `h3-js` `cellToBoundary`.
- Each cell carries only `h3_cell`, `pm25`, `aqi_category` and `nearest_monitor_dist_km`. `method` / `source` (always `interpolated` / `idw`) are sent once on the collection.
- `bbox` is required, and responses are capped at 100,000 cells (400 `too_many_cells`).

| | Cells | Raw JSON | gzip |
|---|---|---|---|
| Fixture (Willows → Paradise strip) | 88 | 17.6 KB | 1.9 KB |
| Whole California, upper bound | ~82,000 | ~16.5 MB | ~2 MB (estimated) |

- Measured: ~200 bytes per cell, compact JSON.
- The California figure is an upper bound. Cells with no monitor within 50 km are left out, so the real count is lower.
- The server must send `Content-Encoding: gzip` (or brotli).
- Polygons from `forecast_points.cell_geom` (GEO-02) can be added later as an optional parameter without breaking v1.

### `/forecast/point`

- Pass **either** `lat` + `lon` **or** `zip`.
- The location snaps to its H3 cell. That cell's forecast is returned for all horizons, ordered 1, 3, 6, 12, 24.
- A ZIP resolves to its Census ZCTA centroid. `query.zip_area_km2` is returned so the UI can warn that a large ZIP's centroid may be far from the user.
- No forecast point is ever created by a request.
- `nearest_monitor` is the closest forecast-point monitor to the query location. `distance_km` is measured from the query location, not the cell centroid.

### `/forecast/monitors`

- AirNow monitors that are Stage A forecast points (outdoor, in California, with a reading in the last 24 h).
- `nearest_monitor_dist_km` is always 0.
- Monitors are identified by `forecast_point_id` (UUIDv7). `aqs_code` (9 characters) and `name` are for display.

### `/fires/active`

- Raw FIRMS detections, one feature per satellite pixel, with `detected_at` in `[window_start, window_end)`.
- **72 h window**, the same as the model's fire features.
- **All confidence levels are returned.** `confidence` is normalized to `low` / `nominal` / `high`, and **`low` must be shown as low confidence** (e.g. a hollow or faded marker). `confidence_raw` keeps FIRMS's own value (0–100 for MODIS, `l`/`n`/`h` for VIIRS).
- All satellites are included (MODIS and VIIRS). This is for display only; the model uses VIIRS-SNPP.
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

- The active production `model_key`, the newest `issued_at` and how old it is, the AQI legend, `h3_resolution`, and freshness per source (`airnow`, `purpleair`, `firms`, `nws_obs`).
- Freshness is `generated_at − latest_data_at`, where `latest_data_at` is the newest data timestamp ingested (`ingestion_runs.watermark`). `last_success_at` is when ingestion last succeeded. When FIRMS has no new overpasses, the latter can be recent while the former is hours old.
- **Provisional:** the stale thresholds (`stale_after_minutes`, `forecast_stale_after_minutes`) aren't decided yet. The values in the fixture are placeholders.

## Fixtures

Every fixture shows the same moment: **the Park Fire (PE-004, Butte and Tehama counties), cycle `issued_at = 2024-07-27T18:00:00Z`, requested at 18:40Z**, with `model_key = baseline_v2/1.0.0`.

- **Monitors:** the 7 AirNow sites are real (codes and locations from `backend/dataset_build/airnow_sites.csv`). Their PM2.5 values are realistic but invented.
- **Grid and point forecasts:** generated from those monitor values with the PM-03 rules (k = 4, 50 km, `1/d²`, 1 km floor). Cell IDs are real H3 resolution-7 cells, so `h3-js` can draw them.
- **Fire detections:** placed around the fire's area and its north-east spread in those days, with realistic satellites and overpass times. Individual detections are invented.
- **PurpleAir sensors and all UUIDs** are illustrative.
- **Showcases:**
  - a `fallback` monitor (Weaverville), which never feeds a grid cell
  - a cell with no forecast ([`forecast_point_no_forecast.json`](api/fixtures/forecast_point_no_forecast.json), Mendocino National Forest, 61 km from the nearest monitor)
  - low-confidence fire detections
  - a stale source in `/meta` (`nws_obs`)
  - the error shape ([`error_out_of_scope.json`](api/fixtures/error_out_of_scope.json))

To change the scenario, edit `gen_fixtures.py` and rerun it (`pip install h3==4.1.2`, then `python docs/api/gen_fixtures.py docs/api/fixtures`). Don't hand-edit generated values, since the grid and point forecasts are derived from the monitor values.

## Validating locally

```bash
pip install -r docs/api/requirements.txt
python docs/api/validate.py
```

The script fails if the spec is invalid, a fixture doesn't match its response schema, a fixture isn't listed in `validate.py`, or an endpoint has no 200 fixture. When you add or change an endpoint, update `openapi.yaml`, its fixture and the `FIXTURES` map in `validate.py` in the same PR.

## Open items

| Item | Owner | Status |
|---|---|---|
| Stale thresholds per source, and forecast age | TBD | Undecided; fields in place, values provisional |
| `airnow` is not yet an ingestion source in `ingestion_runs` | DATA | Needed before `/meta` can report AirNow freshness |
| `backend/shared/aqi.py` is empty | TBD | The table above is the spec for it |
| `forecasts.nearest_monitor_dist_km` NOT NULL | PM-03 (#63) | Requested on #63 |
| Grid polygons (`cell_geom`) | GEO-02 | Optional later addition; v1 sends `h3_cell` only |
