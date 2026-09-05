#!/usr/bin/env bash
# Refresh a replica's SERVING tables from production, hourly. Run ON the replica.
#
#   ./deploy/refresh_serving.sh staging
#
# WHY THIS EXISTS BESIDE sync_from_prod.sh. That script copies the whole database --
# 12 GB, of which 8.5 GB is the corpus (public.documents + extracted.*). On a replica the
# corpus CANNOT change: extraction runs only on VPS-B (KSSL_EXTRACTION=on is set there and
# nowhere else). So an hourly full sync would re-copy 8.5 GB of provably identical bytes
# 24 times a day and put a 12 GB read on production each time, while 198 workers are using
# that disk.
#
# What actually changes hourly is `serving`, which every enrich pass deletes and rebuilds,
# and which is the ONLY thing the dashboard reads: backend/app.py rewrites `serving.` to
# `serving_live.` and has zero references to extracted.* or public.documents. So this
# copies serving + serving_live + metrics -- 3.7 GB -- and leaves the corpus alone.
#
# IN PLACE, NOT A DATABASE SWAP. sync_from_prod.sh restores into kssl_incoming and renames,
# which is instant but would arrive carrying no corpus at all. Replacing just these schemas
# inside the live database keeps whatever full sync last put there.
#
# ATOMIC. --single-transaction means the DROPs and the reloads are one transaction: readers
# see the previous data until it commits, then the new data, and never a partial rebuild.
# The cost is that readers BLOCK for the length of the restore (a minute or two at this
# size) rather than seeing stale rows. On a QA box that is the right trade; on production
# it would not be, which is one more reason this refuses to run anywhere but a replica.
set -euo pipefail

ENVN="${1:?usage: refresh_serving.sh <staging|dev>}"
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP/deploy/envs/$ENVN.env"
[ -f "$ENV_FILE" ] || { echo "!! no such environment: $ENVN"; exit 2; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

# The same guard sync_from_prod.sh uses, for the same reason: production is the source and
# is never a target. This one matters more, not less -- it runs unattended on a timer.
if [ "${KSSL_DATA_ROLE:-}" != "replica" ]; then
  echo "!! $ENVN has KSSL_DATA_ROLE=${KSSL_DATA_ROLE:-unset}, refusing."
  echo "   Only a replica may be overwritten, and this runs on a timer."
  exit 3
fi

PROD_SSH="${PROD_SSH:-root@62.72.59.79}"
LOCAL_DB="${KSSL_PREFIX}-db"
DUMP="/tmp/kssl_serving_$ENVN.dump"
trap 'rm -f "$DUMP"' EXIT

say() { echo ">> [$(date -u +%H:%M:%S)] $*"; }

if [ "$(docker inspect -f '{{.State.Running}}' "$LOCAL_DB" 2>/dev/null)" != "true" ]; then
  echo "!! $LOCAL_DB is not running"; exit 11
fi

# serving_live is views over serving, so it must be dropped and recreated WITH serving or
# the views end up pointing at tables that no longer exist. metrics is 13 MB and the
# /api/bench endpoints read it.
say "dumping serving from production"
ssh -o BatchMode=yes -o ConnectTimeout=30 "$PROD_SSH" \
  "docker exec -i kssl-db pg_dump -U postgres -d kssl -Fc --no-owner --no-acl \
     -n serving -n serving_live -n metrics" > "$DUMP"
SZ=$(du -h "$DUMP" | cut -f1)

# A truncated or failed dump must not reach the restore: --clean would drop the live
# schemas and then have nothing to put back.
if ! docker exec -i "$LOCAL_DB" sh -c 'cat > /tmp/rs.dump' < "$DUMP"; then
  echo "!! could not stage the dump into $LOCAL_DB"; exit 4
fi
N_TOC=$(docker exec -i "$LOCAL_DB" pg_restore -l /tmp/rs.dump 2>/dev/null | grep -c 'TABLE DATA' || echo 0)
if [ "${N_TOC:-0}" -lt 5 ]; then
  echo "!! the dump lists only ${N_TOC:-0} tables with data -- refusing to --clean the live"
  echo "   schemas with it. Production may have been mid-rebuild, or the dump was cut short."
  docker exec -i "$LOCAL_DB" rm -f /tmp/rs.dump
  exit 5
fi
say "dump is $SZ, $N_TOC table(s) with data -- restoring in one transaction"

# --single-transaction implies exit-on-error, so unlike sync_from_prod.sh the exit code IS
# the test here: nothing is committed unless everything applied.
if docker exec -i "$LOCAL_DB" pg_restore -U postgres -d kssl --single-transaction \
     --clean --if-exists --no-owner --no-acl /tmp/rs.dump 2>/tmp/rs.err; then
  say "committed"
else
  echo "!! restore failed and rolled back -- $ENVN still serves its previous data"
  head -5 /tmp/rs.err 2>/dev/null | sed 's/^/   /'
  docker exec -i "$LOCAL_DB" rm -f /tmp/rs.dump
  exit 6
fi
docker exec -i "$LOCAL_DB" rm -f /tmp/rs.dump

docker exec -i "$LOCAL_DB" psql -U postgres -d kssl -At -c \
  "select '   now: competitors='||(select count(*) from serving.competitors)
        ||' cards='||(select count(*) from serving.signal_card)
        ||' news='||(select count(*) from serving.competitor_news)
        ||' serving_live views='||(select count(*) from information_schema.views
                                    where table_schema='serving_live')
        ||' | corpus left alone: documents='||(select count(*) from public.documents)"
