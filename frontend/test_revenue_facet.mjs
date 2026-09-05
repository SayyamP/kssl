/* The Products sidebar's Revenue filter must be built from what the roster carries.
 *
 *     node test_revenue_facet.mjs
 *
 * FOUND 2026-09-05 (interaction sweep, both datasets): the Revenue select offered
 * High / Mid / Emerging as three fixed options, and every one of them emptied the
 * company list -- serving.competitors.revenue_filter is null on all 42 live rows and
 * all 28 sample rows. Three options, zero companies behind any of them, on a page
 * whose two neighbouring filters were already built from the rows. A filter that can
 * only ever remove everything is not a filter.
 *
 * What this pins, on the pure helper the page now reads:
 *   1. with no company carrying a tier there are NO options (the page then omits the
 *      control rather than drawing a dead one);
 *   2. with tiers on file, each option counts the companies that carry it and wears
 *      the house label;
 *   3. an unknown tier value is still offered under its own name -- the filter reports
 *      the data, it does not censor it.
 */
import { revenueOptions, REVENUE_LABEL } from "./src/lib/revenueFacet.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

if (revenueOptions([{ revenueTier: null }, { revenueTier: null }, {}]).length !== 0) fail("no tiers on file must yield no options");
if (revenueOptions([]).length !== 0) fail("an empty roster must yield no options");

const opts = revenueOptions([
  { revenueTier: "high" }, { revenueTier: "high" }, { revenueTier: "mid" }, { revenueTier: null }, { revenueTier: "bespoke" },
]);
const by = Object.fromEntries(opts.map((o) => [o.v, o]));
if (!by.high || by.high.n !== 2) fail(`high should count 2, got ${JSON.stringify(by.high)}`);
if (!by.mid || by.mid.n !== 1) fail(`mid should count 1, got ${JSON.stringify(by.mid)}`);
if (by.high && by.high.l !== REVENUE_LABEL.high) fail(`high should wear the house label, got ${by.high.l}`);
if (!by.bespoke || by.bespoke.l !== "bespoke") fail("an unknown tier is offered under its own name");
if (opts.some((o) => o.n === 0)) fail("no option may have zero rows behind it");
if (opts.length !== 3) fail(`expected 3 options, got ${opts.length}`);

if (bad) { console.log(`test_revenue_facet: ${bad} failure(s)`); process.exit(1); }
console.log("test_revenue_facet: ok -- the revenue filter offers only tiers the roster carries");
