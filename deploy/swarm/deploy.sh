#!/usr/bin/env bash
# Swarm Labs — deploy a custom plane-backend image to the live server.
# Updates only the four backend services (api/worker/beat-worker/migrator);
# frontend/proxy/live keep running the stock makeplane images.
#
# Usage:  deploy.sh <image-tag> [image-repo]
#   image-tag  e.g. v1.3.1-swarm.abc1234   (required)
#   image-repo default: ghcr.io/swarmlabs-io/plane-backend
set -euo pipefail

TAG="${1:?usage: deploy.sh <image-tag> [image-repo]}"
IMAGE="${2:-ghcr.io/swarmlabs-io/plane-backend}"
APP_DIR="/opt/plane-selfhost/plane-app"
cd "$APP_DIR"

COMPOSE=(docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file plane.env)
BACKEND_SVCS=(api worker beat-worker migrator)

upsert_env() { # key value file
  if grep -q "^$1=" "$3"; then sed -i "s|^$1=.*|$1=$2|" "$3"; else echo "$1=$2" >> "$3"; fi
}

echo "==> Pinning backend image: ${IMAGE}:${TAG}"
upsert_env SWARM_BACKEND_IMAGE "$IMAGE" plane.env
upsert_env SWARM_BACKEND_TAG   "$TAG"   plane.env

echo "==> Pulling new backend image"
"${COMPOSE[@]}" pull "${BACKEND_SVCS[@]}"

echo "==> Running DB migrations (migrator runs to completion)"
"${COMPOSE[@]}" up -d --no-deps --force-recreate migrator
mig_cid=$("${COMPOSE[@]}" ps -q migrator)
docker wait "$mig_cid" >/dev/null 2>&1 || true
docker logs --tail 40 "$mig_cid" 2>&1 || true

echo "==> Recreating backend services"
"${COMPOSE[@]}" up -d --no-deps api worker beat-worker

echo "==> Pruning dangling images"
docker image prune -f >/dev/null 2>&1 || true

echo "==> Deployed. Current state:"
"${COMPOSE[@]}" ps
echo "==> Backend now running ${IMAGE}:${TAG}"
