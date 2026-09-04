/* Product names get ONE capitalisation, applied at the dataset funnel.
 *
 *     node test_product_case.mjs
 *
 * 63 of 124 stored product names are sentence case or lower -- "air defense systems",
 * "launched effects", "nag carrier" -- while others arrive title cased, so the
 * portfolio read as two lists stacked and the same product appeared as "nag carrier"
 * on one screen and "Nag Carrier" on the next.
 *
 * TWO things are asserted here, and the second is the one that actually broke.
 *
 * 1. The RULE never damages a name. titleCaseHeadline only ever raises a letter, so
 *    for any input the output must equal the input once both are upper-cased. That
 *    single invariant catches every way the rule could eat an acronym -- AK-203, K10,
 *    YFQ-44A, MPV-I, 155mm -- without enumerating them.
 *
 * 2. The WIRING reaches them. `d.competitors` is a MAP keyed by comp_id, not an array;
 *    the first version of this used .map() on it, which throws, and the wiring catches
 *    its own exceptions and logs a warning -- so the page would have rendered
 *    perfectly, with every product name still uncased and nothing on screen to say so.
 *    A test of the rule alone would have passed while the feature did nothing.
 */
import { wireDataset } from "./src/lib/dataset.js";
import { titleCaseHeadline, formatProductName } from "./src/lib/profile.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };
const eq = (got, want, what) => {
  if (got !== want) fail(`${what}\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`);
};

const NAMES = ["helicopters", "air defense systems", "launched effects", "nag carrier",
  "tracked combat ground vehicles", "AK-203 assault rifle", "K10 ammunition resupply vehicle",
  "BrahMos supersonic cruise missile", "YFQ-44A air vehicle team", "MPV-I (mine protected)",
  "155mm/52 cal artillery", "uncrewed ground vehicles (UGVs)", "Altius-600M loitering munitions"];

// 1. the rule raises only
for (const n of NAMES) {
  const out = titleCaseHeadline(n);
  if (out.toUpperCase() !== n.toUpperCase())
    fail(`the rule damaged ${JSON.stringify(n)} -> ${JSON.stringify(out)}`);
  if (/(^| )[a-z]/.test(out))
    fail(`still lower-cased after the rule: ${JSON.stringify(out)}`);
}

/* 1b. THE PRODUCT RULE -- the raise above, plus a listed acronym lifted to full upper
 *     case (T 20), plus stray separators collapsed (FE 31). Each string here is one the
 *     acceptance sheet named, or the stored form behind it:
 *       FE 32  Eviden's "P3TS military satellite navigation receiver" printed "P3ts"
 *       FE 33  "nag carrier" on the product line, "NAMICA (Nag carrier)" on the matchup
 *       FE 34  ARI's "(ASTT)" and "(DSRV)" printed "(Astt)" and "(Dsrv)"
 *       FE 31  L&T's product content carried a double comma
 *     Products.jsx ran formatLabel over product names, which lower-cases every word
 *     outside its list -- so the page and the funnel disagreed on the same product. */
const PRODUCT_CASES = [
  ["nag carrier", "Nag Carrier", "FE 33: the product line"],
  ["NAMICA (Nag carrier)", "NAMICA (Nag Carrier)", "FE 33: the matchup spelling, NAMICA untouched"],
  ["uav swarms", "UAV Swarms", "T 20: a lower-cased acronym is raised whole"],
  ["Action Speed Tactical Trainer (ASTT)", "Action Speed Tactical Trainer (ASTT)", "FE 34: ASTT stays upper"],
  ["Deep Submergence Rescue Vehicle (DSRV) simulator",
   "Deep Submergence Rescue Vehicle (DSRV) Simulator", "FE 34: DSRV stays upper"],
  ["P3TS military satellite navigation receiver",
   "P3TS Military Satellite Navigation Receiver", "FE 32: Eviden's product"],
  ["Offshore Patrol Vessel (OPV),, Interceptor Boats",
   "Offshore Patrol Vessel (OPV), Interceptor Boats", "FE 31: L&T, a double comma collapses"],
  ["K9 Vajra-T self-propelled howitzers,", "K9 Vajra-T Self-Propelled Howitzers", "FE 31: a trailing comma is dropped"],
  ["Naval Decoy Control &amp; Launching System (DCLS)",
   "Naval Decoy Control & Launching System (DCLS)", "an entity is decoded: the name is printed as text, not injected"],
  ["mk1 turret", "MK1 Turret", "a designation on the shared list is raised like the label rule does"],
  ["Nag Carrier", "Nag Carrier", "idempotent"],
];
for (const [input, want, what] of PRODUCT_CASES) eq(formatProductName(input), want, what);
eq(formatProductName(""), "", "empty in, empty out");
eq(formatProductName(null), "", "null in, empty out");

