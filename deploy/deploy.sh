#!/usr/bin/env bash
# Deploy one build (git short SHA) to this VPS: sync source in lockstep, pin the image
# tag, then pull + recreate ONLY frontend and backend. Never names db/llm/gliner/tunnels,
# so Compose never restarts them and the extraction farm keeps running.
#
#   ./deploy/deploy.sh <git-sha>
#
# Assumes: this dir is a git checkout of the kssl-deploy branch, a root-owned .env holds
# runtime secrets, and the caller is already `docker login`ed to ghcr.io (the Actions
# deploy job logs in with its ephemeral token; for a manual rollback to an already-pulled
# SHA no login is needed).
set -euo pipefail

SHA="${1:?usage: deploy.sh <git-sha>}"
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP"
COMPOSE=(docker compose -f docker-compose.vps.yml -f docker-compose.prod.yml)

echo ">> fetching source @ $SHA"
git fetch --quiet origin
git checkout --quiet --force "$SHA"    # mounted SQL/config move with the image

# pin TAG in the server .env (add the line if it isn't there yet)
if grep -q '^TAG=' .env 2>/dev/null; then
  sed -i "s/^TAG=.*/TAG=$SHA/" .env
else
  echo "TAG=$SHA" >> .env
fi
export TAG="$SHA"

echo ">> pulling images @ $SHA"
"${COMPOSE[@]}" pull frontend backend

echo ">> recreating frontend + backend (nothing else)"
"${COMPOSE[@]}" up -d --no-build frontend backend

# quick health gate — both containers should end up running
sleep 4
if [ "$(docker inspect -f '{{.State.Running}}' kssl-frontend 2>/dev/null)" != "true" ] || \
   [ "$(docker inspect -f '{{.State.Running}}' kssl-backend 2>/dev/null)" != "true" ]; then
  echo "!! a container is not running after deploy — check 'docker compose logs frontend backend'"
  "${COMPOSE[@]}" ps frontend backend
  exit 1
fi

docker image prune -f >/dev/null 2>&1 || true
echo ">> deployed $SHA OK"
"${COMPOSE[@]}" ps frontend backend
