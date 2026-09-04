#!/usr/bin/env bash
# db/sanitise_replica.sql is what stands between production's data and a QA box that
# other people can reach. It is a set of DELETEs whose predicate is a regex, and a regex
# that matches nothing looks exactly like a clean database -- so it gets a test that
# plants rows it must remove, rows it must keep, and a row only its own guard can catch.
#
#   db/test_sanitise_replica.sh [DSN]        default: the CI postgres service
#
# Runs in CI beside the schema job, against a database built from db/*.sql.
#
# THE NEAR-MISS URLS BELOW ARE THE POINT. An unanchored `kssl\.in` also matches
# https://economictimes.com/news?ref=bharatforge.com -- a third-party article deleted
# with all its extraction output because a client domain appears in the query string.
# Each one here is a real shape the corpus carries.
set -euo pipefail

DSN="${1:-${DSN:-postgresql://postgres:kssl@127.0.0.1:5432/kssl}}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${DSN%/*}"
DB=kssl_sanitise_test   # sanitise_replica.sql's own guard permits exactly this name

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
 ('d4','https://kalyanistrategic.com/x','w','2026-01-01',1),
 -- must SURVIVE: third-party articles that merely mention a client domain
 ('k1','https://economictimes.com/news?ref=bharatforge.com','a','2026-01-01',1),
 ('k2','https://www.kssl.info/x','b','2026-01-01',1),
 ('k3','https://www.nkssl.in/x','c','2026-01-01',1),
 ('k4','https://idrw.org/2026/01/bharatforge.com-wins-order','d','2026-01-01',1);
INSERT INTO extracted.extraction_run (run_id) VALUES ('r1');
INSERT INTO extracted.document (document_id,url,text,text_sha256,n_chars) VALUES
 ('d1','https://www.bharatforge.com/defence','x',repeat('a',64),1),
 ('d2','https://idrw.org/a','y',repeat('b',64),1),
 -- Extraction output whose body sync_documents.py has already rolled off. A delete
 -- that only joins to public.documents leaves this behind.
 ('d9','https://kalyanistrategic.com/gone','q',repeat('c',64),1),
 ('k1','https://economictimes.com/news?ref=bharatforge.com','a',repeat('d',64),1);
INSERT INTO extracted.span (document_id,run_id,span_id,start_c,end_c,text,type)
 VALUES ('d1','r1','s1',0,1,'x','ORG'), ('d2','r1','s1',0,1,'y','ORG');
CREATE TABLE extract_queue (document_id text PRIMARY KEY);
INSERT INTO extract_queue VALUES ('d1'),('d2'),('d3');
INSERT INTO metrics.stage_run (run_id,stage,host) VALUES ('r1','sync','vps');
-- Cards written FROM the client's own pages: the body would go and the claim would stay.
INSERT INTO serving.signal_card (id,lane,ord,title,url,sowhat,origin) VALUES
 ('pl_d1','competitive',1,'KSSL launches X','https://www.bharatforge.com/defence','so what','pipeline'),
 ('pl_d2','competitive',2,'Rival wins order','https://idrw.org/a','so what','pipeline');
INSERT INTO serving.signal_detail (id,ord,title,url,origin) VALUES
 ('pl_d1',1,'KSSL launches X','https://www.bharatforge.com/defence','pipeline'),
 ('pl_d3',3,'KSSL brochure','https://kssl.in/products','pipeline'),
 ('pl_d2',2,'Rival wins order','https://idrw.org/a','pipeline');
-- A citation is not the client's material: these SOURCE a KSSL product and must stay.
INSERT INTO serving.competitors (comp_id,ord,name,origin) VALUES ('bharat-forge',1,'Bharat Forge','pipeline');
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
      "select coalesce(string_agg(document_id,',' order by document_id),'') from documents" "d2,k1,k2,k3,k4"
check "and their extraction output with them" \
      "select coalesce(string_agg(document_id,',' order by document_id),'') from extracted.document" "d2,k1"
