---
paths:
  - "docs/api/**"
  - "docs/api.md"
  - "backend/app/schemas/**"
  - "backend/app/api/**"
  - "frontend/src/api/**"
  - "frontend/src/mocks/**"
---
# API contract (PM-02)

- Source of truth: `docs/api/openapi.yaml`. Everything is under `/api/v1` (`/health` also at root).
- v1 changes are additive only (new endpoints, optional params, fields, enum values). Removing or renaming anything needs `/api/v2`.
- Response schemas are strict (`additionalProperties: false`). A spec change means updating fixtures in the same PR: `python docs/api/gen_fixtures.py` then `python docs/api/validate.py`; CI fails on drift. Fixtures are LF.
- Timestamps: ISO-8601 UTC with `Z`. Geo responses are GeoJSON; grid/forecast/fires/observations take a `bbox` query param.
- Frontend types and MSW fixtures are generated from the spec (`npm run gen:api`); never hand-edit.
- Backend returns pydantic schemas, never ORM objects; error bodies expose no internals.
