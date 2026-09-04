#!/usr/bin/env bash
# Refresh a STAGING or DEV database from production.
#
#   ./deploy/sync_from_prod.sh staging
#   ./deploy/sync_from_prod.sh dev
#
# RUN IT DETACHED. A restore of production's dump takes many minutes, and over a plain SSH
# session a dropped connection kills pg_restore mid-way:
#
#   systemd-run --unit=kssl-sync --collect --property=WorkingDirectory=/opt/kssl/app \
#     --setenv=DUMP_FILE=/tmp/prod.dump ./deploy/sync_from_prod.sh staging
#
# The restore-then-rename below means an interrupted run is harmless -- kssl_incoming is
# left behind and the live database is untouched -- but finishing beats retrying.
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
#   serving.*             the projections the pipeline writes
#   serving_live.*        WHAT THE BACKEND ACTUALLY QUERIES. backend/app.py rewrites every
#                         `serving.` to `serving_live.` unless KSSL_SERVE_ORIGIN=all, and
#                         serving_live is a set of views, not tables -- so a dump without
#                         it produced a database the frontend 500s against on every page
#                         while every count below reported healthy.
#   metrics.*             for its STRUCTURE: /api/bench reads metrics.stage_run and
#                         metrics.adhoc_summary. Its ROWS are production's per-host
#                         timings and are truncated by the sanitise stage -- carrying the
#                         schema and dropping the numbers, rather than the old choice of
#                         dropping both and breaking the endpoints.
#
# NOT copied: prio/oversize_backup/prio_demote_backup (operational scratch from one specific
# work order).
#
# TWO STAGES BETWEEN RESTORE AND SWAP, both of which abort before the rename if they fail:
#   sanitise  db/sanitise_replica.sql -- the client's own pages and prod's timings leave
#             before the database becomes reachable. A replica host is a QA box.
#   slice     optional (KSSL_SLICE_DOCS), keeps only the newest N documents.
# And one after it:
#   migrate   the restored schema is production's as of the dump; this checkout may be
#             ahead of it. Same ledger runner the deploy uses, so a replica is never
#             running new code against an old schema.
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

# PREFLIGHT, BEFORE ANYTHING EXPENSIVE. Both of these were once checked at the migrate
# step, which runs at the END -- so a missing file or an unparseable compose meant a
# multi-minute dump and restore, and then a failure. Everything knowable up front is
# checked up front.
if [ ! -f "$APP/extraction/.env" ]; then
  echo "!! extraction/.env is missing, so the migrate step could not run and this sync"
  echo "   would leave $ENVN on production's schema. Run deploy/provision_env.sh $ENVN first."
  exit 8
fi
# `compose config -q` parses and interpolates the whole file without starting anything.
# Compose applies every ${VAR:?} in the file regardless of which service is targeted, so
# this is the only cheap way to know `run --rm migrate` will work before relying on it.
if ! ( cd "$APP/extraction" && docker compose -f docker-compose.yml config -q ); then
  echo "!! extraction/docker-compose.yml does not parse with this host's extraction/.env,"
  echo "   so the migrate step at the end of this sync would fail AFTER the swap. Fix it"
  echo "   first: every \${VAR:?...} in the compose file needs a non-empty value."
  exit 8
fi

PROD_SSH="${PROD_SSH:-root@62.72.59.79}"
LOCAL_DB="${KSSL_PREFIX}-db"
DUMP=/tmp/kssl_prod_$ENVN.dump

# A dump can also be DELIVERED rather than pulled:
#
#   DUMP_FILE=/tmp/prod.dump ./deploy/sync_from_prod.sh staging
#
# That path exists because the replica hosts have no SSH key to production and issuing one
# would mean changing production to serve a non-production environment. An operator who can
# reach both machines streams the dump across and points this at the file.
if [ -n "${DUMP_FILE:-}" ]; then
  [ -f "$DUMP_FILE" ] || { echo "!! DUMP_FILE=$DUMP_FILE does not exist"; exit 4; }
  DUMP="$DUMP_FILE"
  echo ">> [$(date -u +%H:%M:%S)] using delivered dump $DUMP"
