#!/usr/bin/env bash
# Move the serving database to the VPS, and nothing else.
#
#   ./deploy/deploy_vps.sh dump      # snapshot this machine's kssl database
#   ./deploy/deploy_vps.sh tunnel    # open the SSH tunnel to the VPS database
#   ./deploy/deploy_vps.sh restore   # load the snapshot through that tunnel
#
# It does not build, start or stop anything: that is `docker compose -f
# docker-compose.vps.yml`, run on the VPS itself. Keeping the two apart means a
# botched data load cannot take the site down with it.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "no .env -- copy .env.example first"; exit 1; }

# Read .env WITHOUT letting the shell interpret it. `set -a; . ./.env` looks
# tidier and is a trap: these values contain shell metacharacters, so the shell
# either fails to parse the file or expands part of a password -- and a `. `
# that echoes on error puts the password in the terminal and the scrollback.
env_get() {
  sed -n "s/^$1=//p" .env | head -1
}

DUMP=${KSSL_DUMP_FILE:-kssl-serving.dump}
KSSL_DB_PORT=$(env_get KSSL_DB_PORT); KSSL_DB_PORT=${KSSL_DB_PORT:-5460}
KSSL_DB_NAME=$(env_get KSSL_DB_NAME); KSSL_DB_NAME=${KSSL_DB_NAME:-kssl}
KSSL_DB_USER=$(env_get KSSL_DB_USER); KSSL_DB_USER=${KSSL_DB_USER:-postgres}

case "${1:-}" in
  dump)
    # The DSN carries a password, and an argument is visible to every user on
    # the box via `ps`. Pass the parts as flags and the password by environment.
    LOCAL_HOST=${KSSL_LOCAL_DB_HOST:-127.0.0.1}
    LOCAL_PORT=${KSSL_LOCAL_DB_PORT:-5460}
    LOCAL_PW=$(env_get KSSL_LOCAL_DB_PASSWORD)
    LOCAL_PW=${LOCAL_PW:-kssl}
    # -Fc so the restore can be parallel and selective
    PGPASSWORD="$LOCAL_PW" pg_dump -Fc -f "$DUMP" \
      -h "$LOCAL_HOST" -p "$LOCAL_PORT" \
      -U "$KSSL_DB_USER" -d "$KSSL_DB_NAME"
    ls -lh "$DUMP"
    ;;
  tunnel)
    VPS_HOST=$(env_get KSSL_VPS_HOST)
    : "${VPS_HOST:?set KSSL_VPS_HOST in .env}"
    VPS_PORT=$(env_get KSSL_VPS_SSH_PORT); VPS_PORT=${VPS_PORT:-22}
    VPS_USER=$(env_get KSSL_VPS_USER);     VPS_USER=${VPS_USER:-root}
    VPS_KEY=$(env_get KSSL_VPS_SSH_KEY)
    # `-i ""` is not "no key" -- ssh treats the empty string as an identity file
    # and the connection degrades or fails. Only pass -i when there is a key.
    KEY_ARG=()
    if [ -n "$VPS_KEY" ] && [ -f "${VPS_KEY/#\~/$HOME}" ]; then
      KEY_ARG=(-i "${VPS_KEY/#\~/$HOME}")
    else
      echo "note: no usable KSSL_VPS_SSH_KEY -- ssh will prompt for a password"
    fi
    echo "tunnelling 127.0.0.1:${KSSL_DB_PORT} -> ${VPS_HOST}; ctrl-c to close"
    ssh -N -p "$VPS_PORT" "${KEY_ARG[@]}" \
        -o ExitOnForwardFailure=yes \
        -L "${KSSL_DB_PORT}:127.0.0.1:${KSSL_DB_PORT}" \
        "${VPS_USER}@${VPS_HOST}"
    ;;
  restore)
    [ -f "$DUMP" ] || { echo "no $DUMP -- run 'dump' first"; exit 1; }
    DB_PW=$(env_get KSSL_DB_PASSWORD)
    : "${DB_PW:?set KSSL_DB_PASSWORD in .env}"
    # through the tunnel opened above; --clean so a re-run replaces rather than
    # duplicates, --if-exists so the FIRST run does not fail on missing objects
    PGPASSWORD="$DB_PW" pg_restore --clean --if-exists --no-owner \
      -h 127.0.0.1 -p "$KSSL_DB_PORT" \
      -U "$KSSL_DB_USER" -d "$KSSL_DB_NAME" "$DUMP"
    ;;
  *)
    sed -n '2,10p' "$0"; exit 1;;
esac
