# DATA-02: Proof-of-Concept Ingestion

## Purpose

This proof of concept validates the end-to-end ingestion path for the two initial data sources:

* NASA FIRMS fire detections
* AirNow PM2.5 observations

The POC retrieves a small historical data slice, normalizes the records, and persists them to the PostgreSQL/PostGIS database.

## Data Flow

```text
NASA FIRMS API
    ↓
FIRMS connector
    ↓
Normalization
    ↓
fire_detections
    ↓
PostgreSQL/PostGIS


AirNow API
    ↓
AirNow connector
    ↓
Normalization
    ↓
monitors + observations
    ↓
PostgreSQL/PostGIS
```

## FIRMS POC

Test configuration:

* Source: `VIIRS_SNPP_NRT`
* Bounding box: `-122.5,38.0,-120.5,39.5`
* Historical test date: `2026-09-25`

The historical test returned 17 FIRMS detections.

Results:

* Records fetched: 17
* Records written: 16
* Existing duplicate skipped: 1
* Ingestion status: `success`

The duplicate was detected using the FIRMS deduplication fields and was not inserted again.

## AirNow POC

Test configuration:

* Bounding box: `-122.5,38.0,-120.5,39.5`
* Historical test date: `2026-09-25`
* Test window: 12:00–13:00 UTC
* Parameter: PM2.5

Results:

* Records fetched: 34
* Records written on first run: 34
* Records written on repeat run: 0
* Ingestion status: `success`

The 34 observations corresponded to 17 unique monitoring stations.

## Timestamp Handling

Source timestamps are normalized to UTC before being stored in the database.

The ingestion run timestamps are also stored as UTC timestamps.

## Provenance

The POC preserves source identifiers and timestamps needed to trace
normalized records back to their provider records.

For AirNow, the normalized data preserves:
- source (`airnow`)
- station/external ID
- station name
- source observation timestamp (`valid_at`)

`normalize_airnow_row()` also computes additional `source_metadata`
(`agency_name`, `parameter`, and related source fields) for validation,
but these fields are not persisted because the current PM-01 schema does
not provide a dedicated provenance metadata column. Persisting those
additional fields is out of scope for DATA-02 and can be addressed in a
future schema revision if required.

## Idempotency

Both ingestion paths were tested by running the same data slice more than once.

FIRMS:

```text
First test: 17 fetched, 16 written
Existing record: 1 skipped
```

AirNow:

```text
First test: 34 fetched, 34 written
Repeat test: 34 fetched, 0 written
```

This demonstrates that rerunning the POC does not create duplicate records.

## Ingestion Run Tracking

Each ingestion task creates an `ingestion_runs` record containing:

* Source
* Status
* Start time
* Finish time
* Rows fetched
* Rows written
* Error information

For AirNow, the ingestion run source is stored as `airdata` because that is the value defined by the database schema.

## Known Gotchas

### FIRMS historical data

The default FIRMS request may return zero records depending on the current data window. A historical date was therefore used to demonstrate the POC with a known non-empty dataset.

The historical date is a test configuration and should not be hard-coded into the connector for production ingestion.

### AirNow station count

The AirNow test returned 34 observations but only 17 unique monitors. Multiple observations can belong to the same monitoring station.

### Raw data storage

The issue originally described storing raw provider records. The current team decision is instead to preserve source/provenance metadata without storing the complete raw provider payload.

### POC scope

This implementation is intentionally small. It validates the ingestion path before expanding the pipeline to larger datasets, additional sources, scheduling, retries, and production-scale processing.
