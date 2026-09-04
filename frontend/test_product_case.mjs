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
import { titleCaseHeadline } from "./src/lib/profile.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

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

// 2. the wiring reaches products through the real entry point, in BOTH shapes the
//    record uses: a bare string, and a {id,name,source} object.
// the other wiring stages each catch and log; give them their empty shapes so this
// test's output is only ever about products
const wired = wireDataset({
  overviewConfig: { competitive: {}, market: {}, technology: {} },
  techCats: [], innovations: {}, matchups: {}, tenders: [], details: {},
  competitorNews: {}, patents: {},
  competitors: {
    "acme-defence": { name: "Acme Defence", products: ["nag carrier", "air defense systems"] },
    "beta-arms": { name: "Beta Arms", products: [{ id: "ak-203", name: "AK-203 assault rifle", source: "u" }] },
    "no-products": { name: "No Products" },
  },
});

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
console.log("ok - product names cased once at the dataset funnel, both record shapes, no acronym eaten");
