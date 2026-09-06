-- A pairing that is not a comparison stops being shown, and the row stays whole.
--
-- The operator's rule: "no need to delete a client's product -- instead if no correct
-- matchup is there, don't show it." So this withholds the PAIRING and touches no
-- product, no catalogue and no competitor.
--
-- WHY A COLUMN AND NOT origin. The obvious move is to set origin to something the
-- serving view does not select. serving.matchup refuses it, and is right to:
--     matchup_origin_check CHECK (origin = ANY (ARRAY['reference','pipeline']))
-- origin says WHERE a row came from. "We decline to publish this" is a different fact
-- about the same row, and giving one column two meanings is how the next reader learns
-- that a 'withheld' row was harvested by something called withheld. A separate,
-- nullable column says the second thing and carries the reason with it.
--
-- WHAT GETS WITHHELD -- both are findings, never guesses:
--   not_like_for_like  positioning_gate refuses the pairing with a stated reason. KSSL
--                      sells EMPTY shell bodies (export catalogue p37, "Only empties")
--                      and Excalibur is a complete guided round; a 3 kg carbine is not
--                      a tripod-mounted machine gun; a remote weapon station is a
--                      mount, not a rifle. The gate's `unresolved` verdict is NOT
--                      withheld -- that means a keyword table has not heard of
--                      "MaxxPro", which is a gap in a word list, not a fact about the
--                      products.
--   nothing_published  every value on the KSSL side is placeholder prose ("no published
--                      figure", "specifications undisclosed"). There is no number to
--                      put beside the rival's, so the row is a rival's spec sheet
--                      wearing a comparison's chrome. This is what made "Bayonet vs
--                      SkyStriker" read as nonsense to the operator: the client column
--                      was empty in every field.
--
-- REVERSIBLE, and the reason travels with the row:
--     UPDATE serving.matchup SET withheld_reason = NULL;   -- or withhold_matchups.py --restore

ALTER TABLE serving.matchup ADD COLUMN IF NOT EXISTS withheld_reason text;

COMMENT ON COLUMN serving.matchup.withheld_reason IS
  'Non-null = this pairing is not a comparison and is not served. Value is the reason '
  '(not_like_for_like | nothing_published). The row is kept intact; clearing the column '
  'republishes it. Written by extraction/signals/withhold_matchups.py.';

-- The view enumerates its columns (the star was expanded once, at creation), so the
-- column list below is reproduced EXACTLY as it stands -- same names, same order, same
-- types. The only change is the added predicate. withheld_reason is deliberately NOT
-- exposed: the dashboard's contract is "these are the pairings", not "here is what we
-- declined to show".
CREATE OR REPLACE VIEW serving_live.matchup AS
SELECT matchup_id,
       cat,
       anchor,
       "global",
       dir,
       country,
       comp,
       "compBy",
       bf,
       "bfBy",
       ks_thin,
       reason,
       edge,
       specs,
       "advComp",
       "advBf",
       det,
       "verdictH",
       verdict,
       "catKey",
       srcs,
       gen,
       origin,
       updated_at,
       revenue_filter,
       news_image,
       product_news
  FROM serving.matchup
 WHERE origin = 'pipeline'::text
   AND withheld_reason IS NULL;
