#!/usr/bin/env bash
# Runs ON the box, from /opt/smokesense, called by .github/workflows/deploy-staging.yml.
#   ./deploy.sh ghcr.io/<owner>/smokesense <image tag>
# Pull images -> migrate -> start -> check backend AND worker. A failed pull or migration
# stops before anything is recreated, so the previous version keeps running and image.env
# still names it. Rolling back is re-running this with an older tag (a migration that already
# ran is NOT undone).
set -euo pipefail
cd "$(dirname "$0")"

IMAGE_REPO=${1:?usage: deploy.sh <image repo> <image tag>}
IMAGE_TAG=${2:?usage: deploy.sh <image repo> <image tag>}

[ -f .env ] || { echo "ERROR: /opt/smokesense/.env is missing (see .env.example)" >&2; exit 1; }

# The new tag goes into image.env.next first; it replaces image.env only once the pull and the
# migration have worked, so a failed deploy cannot change what later compose commands run.
printf 'IMAGE_REPO=%s\nIMAGE_TAG=%s\n' "$IMAGE_REPO" "$IMAGE_TAG" > image.env.next
IMAGE_ENV=image.env.next

dc() { docker compose --env-file .env --env-file "$IMAGE_ENV" "$@"; }

fail() {
  echo "ERROR: $1; recent logs:" >&2
  dc logs --tail 40 "$2" >&2
  [ -f image.env.previous ] && echo "Previous deploy: $(grep '^IMAGE_TAG=' image.env.previous); redeploy it to roll back." >&2
  exit 1
}

echo "Deploying $IMAGE_TAG"
dc pull
dc run --rm migrate

if [ -f image.env ]; then cp image.env image.env.previous; fi
mv image.env.next image.env
IMAGE_ENV=image.env
dc up -d --remove-orphans

echo "Waiting for backend to become healthy"
healthy=0
for _ in $(seq 1 30); do
  status=$(docker inspect --format '{{.State.Health.Status}}' "$(dc ps -q backend)" 2>/dev/null || true)
  if [ "$status" = "healthy" ]; then healthy=1; break; fi
  sleep 5
done
[ "$healthy" = 1 ] || fail "backend not healthy after 150s" backend
echo "backend healthy"

# The backend's /health does not touch Redis or the worker, so ask the worker itself: this
# proves the app imports, the broker is reachable and a worker has registered.
echo "Checking worker"
answered=0
for _ in $(seq 1 12); do
  if dc exec -T worker celery -A ingestion.tasks inspect ping -t 10 >/dev/null 2>&1; then answered=1; break; fi
  sleep 5
done
[ "$answered" = 1 ] || fail "worker did not answer a Celery ping" worker
echo "worker answers"

docker image prune -f --filter "until=168h" >/dev/null