else
echo ">> [$(date -u +%H:%M:%S)] dumping production ($PROD_SSH)"
# -Fc is compressed and lets pg_restore run its loads in parallel on the way back in.
# --no-owner/--no-acl because the roles on prod need not exist here.
ssh -o BatchMode=yes -o ConnectTimeout=30 "$PROD_SSH" \
  "docker exec -i kssl-db pg_dump -U postgres -d kssl -Fc --no-owner --no-acl \
     -n public -n extracted -n serving -n serving_live -n metrics \
     -T public.prio -T public.prio_demote_backup -T public.oversize_backup" > "$DUMP"
fi

SZ=$(du -h "$DUMP" | cut -f1)
echo ">> [$(date -u +%H:%M:%S)] dump is $SZ, restoring into $LOCAL_DB"

# --clean --if-exists so a re-run replaces rather than conflicts. Restore into a temp
# database first and swap only on success: a half-restored environment that still reports
# itself healthy is worse than one that is plainly a version behind.
# DROP first: an interrupted run leaves a partial kssl_incoming behind, and restoring into
# it again would silently merge two attempts.
docker exec -i "$LOCAL_DB" psql -U postgres -d postgres -q \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='kssl_incoming' AND pid <> pg_backend_pid();" \
  -c "DROP DATABASE IF EXISTS kssl_incoming;" -c "CREATE DATABASE kssl_incoming;"
# A new database is created WITH a public schema, and the dump carries its own
# "CREATE SCHEMA public" -- which then fails with 'schema "public" already exists'. Drop it
# so the dump can create it, rather than leaving pg_restore to report an error for a step
# that actually needs to happen.
docker exec -i "$LOCAL_DB" psql -U postgres -d kssl_incoming -q -c "DROP SCHEMA IF EXISTS public CASCADE;"
# pg_restore cannot run a PARALLEL restore from a stream -- "parallel restore from standard
# input is not supported" -- and a 973MB dump is exactly where -j earns its keep. So the
# dump goes INTO the container as a file first, and is removed afterwards.
docker cp "$DUMP" "$LOCAL_DB:/tmp/restore.dump"
# pg_restore's exit code is NOT the test. It returns non-zero for warnings that do not
# matter (a missing role, an extension comment) and, with -j, keeps going after a failed
# item -- so trusting it either aborts a good restore or, worse, lets a bad one through.
# The test below is whether the data actually arrived.
set +e
docker exec -i "$LOCAL_DB" pg_restore -U postgres -d kssl_incoming --no-owner --no-acl -j 4 /tmp/restore.dump 2>/tmp/restore.err
RC=$?
set -e
docker exec -i "$LOCAL_DB" rm -f /tmp/restore.dump
[ "$RC" -eq 0 ] || echo "   pg_restore exited $RC; $(grep -c . /tmp/restore.err 2>/dev/null || echo 0) message(s) -- verifying the data instead"

# VERIFY BEFORE SWAPPING. An environment that is a version behind is fine; one that is
# half-loaded while reporting itself healthy is not.
CNT=$(docker exec -i "$LOCAL_DB" psql -U postgres -d kssl_incoming -At -F' ' -c \
  "select (select count(*) from public.documents), (select count(*) from extracted.document), (select count(*) from serving.card)" 2>/dev/null || echo "")
read -r N_DOCS N_EXTR N_CARD <<< "${CNT:-0 0 0}"
echo "   restored: documents=$N_DOCS extracted=$N_EXTR serving.card=$N_CARD"
if [ "${N_DOCS:-0}" -lt 1 ] || [ "${N_CARD:-0}" -lt 1 ]; then
  echo "!! restore did not produce data -- leaving $ENVN on its previous database untouched."
  [ -s /tmp/restore.err ] && { echo "   first errors:"; head -5 /tmp/restore.err; }
  exit 6
