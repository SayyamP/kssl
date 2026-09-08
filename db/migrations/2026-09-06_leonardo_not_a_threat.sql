-- A threat with no profile behind it: the two curated lists disagreed about Leonardo.
--
-- roster.py exists because two questions must be answered the same way -- "may this
-- company's news be called a threat" (serving.competitor_roster_allow) and "does this
-- company get a Competitor profile" (serving.competitors). Its own docstring names the
-- failure: "how a company ends up ... flagged as a threat with no profile to click
-- through to."
--
-- That is what shipped. "Leonardo Secures Brazilian Centauro II Order" rendered as the
-- number-one red COMPETITIVE THREAT on the overview, while the Competitor tab -- 28
-- profiles -- had no Leonardo to open. The operator sees a threat and cannot ask who
-- from.
--
-- Leonardo is not a direct competitor of KSSL. It is an Italian prime; the roster is
-- deliberately India-centred, and the reference dataset already carries Leonardo the
-- other way -- as a geoComp with dir='watch', a global presence to be aware of, not a
-- rival to be scored against. The allow-list row is the outlier, so it is the outlier
-- that goes.
--
-- 'leonardo%' is anchored at the start on purpose: it takes the parent and its
-- divisions (Leonardo DRS, whose thermal-camera contract was another red badge in a
-- KSSL core line) and cannot reach a company that merely contains the word.
--
-- REVERSIBLE. If Leonardo should instead become a real rival, do not re-add the
-- allow-list row alone -- that recreates this bug from the other side. Give it a
-- profile in serving.competitors first, then re-INSERT here so both lists agree.

-- GUARDED, because serving.competitor_roster_allow is created by no migration and by
-- no schema file in this repo -- it is absent from db/live/schema_live.sql, the VPS1
-- snapshot taken 2026-09-01. roster.py treats it as ADVISORY and returns "no opinion"
-- when it is missing, so an unguarded DELETE here would be the one statement in the
-- system that requires it to exist, and would abort this file on any database that
-- never had it.
DO $$
DECLARE
  removed integer;
BEGIN
  IF to_regclass('serving.competitor_roster_allow') IS NOT NULL THEN
    DELETE FROM serving.competitor_roster_allow WHERE name ILIKE 'leonardo%';
    -- counted from the DELETE itself; a SELECT after it always reports zero, which
    -- would make a no-op and a real removal print the same line
    GET DIAGNOSTICS removed = ROW_COUNT;
    RAISE NOTICE 'roster allow-list: % Leonardo row(s) removed', removed;
  ELSE
    RAISE WARNING 'serving.competitor_roster_allow does not exist: the roster gate is '
                  'INERT on this database, so every company that clears the evidence '
                  'test can be a threat. The card re-grade below still applies, but it '
                  'is not durable -- the next pipeline pass re-derives dir at write '
                  'time. Seeding this table from serving.competitors is the durable '
                  'fix and is a separate, deliberate change.';
  END IF;
END $$;

-- The allow-list is read when a card is WRITTEN, so the cards already on the overview
-- keep the dir they were stored with. Re-grade them, or the red badge stays until every
-- one of those documents happens to be reprocessed.
UPDATE serving.signal_card
   SET dir = 'watch', updated_at = now()
 WHERE dir = 'threat'
   AND company ILIKE 'leonardo%';

-- signal_detail carries its own copy of dir and has no company column; it is joined by
-- id. It runs after the card update and filters on the DETAIL's dir, so it is
-- idempotent and is not confused by rows the statement above already changed.
UPDATE serving.signal_detail d
   SET dir = 'watch', updated_at = now()
  FROM serving.signal_card c
 WHERE d.id = c.id
   AND d.dir = 'threat'
   AND c.company ILIKE 'leonardo%';
