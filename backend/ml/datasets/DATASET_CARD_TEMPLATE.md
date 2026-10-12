# SmokeSense DATA-04 — Dataset Card Template

## Release metadata
- Dataset version: `<version>`
- Rows: `<row_count>`
- UTC issue-time range: `<start>` to `<end>`
- Fire events: `<event_ids>`
- Features: `<feature_columns>`
- Validation: `<PM-01 contract version/review link>`
- Event-grouped split: `<train>/<val>/<test> events; no event in multiple splits`
- SHA-256 checksums: see adjacent `manifest.json`
- Storage: `<Drive/S3 path>`

## Label definition
`target_pm25` (µg/m³) at `target_time = issue_time + horizon_hours`.
The v1 expected labels are **AirNow preliminary hourly RawConcentration**, or
**AQS values if backfilled**, with a row-level source/provenance column where
available. **VERIFY AND RECORD** the source field with GEO-01 #22; current
`target_source=regulatory` alone does *not* distinguish AirNow from AQS.

## Known quality issues
- **Red Bluff 061030007** upstream time offsets applied; confirm evidence.
- **Lone Pine** and **Tahoe City** offsets are unverified.
- Some stations have gaps on peak smoke days; quantify gaps by station/event.
- Timing at sites without an AQS counterpart remains unverified.
- **No PurpleAir label fallback**; `purpleair_raw` is never a label.
- Weather consists of **NCEI observations at or before `issue_time`**.
- Fire and PM2.5 lag features must not use future observations.

## Required sign-offs before marking v1 final
- [ ] PM-01 columns, dtypes and units agree with the published artifact
- [ ] GEO-01 rows, provenance and site-time corrections reviewed
- [ ] Confirmed list of fire events
- [ ] ML owner approved grouped-event splits, temporal overlap and dataset card
- [ ] Parquet and manifest uploaded to shared Drive/S3 (never tracked by git)
