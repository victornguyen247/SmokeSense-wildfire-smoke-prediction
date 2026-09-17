.PHONY: up down build logs migrate revision seed test lint fmt

# Start the full local stack (db, redis, backend, worker, frontend).
up:
	docker compose up

# Start in the background.
up-d:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

# --- Database migrations (Alembic, run inside the backend container) ---
migrate:
	docker compose exec backend alembic upgrade head

# make revision m="add fire table"
revision:
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

seed:
	docker compose exec backend python -m app.db.seed

# --- Quality ---
test:
	docker compose exec backend pytest

lint:
	docker compose exec backend ruff check .

fmt:
	docker compose exec backend ruff format .