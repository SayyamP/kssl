#!/usr/bin/env bash
# Open every forward this workstation needs, and keep them honest.
#
#   ./llmapi/tunnels_local.sh          # open and supervise; leave the window running
#   ./llmapi/tunnels_local.sh --check  # probe the forwards that are already up, then exit
#   ./llmapi/tunnels_local.sh --stop
#
# THE CODE RUNS HERE. NO MODEL DOES.
# Six forwards, two per box -- an Ollama and a GLiNER each:
#
#   127.0.0.1:11501 -> vps-b ollama      127.0.0.1:11511 -> vps-b gliner
#   127.0.0.1:11502 -> vps-a ollama      127.0.0.1:11512 -> vps-a gliner
#   127.0.0.1:11503 -> dc    ollama      127.0.0.1:11513 -> dc    gliner
#
# ONE SSH SESSION PER BOX, carrying both of that box's services: a dead link takes both
# down together and one restart brings both back. Two sessions per box could disagree
# about whether the box is reachable, which is the state that is hardest to debug.
#
# EVERY PORT IS DISTINCT ON PURPOSE. Two nodes sharing a forward would silently send one
# box's work to another with both reporting healthy -- nodes.check_config() refuses that
# config, and this script is where the ports it checks are actually assigned.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$HERE/.env" ] || { echo "no .env at $HERE" >&2; exit 1; }
set -a; . "$HERE/.env"; set +a

PIDFILE="${TMPDIR:-/tmp}/kssl-tunnels.pids"
NODES="vps-b vps-a dc"

pfx_of() { case "$1" in vps-a) echo VPSA;; vps-b) echo VPSB;; dc) echo DC;; esac; }

ports_of() {   # -> "<llm_local> <llm_target> <gliner_local> <gliner_target>"
    local p; p="$(pfx_of "$1")"
    eval "echo \"\${${p}_TUNNEL_PORT:-0} \${${p}_TARGET:-} \${${p}_GLINER_TUNNEL_PORT:-0} \${${p}_GLINER_TARGET:-}\""
}

probe() {      # probe <port> <path> -> 0 if it answers
    curl -fsS --max-time 6 "http://127.0.0.1:$1$2" >/dev/null 2>&1
}

check() {
    local bad=0
    for n in $NODES; do
        read -r lp lt gp gt <<<"$(ports_of "$n")"
        if probe "$lp" /api/tags; then echo "  $n  ollama :$lp  OK"
        else echo "  $n  ollama :$lp  DOWN"; bad=1; fi
        if probe "$gp" /healthz;  then echo "  $n  gliner :$gp  OK"
        else echo "  $n  gliner :$gp  DOWN"; bad=1; fi
    done
    return $bad
}

stop() {
    [ -f "$PIDFILE" ] || { echo "no pidfile"; return 0; }
    while read -r pid; do kill "$pid" 2>/dev/null && echo "  killed $pid"; done < "$PIDFILE"
    rm -f "$PIDFILE"
}

case "${1:-}" in
    --check) check; exit $? ;;
    --stop)  stop; exit 0 ;;
esac

stop >/dev/null 2>&1 || true
: > "$PIDFILE"

for n in $NODES; do
    p="$(pfx_of "$n")"
    eval "host=\${${p}_SSH_HOST:-}; user=\${${p}_SSH_USER:-root}; sport=\${${p}_SSH_PORT:-22}; key=\${${p}_SSH_KEY:-}"
    read -r lp lt gp gt <<<"$(ports_of "$n")"
    if [ -z "$host" ] || [ -z "$key" ]; then
        echo "SKIP $n -- ${p}_SSH_HOST or ${p}_SSH_KEY is empty in .env"
        continue
    fi
    # ExitOnForwardFailure matters: without it ssh connects, silently fails to bind a
    # port that is already taken, and every call to that node lands somewhere unintended.
    ssh -N \
        -i "$key" -p "$sport" \
        -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
        -L "127.0.0.1:${lp}:${lt}" \
        -L "127.0.0.1:${gp}:${gt}" \
        "${user}@${host}" &
    echo $! >> "$PIDFILE"
    echo "  $n  pid $!  :$lp -> $lt   :$gp -> $gt"
done

sleep 4
echo
echo "probing the forwards (an ssh process being alive proves nothing):"
check || echo "  ^ some forwards are not carrying traffic yet -- a GLiNER container may still be loading its model"

echo
echo "leave this running. ./llmapi/tunnels_local.sh --check  to re-probe, --stop to close."
trap 'echo; echo "closing tunnels..."; stop; exit 0' INT TERM
while :; do
    sleep 30
    while read -r pid; do
        kill -0 "$pid" 2>/dev/null || { echo "ssh $pid died -- rerun this script"; }
    done < "$PIDFILE"
done
