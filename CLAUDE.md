# SmokeSense

PM2.5 wildfire-smoke forecasting (1–24 h) for California: ingest FIRMS/NCEI/AirNow/PurpleAir → PostGIS → features → XGBoost → FastAPI → React/MapLibre map. Capstone, 6 people. Forecasts are **experimental model estimates, not official warnings**.

## Layout (read only the part you need)

| Path | What | Guide |
|---|---|---|
| `backend/app/` | FastAPI: `api/routes` → `services` (→ `repositories`, once API-01 lands) · `schemas`/`models`, `core/config.py` | `backend/CLAUDE.md` |
| `backend/ingestion/` | Celery pulls + `normalize.py` (UTC) | `docs/backend.md`, `docs/data-sources.md` |
| `backend/features/` | spatial/temporal features, shared by training + serving | `docs/ml/serving-contract.md` |
| `backend/ml/`, `dataset_build/` | training, eval, inference, dataset v1 | `docs/ml.md`, `docs/models/` |
| `backend/shared/aqi.py` | the single AQI/PM2.5 threshold home. **Currently empty**; spec is the AQI table in `docs/api.md` | `docs/api.md` |
| `frontend/` | React 19 + TS + Vite + MapLibre | `frontend/CLAUDE.md` |
| `docs/api/openapi.yaml` | **API contract** (frontend ↔ backend) | `docs/api.md` |

## Doc index: open on demand, never all
- Architecture / layer rules: `docs/architecture.md`
- DB tables: `docs/schema.md` (long: **grep it**, don't read it whole)
- Locked data/model decisions (numbered, dated): `docs/data-decisions.md`
- Pilot wildfire events: `docs/pilot-events.md` (long: grep by `PE-0xx`)
- External feeds, keys, quirks: `docs/data-sources.md` (long: grep by source name)
- Git/PR/CI rules: `CONTRIBUTING.md`

## Commands
Local without Docker: `cd backend && ruff check . && pytest` · `cd frontend && npm run lint && npm run build`
Docker: `make up|down|test|lint|fmt|migrate|revision m="..."|seed|db-check`
CI must pass: conventional commits, ruff + pytest, API spec validate, frontend lint + build, compose db/redis.

## Hard rules (violations are bugs; details in `.claude/rules/`)
1. Dependency direction: `frontend → api → services → ml/inference → features → db`. `ml/` and `features/` **never import `app/`**.
2. Routes thin; logic in services; never return ORM objects; in `app/`, config only via `app/core/config.py` (no `os.getenv`; ingestion/scripts still read env directly, leave them).
3. All timestamps UTC (`Z`). No future leakage. Splits are by time / event group, **never random**.
4. AQI/PM2.5 thresholds belong in `backend/shared/aqi.py` (empty today, don't duplicate them elsewhere); the frontend renders thresholds from `/api/v1/meta`.
5. API contract changes edit `docs/api/openapi.yaml` + fixtures in the same PR (additive-only within v1).
6. Never log/print request URLs or params (keys are in them). Never commit `.env`, model binaries or `backend/data/*`.
7. Schema changes via Alembic only.

## How to work (token + safety)
- **Git:** never commit, push, open PRs, or change branches without explicit user approval; the user reviews files before every commit. Branch from `dev`, PR into `dev`. Details: `.claude/rules/git-workflow.md`.
- **Ask first** when scope, target layer, or contract is ambiguous, or a change would cross a layer boundary. Prefer one concise question over guessing.
- Search before reading: Grep/Glob, then read line ranges. Don't read lockfiles, `node_modules`, `docs/api/fixtures/*`, generated `frontend/src/api/types.ts` and `src/mocks/fixtures.ts`, `backend/data/`, CSV/JSON datasets, `mockServiceWorker.js`.
- For API shapes read `docs/api/openapi.yaml` (grep the path), not generated types.
- Docs can be stale (e.g. `docs/frontend.md` says ESLint/Prettier; repo uses oxlint). Trust code and this file; flag the drift.
- Smallest change that works; match surrounding style; no speculative abstractions (CONTRIBUTING §1).
- Report results faithfully: say what was run, what failed, what was not verified.
