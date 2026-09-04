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
-- ON_ERROR_STOP and aborts before the rename, so an unsanitised database is never
-- swapped in -- the same shape as the row-count gate that already guards the swap.
--
-- WHAT IT DOES NOT PROMISE. `kssl_incoming` is a real database on the replica's
-- Postgres for the whole restore, and the copy this replaces survives as
-- `kssl_previous` until the sync after next. If THIS file fails, that unsanitised
-- `kssl_incoming` stays on the host until the next run drops it. Anyone who already has
-- the box's database password can read any of them. The guarantee is narrower than
-- "never present on the host": an unsanitised database is never reachable AS `kssl`,
-- which is the one the backend, the frontend and every operator actually open.
--
-- Objects that db/*.sql does not create (extract_queue comes from route.py) are
-- guarded with to_regclass rather than assumed: this file also runs in CI against a
-- database built from db/*.sql alone.
\set ON_ERROR_STOP on

-- ONE definition of "the client's own page", used by every statement below and by the
-- check at the end. Four hand-copied regexes would drift, and the one that drifts is
-- the one in the check -- which is what makes a dirty database look clean.
--
-- ANCHORED TO THE HOST. An unanchored `kssl\.in` also matches
-- https://economictimes.com/news?ref=bharatforge.com and https://www.kssl.info/x --
-- third-party articles deleted with all their extraction output because a client
-- domain appears somewhere in the path or query. Optional leading label so
-- www.bharatforge.com matches and nkssl.in does not.
\set client_rx '^https?://([^/@]*\\.)?(bharatforge\\.com|kalyanistrategic\\.com|kssl\\.in)(:[0-9]+)?([/?#]|$)'

-- REFUSE TO RUN ON THE LIVE DATABASE. Nothing should ever invoke this against `kssl`,
-- and sync_from_prod.sh does not -- but this file is rsynced onto VPS-B with the rest
-- of the tree, and its statements delete corpus rows. The guard costs one query.
DO $$
BEGIN
  IF current_database() NOT IN ('kssl_incoming', 'kssl_sanitise_test') THEN
    RAISE EXCEPTION 'sanitise_replica.sql refuses to run on database %. It is for the '
                    'restored copy (kssl_incoming) only, before the swap.', current_database();
  END IF;
END $$;

-- psql does NOT interpolate :variables inside dollar-quoted bodies, so the check block
-- at the end cannot say :'client_rx' -- it would run the literal text as a regex and
-- match nothing, which is the one failure mode this file must not have. The pattern is
-- parked in a session-scoped temp table instead, and read back from there. Created
-- outside the transaction below so it survives the COMMIT the check runs after.
CREATE TEMP TABLE _rx AS SELECT :'client_rx'::text AS rx;

BEGIN;

-- 1. THE CLIENT'S OWN PAGES. Bharat Forge, Kalyani and KSSL are one identity
--    (source_tiers._CLIENT); their pages are the client's material, not public news,
--    and staging is a box other people can reach. The corpus bodies go, and with them
--    the extraction output derived from them -- extracted.span / proposition /
--    span_value / prop_arg all cascade from extracted.document.
CREATE TEMP TABLE _client_docs ON COMMIT DROP AS
  SELECT document_id FROM public.documents WHERE url ~* :'client_rx';

-- Matched on BOTH sides, not only by joining to public.documents: extracted.document
-- carries its own url and outlives the body it was extracted from (sync_documents.py
-- copies a rolling subset, the extraction output is kept). A join-only delete leaves
-- the propositions behind and removes just the text.
DELETE FROM extracted.document
 WHERE document_id IN (SELECT document_id FROM _client_docs)
    OR url ~* :'client_rx';
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

-- 2. THE CARDS BUILT FROM THOSE PAGES. serving.signal_card carries the article's own
--    title, url, image and a written `sowhat` -- so deleting the body and leaving the
--    card behind removes the evidence and keeps the claim, which is the worse half.
--    signal_detail shares the card's id (serving_fill.py keys both `pl_<document_id>`)
--    and is matched by id as well as by url, because a detail row may carry no url.
CREATE TEMP TABLE _client_cards ON COMMIT DROP AS
  SELECT id FROM serving.signal_card WHERE url ~* :'client_rx'
  UNION
  SELECT id FROM serving.signal_detail WHERE url ~* :'client_rx';

DELETE FROM serving.signal_detail WHERE id IN (SELECT id FROM _client_cards);
DELETE FROM serving.signal_card   WHERE id IN (SELECT id FROM _client_cards);

-- serving.card is the SAME kind of thing and was missed on the first pass: card_text is
-- "the rendered card, exactly as ask.py builds it" and `statements` holds propositions
-- with evidence offsets (extraction/engine/card_writer.py). That is the client's page
-- re-rendered, not a reference to it -- deleting the body and keeping this leaves the
-- material behind under a different name. Keyed (document_id, run_id) so it is matched
-- by document_id as well as by url. Created by card_writer.py rather than db/*.sql,
-- hence the guard.
DO $$
BEGIN
  IF to_regclass('serving.card') IS NOT NULL THEN
    EXECUTE 'DELETE FROM serving.card c
              WHERE c.document_id IN (SELECT document_id FROM _client_docs)
                 OR c.url ~* (SELECT rx FROM _rx)';
  END IF;
END $$;

-- NOT removed, deliberately: serving.competitors, partner, patent, matchup and the rest
-- CITE client URLs as sources for KSSL's own products, which is what the dashboard is
-- for. Stripping those would leave a replica that cannot show the thing it exists to
-- show. The line is between the client's material -- a crawled page, a card rendered
-- from one -- and a reference to it. A citation is not the material.

-- 3. PRODUCTION'S TIMINGS. metrics.* is carried for its STRUCTURE -- the backend's
--    /api/bench endpoints read metrics.stage_run and metrics.adhoc_summary (a view
--    over adhoc_job), and without the schema they 500 -- but production's per-host
--    numbers measured a 198-worker fleet on VPS-B. Left in place they would be read as
--    this environment's, which is precisely the misreading the old sync avoided by
--    dropping the schema altogether and breaking those endpoints instead.
DO $$
BEGIN
  IF to_regclass('metrics.stage_run') IS NOT NULL THEN TRUNCATE metrics.stage_run; END IF;
  IF to_regclass('metrics.adhoc_job') IS NOT NULL THEN TRUNCATE metrics.adhoc_job CASCADE; END IF;
END $$;

COMMIT;

-- 4. THE CHECK. Not decoration: everything above is a DELETE whose predicate is a
--    regex, and a regex that silently matches nothing looks exactly like a clean
--    database. Outside the transaction so it reads committed state.
DO $$
DECLARE r text; n_docs int; n_extr int; n_card int; n_det int; n_srv int;
BEGIN
  SELECT rx INTO r FROM _rx;
  IF r IS NULL OR r = '' THEN
    RAISE EXCEPTION 'sanitise: the pattern is empty -- nothing above can have matched';
  END IF;
  SELECT count(*) INTO n_docs FROM public.documents      WHERE url ~* r;
  SELECT count(*) INTO n_extr FROM extracted.document    WHERE url ~* r;
  SELECT count(*) INTO n_card FROM serving.signal_card   WHERE url ~* r;
  SELECT count(*) INTO n_det  FROM serving.signal_detail WHERE url ~* r;
  IF to_regclass('serving.card') IS NOT NULL THEN
    EXECUTE 'SELECT count(*) FROM serving.card WHERE url ~* $1' INTO n_srv USING r;
  ELSE
    n_srv := 0;
  END IF;
  IF n_docs > 0 OR n_extr > 0 OR n_card > 0 OR n_det > 0 OR n_srv > 0 THEN
    RAISE EXCEPTION 'sanitise: % document(s), % extraction row(s), % signal card(s), '
                    '% detail(s) and % serving.card row(s) survived',
                    n_docs, n_extr, n_card, n_det, n_srv;
  END IF;
  RAISE NOTICE 'sanitise: clean';
END $$;
