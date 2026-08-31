#!/usr/bin/env bash
# Install the GLiNER service on ONE remote box. Run from this workstation, once per node.
#
#   ./llmapi/install_gliner_remote.sh vps-a
#   ./llmapi/install_gliner_remote.sh dc --dry-run
#
# Reads the SSH details for that node from .env (<NODE>_SSH_HOST / _SSH_USER / _SSH_PORT /
# _SSH_KEY). Nothing is hardcoded here, so the same script serves every box.
#
# WHAT IT DOES ON THE REMOTE
#   1. copies llmapi/gliner_server/ to ~/kssl-gliner/
#   2. builds the image there  (the model is NOT baked in -- see below)
#   3. runs it bound to 127.0.0.1:8620, with a named volume for the weights
#   4. waits for /healthz to go 200, which only happens once the model is resident
#
# WHY BUILD ON THE REMOTE RATHER THAN PUSH AN IMAGE
# -------------------------------------------------
# The image is ~2.5 GB with CPU torch. Pushing that over a home uplink to three boxes is
# slower than each box pulling its own layers from a registry it already talks to, and it
# needs no registry credentials on this machine.
#
# WHY THE MODEL IS NOT BAKED INTO THE IMAGE
# -----------------------------------------
# ~1 GB of weights in a layer means every rebuild re-ships them. A named volume keeps them
# across restarts AND rebuilds, so the first run downloads once per box and never again.
# That is also why the healthcheck's start_period is generous: the first boot is a download.
set -euo pipefail

NODE="${1:?usage: install_gliner_remote.sh <vps-a|vps-b|dc> [--dry-run]}"
DRY=""
[ "${2:-}" = "--dry-run" ] && DRY=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$HERE/.env" ] || { echo "no .env at $HERE -- copy .env.example first" >&2; exit 1; }
set -a; . "$HERE/.env"; set +a

case "$NODE" in
    vps-a) PFX=VPSA ;;
    vps-b) PFX=VPSB ;;
    dc)    PFX=DC ;;
    *) echo "unknown node '$NODE' (expected vps-a, vps-b or dc)" >&2; exit 1 ;;
esac

eval "HOST=\${${PFX}_SSH_HOST:-}"
eval "USER_=\${${PFX}_SSH_USER:-root}"
eval "PORT=\${${PFX}_SSH_PORT:-22}"
eval "KEY=\${${PFX}_SSH_KEY:-}"
eval "GPORT=\${GLINER_PORT:-8620}"
eval "GTHREADS=\${GLINER_THREADS:-2}"

[ -n "$HOST" ] || { echo "${PFX}_SSH_HOST is empty in .env -- fill it before installing" >&2; exit 1; }
[ -n "$KEY" ] || { echo "${PFX}_SSH_KEY is empty in .env -- fill it before installing" >&2; exit 1; }
[ -f "$KEY" ] || { echo "${PFX}_SSH_KEY points at $KEY, which does not exist" >&2; exit 1; }

SSH=(ssh -i "$KEY" -p "$PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$USER_@$HOST")
SCP=(scp -i "$KEY" -P "$PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

say() { printf '[%s] %s\n' "$NODE" "$*"; }

if [ -n "$DRY" ]; then
    say "DRY RUN -- would install to $USER_@$HOST:$PORT, serve on 127.0.0.1:$GPORT"
    say "  threads=$GTHREADS  model=${GLINER_MODEL:-urchade/gliner_multi-v2.1}"
    exit 0
fi

say "checking docker on the remote..."
"${SSH[@]}" 'command -v docker >/dev/null' || {
    echo "docker not found on $NODE -- install it there first" >&2; exit 1; }

say "copying gliner_server/ ..."
"${SSH[@]}" 'mkdir -p ~/kssl-gliner'
"${SCP[@]}" -q -r "$HERE/llmapi/gliner_server/." "$USER_@$HOST:~/kssl-gliner/"

say "building image (first build downloads CPU torch, several minutes)..."
"${SSH[@]}" 'cd ~/kssl-gliner && docker build -t kssl-gliner:latest . 2>&1 | tail -5'

say "starting container on 127.0.0.1:$GPORT ..."
# BOUND TO LOOPBACK. The service is reached from this workstation through an ssh forward,
# never from the network -- these boxes have no firewall in front of them worth trusting
# (ufw is inactive on the VPS; the DC drops inbound but that is the provider, not us).
"${SSH[@]}" "docker rm -f kssl-gliner >/dev/null 2>&1 || true
docker run -d --name kssl-gliner --restart unless-stopped \
    -p 127.0.0.1:${GPORT}:${GPORT} \
    -e GLINER_PORT=${GPORT} \
    -e GLINER_BIND=0.0.0.0 \
    -e GLINER_MODEL='${GLINER_MODEL:-urchade/gliner_multi-v2.1}' \
    -e GLINER_THRESHOLD='${GLINER_THRESHOLD:-0.2}' \
    -e GLINER_THREADS=${GTHREADS} \
    -v kssl_gliner_models:/models \
    --cpus ${GLINER_CPUS:-2} --memory ${GLINER_MEM:-4g} \
    kssl-gliner:latest >/dev/null"

say "waiting for the model to load (first run downloads ~1 GB)..."
for i in $(seq 1 60); do
    if "${SSH[@]}" "curl -fs --max-time 5 http://127.0.0.1:${GPORT}/healthz >/dev/null 2>&1"; then
        say "READY -- $("${SSH[@]}" "curl -s http://127.0.0.1:${GPORT}/healthz")"
        exit 0
    fi
    sleep 10
done

say "did NOT become healthy in 10 minutes. Last state:"
"${SSH[@]}" "curl -s --max-time 5 http://127.0.0.1:${GPORT}/healthz || true; echo; docker logs --tail 20 kssl-gliner"
exit 1
