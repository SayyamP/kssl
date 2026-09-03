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

SHA="${1:?usage: deploy.sh <git-sha> [env]}"
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP"

# ENVIRONMENT. Three of them, one per machine, differing only in which overlay is applied
# and which container-name prefix and ports they claim:
#
#   prod     main branch     VPS-B                authoritative data, the extraction fleet
#   staging  staging branch  VPS-A                replica data, 4+4 workers
#   dev      dev branch      data centre          replica data, 1+1 workers
#
# Defaults to prod so an existing `deploy.sh <sha>` call keeps behaving exactly as before --
# the production deploy path is the one thing this split must not change.
KSSL_ENV_NAME="${2:-${KSSL_ENV:-prod}}"
ENV_FILE="$APP/deploy/envs/$KSSL_ENV_NAME.env"
[ -f "$ENV_FILE" ] || { echo "!! no such environment: $KSSL_ENV_NAME (expected $ENV_FILE)"; exit 2; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a
echo ">> environment: $KSSL_ENV_NAME  prefix=$KSSL_PREFIX  overlay=$COMPOSE_OVERLAY"

COMPOSE=(docker compose -f docker-compose.vps.yml -f "$COMPOSE_OVERLAY")

# pin TAG in the server .env (add the line if it isn't there yet) and record what's live
if grep -q '^TAG=' .env 2>/dev/null; then
  sed -i "s/^TAG=.*/TAG=$SHA/" .env
else
  echo "TAG=$SHA" >> .env
fi
export TAG="$SHA"
# The environment's identity has to be IN the server .env, not just this shell: every later
# `docker compose` run on that box (a manual restart, the next deploy) interpolates
# ${KSSL_PREFIX} and the port variables from it. Without this a hand-run compose on VPS-A
# would fall back to the bare `kssl-` names and try to take over production's.
for kv in "KSSL_ENV=$KSSL_ENV_NAME" "KSSL_PREFIX=$KSSL_PREFIX" "KSSL_DB_PORT=$KSSL_DB_PORT" \
          "KSSL_OLLAMA_PORT=$KSSL_OLLAMA_PORT" "LLMAPI_PORT=$LLMAPI_PORT"; do
  k="${kv%%=*}"
  if grep -q "^$k=" .env 2>/dev/null; then sed -i "s|^$k=.*|$kv|" .env; else echo "$kv" >> .env; fi
done
echo "$SHA" > .DEPLOYED_SHA

echo ">> pulling images @ $SHA"
"${COMPOSE[@]}" pull frontend backend

echo ">> recreating frontend + backend (nothing else)"
"${COMPOSE[@]}" up -d --no-build frontend backend

# health gate — both containers must be running after the swap
sleep 4
for c in "$KSSL_PREFIX-frontend" "$KSSL_PREFIX-backend"; do
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