// 2. the wiring reaches products through the real entry point, in BOTH shapes the
//    record uses: a bare string, and a {id,name,source} object.
// the other wiring stages each catch and log; give them their empty shapes so this
// test's output is only ever about products
const wired = wireDataset({
  overviewConfig: { competitive: {}, market: {}, technology: {} },
  techCats: [], innovations: {}, tenders: [], details: {},
  competitorNews: {}, patents: {},
  competitors: {
    "acme-defence": { name: "Acme Defence", products: ["nag carrier", "air defense systems"] },
    "beta-arms": { name: "Beta Arms", products: [{ id: "ak-203", name: "AK-203 assault rifle", source: "u" }] },
    "no-products": { name: "No Products" },
  },
  /* the same product, as the matchup table spells it: "Company · Product". The
     product segment takes the product rule; the company segment (and compBy, which
     the joins key on) is left exactly as stored. */
  matchups: {
    "238": { comp: "Armoured Vehicles Nigam Limited · NAMICA (Nag carrier)",
             compBy: "Armoured Vehicles Nigam Limited", bf: "KSSL · maverick", anchor: "maverick",
             cat: "Armoured Vehicles", specs: [] },
    "239": { comp: "Acme Defence · nag carrier", compBy: "Acme Defence", bf: "", anchor: "", specs: [] },
  },
});

// 2b. FE 33: the SAME entity renders identically on the product line, in the matchup
//     list and on the product page -- which derives its name from the matchup the way
//     Products.jsx does.
const mu = (wired.matchups || {})["238"] || {};
eq(mu.comp, "Armoured Vehicles Nigam Limited · NAMICA (Nag Carrier)", "FE 33: matchup product segment cased at the funnel");
eq(mu.compBy, "Armoured Vehicles Nigam Limited", "the company key is not touched");
eq(mu.bf, "KSSL · Maverick", "the client-side product segment is cased too");
eq(mu.anchor, "Maverick", "the anchor label matches bf");
const mu2 = (wired.matchups || {})["239"] || {};
const pageName = formatProductName(String(mu2.comp || "").replace(/.*·\s*/, "").trim());
const lineName = (((wired.competitors || {})["acme-defence"] || {}).products || [])[0];
eq(pageName, lineName, "FE 33: product page name and product line name are the same string");

const acme = (wired.competitors || {})["acme-defence"] || {};
if (!Array.isArray(acme.products)) fail("wiring dropped the products array entirely");
else {
  if (acme.products[0] !== "Nag Carrier")
    fail(`string product not cased: ${JSON.stringify(acme.products[0])}`);
  if (acme.products[1] !== "Air Defense Systems")
    fail(`string product not cased: ${JSON.stringify(acme.products[1])}`);
}

const beta = ((wired.competitors || {})["beta-arms"] || {}).products || [];
if (!beta[0] || typeof beta[0] !== "object") fail("object product lost its shape");
else {
  if (beta[0].name !== "AK-203 Assault Rifle")
    fail(`object product not cased: ${JSON.stringify(beta[0].name)}`);
  if (beta[0].id !== "ak-203" || beta[0].source !== "u")
    fail("casing a product must not drop its other fields (id/source carry the link)");
}

// a competitor with no products must survive untouched, not become undefined
if (!((wired.competitors || {})["no-products"] || {}).name)
  fail("a competitor with no products was dropped by the product casing");

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - product names cased once at the dataset funnel, both record shapes and the matchup table, no acronym eaten, listed acronyms upper");
