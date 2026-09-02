#!/usr/bin/env bash
# Pin the image tag and recreate ONLY frontend + backend from GHCR. The source tree
# (compose files, db/*.sql, deploy/) is already in place — CI rsyncs the exact commit
# before calling this. We never name db/llm/gliner/tunnels, so Compose leaves them (and
# the extraction farm) running untouched.
#
#   ./deploy/deploy.sh <git-sha>
#
# Assumes a root-owned .env with runtime secrets and that the caller is `docker login`ed
# to ghcr.io (the CI deploy step logs in with its ephemeral token).
set -euo pipefail

SHA="${1:?usage: deploy.sh <git-sha>}"
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP"
COMPOSE=(docker compose -f docker-compose.vps.yml -f docker-compose.prod.yml)

# pin TAG in the server .env (add the line if it isn't there yet) and record what's live
if grep -q '^TAG=' .env 2>/dev/null; then
  sed -i "s/^TAG=.*/TAG=$SHA/" .env
else
  echo "TAG=$SHA" >> .env
fi
export TAG="$SHA"
echo "$SHA" > .DEPLOYED_SHA

echo ">> pulling images @ $SHA"
"${COMPOSE[@]}" pull frontend backend

echo ">> recreating frontend + backend (nothing else)"
"${COMPOSE[@]}" up -d --no-build frontend backend

# health gate — both containers must be running after the swap
sleep 4
for c in kssl-frontend kssl-backend; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" != "true" ]; then
    echo "!! $c is not running after deploy — see 'docker compose logs $c'"
    "${COMPOSE[@]}" ps frontend backend
    exit 1
  fi
done

# --- Extraction stack (its own compose project, network_mode: host) -------------
# Rebuild the image from the just-synced source and recreate the roles. `up -d` only
# recreates containers whose image actually changed, so a push that didn't touch
# extraction/ is a no-op. restart: unless-stopped + the feeder's lease reaping make a
# rolling recreate safe (in-flight leases expire and requeue).
if [ -f extraction/docker-compose.yml ]; then
  # The scale comes from `deploy.replicas` in extraction/docker-compose.yml -- do NOT pass
  # --scale here. This block used to read the live count and re-apply it, from before the
  # compose file carried replicas:
  #
  #     WN=$(docker ps --filter "name=extraction-worker" -q | wc -l)
  #     docker compose up -d --scale worker="$WN"
  #
  # That filter is a PREFIX match, so once a second pool existed it counted worker,
  # worker-pune AND worker-big -- then applied the TOTAL to the `worker` service alone.
  # Every deploy multiplied the Kharghar pool by the size of the whole fleet: 54 became
  # 198, which made the next deploy's total 342. It exhausted max_connections twice on
  # 2026-09-02 ("sorry, too many clients already") and silently overrode every replicas:
  # value in the compose file.
  echo ">> extraction: rebuild + recreate (scale from compose replicas)"
  ( cd extraction && docker compose build && docker compose up -d ) \
    || echo "!! extraction recreate reported an error — see 'docker compose -f extraction/docker-compose.yml logs'"
fi

docker image prune -f >/dev/null 2>&1 || true
echo ">> deployed $SHA OK"
"${COMPOSE[@]}" ps frontend backend
