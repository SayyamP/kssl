#!/bin/sh
# One SSH tunnel from VPS-B to one remote model server, with a watchdog that checks
# TRAFFIC rather than the ssh process.
#
#   REMOTE_NAME=vps-a  REMOTE_HOST=..  REMOTE_PORT=22     TARGET=127.0.0.1:11434  LOCAL_PORT=11502
#   REMOTE_NAME=dc     REMOTE_HOST=..  REMOTE_PORT=45632  TARGET=172.24.0.2:11434 LOCAL_PORT=11503
#
# WHY -L AND NOT -R
# -----------------
# VPS-B dials out to both boxes. That works because the DC drops every inbound port
# EXCEPT ssh (45632), and vps-a is reachable the same way -- so the hub can own both
# tunnels, restart either one without touching the far end, and there is no daemon to
# install on a machine someone else also uses.
#
# The far side of the DC forward is `172.24.0.2:11434`, a docker-network address. That is
# legal and deliberate: -L resolves the target FROM THE REMOTE HOST, where that address is
# exactly how kssl-extract-ollama is reachable. It publishes no port to its own host, so
# this is the only way in.
#
# THE CHECK THAT MATTERS
# ----------------------
# An ssh process being alive proves nothing. The C4 supervisor watched only its own ssh and
# sat there happily while the service behind it was dead for eleven hours, and autossh does
# not help: it restarts ssh when the SERVER stops answering, never when the session survives
# with dead forwards. So this asks the tunnel to carry a real request, and treats a failure
# to answer as a reason to rebuild the tunnel.
set -eu

: "${REMOTE_NAME:?set REMOTE_NAME}"
: "${REMOTE_HOST:?set REMOTE_HOST}"
: "${REMOTE_USER:=root}"
: "${REMOTE_PORT:=22}"
: "${TARGET:?set TARGET as host:port as seen FROM the remote box}"
: "${LOCAL_PORT:?set LOCAL_PORT}"
: "${PROBE_PATH:=/api/tags}"
# An OPTIONAL second forward on the same session. vps-a and the DC each serve two things
# now -- Ollama and GLiNER -- and one ssh session carries both, so a dead link takes both
# down together and one restart brings both back. Two sessions would let them disagree
# about whether the box is reachable.
: "${TARGET2:=}"
: "${LOCAL_PORT2:=}"
: "${PROBE_PATH2:=/healthz}"
: "${CHECK_EVERY:=20}"
: "${FAIL_LIMIT:=3}"

cp /keys/id_tunnel /tmp/id_tunnel
chmod 600 /tmp/id_tunnel

log() { echo "[tunnel:$REMOTE_NAME] $*"; }

# -g so the OTHER containers on this compose network can use the forward. Without it -L
# binds loopback INSIDE this container and every peer is refused with no log line anywhere,
# which looks exactly like the remote being down.
ssh -N -g \
    -i /tmp/id_tunnel \
    -p "$REMOTE_PORT" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile=/tmp/known_hosts \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=20 \
    -o ServerAliveCountMax=3 \
    -L "0.0.0.0:${LOCAL_PORT}:${TARGET}" \
    ${TARGET2:+-L "0.0.0.0:${LOCAL_PORT2}:${TARGET2}"} \
    "${REMOTE_USER}@${REMOTE_HOST}" &
SSH_PID=$!
log "ssh $SSH_PID: ${LOCAL_PORT}->${TARGET}${TARGET2:+ , ${LOCAL_PORT2}->${TARGET2}} via ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"

# Exit the CONTAINER on a dead tunnel rather than trying to heal in place. `restart:
# unless-stopped` then rebuilds it from a known state -- one recovery path, not two.
trap 'kill $SSH_PID 2>/dev/null || true' EXIT INT TERM

FAILS=0
while :; do
    sleep "$CHECK_EVERY"

    if ! kill -0 "$SSH_PID" 2>/dev/null; then
        log "ssh exited -- restarting container"
        exit 1
    fi

    # EVERY PROBE MUST DIE. Without a hard bound a probe against a half-open link hangs
    # forever, one every CHECK_EVERY seconds, accumulating until the box notices. Observed
    # on the JSW tunnel: three stray processes, the supervisor "running", no tunnel bound.
    OK=1
    curl -fsS --max-time 8 "http://127.0.0.1:${LOCAL_PORT}${PROBE_PATH}" >/dev/null 2>&1 || OK=0
    # BOTH forwards must carry traffic. Checking only the first would leave a dead GLiNER
    # forward invisible -- the session is up, one port answers, and the router keeps
    # sending NER at a hole.
    if [ -n "$TARGET2" ] && [ "$OK" = "1" ]; then
        curl -fsS --max-time 8 "http://127.0.0.1:${LOCAL_PORT2}${PROBE_PATH2}" >/dev/null 2>&1 || OK=0
    fi
    if [ "$OK" = "1" ]; then
        [ "$FAILS" -gt 0 ] && log "forward recovered after $FAILS failure(s)"
        FAILS=0
        continue
    fi

    FAILS=$((FAILS + 1))
    log "no answer through the forward ($FAILS/$FAIL_LIMIT)"
    if [ "$FAILS" -ge "$FAIL_LIMIT" ]; then
        # The session is up and the forward is dead -- the exact case autossh cannot see.
        log "forward dead for $((FAILS * CHECK_EVERY))s -- restarting container"
        kill "$SSH_PID" 2>/dev/null || true
        exit 1
    fi
done
