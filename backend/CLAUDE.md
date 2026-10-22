# Backend (Python / FastAPI)

Run from `backend/`: `ruff check .` · `ruff format .` · `pytest` (pytest.ini puts `backend/` on the path). Tests live in `backend/tests/` (flat, `test_<topic>.py`); model artifacts for integration tests are downloaded in CI, not committed.

## Structure
- `app/api/routes/` thin → `app/services/` logic → `app/schemas/` (pydantic = API contract) / `app/models/` (SQLAlchemy). `app/core/{config,database,logging,scope,ids}.py`.
- `ingestion/` connectors + `normalize.py` + `tasks.py` (Celery). `features/` alignment/spatial/temporal/validation. `ml/` has `feature_columns.py`, `features.py` (shared `add_derived`), inference. `dataset_build/` builds the v1 dataset. `shared/aqi.py` thresholds.
- Migrations: `app/db/migrations/` (Alembic, `make revision m="..."`).

## Rules
- Add a setting → `core/config.py` **and** `backend/.env.example` in the same change.
- Model features: single source `ml/feature_columns.py` (`FEATURES_V2`); training and serving share `ml.features.add_derived`. A test fails if labels/ids/coords become features. Don't duplicate feature math in services.
- California scope via `app.core.scope.in_california_scope`. Horizons fixed: 1, 3, 6, 12, 24 h.
- Models are served only by explicit version from `backend/data/models/<name>/` (git-ignored); a per-horizon release rule picks model vs persistence.
- Errors: never expose stack traces/SQL/config; log server-side. Don't lower `httpx`/`httpcore` log levels (`tests/test_no_keys_in_logs.py`).
- Type-hint public functions. Test priority: normalization, feature math, services, AQI logic.
- Before inventing an ML/data convention, grep `docs/data-decisions.md` (numbered decisions #1–#33 are binding).
