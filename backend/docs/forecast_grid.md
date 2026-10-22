# California forecast grid

GEO-02 stores fixed California cells as `forecast_points` rows with
`kind = 'grid_cell'`. Each clipped cell component is a `GEOGRAPHY(POLYGON,
4326)` in `cell_geom`; `geom` stores the projected polygon's centroid for
forecasting and display. PM-03 owns these columns, the monitor link, and the
GiST indexes. Migration `0005` adds the point-to-cell lookup function.

## Grid choice

- Cell width: **12,500 m** in California Albers, EPSG:3310.
- A full square covers 156.25 km². California's roughly 403,000 km² land area
  is about 2,580 full-cell equivalents before partial border cells. The seed
  logs the exact count and WKB payload for TIGER/Line 2025 so these can be
  reviewed against the ~3,000-cell target.
- Squares align to EPSG:3310 coordinate multiples. IDs start with the shared
  `california_grid_key()` (including TIGER vintage), then row, column, and
  polygon-part number, so regeneration is deterministic. Changing the vintage
  creates new IDs; earlier generated cells are retired, preserving history.
- The stable grid key comes from the grid settings and TIGER vintage
  (california_grid_key in app.core.geo); identical inputs retain the same key,
  while a change in cell width, projection, or TIGER vintage changes it. API
  responses and /meta should use this shared helper for cache invalidation.
- Every positive-area square intersection is retained and clipped to the
  California boundary. Disconnected polygon parts within one square become
  separate rows because PM-03 uses `POLYGON`, not `MULTIPOLYGON`; together they
  retain the full clipped coverage.
- `forecast_points.geom` is the centroid of each clipped polygon, as required
  by PM-03's Stage B IDW contract.
- ZIP scope includes Census 2025 ZCTAs whose TIGER internal point lies in
  California. `zip_codes.geom` stores that Census point, `area_km2` stores the
  full ZCTA area, and `forecast_point_id` points to the containing cell.

## Monitor forecast points

With `--sync-monitors`, the seed creates an active monitor point only for an active outdoor AirNow
monitor in California scope with a regulatory PM2.5 observation in the last
24 hours. New monitor forecast points receive their own UUIDv7 and link through
`monitor_id`; repeat seeds preserve existing point IDs. Grid-only seeds leave
monitor activation unchanged, so an ingestion outage cannot silently retire
monitors during grid maintenance. Run `--sync-monitors` only when current
observations are available; it deliberately retires ineligible points.
Before the first monitor sync on a database with existing monitor rows,
run `python scripts/backfill_monitor_aqs_code.py`; future AirNow ingestion
stores the normalized AQS code directly.

## Seed

Apply migrations first, then run:

```sh
docker compose exec backend python -m app.db.seed_ca_forecast_grid
```

The command pins both source files to TIGER/Line 2025. The national ZCTA
archive is large; downloads are cached under the container's temporary
directory. Use `--data-dir` on a persistent mounted path to retain the cache
across container replacement. A dry run still needs the source archives and
downloads them when absent. Local source files can be passed with `--state-file` and
`--zcta-file`. Add `--dry-run` to calculate and report counts without writing
to PostGIS.

```sh
docker compose exec backend python -m app.db.seed_ca_forecast_grid --dry-run
```

The seed is repeatable. It retires legacy H3 grid rows and earlier generated
California grids, upserts the selected grid and Census ZCTAs, recalculates
every included ZCTA mapping. The seed logs all intersecting ZCTAs excluded
because their Census internal point lies outside California. `state='CA'`
denotes this explicit California scope, not a nationwide ZCTA-to-state assignment.

## Lookup

`lookup_grid_forecast_point(longitude, latitude)` uses `ST_Covers` against the
GiST-indexed geography polygons and returns at most one active grid cell. A
coordinate on a shared edge or vertex is assigned to the lexically smallest
cell ID, making boundary results deterministic.

```sql
SELECT forecast_point_id
FROM lookup_grid_forecast_point(-121.4944, 38.5816);

SELECT forecast_point_id
FROM zip_codes
WHERE zcta = '95814' AND state = 'CA';
```

## PostGIS verification (2026-10-20)

Run after migrations and the seed, using the cached TIGER state archive:

```sh
docker compose exec -T backend alembic heads
docker compose exec -T backend python scripts/verify_forecast_grid.py
```

The verifier uses temporary tables and rolls back. It fails on missing lookup
results, incorrect lexical tie-breaking, missing index use, or a lookup above
50 ms in the measured 100-query run. It checks the installed function and its
exact stored SQL body: a `STRICT` table function can appear as an opaque
`Function Scan` in the outer plan, so that plan alone cannot demonstrate the
underlying index use. No planner settings are forced.

Measured locally on PostgreSQL 16 / PostGIS 3.4 with TIGER/Line 2025:

| Check | Result |
|---|---|
| Alembic heads | `0005` only; PM-03 is already merged in `dev` |
| Active grid cells | 2,950 (under 3,000) |
| ZCTA candidates intersecting California | 1,846 |
| Included Census internal points / mapped | 1,803 / 1,803 |
| Excluded internal points outside California | 43, IDs logged by seed |
| Cell interior samples | 2,950; no missing lookups |
| Stored geodesic edge/vertex samples | 191,759; no missing lookups |
| Samples covered by multiple cells | 178,326; all returned the smallest ID exactly once |
| State-border/coast samples 1 m inside original boundary | 20,770; no missing lookups |
| ZIP point samples | 1,803; no missing lookups |
| Null input / (0, 0) outside scope | No result |
| Stored SQL body access path | `Index Scan using ix_forecast_points_cell_geom` |
| `EXPLAIN ANALYZE` execution, outer function / body | 0.243 / 0.048 ms |
| 100 Sacramento lookups, median / maximum | 0.331 / 0.663 ms |

Stored edges are sampled by geography segmentization at at most 1 km spacing,
including original vertices. State-border samples use the original Census
boundary projected into Albers and inset 1 m, sampled at at most 1 km spacing.
This is reproducible sampling evidence, not a mathematical guarantee for
every coordinate or for sub-metre coastal differences. Shared-edge polygon
coverage can exceed one; the API lookup deliberately returns exactly one.

API-02 (#55) can use `kind='grid_cell'`, `active`, `cell_geom` for map queries,
`kind='monitor'` / `monitor_id` for monitor queries, the lookup function for
point containment, and `zip_codes.forecast_point_id` for ZIP queries. Forecast
recency, `is_shadow` filtering, caching, and full-response latency/payload are
API-02 responsibilities. Point containment returns no row outside coverage;
it does not snap an out-of-state point to the nearest cell. Shresta's explicit
confirmation remains pending.

Local checks: Ruff passed and all 9 focused GEO/serving-contract tests passed.
The full backend suite produced 381 passes and 10 failures, all caused by
missing `data/models/ml01_baselines/models/decision_tree_{horizon}h.joblib`
artifacts required by the newly merged ML-01 tests. These artifacts were not
fabricated or the tests skipped to report a green suite.
