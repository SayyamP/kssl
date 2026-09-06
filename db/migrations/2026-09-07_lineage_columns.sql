-- Additive lineage columns: let a served row point back at the document(s), run and
-- proposition(s) that produced it. Read by GET /api/lineage/doc/{id}; nothing else
-- selects them, so no served contract changes. All nullable -- reference/archive rows
-- and any row written before this stay NULL rather than getting fabricated ids.
--
-- WHY THESE COLUMNS ON THESE TABLES, AND NOT BLINDLY EVERYWHERE:
--   signal_card / signal_detail are written per-document by serving_fill.py, so the
--     document, its single extraction run, and the proposition indices fed to the card
--     are all unambiguous -- all three columns.
--   partner (the client's ties) is aggregated across the documents that corroborate a
--     pair, so only source_doc_ids is meaningful: a run is per-document and a bare
--     proposition index means nothing without its document, so those two are NOT added
--     here -- recording them would be a guess.
-- Other serving tables (competitors.partners jsonb, matchup, structure, news) are left
-- for a later step; this is the smallest change that closes the two gaps the POC found.

SET LOCAL lock_timeout = '30s';   -- fail fast rather than queue behind an enrich rebuild

ALTER TABLE serving.signal_card   ADD COLUMN IF NOT EXISTS source_doc_ids  text[];
ALTER TABLE serving.signal_card   ADD COLUMN IF NOT EXISTS source_run_id   text;
ALTER TABLE serving.signal_card   ADD COLUMN IF NOT EXISTS source_prop_ids integer[];
ALTER TABLE serving.signal_detail ADD COLUMN IF NOT EXISTS source_doc_ids  text[];
ALTER TABLE serving.signal_detail ADD COLUMN IF NOT EXISTS source_run_id   text;
ALTER TABLE serving.signal_detail ADD COLUMN IF NOT EXISTS source_prop_ids integer[];
ALTER TABLE serving.partner       ADD COLUMN IF NOT EXISTS source_doc_ids  text[];

-- serving_live.* are SELECT * views; an existing view binds its column list at creation,
-- so it will NOT show the new columns until recreated. A fresh database is fine (03 runs
-- after 02), but a live one needs these. Recreate the three affected views.
CREATE OR REPLACE VIEW serving_live.signal_card AS
  SELECT * FROM serving.signal_card WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.signal_detail AS
  SELECT * FROM serving.signal_detail WHERE origin = 'pipeline';
CREATE OR REPLACE VIEW serving_live.partner AS
  SELECT * FROM serving.partner WHERE origin = 'pipeline';
