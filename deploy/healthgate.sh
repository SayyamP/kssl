#!/usr/bin/env bash
# The post-deploy health gate, in its own file so it can be TESTED.
#
# It lived inline in deploy.sh, which meant the only way to find out whether it
# catches a crash-looping backend was to ship a crash-looping backend. On 2026-09-06
# that is exactly what happened: the gate slept 4 seconds, read `.State.Running`,
# saw the container up between two restarts, and reported success while the site
# served 404. deploy/test_healthgate.sh drives the functions below with a stubbed
# `docker` so every branch is exercised without a deploy.
#
# Callers must set: KSSL_PREFIX, SHA, APP, COMPOSE (array), and may set KSSL_API_PORT.

# HEALTH GATE.
# PREV_TAG is captured by deploy.sh BEFORE the image swap -- it cannot be read here,
# because by now the container has already been replaced. Defaulted rather than assumed:
# this file runs under `set -u`, and an unbound PREV_TAG killed the rollback branch
# outright, so a failed deploy printed nothing and rolled back nothing.
PREV_TAG="${PREV_TAG:-}"
# A tag that is not a pinned build is no safer to return to than the one that failed:
# `latest` is whatever was pushed most recently, which on a bad deploy is the broken
# image itself, and an image with no tag at all names nothing to go back to.
case "$PREV_TAG" in
  ""|latest|"${PREV_BE_IMAGE:-}") PREV_TAG="" ;;
esac

#
# The gate this replaces slept 4 seconds and asked `.State.Running`. On 2026-09-06 a
# backend that could not import crash-looped straight through it: Docker restarts a
# dead container, so at the moment of the single sample it was Running=true, between
# two crashes. The deploy went green and the dashboard served 404 until a human said so.
#
# Two things were wrong and both are fixed here:
#   * ONE SAMPLE OF A LIVENESS FLAG IS NOT HEALTH. A container that is restarting is
#     "running" for part of every cycle, so the flag has to be watched over time and
#     RestartCount has to be part of the reading.
#   * RUNNING IS NOT SERVING. The process being alive says nothing about whether the
#     API answers; the failure that took the site down was at import, after the
#     container had started. So the gate now asks the backend for a real response.
BE_PORT="${KSSL_API_PORT:-8600}"
_be_answers() {
  docker exec "$KSSL_PREFIX-backend" python -c "
import sys, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:${BE_PORT}/api/health', timeout=5) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    pass
try:                      # older images may not carry /api/health
    with urllib.request.urlopen('http://127.0.0.1:${BE_PORT}/api/dataset', timeout=25) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1
}

_settled() {              # both up, neither restarting, and the API answering
  for c in "$KSSL_PREFIX-frontend" "$KSSL_PREFIX-backend"; do
    [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = "true" ] || return 1
    [ "$(docker inspect -f '{{.State.Restarting}}' "$c" 2>/dev/null)" = "false" ] || return 1
  done
  _be_answers || return 1
}

BE_RESTARTS_BEFORE=$(docker inspect -f '{{.RestartCount}}' "$KSSL_PREFIX-backend" 2>/dev/null || echo 0)
HEALTHY=0
# Timing is injectable so deploy/test_healthgate.sh can exercise the failing
# branches without waiting a real minute for each. Production keeps 20x3s, which
# is longer than an import crash takes to show itself.
HG_TRIES="${KSSL_HEALTH_TRIES:-20}"
HG_SLEEP="${KSSL_HEALTH_SLEEP:-3}"
for _ in $(seq 1 "$HG_TRIES"); do
  if _settled; then HEALTHY=1; break; fi
  sleep "$HG_SLEEP"
done

# A container that restarted DURING the gate never settled, even if the last sample
# happened to catch it up. That is precisely the crash-loop this exists to see.
BE_RESTARTS_AFTER=$(docker inspect -f '{{.RestartCount}}' "$KSSL_PREFIX-backend" 2>/dev/null || echo 0)
if [ "$BE_RESTARTS_AFTER" -gt "$BE_RESTARTS_BEFORE" ]; then
  echo "!! backend restarted $((BE_RESTARTS_AFTER - BE_RESTARTS_BEFORE)) time(s) during the health gate"
  HEALTHY=0
fi

if [ "$HEALTHY" != "1" ]; then
  echo "!! $SHA IS NOT HEALTHY — rolling back"
  docker logs --tail 30 "$KSSL_PREFIX-backend" 2>&1 | sed 's/^/   be| /' || true
  if [ -n "$PREV_TAG" ] && [ "$PREV_TAG" != "$SHA" ]; then
    echo ">> restoring TAG=$PREV_TAG"
    # Through the same compose file, so the rollback lands the way the deploy did
    # rather than by a hand-rolled `docker run` with different wiring. TAG is also
    # rewritten in the server .env, or the NEXT unrelated `up` silently re-applies
    # the broken SHA.
    if [ -f "$APP/.env" ]; then
      sed -i "s/^TAG=.*/TAG=$PREV_TAG/" "$APP/.env" 2>/dev/null || true
    fi
    TAG="$PREV_TAG" "${COMPOSE[@]}" up -d --no-build frontend backend || true
    sleep "${KSSL_HEALTH_SLEEP:-5}"
    if _settled; then
      echo "!! rolled back to the previous images. $SHA was NOT deployed."
    else
      echo "!! ROLLBACK ALSO UNHEALTHY. The site is down and needs a human."
    fi
  else
    echo "!! no previous image recorded — cannot roll back automatically."
  fi
  "${COMPOSE[@]}" ps frontend backend
  exit 1
fi
echo ">> health gate passed: both containers settled and the API answered"
