# GEO-03: monitor features and grid interpolation

The read-only entry points are in `serving.geo`:

```python
from serving.geo import build_monitor_features, interpolate_to_grid

features = build_monitor_features(
    issued_at, connection=connection, fire_feed_available=True,
)
# ML-04 predicts at these monitors using an explicit model_key.
# monitor_forecasts follows docs/ml/serving-contract.md section 5.
grid_forecasts = interpolate_to_grid(monitor_forecasts, connection=connection)
```

`issued_at` must be a timezone-aware top-of-hour timestamp; it is converted
to UTC. The caller provides a SQLAlchemy connection and migration `0006`.
Live serving also requires GEO-02 seeded monitor and grid rows. Historical
Parquet replay uses v1 points directly and requires no live monitor seeds.
This module does not migrate, seed, load models, or write forecasts.

With the ML-04 adapter available, OPS can pass Stage A directly to inference:

```python
from ml.inference.service import InferenceService

# registry is constructed by the caller; choose an explicit registered version.
service = InferenceService.from_registry(registry, model_key="baseline/v2")
monitor_forecasts = service.predict(features)
grid_forecasts = interpolate_to_grid(monitor_forecasts, connection=connection)
```

## Stage A

`load_inputs(connection, event, row_scope="live")` from DATA-06 supplies
SNPP detections, regulatory AirNow readings and observed weather. By default
the event covers `app.core.scope.CALIFORNIA_BBOX`; the existing loader expands
the source-specific boxes and lookback windows. Historical parity callers
pass the original `PilotEvent` and `row_scope="historical"`.

For historical replay, pass `points=` from DATA-04's original
`dataset_build.build_v1.forecast_points(..., row_scope="historical")` selection.
These IDs are monitor external IDs and coordinates come from the historical
database at original precision. They are independent of today's `active` flags
and `--sync-monitors`, which checks readings relative to `now()`. Optional
`inputs=` reuses a historical `load_inputs` snapshot so eligibility verification
and feature calculation see the same data. Explicit v1 points and input
snapshots are supported only with historical scope. The serving 24 h reading
eligibility rule still applies to these points, relative to the requested hour.

Live points come from the seeded `forecast_points` table, never the training
`forecast_points()` function. Eligible points are active monitor points
linked to active outdoor California AirNow monitors with a regulatory reading
in `[H - 24h, H)`. Loaded history is joined through `monitors.external_id`
to the seeded forecast-point ID before lag calculation. Output IDs therefore
remain the opaque IDs expected by the API and forecast tables.

Training and serving both call `features.alignment.build_input_features`.
Training subsequently attaches labels and drops unlabeled rows; serving keeps
them. Output contains `forecast_point_id`, `issued_at` and PM-03's 22 input
columns, cast to the training dtypes. Horizon and derived persistence/trend
columns remain the model wrapper's responsibility.