fi

# serving_live is views, not tables, so no row count can miss it -- and its absence is
# invisible until the frontend loads. Checked by name, before the swap, because that is
# the failure this sync actually had: every count above healthy, every page 500.
N_VIEWS=$(docker exec -i "$LOCAL_DB" psql -U postgres -d kssl_incoming -Atc \
  "select count(*) from information_schema.views where table_schema='serving_live'" 2>/dev/null || echo 0)
if [ "${N_VIEWS:-0}" -lt 1 ]; then
  echo "!! the dump carried no serving_live views -- backend/app.py queries that schema and"
  echo "   would 500 on every page. Leaving $ENVN untouched; re-dump with -n serving_live."
  exit 7
fi
echo "   serving_live: $N_VIEWS view(s)"

# --- SANITISE. Before the swap, so an unsanitised database is never reachable. ------
# ON_ERROR_STOP and `set -e` together: the file raises if what it removed is still there,
# psql exits non-zero, and this script dies BEFORE the rename. That ordering is the whole
# guarantee -- staging keeps serving its previous database rather than a fresh copy of the
# client's material.
echo ">> [$(date -u +%H:%M:%S)] sanitising"
docker exec -i "$LOCAL_DB" psql -U postgres -d kssl_incoming -q -v ON_ERROR_STOP=1 \
  < "$APP/db/sanitise_replica.sql"

# --- SLICE (optional). ---------------------------------------------------------------
# KSSL_SLICE_DOCS=20000 keeps only the newest N corpus documents. For the data centre,
# which is a shared box and does not need 35k bodies to prove a change runs.
#
# ponytail: this trims AFTER the transfer, so it bounds the replica's disk, not the
# 7.9 GB that crossed the wire. A real slice has to be built on production -- an
# export step there, reading only -- and that is the upgrade when transfer time hurts.
if [ -n "${KSSL_SLICE_DOCS:-}" ]; then
  # psql -v substitutes the value as raw SQL text, so it is checked as a number here
  # rather than trusted from an env file.
  case "$KSSL_SLICE_DOCS" in
    ''|*[!0-9]*) echo "!! KSSL_SLICE_DOCS must be a positive integer, got '$KSSL_SLICE_DOCS'"; exit 9 ;;
  esac
  echo ">> [$(date -u +%H:%M:%S)] slicing to the newest $KSSL_SLICE_DOCS document(s)"
  docker exec -i "$LOCAL_DB" psql -U postgres -d kssl_incoming -q -v ON_ERROR_STOP=1 \
    -v n="$KSSL_SLICE_DOCS" <<'SQL'
BEGIN;
-- EACH TABLE BY ITS OWN NEWEST N, not both by the corpus's. extracted.document has no
-- FK to public.documents and deliberately outlives it: sync_documents.py copies a
-- rolling window of bodies while the extraction output accumulates. Keeping only the
-- extraction rows whose BODY survived would therefore delete most of extracted.* on a
-- replica -- orphaning serving.card and signal_card from the spans they were built
-- from -- which is the opposite of bounding disk.
CREATE TEMP TABLE _keep_doc ON COMMIT DROP AS
  SELECT document_id FROM public.documents   ORDER BY fetched_at DESC LIMIT :n;
CREATE TEMP TABLE _keep_ext ON COMMIT DROP AS
  SELECT document_id FROM extracted.document ORDER BY first_seen DESC LIMIT :n;
