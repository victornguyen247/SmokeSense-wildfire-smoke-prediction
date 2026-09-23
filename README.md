# SmokeSense

An AI-powered system that combines real-time wildfire, weather, and air-quality data to predict how wildfire smoke may affect specific locations over the next 1–24 hours. The platform provides location-based PM2.5 predictions, smoke-impact visualization, and alerts through an interactive dashboard.

A secondary **City Air Quality History** view reuses the same historical data to show a city's multi-year PM2.5 trend, seasonal smoke pattern, and unhealthy-air days per year.

## Documentation

Start here, then read the doc for the area you're working in:

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — git workflow, branch names, pull requests, code review. **Read this before your first PR.**
- **[docs/architecture.md](docs/architecture.md)** — how the whole system fits together and what it means for day-to-day development.
- **[docs/frontend.md](docs/frontend.md)** — React + Vite structure and conventions.
- **[docs/backend.md](docs/backend.md)** — FastAPI structure and conventions.
- **[docs/ml.md](docs/ml.md)** — the machine-learning workflow: data splits, experiments, models.
- **[docs/data-sources.md](docs/data-sources.md)** — the external data feeds and how to access them.

## Tech stack

| Layer | Technology |
|---|---|
| Data / ML | Python, Pandas, scikit-learn, XGBoost, GeoPandas |
| Database | PostgreSQL + PostGIS |
| Backend | FastAPI |
| Async / scheduling | Celery + Redis |
| Frontend | React + TypeScript + Vite, MapLibre |
| Deployment | AWS, Docker |

## Quickstart (local)

You need Docker and Docker Compose installed. Nothing else — Python and Node run
inside the containers.

```bash
# 1. Clone and enter the repo
git clone https://github.com/victornguyen247/SmokeSense-wildfire-smoke-prediction.git
cd SmokeSense-wildfire-smoke-prediction

# 2. Start the stack (Postgres+PostGIS, Redis, backend, worker, frontend)
#    `make up` creates .env, backend/.env and frontend/.env from the .env.example
#    templates on first run, then brings everything up.
make up
```

Then open:

- API health check: http://localhost:8000/health
- API docs (auto-generated): http://localhost:8000/docs
- Frontend: http://localhost:5173

The stack runs without API keys; ingestion of live feeds needs them. Add yours to
`backend/.env` (see [docs/data-sources.md](docs/data-sources.md)) and restart.

Verify the database came up with PostGIS enabled:

```bash
make db-check     # prints POSTGIS="3.4.x" ...
```

Ports on the host: Postgres `5433`, Redis `6380`, API `8000`, frontend `5173`.
The non-default database ports avoid clashing with a local Postgres or Redis.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the common `make` commands (migrations, tests, linting).

## Repository layout

```
SmokeSense/
├── backend/      FastAPI app, ingestion, features, ML
├── frontend/     React + Vite dashboard
├── infra/        Dockerfiles, Postgres init scripts, deployment config
├── docs/         Architecture and area guides
├── scripts/      Repo administration (branch protection)
├── .github/      CI workflow, PR template
└── docker-compose.yml
```

See [docs/architecture.md](docs/architecture.md) for the full breakdown.
