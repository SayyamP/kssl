#!/bin/sh
# Run a migration against a copy of PRODUCTION's schema before running it on production.
#
#   db/rehearse_migration.sh
#
# This is the check that caught both faults in the 2026-09-04 migration, and neither was
# visible any other way:
#
#   1. A migration file edited AFTER production had applied it. The runner keys its ledger
#      on filename, so the edit was invisible to prod -- the table stayed six columns wide
#      while the next deploy shipped code writing nine. Only a copy carrying production's
#      real ledger shows this; a fresh database applies the edited file and looks fine.
#   2. The deploy's rsync has no --delete, so renamed schema files pile up on the box. On
#      an existing database that is harmless, on an empty one the base apply runs every
#      schema twice and dies. Only a copy of the real tree shows this.
#
# It runs extraction/entrypoint.sh itself rather than reimplementing the apply loop, so
# what is rehearsed is the runner that will actually run, not a second copy of its logic.
#
# Needs: a local Postgres (same major as prod) and ssh to the prod host. Touches nothing
# on production -- one pg_dump --schema-only and one SELECT from the ledger, both reads.
set -eu

PROD_SSH="${KSSL_PROD_SSH:-root@62.72.59.79}"
PROD_DB="${KSSL_PROD_DB:-kssl}"
PG="${KSSL_LOCAL_PG:-postgresql://postgres@127.0.0.1:5499/postgres}"
COPY_DB="${KSSL_COPY_DB:-kssl_prodcopy}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say() { printf '\n== %s\n' "$*"; }

say "pulling production's schema and ledger (read-only)"
ssh -o BatchMode=yes "$PROD_SSH" \
  "docker exec kssl-db pg_dump -U postgres -d $PROD_DB --schema-only --no-owner --no-privileges" \
  > "$WORK/schema.sql"
ssh -o BatchMode=yes "$PROD_SSH" \
  "docker exec kssl-db psql -U postgres -d $PROD_DB -Atc \"copy (select filename, applied_at from schema_version) to stdout\"" \
  > "$WORK/ledger.tsv" 2>/dev/null || : > "$WORK/ledger.tsv"
echo "   schema: $(grep -c '^CREATE ' "$WORK/schema.sql") CREATE statements, ledger: $(wc -l < "$WORK/ledger.tsv") row(s)"

say "building a local copy"
BASE="${PG%/*}"
psql "$PG" -q -c "DROP DATABASE IF EXISTS $COPY_DB" -c "CREATE DATABASE $COPY_DB"
psql "$BASE/$COPY_DB" -q -v ON_ERROR_STOP=1 -f "$WORK/schema.sql" > /dev/null
# The ledger is the whole point: without it every migration looks pending and the
# rehearsal silently tests a case production is not in.
if [ -s "$WORK/ledger.tsv" ]; then
  psql "$BASE/$COPY_DB" -q -c "COPY schema_version (filename, applied_at) FROM STDIN" < "$WORK/ledger.tsv"
fi

say "running the real migrate role against it"
# entrypoint.sh resolves its paths from its own location, so give it a tree that looks
# like the container's: db/ beside it, and engine/ + signals/ because it touches them.
cp "$HERE/extraction/entrypoint.sh" "$WORK/"
ln -s "$HERE/db" "$WORK/db"
ln -s "$HERE/extraction/engine" "$WORK/engine"
ln -s "$HERE/extraction/signals" "$WORK/signals"
KSSL_CORPUS_DSN="$BASE/$COPY_DB" sh "$WORK/entrypoint.sh" migrate

say "does a migrated production match a database built from db/*.sql?"
"$HERE/db/schema_snapshot.sh" "$BASE/$COPY_DB" > "$WORK/after.txt"
if diff -u "$HERE/db/schema_snapshot.txt" "$WORK/after.txt"; then
  echo "   IDENTICAL -- safe to run this migration on production"
else
  echo
  echo "   DIVERGED. The migration does not leave production in the state db/*.sql builds."
  echo "   Left is what a fresh database gets, right is what production would become."
  exit 1
fi
