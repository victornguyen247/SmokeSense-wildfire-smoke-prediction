#!/usr/bin/env bash
# Runs ON the box, from /opt/smokesense, called by .github/workflows/deploy-staging.yml.
#   ./deploy.sh ghcr.io/<owner>/smokesense <image tag>
# Pull images -> migrate -> start. A failed pull or migration stops here, so the previous
# version keeps running. Rolling back is re-running this with an older tag (a migration that
# already ran is NOT undone).
set -euo pipefail
cd "$(dirname "$0")"

IMAGE_REPO=${1:?usage: deploy.sh <image repo> <image tag>}
IMAGE_TAG=${2:?usage: deploy.sh <image repo> <image tag>}

[ -f .env ] || { echo "ERROR: /opt/smokesense/.env is missing (see .env.example)" >&2; exit 1; }

[ -f image.env ] && cp image.env image.env.previous
printf 'IMAGE_REPO=%s\nIMAGE_TAG=%s\n' "$IMAGE_REPO" "$IMAGE_TAG" > image.env

dc() { docker compose --env-file .env --env-file image.env "$@"; }

echo "Deploying $IMAGE_TAG"
dc pull
dc run --rm migrate
dc up -d --remove-orphans

echo "Waiting for backend to become healthy"
for _ in $(seq 1 30); do
  status=$(docker inspect --format '{{.State.Health.Status}}' "$(dc ps -q backend)" 2>/dev/null || true)
  if [ "$status" = "healthy" ]; then
    echo "backend healthy"
    docker image prune -f --filter "until=168h" >/dev/null
    exit 0
  fi
  sleep 5
done

echo "ERROR: backend not healthy after 150s; recent logs:" >&2
dc logs --tail 40 backend >&2
exit 1
