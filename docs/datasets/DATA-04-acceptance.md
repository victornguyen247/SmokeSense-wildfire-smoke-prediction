# DATA-04 acceptance checklist

Issue #7 ("Generate the one-time Parquet training set"), as delivered on 2026-10-12. Each deliverable lists where it lives and the test or command that proves it. Run commands from `backend/` with `POSTGRES_HOST=localhost POSTGRES_PORT=5433`.

## Deliverables

| Deliverable | Status | Where | Proof |
|---|---|---|---|
| **DB loader** | Done | `dataset_build/build_v1.py` (`forecast_points`, `load_inputs`), `ml/datasets/load.py` | `python -m dataset_build.build_v1` (20 events, 141,954 rows); `tests/test_dataset_build.py` |
| **Parquet writer** | Done | `dataset_build/build_v1.py` (`main`, pyarrow) → `data/datasets/smokesense_v1/data.parquet` | `scripts/reproduce_data04.sh` step 2: rebuilt file sha256 = manifest sha256 |
| **dtype casting** | Done | `dataset_build/build_v1.py` (`cast`, `DTYPES`), per `docs/schema.md` | `tests/test_dataset_build.py::test_cast_applies_contract_dtypes`; `validate_feature_dataset` runs in every build |
| **Checksum and versioning** | Done | `data/datasets/smokesense_v1/manifest.json`: version 1.0.0, git commit, sha256 of the data and of `pilot_events.json`, counts | `ml/datasets/load.py::load_dataset` refuses a file whose sha256 differs from the manifest; reproduce step 2 |
| **Dataset card** | Done | `docs/datasets/smokesense_v1.md` | Covers row counts, date ranges, events, feature list, label definition, null rates and known gaps |
| **Leakage checks** | Done | `dataset_build/checks.py`, run on every event in the build. Fires before `issue_time`; weather ≤ `issue_time` and ≤ 3 h old; lags strictly before; label at `issue_time + horizon` | `tests/test_dataset_build.py::test_checks_catch_leaks` (each check catches an injected leak); the build log reports rows checked per event |
| **CV design** | Done | Leave-one-group-out on `group_id` (`docs/data-decisions.md` #21, #22, #26); `ml/evaluation/metrics.py`, `ml/evaluation/release.py` | `tests/test_ml_baseline.py`, `tests/test_ml_baseline_v2.py` (metrics, release rule) |
| **Baseline models** | Done | `ml/models/` (persistence, climatology, XGBoost v1, v2), `ml/training/`, `ml/inference/` → `data/models/baseline_v1/`, `baseline_v2/` | `python -m ml.training.train_baseline_v1` / `_v2`; tests above; reproduce steps 3–5 |
| **Model cards** | Done | `docs/models/baseline_v1.md`, `docs/models/baseline_v2.md` | All metric tables are generated from `metrics.json` |
| **Decision log** | Done | `docs/data-decisions.md` #1–#33 | — |
| **Reproduce script** | Done | `scripts/reproduce_data04.sh` (+ `scripts/compare_repro.py`, `scripts/README.md`) | Run end to end on 2026-10-12: REPRODUCED in **254 s** (dataset sha256, v1 and v2 metrics, release and thresholds all match) |
| **AQS code in the DB** | Done | Migration `0003`, connector, `scripts/backfill_monitor_aqs_code.py` | `tests/test_monitor_aqs_code.py`, `tests/test_dataset_build.py::test_resolve_aqs_*`; backfill filled 35 of 35; the rebuild from the DB column is byte-identical |

## Issue #7 acceptance criteria

| Criterion | Status | Notes |
|---|---|---|
| File matches the PM-01 Parquet contract (columns, dtypes, units) | Done | Every contract column is present with the contract dtype. `docs/schema.md` now lists the added columns and the observed-weather change (#33). `precip_prob_pct` is present but always null. |
| Fully reproducible from clean tables via the script (no manual steps) | Done, from ingested tables | From an ingested DB, `reproduce_data04.sh` is one command. From an empty DB, ingestion comes first (`alembic upgrade head`, then `scripts/ingest_runner/`); it calls live APIs and takes about an hour, so it is a separate, documented step. |
| Version and checksum recorded so everyone trains on the same data | Done | The manifest holds the version, sha256 and git commit. Loading verifies the sha256. |

## Issue #7 review checklist

| Item | Status | Notes |
|---|---|---|
| Label definition documented and consistent | Done | Dataset card, "Labels": regulatory AirNow `RawConcentration` at `target_time`, from the nearest eligible monitor within 25 km (97.8% from the point's own monitor). |
| File loads in Pandas / Polars in seconds; size is reasonable | Done for Pandas | 1.8 MB on disk; `pd.read_parquet` in 0.17 s (141,954 × 38, 89 MB in memory). **Polars not checked:** it is not a project dependency. |
| Dataset card reviewed by ML owner | **Open** | Needs a human review. |

## Open items

| Item | Why it is open |
|---|---|
| **Versioned Parquet in shared storage (Drive/S3)** | The file and manifest are built locally in `backend/data/datasets/smokesense_v1/` (gitignored) and have not been uploaded. Uploading needs the team's storage location and access, so a team member should do it. Upload both `data.parquet` and `manifest.json`; the sha256 in the manifest proves the copy is the same file. |
| **ML-owner review of the dataset card and model cards** | Needs a human. |
| **PurpleAir labels** | Deferred to v1.1 (#12). |
| **NWS forecast weather** | v1 uses observed NCEI weather at issue time (#33). Archived NWS forecasts were not sourced. |
| **Lone Pine / Tahoe City time offsets** | Seen but not encoded (`docs/data-sources.md`); neither is a v1 forecast point. |
| **CI coverage of the reproduce script** | CI has no ingested DB, so `reproduce_data04.sh` runs locally only. CI does run every unit test above. |
