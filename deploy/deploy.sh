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
# A DEPLOY RUN BY HAND IS ALLOWED, BUT IT HAS TO BE MEANT AND IT HAS TO BE RECORDED.
#
# On 2026-09-07 staging was found running a `main` commit that no workflow deployed: a
# /tmp/deploy.sh written by heredoc and run as root. It worked -- root can always run
# this script -- and it left staging on a commit nobody had asked for, with an index
# build holding an AccessExclusiveLock that stalled the API for minutes. Nothing was
# malicious; it was a recovery action that quietly became a deployment.
#
# What a hand-run skips is everything OUTSIDE this file: the ancestry check that stops a
# commit from another branch being deployed, DEPLOY_ENABLED, the environment approval,
# CI and selfcheck, and the Actions run that would have recorded any of it. What it does
# NOT skip is the host marker below and the health gate -- those live here and still
# apply, which is why a manual deploy is worth keeping rather than blocking.
#
# So: keep it working, make it deliberate, and leave a trail. One environment variable
# is enough to stop an accident (nobody sets it by mistake) and cheap enough not to
# obstruct a real 3am recovery.
if [ "${GITHUB_ACTIONS:-}" != "true" ] && [ -z "${KSSL_MANUAL_DEPLOY:-}" ]; then
  echo "!! REFUSING: this is a manual deploy, not a GitHub Actions run."
  echo "   Deploying by hand skips the ancestry check, DEPLOY_ENABLED, the environment"
  echo "   approval, CI/selfcheck, and the audit trail. The host guard and the health"
  echo "   gate below still apply."
  echo
  echo "   Normal route:    push, or dispatch the Deploy workflow (rollback: -f sha=...)"
  echo "   If you mean it:  KSSL_MANUAL_DEPLOY=1 $0 $SHA ${2:-}"
  exit 6
fi
if [ "${GITHUB_ACTIONS:-}" != "true" ]; then
  # WHO, not just WHAT. SSH_CONNECTION survives sudo where SUDO_USER does not exist,
  # and the reverse; take whatever is there rather than insisting on one.
  #
  # AND NEITHER MAY BE SET AT ALL. `${SSH_CLIENT%% *}` is an EXPANSION, not a default,
  # so under `set -u` it aborts the script when the variable is unset -- which is
  # precisely the console case: somebody at the machine, not over ssh, running the
  # recovery this guard was written to keep possible. The deploy died on the line whose
  # only job was to record it. Read the variable through a default first, then expand.
  _ssh="${SSH_CLIENT:-${SSH_CONNECTION:-}}"
  _who="${SUDO_USER:-$(id -un)}${_ssh:+@${_ssh%% *}}"
  _line="$(date -u +%FT%TZ) MANUAL sha=$SHA env=$KSSL_ENV_NAME by=${_who:-unknown} tty=$(tty 2>/dev/null || echo none)"
  echo "$_line" >> "$APP/.manual-deploys.log" 2>/dev/null || true
  echo "!! MANUAL DEPLOY -- recorded in $APP/.manual-deploys.log"
  echo "   $_line"
fi

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
# .DEPLOYED_SHA IS NOT WRITTEN HERE. It is written after the health gate, below.
#
# It used to be written at this point, before the image swap. So a deploy the gate
# REJECTED left the marker naming the rejected SHA while .env TAG and the running
# containers had been rolled back to the previous one -- two files disagreeing about
# what production was running, with only one of them right. Found by the 2026-09-07
# rollback drill on staging: the gate correctly refused a48bb36 and restored 3f875de,
# and .DEPLOYED_SHA still said a48bb36.
#
# Nothing in this repository READS the marker -- it exists for humans and for
# monitoring -- which is exactly why a lie in it survives: no test fails, no deploy
# breaks, and it is believed the next time somebody asks what is deployed.

