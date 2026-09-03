#!/usr/bin/env bash
# Refresh a STAGING or DEV database from production.
#
#   ./deploy/sync_from_prod.sh staging
#   ./deploy/sync_from_prod.sh dev
#
# ONE WAY, ALWAYS. Production is the only writable copy of the corpus and the serving
# tables; this pulls from it and never pushes back. That is what makes staging and dev safe
# to be destructive in -- whatever they do to their data, the next refresh overwrites it and
# prod never saw it.
#
# WHY NOT LOGICAL REPLICATION. It would need wal_level=logical and a restart on the box
# currently running the extraction fleet, and the serving tables are DROPPED and rebuilt by
# every enrich pass, which a replication slot handles badly. A periodic dump is coarser and
# survives that.
#
# WHAT IS COPIED, AND WHY THOSE:
#   public.documents      the corpus bodies -- without them a worker has nothing to extract
#   public.extract_queue  so a non-prod environment can watch a real queue drain
#   extracted.*           the extraction output, so serving projections have inputs
#   serving.*             what the frontend reads; the point of having an environment at all
#
# NOT copied: prio/oversize_backup/prio_demote_backup (operational scratch from one specific
# work order) and the metrics schema (per-host timings that would be misleading elsewhere).
set -euo pipefail

ENVN="${1:?usage: sync_from_prod.sh <staging|dev>}"
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP/deploy/envs/$ENVN.env"
[ -f "$ENV_FILE" ] || { echo "!! no such environment: $ENVN"; exit 2; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

if [ "${KSSL_DATA_ROLE:-}" != "replica" ]; then
  echo "!! $ENVN has KSSL_DATA_ROLE=${KSSL_DATA_ROLE:-unset}, refusing."
  echo "   Only a replica may be overwritten. Production is the source and is never a target."
  exit 3
fi

PROD_SSH="${PROD_SSH:-root@62.72.59.79}"
LOCAL_DB="${KSSL_PREFIX}-db"
DUMP=/tmp/kssl_prod_$ENVN.dump

echo ">> [$(date -u +%H:%M:%S)] dumping production ($PROD_SSH)"
# -Fc is compressed and lets pg_restore run its loads in parallel on the way back in.
# --no-owner/--no-acl because the roles on prod need not exist here.
ssh -o BatchMode=yes -o ConnectTimeout=30 "$PROD_SSH" \
  "docker exec -i kssl-db pg_dump -U postgres -d kssl -Fc --no-owner --no-acl \
     -n public -n extracted -n serving \
     -T public.prio -T public.prio_demote_backup -T public.oversize_backup" > "$DUMP"

SZ=$(du -h "$DUMP" | cut -f1)
echo ">> [$(date -u +%H:%M:%S)] dump is $SZ, restoring into $LOCAL_DB"

# --clean --if-exists so a re-run replaces rather than conflicts. Restore into a temp
# database first and swap only on success: a half-restored environment that still reports
# itself healthy is worse than one that is plainly a version behind.
docker exec -i "$LOCAL_DB" psql -U postgres -d postgres -q \
  -c "DROP DATABASE IF EXISTS kssl_incoming;" -c "CREATE DATABASE kssl_incoming;"
docker exec -i "$LOCAL_DB" pg_restore -U postgres -d kssl_incoming --no-owner --no-acl -j 4 < "$DUMP"

docker exec -i "$LOCAL_DB" psql -U postgres -d postgres -q <<'SQL'
-- Swap under one lock. Sessions on the old database are terminated first, or the rename
-- blocks behind them and the script appears to hang.
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname IN ('kssl','kssl_previous') AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS kssl_previous;
ALTER DATABASE kssl RENAME TO kssl_previous;
ALTER DATABASE kssl_incoming RENAME TO kssl;
SQL

rm -f "$DUMP"
echo ">> [$(date -u +%H:%M:%S)] $ENVN now carries production's data (previous kept as kssl_previous)"
docker exec -i "$LOCAL_DB" psql -U postgres -d kssl -At -c \
  "select 'documents='||(select count(*) from documents)
        ||' extracted='||(select count(*) from extracted.document)
        ||' serving.card='||(select count(*) from serving.card)"
