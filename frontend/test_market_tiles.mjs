/* The Market overview's metric strip must be counted from the wired data, and every
 * tile that reads as a door must open the rows it counts.
 *
 *     node test_market_tiles.mjs
 *
 * FOUND 2026-09-05 (interaction sweep, live dataset): the strip read
 * "Open opportunities 7 · Already concluded 15 · Markets tracked 14 · All signals 6"
 * above a feed of 323 signals promoted from 89 open tenders. Those are the numbers
 * baked into the served config for the Sep-2 sample. metricsFor computes the real
 * ones -- but wireDataset stamps `sec: t.cat` (a STRING) on every promoted tender
 * card, every other card carries `sec` as an array of lens sections, the lens loop
 * called .forEach on the string, threw, and the catch left the baked values on
 * screen. A number on the dashboard the data did not hold -- the exact thing the
 * strip exists to prevent -- and invisible on the sample dump, where the baked
 * values happened to be right.
 *
 * The doors were wrong independently: "Open opportunities" (act fav) opened
 * fav+watch = every demand card plus the unpriced tenders, "Already concluded" (act
 * deadline) opened everything, "Markets tracked" (act all) reset a filter that was
 * already clear. What this pins:
 *
 *   1. a promoted tender card's `sec` is an array, like every other card's;
 *   2. metricsFor(market) counts All signals / Open opportunities / Already concluded /
 *      Markets tracked from the wired data, never from the served `v`;
 *   3. a non-array `sec` on any card cannot take the whole strip down;
 *   4. the "Open opportunities" tile's door (act "open") selects exactly the promoted
 *      open tenders, and the two tiles that have no feed behind them carry acts
 *      Layout routes to the Market Report rather than a feed predicate.
 */
import assert from "node:assert/strict";
import { wireDataset } from "./src/lib/dataset.js";
import { metricsFor, tilePredicate } from "./src/lib/overview.js";

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
    market: {
      cnt: "6 demand signals · sorted by urgency",
      /* the baked sample numbers -- none of them true for this fixture */
      metrics: [
        { l: "Live bid value", v: "73,895", act: "atstake" },
        { l: "Open opportunities", v: "7", act: "fav" },
        { l: "Already concluded", v: "15", act: "deadline" },
        { l: "Markets tracked", v: "14", act: "all" },
        { l: "All signals", v: "6", act: "all" },
      ],
    },
  },
  techCats: [], innovations: {}, matchups: {}, details: {}, competitorNews: {},
  patents: {}, competitors: {},
  marketCards: [
    { id: "d1", dir: "watch", title: "Kyiv faces sustained attacks", lens: "Market", sec: [{ lens: "Market" }] },
    { id: "d2", dir: "watch", title: "Japan MoD allocates funds", lens: "Market", sec: [] },
  ],
  tenders: [
    tender("t-open-1"),
    tender("t-open-2", { country: "France" }),
    tender("t-open-val", { value: "₹1,200 cr", country: "Egypt" }),
    tender("t-awarded", { status: "awarded" }),
    tender("t-closed", { status: "open", deadline: "Closed 01 Jan 2020" }),
  ],
};

const d = wireDataset(raw);
const cfg = d.overviewConfig.market;
const promoted = cfg.cards.filter((c) => c.id.startsWith("tender_"));
if (promoted.length !== 3) fail(`expected 3 promoted open tenders, got ${promoted.length}`);

// 1. shape
promoted.forEach((c) => {
  if (!Array.isArray(c.sec)) fail(`promoted card ${c.id} carries sec as ${typeof c.sec}, not an array`);
});

// 2. counted, not baked
const m = metricsFor(cfg, "market", d);
const v = (l) => (m.find((x) => x.l === l) || {}).v;
const act = (l) => (m.find((x) => x.l === l) || {}).act;
if (v("All signals") !== String(cfg.cards.length)) fail(`All signals reads ${v("All signals")}, feed holds ${cfg.cards.length}`);
if (v("Open opportunities") !== "3") fail(`Open opportunities reads ${v("Open opportunities")}, 3 are open`);
if (v("Already concluded") !== "2") fail(`Already concluded reads ${v("Already concluded")}, 2 are concluded`);
if (v("Markets tracked") !== "3") fail(`Markets tracked reads ${v("Markets tracked")}, 3 countries on file`);
if (v("Live bid value") !== "1,200") fail(`Live bid value reads ${v("Live bid value")}, one open tender publishes 1,200 cr`);

// 3. a hostile shape on one card degrades that card, not the strip
const hostile = { ...cfg, cards: cfg.cards.concat([{ id: "x", dir: "watch", sec: "Artillery" }]) };
const m2 = metricsFor(hostile, "market", d);
if ((m2.find((x) => x.l === "All signals") || {}).v !== String(hostile.cards.length))
  fail("a string `sec` on one card still takes the whole strip back to the baked values");

// 4. doors
if (act("Open opportunities") !== "open") fail(`Open opportunities tile act is ${act("Open opportunities")}, expected "open"`);
if (act("Already concluded") !== "concluded") fail(`Already concluded tile act is ${act("Already concluded")}, expected "concluded" (routed to the report)`);
if (act("Markets tracked") !== "markets") fail(`Markets tracked tile act is ${act("Markets tracked")}, expected "markets" (routed to the report)`);
const opened = cfg.cards.filter(tilePredicate("open"));
const openedIds = opened.map((c) => c.id).sort().join(",");
const promotedIds = promoted.map((c) => c.id).sort().join(",");
if (openedIds !== promotedIds) fail(`the Open opportunities door opens [${openedIds}], the tile counts [${promotedIds}]`);
if (opened.length !== Number(v("Open opportunities"))) fail(`door opens ${opened.length}, tile says ${v("Open opportunities")}`);

if (bad) { console.log(`test_market_tiles: ${bad} failure(s)`); process.exit(1); }
console.log("test_market_tiles: ok -- market tiles are counted from the wired data and their doors open what they count");
