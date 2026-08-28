#!/bin/sh
# One ssh session, two forwards, bound on 0.0.0.0 *inside this container* so the
# other containers on the kssl network reach them by name -- and nothing outside
# the network can, because the container publishes no port.
#
#   kssl-tunnel:5460   -> the VPS Postgres
#   kssl-tunnel:11500  -> the VPS Ollama
#
# Binding on the host's 172.17.0.1 instead would have worked for these two ports
# but the box DROPs container->host traffic in DOCKER-USER for the corpus ports,
# and a wiring that is correct only for some ports is a trap for the next person.
set -eu

: "${VPS_HOST:?set VPS_HOST}"
: "${VPS_USER:=root}"
: "${VPS_SSH_PORT:=22}"
: "${DB_PORT:=5460}"
: "${LLM_PORT:=11434}"

cp /keys/id_vps /tmp/id_vps
chmod 600 /tmp/id_vps

# -g is required: without it -L binds loopback only and the other containers,
# which arrive on the bridge interface, are refused with no log line anywhere.
exec ssh -N -g \
    -i /tmp/id_vps \
    -p "$VPS_SSH_PORT" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile=/tmp/known_hosts \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=20 \
    -o ServerAliveCountMax=3 \
    -L "0.0.0.0:5460:127.0.0.1:${DB_PORT}" \
    -L "0.0.0.0:11500:127.0.0.1:${LLM_PORT}" \
    "${VPS_USER}@${VPS_HOST}"
