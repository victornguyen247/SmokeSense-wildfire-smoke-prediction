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
to UTC. The caller provides a SQLAlchemy connection. Migration `0006` and
the GEO-02 seeded monitor and grid rows must already exist. This module
does not migrate, seed, load models, or write forecasts.

## Requirements reviewed on 2026-10-30

`origin/dev` is current at `1fd62f3`; there were no newer merged changes to
bring in. Issue [#48](https://github.com/victornguyen247/SmokeSense-wildfire-smoke-prediction/issues/48)
has no direct comments. Its newest timeline cross-reference is
[PR #92](https://github.com/victornguyen247/SmokeSense-wildfire-smoke-prediction/pull/92)
(ML-04/05, still open; adapter checked at `8119229`). The preceding
[PR #88](https://github.com/victornguyen247/SmokeSense-wildfire-smoke-prediction/pull/88)
scope freeze is also open. Neither PR's implementation is merged into GEO-03.

| Source | GEO-03 requirement / handling |
|---|---|
| #48 and PM-03 | Shared training feature math, Parquet parity, monitor-first IDW, full-grid timing; real-data checks remain pending below |
| #85 (merged) | Live scoped loader, migration 0006, SNPP-only fires, regulatory AirNow, NWS observations, missing weather left missing |
| #92 (open) | Exact 22-column feature order, UTC issue times including empty frames, `baseline/v2` as an example opaque registry key, forecast `target_time` |
| #92 seed note | No monitor points were seeded in its test environment; Stage A now reports missing seeds explicitly |
| #88 (open) | Retains monitor-first baseline_v2 and current horizons; no live PurpleAir or new rain features. OPS-04 owns retention: monitor forecasts 30 days, grid forecasts latest run only |

After #92 merges, OPS can pass Stage A directly to its adapter:

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

Points come from the seeded `forecast_points` table, never the training
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

No seeded active monitor points is a configuration error, distinct from seeded
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
python -m pytest tests/test_geo_serving.py tests/test_alignment.py tests/test_dataset_build.py tests/test_build_ignores_live_rows.py tests/test_serving_contract.py -q
python -m ruff check .
python scripts/check_geo03.py benchmark
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

The Parquet command requires the actual v1 artifact and a database containing
its historical inputs plus corresponding active seeded monitor points. It
compares every input column with null equality and 1e-6 tolerances at sampled
event/hours. It fails if a reference point is absent rather than silently
skipping it. Real Parquet parity has **not yet been run** in this checkout:
the `backend/data` artifacts are absent.
Samples are spread across the artifact rather than restricted to its first
event's hours. `test_geo_parquet.py` runs the same acceptance check when
`GEO03_PARQUET_PATH` is set, otherwise it reports a skip. Miaoqing's review of
real parity results is still required by #48.

The #92 adapter compatibility test is opt-in through module availability until
that PR merges. On 2026-10-30 it was also run successfully against the actual
`8119229` adapter source loaded from a temporary directory, without adding that
source to this branch. Model prediction was stubbed: this verifies input order,
UTC empty frames and the five-horizon output handoff, not booster accuracy or
registry availability.

The deterministic synthetic benchmark on this Windows environment measured
0.18 s for monitor features and 7.36 s for IDW (7.53 s combined on 2026-10-30), using 129
monitors, 179 fires, 107 weather stations with 72 hourly reports, 3,000 grid
centroids and five horizons. Points are generated within the California bbox,
not the actual clipped GEO-02 grid. This excludes database and model I/O and
does **not** establish the full real-data two-minute acceptance criterion.
Run that measurement after migration, seeding and live input availability.
`benchmark-live` measures cold registry model loading, SQL input/point loading,
features, all five inference horizons and interpolation onto all seeded cells.
It prints stage timings and fails at 120 seconds or above. It writes no forecasts
or database rows; registry materialization may populate the verified local model
cache. The flag confirms fire-feed health and full retained-lookback availability;
the command does not infer either from an empty source table.
