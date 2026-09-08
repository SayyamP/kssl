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
  # Seed the marker with a value that is NEITHER the new sha NOR the rollback target,
  # so an assertion can tell "the gate wrote this" from "it was already there". Seeding
  # it with PREV_TAG instead made the `latest` case unfalsifiable -- it read `latest`
  # because the seed put it there, not because the gate did.
  echo "seedsha0" > "$TMP/.DEPLOYED_SHA"
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


# ---- .DEPLOYED_SHA MUST NEVER NAME A BUILD THAT IS NOT RUNNING -------------------
#
# Found by the 2026-09-07 rollback drill on staging. deploy.sh wrote the marker BEFORE
# the swap, so a deploy this gate rejected left .DEPLOYED_SHA naming the rejected SHA
# while .env TAG and the containers had been rolled back -- two files disagreeing, one
# of them wrong, and nothing in the repository reads the marker so nothing ever failed
# because of it. It is read by humans deciding what is deployed, which is worse.
echo "marker:"

cat > "$TMP/docker" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  inspect)
    n=$(cat "$TMPDIR_T/restarts" 2>/dev/null || echo 0)
    case "$3" in
      *State.Running*)    echo true ;;
      *State.Restarting*) echo false ;;
      *RestartCount*)     n=$((n + 1)); echo "$n" > "$TMPDIR_T/restarts"; echo "$n" ;;
      *Config.Image*)     echo "ghcr.io/137mallory/kssl-deploy/backend:$PREVTAG" ;;
    esac ;;
  exec) exit 1 ;;
  logs) echo "   (stub)" ;;
  *) : ;;
esac
exit 0
STUB
chmod +x "$TMP/docker"

rc=$(run_gate crashloop 3f875de)
ck "a rejected deploy fails" 1 "$rc"
ck "...and the marker names the RESTORED sha, not the rejected one" \
   "3f875de" "$(cat "$TMP/.DEPLOYED_SHA")"
ck "...so the marker never names the sha the gate refused" \
   0 "$(grep -c deadbee "$TMP/.DEPLOYED_SHA")"

# `latest` is refused as a rollback target, so nothing is restored -- and a marker
# rewritten to `latest` would be a worse lie than the one this fixes. Nothing was
# rolled back, so the marker must be left exactly as it was found.
rc=$(run_gate crashloop latest)
ck "'latest' is refused, and the marker is not rewritten to it" \
   0 "$(grep -c '^latest$' "$TMP/.DEPLOYED_SHA")"
ck "...the marker is left untouched when no rollback happened" \
   "seedsha0" "$(cat "$TMP/.DEPLOYED_SHA")"

# ---- and the ORDERING in deploy.sh, which is the other half of the fix -----------
# The gate exits 1 on failure, so a marker written after it is unreachable on a failed
# deploy. Asserted structurally because there is no way to observe it from here, and
# because moving that one line back is a silent regression.
gate_line=$(grep -n 'healthgate.sh"' "$HERE/deploy.sh" | head -1 | cut -d: -f1)
mark_line=$(grep -n '^echo "\$SHA" > .DEPLOYED_SHA' "$HERE/deploy.sh" | head -1 | cut -d: -f1)
ck "deploy.sh writes the marker (exactly once)" \
   1 "$(grep -c '^echo "\$SHA" > .DEPLOYED_SHA' "$HERE/deploy.sh")"
ck "...AFTER the health gate, so a failed deploy cannot record its sha" \
   yes "$([ -n "$gate_line" ] && [ -n "$mark_line" ] && [ "$mark_line" -gt "$gate_line" ] && echo yes || echo no)"


# ---- a hand-run deploy is deliberate, and still possible -------------------------
# The control added after the 2026-09-07 bypass. It must refuse an accident and must
# NOT obstruct a real recovery -- a guard nobody can get past at 3am gets deleted.
echo "manual-deploy control:"
# A HAND-RUN DEPLOY IS DEFINED BY THE ABSENCE OF GITHUB_ACTIONS, and this suite runs
# INSIDE GitHub Actions, where that variable is "true". So every check below has to
# unset it explicitly or it is not testing a hand-run deploy at all -- deploy.sh takes
# the Actions branch, skips the guard and the log line, and each assertion reads the
# silence as a failure. On a laptop the variable is already absent and the section
# passes, which is why it survived: staging carried these checks but never ran them in
# CI (its selfcheck.sh did not call this file), and main called this file but its copy
# had no manual section. Neither branch alone could see it; the merge of the two is the
# first tree where both halves are present.
MANUAL="env -u GITHUB_ACTIONS"
out=$(cd "$HERE/.." && $MANUAL bash deploy/deploy.sh testsha staging 2>&1); rc=$?
ck "an unset KSSL_MANUAL_DEPLOY refuses a hand-run deploy" 6 "$rc"
ck "...and the message names the escape hatch" 1 "$(echo "$out" | grep -c 'KSSL_MANUAL_DEPLOY=1')"
out=$(cd "$HERE/.." && KSSL_MANUAL_DEPLOY=1 $MANUAL bash deploy/deploy.sh testsha staging 2>&1); rc=$?
ck "...but KSSL_MANUAL_DEPLOY=1 gets past it (recovery preserved)" 0 "$(echo "$out" | grep -c 'REFUSING: this is a manual deploy')"
ck "...and the run is recorded as MANUAL" 1 "$(echo "$out" | grep -c 'MANUAL DEPLOY -- recorded')"
# BOTH BRANCHES OF `by=`. The line above passes on a console, where SSH_CLIENT is unset
# -- and that was the broken one: `${SSH_CLIENT%% *}` is an expansion, not a default, so
# under `set -u` it killed the deploy on the line meant to record it. Over ssh the
# variable IS set and the same code took a different path, which is why the bug lived on
# the box nobody deploys from. Assert the caller is named in each case.
out=$(cd "$HERE/.." && KSSL_MANUAL_DEPLOY=1 SSH_CLIENT="203.0.113.9 51234 22" $MANUAL bash deploy/deploy.sh testsha staging 2>&1)
ck "...over ssh it still records, and names the client ip" 1 "$(echo "$out" | grep -c 'by=[^ ]*@203.0.113.9')"
out=$(cd "$HERE/.." && KSSL_MANUAL_DEPLOY=1 env -u SSH_CLIENT -u SSH_CONNECTION -u GITHUB_ACTIONS bash deploy/deploy.sh testsha staging 2>&1)
ck "...on a console, with no SSH_CLIENT at all, it does not die" 1 "$(echo "$out" | grep -c 'MANUAL DEPLOY -- recorded')"
ck "...and still names who ran it" 0 "$(echo "$out" | grep -c 'by=unknown')"
out=$(cd "$HERE/.." && GITHUB_ACTIONS=true bash deploy/deploy.sh testsha staging 2>&1)
ck "an Actions run is never asked for the flag" 0 "$(echo "$out" | grep -c 'manual deploy')"

if [ "$fails" -gt 0 ]; then
  echo "$fails FAILED"; exit 1
fi
echo "ok - the gate catches a crash loop, a silent API, rolls back, and the marker follows"
