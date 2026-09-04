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
# HOST GUARD. The GitHub Environments named staging and dev fall back to the REPOSITORY
# secrets when they carry none of their own -- and those point at production. Without this
# check a push to `dev` deploys onto VPS-B under kssl-dev- names, orphaning production's
# frontend and backend while reporting success. It nearly happened on 2026-09-03; only a
# missing env file stopped it.
#
# The marker is written by provision_env.sh, so it is present exactly on the machines that
# were deliberately set up as staging or dev. Production has none, which is why a missing
# marker is allowed for prod and refused for everything else: an unprovisioned host must
# never receive a non-production deploy.
MARKER="$APP/.KSSL_ENV"
if [ -f "$MARKER" ]; then
  HOST_ENV="$(tr -d '[:space:]' < "$MARKER")"
  if [ "$HOST_ENV" != "$KSSL_ENV_NAME" ]; then
    echo "!! REFUSING: this machine is provisioned as '$HOST_ENV' but the deploy asked for '$KSSL_ENV_NAME'."
    echo "   Set VPS_HOST/VPS_USER/VPS_SSH_KEY on the '$KSSL_ENV_NAME' GitHub Environment."
    exit 5
  fi
elif [ "$KSSL_ENV_NAME" != "prod" ]; then
  echo "!! REFUSING: asked to deploy '$KSSL_ENV_NAME' to a host with no $MARKER."
  echo "   That means the '$KSSL_ENV_NAME' environment has no host secrets and fell back to"
  echo "   the repository ones, which point at PRODUCTION. Run deploy/provision_env.sh on the"
  echo "   intended machine first, and give the GitHub Environment its own VPS_HOST."
  exit 5
else
  # Production is the one environment allowed onto an unstamped host -- VPS-B was
  # provisioned years before this marker existed, so demanding one would lock prod out
  # of its own deploy. Stamp it here instead of over ssh by hand: after the first
  # production deploy the guard above is armed on VPS-B too, and the fallback case it
  # exists for -- a staging or dev Environment with no host secrets of its own -- is
  # refused rather than landing on production under kssl-stg- names.
  echo "prod" > "$MARKER"
fi

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
# A REPLICA MAY LEGITIMATELY HAVE NO EXTRACTION CONFIG. provision_env.sh brings a staging
# or dev host up with the database only -- "extraction is intentionally NOT started", since
# those fleets share the farms with production's -- and extraction/.env is what every
# `docker compose` under extraction/ needs to parse at all. Without this check the block
# below fails on such a host and, now that its failure is no longer swallowed, turns every
# replica deploy red. It also made provisioning circular: the deploy could not run until
# the file existed, and the file arrives with the source the deploy transfers.
#
# Deliberately NOT silent, and deliberately not a failure: on production the file is always
# there, so a missing one here means someone is looking at a replica that has never been
# given LLM credentials.
if [ -f extraction/docker-compose.yml ] && [ ! -f extraction/.env ]; then
  echo ">> extraction: skipped — no extraction/.env on this host."
  echo "   That is expected on a freshly provisioned $KSSL_ENV_NAME box (the fleet is not"
  echo "   started there by default). Run deploy/provision_env.sh $KSSL_ENV_NAME to create it."
elif [ -f extraction/docker-compose.yml ]; then
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
  #
  # THE OVERLAY. extraction/ is a separate compose project, so the app's $COMPOSE_OVERLAY
  # does not reach it -- it needs its own, and without one a staging deploy applies the
  # BASE file's replicas: 54 + 128 + 16 workers on VPS-A, a box already carrying the
  # crawler and comprehension dashboards, all of them sharing prod's kssl-db connection
  # budget. prod has no extraction/docker-compose.prod.yml and is meant not to: the base
  # file IS production's fleet, so this resolves to the exact command prod ran before --
  # verified on VPS-B: no COMPOSE_FILE in its extraction/.env and no override file.
  #
  # if/then, not `[ -f x ] && EX+=(...)`: under `set -e` a false test as the last command
  # of a line exits the script, which on PROD -- the one environment with no overlay --
  # would end the deploy right here, silently, reporting success.
  #
  # A box-local override is picked up AUTOMATICALLY by a bare `docker compose`, and naming
  # any -f explicitly turns that off. rsync has no --delete, so one could be sitting on a
  # host from a hand-run experiment and would silently drop out of the fleet definition.
  # Named explicitly here, with the environment overlay LAST so it still wins.
  EX=(docker compose -f docker-compose.yml)
  for o in docker-compose.override.yml docker-compose.override.yaml \
           compose.override.yml compose.override.yaml; do
    if [ -f "extraction/$o" ]; then
      echo "   note: box-local $o is in effect"
      EX+=(-f "$o")
    fi
  done
  if [ -f "extraction/docker-compose.$KSSL_ENV_NAME.yml" ]; then
    EX+=(-f "docker-compose.$KSSL_ENV_NAME.yml")
  fi

  # ...AND ONLY WHEN THE EXTRACTION SOURCE ACTUALLY CHANGED. `up -d` replaces every
  # extraction role, and the enrich rebuild is a 1.5-2 hour pass that starts over from
  # nothing when its container is replaced. So ANY push recreated the fleet, including
  # frontend-only ones. On 2026-09-04 that killed the pass three times -- twice by
  # extraction commits, once by a partnerships-graph commit touching nothing but frontend/ --
  # and every one of those deploys reported success. serving.matchup, serving.partner and
  # serving.innovation had not been rebuilt since 2 September as a direct result, and no log
  # anywhere said why.
  #
  # The box has no git history (rsync excludes .git), so "changed" is a content hash of the
  # tree, not a diff. It costs 46ms over ~700 files. extraction/.env lives inside that tree
  # and is deliberately included, so editing a secret by hand still forces a recreate.
  stamp="$APP/.EXTRACTION_HASH"
  new_hash=$(find extraction -type f -not -path '*/__pycache__/*' -not -name '*.pyc' -print0 \
               | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)
  # The safety net: hash matches but nothing running (a pruned image, a wiped host) must
  # still recreate, never "succeed" onto an empty box. The extraction stack is its own
  # compose project named after its directory, so its containers are extraction-* here.
  running=$(docker ps -q --filter "name=extraction-" | wc -l)
  if [ "$new_hash" = "$(cat "$stamp" 2>/dev/null)" ] && [ "$running" -gt 0 ]; then
    echo ">> extraction unchanged ($running containers up) — not recreating."
    echo "   An enrich rebuild or a worker's in-flight document survives this deploy."
  else
    echo ">> extraction: rebuild + recreate as $KSSL_ENV_NAME (scale from compose replicas)"
    # NOT swallowed. This printed a warning and returned 0, so a deploy that left the fleet
    # down still went green -- the frontend and backend are the visible half, and the half
    # that produces the data they serve failed silently. It matters more with the hash
    # guard above, not less: a swallowed failure now also leaves the stamp unwritten, so
    # the next deploy retries and the one after that, each reporting success.
    if ! ( cd extraction && "${EX[@]}" build && "${EX[@]}" up -d ); then
      echo "!! extraction recreate FAILED. frontend+backend ARE live at $SHA; the fleet is not."
      echo "   cd /opt/kssl/app/extraction && ${EX[*]} logs --tail=50"
      exit 1
    fi
    # Stamped only AFTER a successful recreate, so a failed deploy retries next time
    # instead of recording a hash for containers that never came up.
    echo "$new_hash" > "$stamp"
  fi
fi

docker image prune -f >/dev/null 2>&1 || true
echo ">> deployed $SHA OK"
"${COMPOSE[@]}" ps frontend backend
