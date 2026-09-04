#!/usr/bin/env bash
# db/sanitise_replica.sql is what stands between production's data and a QA box that
# other people can reach. It is a DELETE whose predicate is a regex, and a regex that
# matches nothing looks exactly like a clean database -- so it gets a test that plants
# rows it must remove, rows it must keep, and a row only its own guard can catch.
#
#   db/test_sanitise_replica.sh [DSN]        default: the CI postgres service
#
# Runs in CI beside the schema job, against a database built from db/*.sql.
set -euo pipefail

DSN="${1:-${DSN:-postgresql://postgres:kssl@127.0.0.1:5432/kssl}}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${DSN%/*}"
DB=kssl_sanitise_test

psql "$BASE/postgres" -q -c "DROP DATABASE IF EXISTS $DB" -c "CREATE DATABASE $DB"
trap 'psql "$BASE/postgres" -q -c "DROP DATABASE IF EXISTS $DB" >/dev/null 2>&1 || true' EXIT
D="$BASE/$DB"
for f in "$HERE"/[0-9][0-9]_*.sql; do psql "$D" -q -v ON_ERROR_STOP=1 -f "$f"; done

# extract_queue is created by route.py, not by db/*.sql. Planted here because the
# sanitise guards its existence, and a guard that is never exercised is a guess.
psql "$D" -q -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO documents (document_id,url,main_text,fetched_at,text_len) VALUES
 ('d1','https://www.bharatforge.com/defence','x','2026-01-01',1),
 ('d2','https://idrw.org/a','y','2026-01-01',1),
 ('d3','https://kssl.in/products','z','2026-01-01',1),
 ('d4','https://kalyanistrategic.com/x','w','2026-01-01',1);
INSERT INTO extracted.extraction_run (run_id) VALUES ('r1');
INSERT INTO extracted.document (document_id,url,text,text_sha256,n_chars) VALUES
 ('d1','https://www.bharatforge.com/defence','x',repeat('a',64),1),
 ('d2','https://idrw.org/a','y',repeat('b',64),1),
 -- Extraction output whose body sync_documents.py has already rolled off. A delete
 -- that only joins to public.documents leaves this behind.
 ('d9','https://kalyanistrategic.com/gone','q',repeat('c',64),1);
INSERT INTO extracted.span (document_id,run_id,span_id,start_c,end_c,text,type)
 VALUES ('d1','r1','s1',0,1,'x','ORG'), ('d2','r1','s1',0,1,'y','ORG');
CREATE TABLE extract_queue (document_id text PRIMARY KEY);
INSERT INTO extract_queue VALUES ('d1'),('d2'),('d3');
INSERT INTO metrics.stage_run (run_id,stage,host) VALUES ('r1','sync','vps');
SQL

psql "$D" -q -v ON_ERROR_STOP=1 -f "$HERE/sanitise_replica.sql" > /dev/null
# Twice: the sync can be re-run, and the second pass must be a no-op rather than an error.
psql "$D" -q -v ON_ERROR_STOP=1 -f "$HERE/sanitise_replica.sql" > /dev/null

fail=0
check() {  # check <name> <sql> <expected>
  got="$(psql "$D" -Atc "$2")"
  if [ "$got" = "$3" ]; then echo "  ok   $1"
  else echo "  FAIL $1 -- expected '$3', got '$got'"; fail=1; fi
}
check "the client's own pages are gone from the corpus" \
      "select coalesce(string_agg(document_id,',' order by document_id),'') from documents" "d2"
check "and their extraction output with them" \
      "select coalesce(string_agg(document_id,',' order by document_id),'') from extracted.document" "d2"
check "a client row whose body had already rolled off is caught by url, not by the join" \
      "select count(*) from extracted.document where url like '%kalyanistrategic%'" "0"
check "spans cascade -- no orphan evidence left pointing at a deleted document" \
      "select coalesce(string_agg(document_id,',' order by document_id),'') from extracted.span" "d2"
check "the queue no longer claims a body that is not there" \
      "select coalesce(string_agg(document_id,',' order by document_id),'') from extract_queue" "d2"
check "production's stage timings do not become this environment's" \
      "select count(*) from metrics.stage_run" "0"
check "everything else survives -- this sanitises, it does not empty" \
      "select count(*) from documents where url like '%idrw%'" "1"

# The guard itself. Plant a client row and run ONLY the file's final check block --
# lifted out of the file rather than retyped, so this tests the guard that ships. It
# must exit non-zero; a sanitise whose verification cannot fail verifies nothing.
psql "$D" -q -c "INSERT INTO documents (document_id,url,main_text,fetched_at,text_len)
                 VALUES ('d5','https://kssl.in/late','q','2026-01-01',1)" > /dev/null
sed -n '/^-- 3\. THE CHECK/,/^END \$\$;/p' "$HERE/sanitise_replica.sql" > /tmp/guard.sql
if psql "$D" -q -v ON_ERROR_STOP=1 -f /tmp/guard.sql >/dev/null 2>&1; then
  echo "  FAIL the check passed a database still holding a client page"; fail=1
else
  echo "  ok   the check refuses a database still holding a client page"
fi
# ...and a re-run of the whole file cleans it, so the sync can be repeated.
psql "$D" -q -v ON_ERROR_STOP=1 -f "$HERE/sanitise_replica.sql" >/dev/null 2>&1 \
  && echo "  ok   a re-run removes a row that arrived after the last one" \
  || { echo "  FAIL a re-run did not clean up"; fail=1; }

[ "$fail" = 0 ] && echo "sanitise_replica: all checks passed"
exit "$fail"
