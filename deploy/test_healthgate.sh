#!/usr/bin/env bash
# Does the health gate actually catch the outage it was written for?
#
#   bash deploy/test_healthgate.sh
#
# THE FAILURE IT MUST SEE. On 2026-09-06 a backend that could not import crash-looped.
# Docker restarts a dead container, so a single sample of `.State.Running` caught it up
# between two crashes; the deploy went green and the dashboard served 404 until a human
# said so. The gate that missed it was four lines and had no way to be tested short of
# shipping another broken backend -- which is why this file exists at all.
#
# `docker` is stubbed on PATH, so every branch below runs in about a second and touches
# nothing real. SCENARIO tells the stub what kind of container to pretend to be.
set -uo pipefail
export KSSL_HEALTH_TRIES=2 KSSL_HEALTH_SLEEP=0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fails=0

ck() { # name expected actual
  if [ "$2" = "$3" ]; then
    printf '  %-62s ok\n' "$1"
  else
    printf '  %-62s FAIL (want %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails + 1))
  fi
}

# ---- the stub -------------------------------------------------------------------
# Counts its own calls in $TMP/restarts so a "crash-looping" container can report a
# rising RestartCount the way a real one does.
cat > "$TMP/docker" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  inspect)
    fmt="$3"; name="$4"
    case "$SCENARIO" in
      healthy)   run=true;  restarting=false; rc=0 ;;
      crashloop) run=true;  restarting=false
                 n=$(cat "$TMPDIR_T/restarts" 2>/dev/null || echo 0); n=$((n + 1))
                 echo "$n" > "$TMPDIR_T/restarts"; rc="$n" ;;
      restarting) run=true; restarting=true;  rc=0 ;;
      dead)      run=false; restarting=false; rc=0 ;;
    esac
    case "$fmt" in
      *State.Running*)    echo "$run" ;;
      *State.Restarting*) echo "$restarting" ;;
      *RestartCount*)     echo "$rc" ;;
      *Config.Image*)     echo "ghcr.io/137mallory/kssl-deploy/backend:$PREVTAG" ;;
    esac ;;
  exec)   # the API probe
    [ "$SCENARIO" = "healthy" ] && exit 0 || exit 1 ;;
  logs)   echo "   (stub logs)" ;;
  compose) if [ "${2:-}" = "up" ] || [ "$*" = *up* ]; then echo "$*" >> "$TMPDIR_T/ups"; fi ;;
  *) : ;;
esac
exit 0
STUB
chmod +x "$TMP/docker"
export PATH="$TMP:$PATH" TMPDIR_T="$TMP"

# the gate expects these from deploy.sh
# The gate calls `exit 1` on failure, which ends the subshell -- so the status has to
# be read from the subshell itself, not echoed from inside it. Getting that wrong is
# how every failing case reported an empty status and looked like a passing one.
run_gate() {
  export SCENARIO="$1" PREVTAG="${2:-abc1234}"
  export PREV_TAG="${2:-abc1234}"   # deploy.sh captures this before the swap
  rm -f "$TMP/restarts" "$TMP/ups"
  ( set +e
    KSSL_PREFIX=kssl SHA=deadbee APP="$TMP" KSSL_API_PORT=8600
    COMPOSE=(docker compose)
    # shellcheck disable=SC1090
    . "$HERE/healthgate.sh" ) >"$TMP/out" 2>&1
  echo "$?"
}

echo "health gate:"

rc=$(run_gate healthy)
ck "a healthy deploy passes the gate" 0 "$rc"
ck "...and says so" 1 "$(grep -c 'health gate passed' "$TMP/out")"

# THE ACTUAL OUTAGE: up, but restarting under it.
rc=$(run_gate crashloop)
ck "a crash-looping backend FAILS the gate" 1 "$rc"
ck "...and the reason names the restarts" 1 "$(grep -c 'restarted .* time' "$TMP/out")"
ck "...and it rolls back rather than leaving the site down" 1 "$(grep -c 'restoring TAG=' "$TMP/out")"

rc=$(run_gate restarting)
ck "a container reporting Restarting=true never settles" 1 "$rc"

rc=$(run_gate dead)
ck "a container that is not running fails" 1 "$rc"

# A tag that is not a pinned build is not a rollback target.
rc=$(run_gate crashloop latest)
ck "'latest' is refused as a rollback target" 1 "$rc"
ck "...and it says it cannot roll back" 1 "$(grep -c 'cannot roll back' "$TMP/out")"

# Running is not serving: the container is up and quiet, but the API says no.
cat > "$TMP/docker" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  inspect)
    case "$3" in
      *State.Running*)    echo true ;;
      *State.Restarting*) echo false ;;
      *RestartCount*)     echo 0 ;;
      *Config.Image*)     echo "ghcr.io/137mallory/kssl-deploy/backend:abc1234" ;;
    esac ;;
  exec) exit 1 ;;          # up, quiet, and not answering
  logs) echo "   (stub)" ;;
  *) : ;;
esac
exit 0
STUB
chmod +x "$TMP/docker"
rc=$(run_gate healthy)
ck "a container that is UP but does not answer still fails" 1 "$rc"

if [ "$fails" -gt 0 ]; then
  echo "$fails FAILED"; exit 1
fi
echo "ok - the gate catches a crash loop, a silent API, and rolls back"
