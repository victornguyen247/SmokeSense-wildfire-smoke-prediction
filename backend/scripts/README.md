# backend/scripts

Run everything from `backend/`. Point the DB at local Postgres with `POSTGRES_HOST=localhost POSTGRES_PORT=5433`.

| Script | What it does |
|---|---|
| `fetch_data04.sh` | Downloads the DATA-04 release (`data04-v1.0.0`) with `gh release download` and checks `SHA256SUMS.txt`. Unzips the dataset into `data/datasets/smokesense_v1/` and the models into `data/models/baseline_v{1,2}/`, then verifies `data.parquet` against its manifest's sha256. `--with-db` also fetches the local-DB dump (to `data/release/`, not restored); `--force` overwrites existing folders. Needs `gh auth login`. Use it to train or evaluate without re-ingesting. |
| `reproduce_data04.sh` | Reproduces DATA-04 end to end from an already-ingested DB, in five steps: build the dataset, check its sha256 against `data/datasets/smokesense_v1/manifest.json`, train baseline v1, train baseline v2, and compare metrics, `release.json` and thresholds with `data/models/baseline_v{1,2}/` (via `compare_repro.py`). It writes only to `data/repro/<timestamp>/` and exits non-zero on any mismatch. |
| `compare_repro.py` | The comparison step of `reproduce_data04.sh`: `python scripts/compare_repro.py <repro_dir>`. |
| `backfill_monitor_aqs_code.py` | After `alembic upgrade head` (migration 0003), fills `monitors.aqs_code` for AirNow monitors ingested before the column existed, from `dataset_build/airnow_sites.csv`. Idempotent. |
| `ingest_runner/` | Loads the pilot events into the DB, one `batch_ingest` per event, and runs the ingest QA. See its README. |
| `pilot_verification/` | The pilot-event verification and selection scripts (PR #26, #32). See its README. |

To use the released files without the DB: `backend/scripts/fetch_data04.sh`.

To rebuild everything, in order on a fresh machine:
1. `alembic upgrade head`
2. Ingest (`ingest_runner/`)
3. `backfill_monitor_aqs_code.py`, only if monitors were ingested before migration 0003
4. `reproduce_data04.sh`