check "a client row whose body had already rolled off is caught by url, not by the join" \
      "select count(*) from extracted.document where url like '%kalyanistrategic%'" "0"
check "a client domain in a third party's QUERY STRING is not a client page" \
      "select count(*) from documents where document_id='k1'" "1"
check "kssl.info and nkssl.in are different hosts and survive" \
      "select count(*) from documents where document_id in ('k2','k3')" "2"
check "a client domain in a third party's PATH is not a client page" \
      "select count(*) from documents where document_id='k4'" "1"
check "spans cascade -- no orphan evidence left pointing at a deleted document" \
      "select coalesce(string_agg(document_id,',' order by document_id),'') from extracted.span" "d2"
check "the queue no longer claims a body that is not there" \
      "select coalesce(string_agg(document_id,',' order by document_id),'') from extract_queue" "d2"
check "the card written from a client page goes with the page" \
      "select coalesce(string_agg(id,',' order by id),'') from serving.signal_card" "pl_d2"
check "so does its detail, and a detail matched only by its own url" \
      "select coalesce(string_agg(id,',' order by id),'') from serving.signal_detail" "pl_d2"
check "production's stage timings do not become this environment's" \
      "select count(*) from metrics.stage_run" "0"
check "a citation is not the material -- competitor rows sourcing a client page stay" \
      "select count(*) from serving.competitors where comp_id='bharat-forge'" "1"
check "everything else survives -- this sanitises, it does not empty" \
      "select count(*) from documents where url like '%idrw%'" "2"

# THE GUARD ITSELF. Plant a client row and run only the file's final check block --
# lifted out of the file rather than retyped, so this tests the guard that ships. It
# must exit non-zero; a sanitise whose verification cannot fail verifies nothing.
psql "$D" -q -c "INSERT INTO documents (document_id,url,main_text,fetched_at,text_len)
                 VALUES ('d5','https://kssl.in/late','q','2026-01-01',1)" > /dev/null
{ sed -n "/^\\\\set client_rx/p" "$HERE/sanitise_replica.sql"
  echo "CREATE TEMP TABLE _rx AS SELECT :'client_rx'::text AS rx;"
  sed -n '/^-- 4\. THE CHECK/,/^END \$\$;/p' "$HERE/sanitise_replica.sql"; } > /tmp/guard.sql
grep -q 'client_rx' /tmp/guard.sql || { echo "  FAIL could not lift the guard out of the file"; fail=1; }
if psql "$D" -q -v ON_ERROR_STOP=1 -f /tmp/guard.sql >/dev/null 2>&1; then
  echo "  FAIL the check passed a database still holding a client page"; fail=1
else
  echo "  ok   the check refuses a database still holding a client page"
fi
# ...and a re-run of the whole file cleans it, so the sync can be repeated.
if psql "$D" -q -v ON_ERROR_STOP=1 -f "$HERE/sanitise_replica.sql" >/dev/null 2>&1; then
  echo "  ok   a re-run removes a row that arrived after the last one"
else
  echo "  FAIL a re-run did not clean up"; fail=1
fi

# AND IT MUST REFUSE THE LIVE DATABASE. The file is rsynced onto VPS-B with the rest of
# the tree and its statements delete corpus rows; only the restored copy may run it.
psql "$BASE/postgres" -q -c "DROP DATABASE IF EXISTS kssl_sanitise_live" -c "CREATE DATABASE kssl_sanitise_live"
if psql "$BASE/kssl_sanitise_live" -q -v ON_ERROR_STOP=1 -f "$HERE/sanitise_replica.sql" >/dev/null 2>&1; then
  echo "  FAIL it ran against a database that is not the restored copy"; fail=1
else
  echo "  ok   it refuses any database but the restored copy"
fi
psql "$BASE/postgres" -q -c "DROP DATABASE kssl_sanitise_live" >/dev/null

[ "$fail" = 0 ] && echo "sanitise_replica: all checks passed"
exit "$fail"
