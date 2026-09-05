/* The Products sidebar's revenue facet, built from the roster like its two
   neighbours (lib/countryFacet.js).

   It used to be three fixed options -- High / Mid / Emerging -- over a roster on
   which serving.competitors.revenue_filter is null for every row (measured
   2026-09-05: 0 of 42 live, 0 of 28 sample). Each option emptied the list. The
   options now come from the rows, each with its count; with no tier on file there
   are none, and the page draws no control rather than a dead one. */
import { facetOptions } from "./countryFacet.js";

/* The house wording for the tiers the pipeline is specified to write. A value
   outside this set is still offered, under its own name: the facet reports the
   data, it does not censor it. */
export const REVENUE_LABEL = {
  high: "High (> ₹5,000 Cr / $1B+)",
  mid: "Mid (₹1,000 - ₹5,000 Cr)",
  emerging: "Emerging (< ₹1,000 Cr)",
};

const ORDER = Object.keys(REVENUE_LABEL);

/* rows -> [{ v, n, l }] : every tier the rows carry, in house order, then by name. */
export function revenueOptions(rows) {
  return facetOptions(rows, (r) => (r && r.revenueTier) || null, ORDER)
    .map((o) => ({ ...o, l: REVENUE_LABEL[o.v] || o.v }))
    .sort((a, b) => {
      const ia = ORDER.indexOf(a.v), ib = ORDER.indexOf(b.v);
      return (ia < 0 ? ORDER.length : ia) - (ib < 0 ? ORDER.length : ib) || a.v.localeCompare(b.v);
    });
}
