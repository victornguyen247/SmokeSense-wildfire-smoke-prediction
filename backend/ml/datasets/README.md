# DATA-04 dataset builder (starter PR)

This is the portion authorized before final events and GEO-01 #22 are confirmed.
It does **not** build features or modify ingestion/event configuration.

## Install (from `backend/`)

```powershell
python -m pip install -r requirements-data04.txt
```

## Run tests (from `backend/`)

```powershell
python -m pytest tests/test_data04_dataset.py -q
```

## Run against Postgres (AFTER GEO-01 #22 confirms the table)

Set `DATABASE_URL` through the team's approved local secret mechanism. Never
put the URL/password in a command, a tracked config file, or a log.

```powershell
python -m ml.datasets.cli --table YOUR_GEO01_TABLE --event-id PE-001 --event-id PE-002 --version v1-draft --output-root data/processed
```

For a custom **reviewed** read-only SQL query, use `--sql-file path.sql`. It must
include `:event_ids` as an expanding parameter, e.g. `WHERE pilot_event_id IN :event_ids`.

To use an existing GEO-01 Parquet file instead of Postgres:

```powershell
python -m ml.datasets.cli --from-parquet path/to/geo01.parquet --version v1-draft --output-root data/processed
```

**Do not claim v1 production readiness yet.** Current known blockers:

1. PM-01 has to confirm the exact schema, including `split`, `target_monitor_id`,
   and whether row-level AirNow/AQS provenance needs another column. DATA-04
   currently validates the GEO-01 REQUIRED_COLUMNS plus its observed optional
   `target_monitor_id`; no other unknown columns are accepted.
2. GEO-01 `target_source=regulatory` does not distinguish AirNow preliminary
   RawConcentration vs AQS backfill. Ask #22 owner for verified row-level source.
3. Confirm final event IDs and ensure timestamp corrections + site gaps are audited.
4. Agree on complete-event holdouts with the ML owner. Current implementation
   gives chronological time splits with target-time embargo only.
5. `event_id=<id>/part-00000.parquet` is a **partitioned dataset directory**.
   Issue #7 originally gave a single physical `training_v1.parquet` example, but
   the lead later explicitly requested event partitions. Agree which physical
   representation is required before publishing.
6. This starter doesn't upload files to team Drive/S3 automatically. Shared
   storage credentials/path are needed for the final publication step.

All data files go under `backend/data/processed/`, already ignored by `.gitignore`.
The version directory contains `manifest.json`, `DATASET_CARD.md`, and event
partitions; the script never overwrites an existing version.

The markdown document `DATASET_CARD_TEMPLATE.md` is the reviewable template;
the generated `DATASET_CARD.md` inside each dataset version is populated with
its actual row count, date range, event IDs, feature list, and split details.
