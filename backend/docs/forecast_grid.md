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
- Squares align to EPSG:3310 coordinate multiples. IDs include projection,
  width, row, column, and polygon-part number, so regeneration is deterministic.
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

The seed creates an active monitor point only for an active outdoor AirNow
monitor in California scope with a regulatory PM2.5 observation in the last
24 hours. It uses `monitors.external_id` as the forecast-point ID and sets
`monitor_id`. Before the first seed on a database with existing monitor rows,
run `python scripts/backfill_monitor_aqs_code.py`; future AirNow ingestion
stores the normalized AQS code directly.

## Seed

Apply migrations first, then run:

```sh
docker compose exec backend python -m app.db.seed_ca_forecast_grid
```

The command pins both source files to TIGER/Line 2025. The national ZCTA
archive is large; downloads are cached under the container's temporary
directory. Local source files can be passed with `--state-file` and
`--zcta-file`. Add `--dry-run` to calculate and report counts without writing
to PostGIS.

```sh
docker compose exec backend python -m app.db.seed_ca_forecast_grid --dry-run
```

The seed is repeatable. It retires legacy H3 grid rows and earlier generated
California grids, upserts the selected grid and Census ZCTAs, recalculates
every ZCTA mapping, and deactivates monitor points that no longer meet the
eligibility rules.

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
