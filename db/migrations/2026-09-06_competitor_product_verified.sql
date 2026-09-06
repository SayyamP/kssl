-- competitor_product: the two columns a VERIFIED import needs and the table has never
-- had. Written for extraction/signals/competitor_specs.py. NOT YET RUN.
--
-- WHAT WAS ALREADY THERE AND IS ENOUGH
-- ------------------------------------
-- The provenance the operator asked to keep per specification -- the source URLs, the
-- source count and the evidence tier -- needs NO new column. `sources` already holds
-- the URLs, `evidence` is jsonb and already holds {why, tier, independent}, and
-- competitor_specs.py widens it to also carry source_count, the workbook's own
-- Source Health and Evidence tier, the granularity level (with the workbook's own
-- "this is a heuristic" caveat beside it), the positioning kind, and `absent` -- the
-- clauses the cell used to DECLINE a figure, kept as an absence and never as a value.
-- Each entry of `specs` additionally carries srcs / src_n / tier, because a spec that
-- travels into a matchup row is separated from the product that sourced it.
--
-- Adding jsonb keys needs no migration, and inventing columns for them would have
-- been the wrong instinct: this file adds only what a KEY cannot express.
--
-- 1. comp_id -- WHICH COMPETITOR, BY ID, NOT BY LABEL
-- ---------------------------------------------------
-- `company` is the workbook's display spelling: "Hanwha (Aerospace/Group)", "Larsen &
-- Toubro (L&T)", "RTX (Raytheon)". Nothing joins on it because nothing can. This repo
-- has already lost a whole layer to a display label used as a join key -- the client
-- was "KSSL" in config and a slug everywhere else, which listed the client as its own
-- competitor -- and the fix each time is to store the resolved id at write time
-- instead of re-deriving it at read time.
--
-- It is DELIBERATELY NOT a foreign key to serving.competitors. The FK would cascade,
-- and a roster row being deleted or re-keyed must not silently take a verified
-- product catalogue with it; the importer's own rules already refuse to write a
-- comp_id that is not in serving_live.competitors at the moment it runs.
--
-- 2. withheld_reason -- DECLINING TO PUBLISH A ROW IS NOT DELETING IT
-- -------------------------------------------------------------------
-- competitor_portfolio.py writes this table with DELETE-then-INSERT, so a row that
-- stops clearing the gate simply vanishes and nothing records that it ever did, or
-- why. serving.matchup solved the identical problem on 2026-09-06 with exactly this
-- column (db/migrations/2026-09-06_matchup_withheld.sql), and the argument is the same
-- one: the reason travels with the row, one UPDATE restores it, and a refusal rule
-- that turns out to be wrong costs a --restore instead of a re-import.
--
-- NOT `origin`. That column is CHECK-constrained to 'reference'/'pipeline' and means
-- WHERE a row came from. "We decline to publish this" is a different fact about the
-- same row.
--
-- 3. the ON CONFLICT target
-- -------------------------
-- product_id is already the PRIMARY KEY, so the importer's UPSERT needs no new index.
-- Named here only so a reader does not go looking for one.
--
-- BEFORE RUNNING: stop extraction-enrich-1, as for every serving.* change. The enrich
-- pass holds locks across minutes of LLM calls (measured 2m37s wait on 2026-09-02),
-- and serving.competitors' FK cascades make an ALTER in this schema worse than a wait.

SET lock_timeout = '5s';

ALTER TABLE serving.competitor_product
    ADD COLUMN IF NOT EXISTS comp_id         text,
    ADD COLUMN IF NOT EXISTS withheld_reason text;

-- The Positioning screen reads a competitor's products by id, so this is the index
-- the reader that does not yet exist will want; competitor_product_company_idx keys
-- the display label and cannot serve it.
CREATE INDEX IF NOT EXISTS competitor_product_comp_idx
    ON serving.competitor_product (comp_id);

COMMENT ON COLUMN serving.competitor_product.comp_id IS
    'serving.competitors.comp_id resolved at import time. Not an FK on purpose: a '
    'roster change must not cascade into a verified product catalogue.';
COMMENT ON COLUMN serving.competitor_product.withheld_reason IS
    'Non-null means the row is kept but not published. Set by competitor_specs.py '
    'when a row stops clearing the verification rules; cleared by --restore.';
