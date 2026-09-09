-- Additive lineage column for serving.matchup: the document(s) whose corpus
-- propositions produced a matchup's specs. The 2026-09-07 lineage migration explicitly
-- left matchup "for a later step"; this is that step, and the smallest one.
--
-- WHY ONLY source_doc_ids (and not run/prop ids, like signal_card):
--   A pipeline matchup is built by enrich_serving.step_matchups from EVERY product-
--   matching proposition across potentially several documents (the same set that builds
--   its spec text and sourced evidence). It is multi-document and multi-run, so only the
--   contributing document set is unambiguous -- a single run id or a bare proposition
--   index would be a guess. Recording just source_doc_ids is the honest maximum.
--
-- WHAT STAYS UNAVAILABLE (not fabricated):
--   revive_matchups.py rows (matchup_id >= 20000) are archival revivals with no per-row
--   contributing propositions; they keep source_doc_ids NULL. Hence the feature is
--   RECORDED_PARTIAL, never RECORDED. Reference rows (origin='reference') stay NULL too.
--
-- Nullable, so every existing row stays NULL rather than getting invented ids; it
-- populates on the next enrich pass once step_matchups runs under this column.
--
-- serving_live.matchup is NOT recreated on purpose: no served contract reads this column
-- through the view. /api/lineage/doc/{id}, /api/dataset matchups and the Database
-- Explorer grounding all read the base serving.matchup. The withheld view keeps its
-- explicit column list (and its withheld_reason predicate) untouched.

SET LOCAL lock_timeout = '30s';   -- fail fast rather than queue behind an enrich rebuild

ALTER TABLE serving.matchup ADD COLUMN IF NOT EXISTS source_doc_ids text[];
