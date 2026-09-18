# Backend Architecture (FastAPI + PostgreSQL/PostGIS)

The backend is a FastAPI application plus the ingestion, feature, and ML code that runs alongside it. This document covers structure and conventions. For how the backend fits the whole system, see [architecture.md](architecture.md).

---

## 1. Core principle

**Routes stay thin. Business logic lives in services.** A route's job is to validate the request, call a service, and return the response. Everything else — orchestration, rules, calling the model, shaping data — belongs in a service. This keeps routes readable and logic testable without spinning up HTTP.

---

## 2. Folder structure

```
backend/
  app/                    the FastAPI application
    main.py               app creation, router registration, health check
    core/
      config.py           typed settings (pydantic-settings) — single source of config
      database.py         engine, session, PostGIS setup
      logging.py          structured logging
    api/
      routes/             one file per domain: predictions, locations, alerts, city_history
    schemas/              pydantic request/response models (the API contract)
    models/               SQLAlchemy ORM tables (DB structure)
    services/             business logic; calls ml/inference and the DB
    db/
      migrations/         Alembic versions
      seed.py             load sample data for local dev

  ingestion/              scheduled data pulls (run by the Celery worker)
    connectors/           firms.py, nws.py, airdata.py, purpleair.py
    normalize.py          UTC timestamps, field validation
    tasks.py              Celery tasks / scheduler entry

  features/               spatial + temporal feature engineering (shared by training + inference)
  ml/                     training, evaluation, inference (see ml.md)
  shared/
    aqi.py                AQI breakpoints + risk thresholds (single source of truth)
  data/                   raw/ processed/ samples/ (only samples/ is committed)
  tests/                  cross-cutting / integration tests
```

---

## 3. Layer responsibilities

### Routes (`app/api/routes/`)
- Receive the request, validate it via a schema, call a service, return the result.
- **No business logic.** No direct database queries beyond what a trivial read needs; prefer a service.
- Keep them small — a route should read like a table of contents.

### Schemas (`app/schemas/`)
Pydantic models that define the **API contract**: what requests look like and what responses look like. These are what FastAPI turns into the OpenAPI schema the frontend generates types from. Keep them separate from ORM models.

### Models (`app/models/`)
SQLAlchemy ORM tables — the **database structure**. Tenant-style relationships aren't relevant here (SmokeSense is a single public app), but the separation between "DB model" and "API schema" still matters: never return an ORM object directly from a route, map it through a schema.

### Services (`app/services/`)
Business logic and orchestration:

- fetch data from the database,
- call `ml/inference` for predictions,
- assemble the City Air Quality History from stored PM2.5,
- shape results into what the schema expects.

Services are where the interesting logic lives and where most unit tests point.

### Config (`app/core/config.py`)
All configuration flows through one typed `Settings` object built with `pydantic-settings`. Read config from here — **never call `os.getenv` directly** elsewhere. New setting? Add it to `config.py` and to `backend/.env.example` in the same PR.

---

## 4. The dependency rule

Repeating the most important rule from [architecture.md](architecture.md) because it lives here:

```
app/services  →  ml/inference     ✅  allowed
ml/           →  app/             ❌  never
```

`ml/` and `features/` must not import anything from `app/`. They must be runnable without the web server. If inference seems to need something from `app/`, that something is in the wrong place — lift it into `shared/` or pass it as a plain argument.

---

## 5. Database and migrations

- **PostgreSQL + PostGIS.** Use PostGIS types for anything spatial (points, distances, regions) rather than rolling your own lat/lon math in SQL.
- **All schema changes go through Alembic migrations.** Never edit tables by hand.

```bash
make revision m="add predictions table"   # generate a migration
make migrate                              # apply migrations
```

- Store **all timestamps in UTC**. This system is about when data was available; mixed time zones will corrupt both predictions and training splits.
- Keep raw and cleaned records, plus source timestamps and identifiers, so we can reconstruct what was known at prediction time.

---

## 6. API response conventions

- Use appropriate HTTP status codes (200, 201, 400, 404, 422, 500). FastAPI + pydantic handle validation errors (422) for you.
- Keep response shapes consistent within a domain, driven by the response schema.
- **Never expose internals** in error messages — no stack traces, raw SQL, or config details. Log the detail server-side; return a safe message.
- Label forecasts clearly as model predictions (experimental), not official warnings — this is a product requirement, enforced in the response text/flags.

---

## 7. Validation and errors

- Validate input with pydantic schemas at the boundary.
- Use centralized error handling; log internal errors with enough context to debug.
- Return safe, useful messages: say what the caller can do, not what broke internally.

---

## 8. Code style

- Lint and format with **ruff**; both run in CI (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
- Prefer small, focused functions and clear names.
- Type-hint public functions — it documents intent and helps reviewers.

```bash
make lint    # ruff check
make fmt     # ruff format
make test    # pytest
```

---

## 9. Testing

Testing scales with importance. Prioritize:

- ingestion normalization (timestamps, validation, dedupe),
- feature calculations (distance, bearing, wind alignment — these are easy to get subtly wrong),
- services (prediction assembly, city-history aggregation),
- the AQI threshold logic in `shared/aqi.py`.

Every PR includes testing instructions the reviewer can actually run.
