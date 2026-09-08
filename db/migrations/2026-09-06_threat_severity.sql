-- Threat gate: a severity column that holds a severity, and a record of demotions.
--
-- NOT RUN by whoever wrote this. deploy.sh applies no migrations on any environment
-- (sync_from_prod.sh is the only thing that does, and it says so itself), so everything
-- below is optional to the code that ships with it: extraction/signals/serving_fill.py
-- feature-detects dir_reason before naming it, and backend/app.py derives severity at
-- serve time rather than reading a column. Run this when no pass is in flight.
--
-- WHAT IT FIXES
--
-- 1. serving.competitors.threat is documented as "high, medium or low" and has no
--    constraint saying so. Two production rows hold a paragraph:
--
--      "Adani Defence - 9 mapped partnership(s), 1 touching KSSL core lines. Lead:
--       Alpha Design Technologies - CORE OVERLAP (ammunition/propellants...)"
--
--    That is a threatNote in the threat column. Every consumer renders whatever it finds
--    as a rating -- the Profile dot, the Products dot, the patent leader sort -- and the
--    new severity grade would have derived a severity from it. The writers are fixed
--    (enrich_serving.py now routes every write through threat_gate.threat_level), and
--    this adds the constraint that makes the next writer's mistake fail loudly instead
--    of rendering.
--
-- 2. A card demoted from threat to watch had nowhere to record WHY. "This was demoted
--    because its company is not a served competitor" and "this was never a threat" are
--    different states and only one of them is worth an operator's time.
--
-- WHAT IT DELIBERATELY DOES NOT ADD: a severity column on signal_card. Severity is
-- derived from two tables that are rebuilt on different schedules (the card pass and the
-- competitor pass), so a stored copy is stale for exactly as long as the gap between
-- them. backend/app.py._grade_cards computes it on the response, from
-- threat_gate.severity_of, and it is the only place it is computed.

-- ACCESS EXCLUSIVE on a table the enrich pass holds open across minutes of LLM calls is
-- how a 2m37s reader stall happened on 2026-09-02. Fail fast rather than queue.
SET lock_timeout = '5s';

BEGIN;

-- ---------------------------------------------------------------------------------
-- 1. Move the prose out of the level column, into the column that is FOR prose.
--
-- Nothing is deleted. threatNote is the measurement behind the rating and is where this
-- text belonged; the rating itself becomes NULL, which threat_gate reads as "not
-- assessed" -- distinguishable from 'low', which is a measurement nobody made.
UPDATE serving.competitors
   SET "threatNote" = coalesce(nullif("threatNote", ''), threat),
       threat       = NULL,
       updated_at   = now()
 WHERE threat IS NOT NULL
   AND btrim(lower(threat)) NOT IN ('high', 'medium', 'low');

-- ---------------------------------------------------------------------------------
-- 2. The vocabulary, in the database.
--
-- NOT VALID is not an option here: the rows above are the only offenders and they have
-- just been repaired, so the constraint is validated now rather than left as a promise.
-- Empty string is refused as well as prose -- '' is not a rating either, and it is what a
-- careless coalesce writes.
ALTER TABLE serving.competitors
  DROP CONSTRAINT IF EXISTS competitors_threat_is_a_level;
ALTER TABLE serving.competitors
  ADD CONSTRAINT competitors_threat_is_a_level
  CHECK (threat IS NULL OR threat IN ('high', 'medium', 'low'));

COMMENT ON COLUMN serving.competitors.threat IS
  'high, medium or low -- derived from countable inputs, not asserted by a model. '
  'NULL when nothing measurable places the company in a KSSL category, which is NOT '
  'the same as low. Constrained: the measurement goes in threatNote, never here.';

-- ---------------------------------------------------------------------------------
-- 3. Why a card is not a threat.
--
-- Written by serving_fill.py only where this column exists, so a deploy that lands
-- before this migration keeps working and merely logs its demotions instead of storing
-- them. Values are short machine tokens, not prose: 'not-a-served-competitor',
-- 'no-kssl-line', 'roster-unavailable'.
ALTER TABLE serving.signal_card ADD COLUMN IF NOT EXISTS dir_reason text;

COMMENT ON COLUMN serving.signal_card.dir_reason IS
  'Why this card is not a threat, when it was demoted from one. NULL on a card that '
  'was never claimed as a threat -- absence here is not evidence of a clean pass.';

-- The view is SELECT *, so it cannot see a new column until it is replaced, and
-- CREATE OR REPLACE VIEW only allows a column to be APPENDED -- naming it earlier reads
-- as renaming the column already in that position and is refused.
CREATE OR REPLACE VIEW serving_live.signal_card AS
  SELECT * FROM serving.signal_card WHERE origin = 'pipeline';

COMMIT;

-- ---------------------------------------------------------------------------------
-- AFTERWARDS, and NOT part of this transaction:
--
--   python extraction/signals/backfill_card_direction.py            # dry run, prints
--   python extraction/signals/backfill_card_direction.py --apply    # demotes
--
-- The 74 threat cards standing today were written by the old gate. The pipeline will not
-- revisit them: cards are keyed pl_<document_id> and a document that already produced a
-- card is excluded from the queue. That script re-runs the new gate over the stored rows.
