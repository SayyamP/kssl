/* The Market pills must have members, and must count what the tiles count.
 *
 *     node test_market_facets.mjs
 *
 * REPORTED: "filter of market tab opportunity is 0 and live bid also 0".
 *
 * They filtered the 231 demand-signal cards, every one of which carries dir='watch' --
 * the promoter never assigns another value on this lane. The bid state they wanted
 * exists, but on the TENDERS, and not one demand card joins to a tender (measured: 0 of
 * 231 share a url). So the tiles counted tenders while the pills counted cards: two
 * populations under one heading, and the pills read 0 for months.
 *
 * wireDataset now promotes OPEN tenders into the feed. What this pins:
 *
 *   1. the facets are non-empty -- the actual complaint;
 *   2. the split is a PARTITION. Overview filters on `card.dir === f.f`, so a card sits
 *      in exactly one facet; overlapping facets would silently drop rows. fav + threat
 *      must equal the open tenders, no double counting, none missed;
 *   3. CONCLUDED tenders are not promoted. Awarded and closed have their own two views,
 *      and adding them here would inflate "Emerging Demand" with unbiddable contracts;
 *   4. every promoted card has a DETAIL. The drawer reads data.details[id]; a card
 *      without one opens an empty panel, which is how this would look "done" and not be;
 *   5. the demand cards are untouched -- still 'watch', still there.
 */
import { wireDataset } from "./src/lib/dataset.js";
import { marketSelfCheck } from "./src/lib/marketOverview.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

const tender = (id, over) => ({
  id, title: `tender ${id}`, issuer: "Some Ministry", country: "India",
  cat: "Artillery", value: null, qty: null, deadline: "22 Jun 2027",
  status: "open", url: `https://example.test/${id}`, srcs: [], req: [], matches: [],
  ...over,
});

const raw = {
  overviewConfig: {
    competitive: {}, technology: {},
    market: { cnt: "6 demand signals · sorted by urgency" },
  },
  techCats: [], innovations: {}, matchups: {}, details: {}, competitorNews: {},
  patents: {}, competitors: {},
  marketCards: [
    { id: "d1", dir: "watch", title: "Kyiv faces sustained attacks", lens: "Market" },
    { id: "d2", dir: "watch", title: "Japan MoD allocates funds", lens: "Market" },
  ],
  tenders: [
    tender("t-open-noval"),
    tender("t-open-noval2"),
    tender("t-open-val", { value: "₹1,200 cr" }),
    tender("t-awarded", { status: "awarded" }),
    tender("t-closed", { status: "open", deadline: "Closed 01 Jan 2020" }),
  ],
};

const d = wireDataset(raw);
const cards = d.marketCards || [];
const by = (dir) => cards.filter((c) => c.dir === dir);

// 1. the facets have members -- the complaint
if (by("fav").length === 0) fail("Opportunities is still empty");
if (by("threat").length === 0) fail("Live Bids is still empty");

// 2. partition: exactly the open tenders, split on a published value
if (by("fav").length !== 2)
  fail(`Opportunities should be the 2 open tenders with no value, got ${by("fav").length}`);
if (by("threat").length !== 1)
  fail(`Live Bids should be the 1 open tender with a value, got ${by("threat").length}`);
const ids = cards.map((c) => c.id);
if (new Set(ids).size !== ids.length) fail("a tender was promoted twice");

// 3. concluded tenders are NOT promoted
for (const gone of ["tender_t-awarded", "tender_t-closed"]) {
  if (ids.includes(gone)) fail(`${gone} was promoted -- concluded tenders must not be`);
}

// 4. every promoted card has a detail, with the tender's real fields
for (const c of cards.filter((x) => x.id.startsWith("tender_"))) {
  const det = (d.details || {})[c.id];
  if (!det) { fail(`${c.id} has no detail -- its drawer would open empty`); continue; }
  if (det.dir !== c.dir) fail(`${c.id} detail dir disagrees with the card`);
  if (!det.url) fail(`${c.id} detail has no source url`);
  if (!det.facts.some((f) => f[0] === "Issuer")) fail(`${c.id} detail lost its issuer`);
  // no fabricated value on a tender that publishes none
  const v = det.facts.find((f) => f[0] === "Value");
  if (c.dir === "fav" && v) fail(`${c.id} shows a Value but the tender publishes none`);
  if (c.dir === "threat" && !v) fail(`${c.id} is a Live Bid with no Value fact`);
}

// 5. the demand cards survive, untouched
if (by("watch").length !== 2) fail(`the 2 demand cards should be intact, got ${by("watch").length}`);

// the pillar must serve the NEW array -- it held the old one by reference
const served = ((d.overviewConfig || {}).market || {}).cards || [];
if (served.length !== cards.length)
  fail(`overviewConfig.market still serves ${served.length} of ${cards.length} cards`);
if (/demand signals/.test(((d.overviewConfig || {}).market || {}).cnt || ""))
  fail("the subhead still calls promoted tenders 'demand signals'");

// and the invariant that keeps the pills and the tiles honest
try {
  marketSelfCheck(d.tenders, d.marketCards);
} catch (e) {
  fail("marketSelfCheck rejected a correct dataset: " + e.message);
}
// ...which must actually fire when they disagree
try {
  marketSelfCheck(d.tenders, cards.filter((c) => c.dir !== "threat"));
  fail("marketSelfCheck passed when a Live Bid card went missing");
} catch (e) { /* expected */ }

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - market facets: open tenders promoted, partition holds, "
  + "concluded excluded, every card has a detail");
