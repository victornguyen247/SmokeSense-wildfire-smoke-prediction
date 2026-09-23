.PHONY: up up-d down build logs migrate revision seed test lint fmt db-check env protect

# Create local env files from the templates (safe to re-run; never overwrites).
env:
	@for f in .env backend/.env frontend/.env; do \
		if [ -f "$$f" ]; then echo "keep  $$f"; else cp "$$f.example" "$$f"; echo "write $$f"; fi; \
	done

# Start the full local stack (db, redis, backend, worker, frontend).
up: env
	docker compose up

# Start in the background.
up-d: env
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

# Verify the dev database really has PostGIS enabled.
db-check:
	docker compose exec -T db psql -U $${POSTGRES_USER:-smokesense} -d $${POSTGRES_DB:-smokesense} -c "SELECT postgis_full_version();"

# --- Repo administration (needs an authenticated gh CLI with admin rights) ---
protect:
	./scripts/setup-branch-protection.sh
