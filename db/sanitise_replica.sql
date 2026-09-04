-- Everything a QA copy of production must NOT carry. Run against `kssl_incoming`
-- BETWEEN the restore and the swap, by deploy/sync_from_prod.sh.
--
-- WHY HERE AND NOT IN THE DUMP. pg_dump filters tables, not rows, and the rows that
-- matter here are picked by a URL pattern. Doing it after the restore also means the
-- check below runs against the database that is about to become `kssl` -- not against
-- a dump nobody reads.
--
-- IT MUST FAIL LOUDLY. The last DO block re-counts what this file claims to have
-- removed and raises if anything survived. sync_from_prod.sh runs psql with
-- ON_ERROR_STOP and aborts before the rename, so an unsanitised database can never
-- be swapped in -- the same shape as the row-count gate that already guards the swap.
--
-- Objects that db/*.sql does not create (extract_queue comes from route.py) are
-- guarded with to_regclass rather than assumed: this file also runs in CI against a
-- database built from db/*.sql alone.
\set ON_ERROR_STOP on
BEGIN;

-- 1. THE CLIENT'S OWN PAGES. Bharat Forge, Kalyani and KSSL are one identity
--    (source_tiers._CLIENT); their pages are the client's material, not public news,
--    and staging is a box other people can reach. The corpus bodies go, and with them
--    the extraction output derived from them -- extracted.span / proposition /
--    span_value / prop_arg all cascade from extracted.document.
CREATE TEMP TABLE _client_docs ON COMMIT DROP AS
  SELECT document_id FROM public.documents WHERE url ~* '(bharatforge|kalyanistrategic|kssl)\.(com|in)';

-- Matched on BOTH sides, not only by joining to public.documents: extracted.document
-- carries its own url and outlives the body it was extracted from (sync_documents.py
-- copies a rolling subset, the extraction output is kept). A join-only delete leaves
-- the propositions behind and removes just the text.
DELETE FROM extracted.document
 WHERE document_id IN (SELECT document_id FROM _client_docs)
    OR url ~* '(bharatforge|kalyanistrategic|kssl)\.(com|in)';
DELETE FROM public.documents WHERE document_id IN (SELECT document_id FROM _client_docs);

-- The queue would otherwise point at bodies that are no longer there, and a worker
-- claiming one fails on every retry until its lease reaping gives up.
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

-- 2. PRODUCTION'S TIMINGS. metrics.* is carried for its STRUCTURE -- the backend's
--    /api/bench endpoints read metrics.stage_run and metrics.adhoc_summary, and
--    without the schema they 500 -- but production's per-host numbers measured a
--    198-worker fleet on VPS-B. Left in place they would be read as this
--    environment's, which is precisely the misreading the old sync avoided by
--    dropping the schema altogether and breaking those endpoints instead.
DO $$
BEGIN
  IF to_regclass('metrics.stage_run') IS NOT NULL THEN TRUNCATE metrics.stage_run; END IF;
  IF to_regclass('metrics.adhoc_job') IS NOT NULL THEN TRUNCATE metrics.adhoc_job CASCADE; END IF;
END $$;

-- 3. THE CHECK. Not decoration: 1 and 2 are DELETEs whose predicate is a regex, and a
--    regex that silently matches nothing looks exactly like a clean database.
DO $$
DECLARE n_docs int; n_extr int;
BEGIN
  SELECT count(*) INTO n_docs FROM public.documents
   WHERE url ~* '(bharatforge|kalyanistrategic|kssl)\.(com|in)';
  SELECT count(*) INTO n_extr FROM extracted.document
   WHERE url ~* '(bharatforge|kalyanistrategic|kssl)\.(com|in)';
  IF n_docs > 0 OR n_extr > 0 THEN
    RAISE EXCEPTION 'sanitise: % client document(s) and % extraction row(s) survived', n_docs, n_extr;
  END IF;
  RAISE NOTICE 'sanitise: clean';
END $$;

COMMIT;
