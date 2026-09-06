-- Two more reasons a pairing is not a comparison, and NO new column.
--
-- 2026-09-06_matchup_withheld.sql added serving.matchup.withheld_reason for
-- not_like_for_like / nothing_published. extraction/signals/check_portfolio.py writes
-- two more into the same column, and nothing else changes: no new table, no new view,
-- no CHECK constraint (the column is deliberately free text so a new finding needs a
-- pass, not a migration), and serving_live.matchup already excludes every non-null
-- value. This file exists to keep the column's COMMENT honest, and to write down what
-- the two new reasons mean.
--
--   not_a_client_product  the name on the KSSL side of the pairing is in no row of
--                         serving.client_product -- the client's OWN product workbook.
--                         This is the fault that put "Adani SkyStriker vs KSSL Bayonet"
--                         on the Positioning tab. "Bayonet" and "Cleaver" were carried
--                         as KSSL products on the strength of 138 and 135 occurrences
--                         INSIDE extraction/reference_dataset.json -- a file this
--                         project wrote. Repetition in a curated file is one author
--                         138 times, not 138 witnesses. A corpus check later found
--                         Bayonet had 22 quotes and not one tied to KSSL, and every
--                         "Cleaver" hit was "Sian Cleaver, an Airbus engineer". The
--                         string "bayonet" occurs in the client's workbook exactly
--                         once, as a lug on the Protective Carbine.
--
--   offered_not_owned     the name belongs to another company and reaches KSSL through
--                         an MoU, a partnership or an offer. AAROK is a Turgis &
--                         Gaillard MALE design offered to KSSL under a 2025 MoU;
--                         serving.geo_presence already says so in as many words --
--                         "AAROK is a Turgis & Gaillard MALE design offered under a
--                         2025 MoU, not a KSSL product" -- while serving.innovation, in
--                         the same dataset, calls it "KSSL's airframe portfolio (AAROK
--                         MALE, Omega)". A file that contradicts itself is not a
--                         source; the disclaimer is the half that is a finding about
--                         ownership, and check_portfolio.py reads it out of the prose
--                         rather than carrying a hand-written ban list.
--
-- NO PRODUCT IS DELETED, HERE OR ANYWHERE. The operator's rule stands: "no need to
-- delete a client's product -- instead if no correct matchup is there, don't show it."
-- serving.client_product is not written by check_portfolio.py at all; rows that fail
-- its source or entailment rules are printed for a person and left whole.
--
-- REVERSIBLE, and scoped:
--     UPDATE serving.matchup SET withheld_reason = NULL
--      WHERE withheld_reason IN ('not_a_client_product','offered_not_owned');
--   -- or: python check_portfolio.py --restore
-- which is narrower than withhold_matchups.py --restore on purpose: one pass must not
-- silently republish what the other declined.

COMMENT ON COLUMN serving.matchup.withheld_reason IS
  'Non-null = this pairing is not a comparison and is not served. Value is the reason: '
  'not_like_for_like | nothing_published (extraction/signals/withhold_matchups.py), or '
  'not_a_client_product | offered_not_owned (extraction/signals/check_portfolio.py). '
  'The row is kept intact; clearing the column republishes it. No product is ever '
  'deleted to withhold a pairing.';