-- Spans, propositions and their arguments cascade from extracted.document.
DELETE FROM extracted.document WHERE document_id NOT IN (SELECT document_id FROM _keep_ext);
DELETE FROM public.documents   WHERE document_id NOT IN (SELECT document_id FROM _keep_doc);
-- The queue last, because the slice has just removed bodies it may point at. The
-- sanitise does this too, but it runs BEFORE the slice, so on its own it leaves exactly
-- the rows this step creates: a claim on a document that is no longer there, which a
-- worker retries until its lease reaping gives up.
DO $$
BEGIN
  IF to_regclass('public.extract_queue') IS NOT NULL
     AND EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema='public' AND table_name='extract_queue'
                    AND column_name='document_id') THEN
    EXECUTE 'DELETE FROM public.extract_queue q WHERE NOT EXISTS
               (SELECT 1 FROM public.documents d WHERE d.document_id = q.document_id)';
  END IF;
END $$;
COMMIT;
SQL
  # serving.* is left whole. It is small next to the bodies, and a card whose source
  # document was sliced away still renders -- it carries its own url and quote.
  docker exec -i "$LOCAL_DB" psql -U postgres -d kssl_incoming -Atc \
    "select '   sliced to documents='||(select count(*) from public.documents)
          ||' extracted='||(select count(*) from extracted.document)"
fi

# --- MIGRATE, BEFORE THE SWAP. The restored schema is production's AT THE MOMENT OF THE
# DUMP, and this checkout is by definition ahead of it -- staging exists to run code prod
# has not seen. Without this step every sync silently reverts the replica's schema and the
# next deploy runs new code against an old one.
#
# It runs against kssl_incoming, NOT after the rename, so a migration that fails leaves
# the environment on its PREVIOUS database rather than on a freshly restored one carrying
# production's schema -- the same principle as restoring into kssl_incoming in the first
# place. Same ledger runner the deploy uses (each file applied once, recorded in
# schema_version), not a second copy of its logic.
#
# The DSN is the host's own, with only the database name changed, so the credentials and
# port stay whatever provision_env.sh wrote. The guard below is not decoration: if that
# substitution ever fails to bite, migrate would run against the LIVE database.
#
# Two -e expressions, not one with `\|`: alternation is a GNU extension to basic regex
# and silently matches nothing elsewhere, which the guard below would then catch as a
# refusal rather than as the wrong database -- but a check that always refuses is no
# check. `dbname=kssl` mid-line and at end-of-line are the two forms.
INC_DSN="$(sed -n 's/^KSSL_CORPUS_DSN=//p' "$APP/extraction/.env" | head -1 \
           | sed -e 's/\(dbname=\)kssl\([[:space:]]\)/\1kssl_incoming\2/' \
                 -e 's/\(dbname=\)kssl$/\1kssl_incoming/')"
case "$INC_DSN" in
  *dbname=kssl_incoming*) : ;;
  *) echo "!! could not point the migrate role at kssl_incoming."
     echo "   KSSL_CORPUS_DSN in extraction/.env must contain 'dbname=kssl'. Refusing to run"
     echo "   a migration that might target the live database."; exit 10 ;;
esac
echo ">> [$(date -u +%H:%M:%S)] applying pending migrations to the restored copy"
( cd "$APP/extraction" && docker compose -f docker-compose.yml \
    run --rm -e KSSL_CORPUS_DSN="$INC_DSN" migrate )

docker exec -i "$LOCAL_DB" psql -U postgres -d postgres -q <<'SQL'
-- Swap under one lock. Sessions on the old database are terminated first, or the rename
-- blocks behind them and the script appears to hang.
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname IN ('kssl','kssl_previous') AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS kssl_previous;
ALTER DATABASE kssl RENAME TO kssl_previous;
ALTER DATABASE kssl_incoming RENAME TO kssl;
SQL

[ -z "${DUMP_FILE:-}" ] && rm -f "$DUMP"   # a delivered dump belongs to the caller
echo ">> [$(date -u +%H:%M:%S)] $ENVN now carries production's data (previous kept as kssl_previous)"
docker exec -i "$LOCAL_DB" psql -U postgres -d kssl -At -c \
  "select 'documents='||(select count(*) from documents)
        ||' extracted='||(select count(*) from extracted.document)
        ||' serving.card='||(select count(*) from serving.card)"