Time rules are unchanged: exact-hour lags, fires in `[H - 72h, H)` within
200 km, and the nearest weather station's latest report in `[H - 3h, H]`.
Missing pressure, precipitation and lags stay missing. The reported live null
rates are 87% precipitation and 60% pressure. Training dataset-row rates are
58.7% and 53.9%; the earlier 61% / 57% figures were measured over database
weather rows. The merged [missingness analysis](../../docs/ml/weather-missingness-check.md)
found the tested gap harmless for baseline_v2 (decision #43). Missing values
remain missing; neither features nor the model recipe changes.

DATA-06 is merged through PR #85. Its final live sources are FIRMS, AirNow and
NWS; live PurpleAir was removed and is not a feature dependency. Retention now
deletes marked live rows older than 72 h by default. GEO-03 remains read-only
and does not invoke retention. Replay of an older live hour is only possible
while its source rows remain available; use historical scope and retained
historical inputs for the Parquet parity check. A healthy empty fire frame
cannot establish that a past live window survived retention: OPS must enforce
the retained-window and feed-health preconditions before calling Stage A.

OPS must check fire-feed health and the AirNow publication cutoff. Passing
`fire_feed_available=False` rejects the cycle; an empty healthy feed retains
the training no-fire sentinel behavior. The function does not infer health
from an empty table. No eligible monitor yields an empty frame with the
expected columns.

For live serving, no seeded active monitor points is a configuration error, distinct from seeded
points with no recent readings. Stage A raises a message naming
`python -m app.db.seed_ca_forecast_grid --sync-monitors`. Run that setup step
only with fresh observations; it may deactivate ineligible monitors. See
[forecast_grid.md](forecast_grid.md#monitor-forecast-points) for source archives
and the AQS backfill prerequisite. No seeding is performed by the feature builder.

## Stage B

`features.idw.interpolate_to_grid` is the pure DataFrame implementation;
`serving.geo.interpolate_to_grid` loads active seeded points and calls it.
Each UTC issue-hour/horizon group uses up to four nearest `v2` or
`persistence` monitors within 50 km. Weights are proportional to
`1 / max(distance_km, 1)^2`; snapshot weights are normalized. The radius
comparison allows 1e-9 km of numerical roundoff at the boundary.

Fallback and nonfinite predictions do not contribute. Uncovered cells yield
no row. Output includes `source="idw"`, the explicit model key, the real
unfloored nearest distance, and neighbor IDs, distances, weights, predictions
and sources in `feature_snapshot`. Equal-distance ties are resolved by ID.
Duplicate forecasts, invalid coordinates/horizons, negative predictions,
unknown eligible monitor IDs and mixed model keys in a group raise errors.
Grid output also includes UTC `target_time = issued_at + horizon_hours`, as
required by #92. When supplied in monitor output, it must match that formula;
older frames without it are accepted and it is derived. Empty grid output keeps
UTC timestamp dtypes. The seeded-grid wrapper raises a setup error if no active
grid cells exist.

## Verification

Run from `backend/`:

```powershell
$env:DEBUG='false'  # needed if the host sets DEBUG to a non-Boolean value
python -m pytest tests/test_geo_serving.py tests/test_geo_parity_check.py tests/test_alignment.py tests/test_dataset_build.py tests/test_build_ignores_live_rows.py tests/test_serving_contract.py -q
python -m ruff check .
python scripts/check_geo03.py benchmark
python scripts/check_geo03.py parity --dataset data/datasets/smokesense_v1/data.parquet
# Optional sampled smoke check; this does not establish full parity:
python scripts/check_geo03.py parity --dataset data/datasets/smokesense_v1/data.parquet --samples 5
# Optional real-artifact pytest (reads the configured historical DB):
$env:GEO03_PARQUET_PATH='data/datasets/smokesense_v1/data.parquet'
python -m pytest tests/test_geo_parquet.py -q
# Once PR #92, a registered model and live seeded data are available:
# Replace H below with the top of a UTC hour whose full live lookback is retained.
python scripts/check_geo03.py benchmark-live --issued-at H --model-key baseline/v2 --fire-feed-available
```

Fixture tests compare serving features with the shared training builder at
all five horizons, including missing weather. They cover label-free serving,
lag gaps, future reports, exact 72h/3h boundaries, monitor-ID mapping, scope,
seeded-point query filters, IDW neighbor limits, the distance floor, the 50 km
boundary, fallback exclusion and independent issue hours/horizons.

The Parquet command requires the v1 artifact and its historical DATA-03 inputs;
it does not require active seeded monitor points. It checks all event/hours by
default. `--samples N` is a smoke check and prints `coverage="sampled"`.
Input columns are compared with null equality and 1e-6 tolerances.

Serving excludes a point with no non-null regulatory reading in `[H - 24h, H)`,
while v1 keeps those rows. The parity runner verifies every excluded row against
the raw historical reading window and asserts that its reference lags are null.
An off-hour reading still makes a point eligible even if all five exact-hour
lags are null. Every other missing point or feature row is an error. The printed
summary includes `reference_rows`, `parity_rows`, `excluded_no_recent_reading`
and `event_hours`; compared and excluded counts account for every reference row
in the selected coverage. Event point/input snapshots are loaded once per event.

`test_geo_parquet.py` runs full parity when `GEO03_PARQUET_PATH` is set; otherwise
it reports a skip. Fixture regression tests exercise historical replay with no
live seeds, the inclusive 24 h boundary, stale/current/future and off-hour
readings, counted exclusions, unexpected missing rows and feature mismatches.

## Reported real-data validation

Reviewer results on the DATA-03 dump:

- Tests: 66 passed, 1 skipped (ML-04 adapter unavailable); ruff clean.
- `smokesense_v1` still **REPRODUCED**: sha256 `6799c405…`, 141,954 rows.
- Direct Parquet comparison: **0 mismatches over 28,397 rows × 22 columns**.
- Of 28,991 reference rows, 594 (2%) had no reading in `[H - 24h, H)` and all
  lags null, mostly PE-004 and PE-001. These are the eligibility exclusions
  that the corrected runner now verifies and reports explicitly.
- IDW constants and hand-checked cases agree with serving-contract §4.
- Feature/IDW benchmark: about **3 s** (features 0.07 s, IDW about 2.9 s),
  for 129 monitors, 3,000 cells and five horizons.

These are the reviewer's measurements, not a rerun of the corrected parity
runner in this checkout. The corrected full parity run and Miaoqing's review
are still pending. The benchmark excludes cold registry/model loading and the
complete live pipeline.

The adapter compatibility test runs when ML-04 is available. Its prediction
stub verifies column order, UTC empty frames and the five-horizon handoff;
it does not establish booster accuracy or registry availability.

`benchmark-live` measures cold registry model loading, SQL input/point loading,
features, all five inference horizons and interpolation onto all seeded cells.
It prints stage timings and fails at 120 seconds or above. It writes no forecasts
or database rows; registry materialization may populate the verified local model
cache. The flag confirms fire-feed health and full retained-lookback availability;
the command does not infer either from an empty source table.