# --- pending migrations, on a REPLICA only ---------------------------------------
# A BACKEND MUST NEVER ARRIVE AHEAD OF ITS SCHEMA.
#
# This script used to apply no migrations at all, on any environment, and
# sync_from_prod.sh was the only thing that did -- but that runs on a schedule, not on
# a deploy. So a commit that added a column to a backend field list AND shipped its
# migration put a backend selecting that column in front of a database without it, on
# the very next deploy. On 2026-09-06 that was `country`: the competitors SELECT is the
# first field-list query the API makes, so UndefinedColumn was not a missing field, it
# was 500 for GET /api/dataset and a blank dashboard behind every panel.
#
# PROD IS DELIBERATELY EXCLUDED. Production owns the data; a schema change there is a
# decision with a person behind it, and the extraction `migrate` role stays the way to
# make it. A replica is the environment that is ALLOWED to be destructive --
# sync_from_prod.sh overwrites it one way and refuses to run the other -- so a replica
# that heals its own schema costs nothing and removes a whole class of outage from the
# only environments that deploy on every push.
#
# The ledger is the same table and the same rule the migrate role uses: each file
# applied once and recorded, with -1 putting the file and its ledger row in ONE
# transaction, so a migration that fails half way leaves neither the change nor a row
# claiming it was made. Files arrive over stdin, so nothing has to be mounted or copied.
# NOTHING BELOW MAY ABORT THE DEPLOY.
#
# This script runs under `set -euo pipefail`, and this block sits BEFORE the image
# swap. A command substitution that fails -- and every probe here is one --
# terminates the script, so a single unreachable psql would have meant a deploy that
# transferred the source, applied nothing, swapped nothing, and reported failure.
# Verified: `set -euo pipefail; X="$(false | tr -d abc)"` exits without reaching the
# next line.
#
# Invoking the function as `fn || echo ...` suppresses errexit for everything inside
# it. That is the intent, not a workaround: a replica that cannot migrate should say
# so plainly and still receive its new images, because the backend omits an optional
# column it cannot see rather than failing the request. A field short beats down.
_apply_pending_migrations() {
  local PSQL n f DONE HAVE_LEDGER HAVE_TABLES
  PSQL=("${COMPOSE[@]}" exec -T db psql -U "${KSSL_DB_USER:-postgres}" -d "${KSSL_DB_NAME:-kssl}")
  if ! "${PSQL[@]}" -qtAc "SELECT 1" >/dev/null 2>&1; then
    echo ">> migrations: skipped -- no reachable db service in this compose project."
    return 0
  fi
  "${PSQL[@]}" -q -v ON_ERROR_STOP=1 -c "CREATE TABLE IF NOT EXISTS schema_version (
      filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())" || {
    echo "!! migrations: could not create the ledger table. Skipping."
    return 0
  }

  # AN EMPTY LEDGER MUST NOT MARK A PENDING MIGRATION AS ALREADY APPLIED.
  #
  # The extraction migrate role bootstraps by recording the base files AND every
  # migration on disk without replaying them, and there that is right: an empty ledger
  # means the database was just built from those same base files, so each migration's
  # effect is already folded into them and replaying one would be an error, not a
  # no-op.
  #
  # On a replica being deployed it is wrong. The database was built from an OLDER base;
  # this checkout's base files carry the new column and the running database does not.
  # Recording the new migration as applied without running it means it never runs, and
  # the deploy reports success having not done the single thing this block exists for.
  #
  # So only the BASE files are recorded. Every migration is attempted; one whose effect
  # is already present fails inside its own transaction, changes nothing, and is
  # reported. That is the honest direction to be wrong in -- a migration that runs
  # twice says so, a migration that never runs says nothing at all.
  HAVE_LEDGER="$("${PSQL[@]}" -qtAc "SELECT NOT EXISTS (SELECT 1 FROM schema_version)" 2>/dev/null | tr -d '[:space:]')"
  HAVE_TABLES="$("${PSQL[@]}" -qtAc "SELECT to_regclass('serving.competitors') IS NOT NULL" 2>/dev/null | tr -d '[:space:]')"
  if [ "$HAVE_LEDGER" = "t" ] && [ "$HAVE_TABLES" = "t" ]; then
    echo ">> migrations: recording the base schema as this database's starting point"
    for f in db/[0-9][0-9]_*.sql; do
      [ -e "$f" ] || continue
      "${PSQL[@]}" -q -c "INSERT INTO schema_version(filename) VALUES ('$(basename "$f")')
                          ON CONFLICT DO NOTHING" >/dev/null 2>&1
    done
  fi

  for f in db/migrations/*.sql; do
    [ -e "$f" ] || continue
    n="$(basename "$f")"
    DONE="$("${PSQL[@]}" -qtAc "SELECT 1 FROM schema_version WHERE filename = '$n'" 2>/dev/null | tr -d '[:space:]')"
    if [ "$DONE" = "1" ]; then
      continue
    fi
    echo ">> migrations: apply $n"
    # -1 puts the file AND its ledger row in ONE transaction, so a migration that fails
    # half way leaves neither the change nor a row claiming it was made.
    if ! "${PSQL[@]}" -q -v ON_ERROR_STOP=1 -1 -f - -c "INSERT INTO schema_version(filename) VALUES ('$n')" < "$f"; then
      echo "!! migrations: $n FAILED. Nothing from it was applied (it ran in one"
      echo "   transaction). The deploy continues; fix it before relying on that column."
    fi
  done
  return 0
}

if [ "$KSSL_ENV_NAME" != "prod" ] && [ -d db/migrations ]; then
  _apply_pending_migrations || echo "!! migrations: step did not complete. The deploy continues."
fi

# IMAGES THIS HOST ALREADY HAS, when the registry is not an option.
#
# The images are built by CI and pulled from GHCR, and that is the only path production
# should ever take: staging then runs the exact bytes prod will run. But the pull is also
# the one step that needs an outside service, and on 2026-09-07 GitHub Actions stopped
# starting jobs (billing), leaving two fixes built, pushed and undeployable while the
# boxes themselves were healthy.
#
# KSSL_SKIP_PULL is the operator saying "the images for this SHA are already here". It is
# opt-in and never inferred: a failed pull still fails the deploy, because a registry that
# is refusing us is not the same as an operator who has staged the images by hand. And it
# is checked, not trusted -- if the tag is not actually present locally this exits rather
# than letting `up -d` fall back to whatever `latest` happens to be.
if [ "${KSSL_SKIP_PULL:-0}" = "1" ]; then
  echo ">> KSSL_SKIP_PULL=1 -- using images already on this host @ $SHA"
  for svc in frontend backend; do
    docker image inspect "ghcr.io/137mallory/kssl-deploy/$svc:$SHA" >/dev/null 2>&1 || {
      echo "!! KSSL_SKIP_PULL=1 but there is no local ghcr.io/137mallory/kssl-deploy/$svc:$SHA"
      echo "   Build or load it on this host first. Refusing to deploy an unknown image."
      exit 6
    }
  done
else
  echo ">> pulling images @ $SHA"
  "${COMPOSE[@]}" pull frontend backend
fi

# WHAT IS RUNNING NOW, so a bad swap has somewhere to go back to. Captured BEFORE the
# recreate: once `up -d` has replaced the container this is unknowable, and a rollback
# that has to guess a tag is not a rollback. The overlay pins both services from a
# single ${TAG}, so the tag off the running backend is the whole rollback target.
PREV_BE_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$KSSL_PREFIX-backend" 2>/dev/null || true)
PREV_TAG="${PREV_BE_IMAGE##*:}"   # validity is judged in healthgate.sh

# WHAT IS RUNNING NOW, so a bad swap has somewhere to go back to. Captured BEFORE the
# recreate: once `up -d` has replaced the container this is unknowable, and a rollback
# that has to guess a tag is not a rollback. The overlay pins both services from a
# single ${TAG}, so the tag off the running backend is the whole rollback target.
PREV_BE_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$KSSL_PREFIX-backend" 2>/dev/null || true)
PREV_TAG="${PREV_BE_IMAGE##*:}"   # validity is judged in healthgate.sh

echo ">> recreating frontend + backend (nothing else)"
"${COMPOSE[@]}" up -d --no-build frontend backend

# HEALTH GATE -- see deploy/healthgate.sh (extracted so it can be tested).
# It exits 1 on failure, so everything below is reached only by a deploy that passed.
. "$APP/deploy/healthgate.sh"

# THE MARKER, WRITTEN ONLY ONCE THE GATE HAS PASSED. Unreachable on a failed deploy
# because healthgate.sh exits; and the gate's rollback branch writes the restored tag
# itself, so every path that changes what is running also updates this file. There is
# no ordering in which the marker can name something that is not deployed.
echo "$SHA" > .DEPLOYED_SHA

# --- Extraction stack (its own compose project, network_mode: host) -------------
# Rebuild the image from the just-synced source and recreate the roles. `up -d` only
# recreates containers whose image actually changed, so a push that didn't touch
# extraction/ is a no-op. restart: unless-stopped + the feeder's lease reaping make a
# rolling recreate safe (in-flight leases expire and requeue).
# WHO RUNS A FLEET IS A PROPERTY OF THE ENVIRONMENT, NOT AN ACCIDENT OF WHICH FILES EXIST.
# KSSL_EXTRACTION=on is set in deploy/envs/prod.env and nowhere else, so production behaves
# exactly as before and a replica stays quiet.
#
# This used to key off the ABSENCE of extraction/.env, which held only by luck. The moment
# that file was created on VPS-A -- and it had to be, because the `migrate` role
# sync_from_prod.sh runs needs it to parse the compose file at all -- the next staging
# deploy would have started 18 containers there: 4 + 4 workers, 6 signals, feeder, cards,
# enrich and layerb. On a box that also carries the crawler and the comprehension
# dashboards, running against an extraction/.env whose OLLAMA_API_KEY is empty and whose
# corpus DSN still says CHANGEME. They could not have done any work; they would only have
# spun and failed.
#
# So the documented intent -- "extraction is intentionally NOT started" on a replica -- is
# now something the code states rather than something two unrelated facts happen to imply.
# To run a fleet on a replica deliberately: set KSSL_EXTRACTION=on in that environment's
# file and fill in the LLM block of extraction/.env first.
if [ -f extraction/docker-compose.yml ] && [ "${KSSL_EXTRACTION:-}" != "on" ]; then
  echo ">> extraction: skipped — $KSSL_ENV_NAME does not run a fleet."
  echo "   These fleets share the farms with production's, so a replica stays out of the way."
  echo "   To run one here: set KSSL_EXTRACTION=on in deploy/envs/$KSSL_ENV_NAME.env and give"
  echo "   extraction/.env real LLM credentials (see extraction/.env.example)."
elif [ -f extraction/docker-compose.yml ] && [ ! -f extraction/.env ]; then
  # KSSL_EXTRACTION=on but no config to run it with. Still not a failure -- it is a
  # misconfiguration to report, not a reason to fail a deploy that already swapped the
  # frontend and backend.
  echo ">> extraction: KSSL_EXTRACTION=on but this host has no extraction/.env — skipping."
  echo "   Run deploy/provision_env.sh $KSSL_ENV_NAME, then fill in its LLM block."
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
