/* Fail the build if invented content is in the bundle.
 *
 *   npm run build && node check_no_fabrication.mjs
 *
 * Seven code paths in this app used to generate content no source produced and
 * attribute it to real publishers and real people. Removing them is not enough,
 * because the class is easy to reintroduce: a hand-typed roster reads like a
 * reasonable stopgap right up until it ships. This is a grep over the built
 * bundle, which is the only artefact that reflects what a viewer actually sees --
 * two of these strings were found by grepping the DEPLOYED bundle after I had
 * already convinced myself the source was clean.
 *
 * Rules for adding to this list: a marker must be a string that can ONLY come
 * from invented data. A publisher name is fine as a marker only because this app
 * never hard-codes a real publisher legitimately -- publishers arrive as data,
 * from serving.competitor_news.source.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const DIST = join(process.cwd(), "dist", "assets");

const BANNED = [
  // hand-typed people in real roles at real companies
  ["Shailesh Vagerwal", "hand-typed executive roster"],
  ["Sukaran Singh", "hand-typed executive roster"],
  ["Gautam Adani", "hand-typed executive roster"],
  // hand-typed plants and org trees
  ["Kanchanbagh", "hand-typed facility list"],
  ["Munitions India Limited (MIL)", "hand-typed corporate hierarchy"],
  // invented articles attributed to real publishers
  ["NDTV Profit", "publisher named in code, not in data"],
  ["Business Standard", "publisher named in code, not in data"],
  ["The Hindu BusinessLine", "publisher named in code, not in data"],
  ["Moneycontrol", "publisher named in code, not in data"],
  ["ET The Economic Times", "publisher named in code, not in data"],
  // invented issuing bodies dressed as citations
  ["Defense Intelligence Unit", "invented issuing body"],
  ["MoD Official Gazette", "invented issuing body"],
  ["Bilateral Trade & Export Credit Bureau", "invented issuing body"],
  ["Defence Procurement Directorate", "invented issuing body"],
  ["Ministry of Defence / Official", "invented issuing body"],
  ["mod.gov.in", "fallback link to a ministry that published nothing"],
  // invented figures
  ["480 Units", "invented contract quantity"],
  ["Published Financials", "invented revenue placeholder"],
  ["1,000 Cr+", "invented revenue placeholder"],
  ["547%", "invented financial result"],
  // stock photography standing in for an article's own image
  ["images.unsplash.com", "stock photo presented as an article image"],
  /* Found on 2026-09-03 by tracing the FINAL TESTS findings, still in the deployed
     bundle. Each was a literal in Products.jsx dressed as a measurement: nothing in
     this system counts mentions, none of it has a 24-hour window, and no product
     spec was ever "logged" for the 412 products that carry no spec data at all. */
  ["Mentions in last 24h", "invented engagement metric -- nothing counts mentions"],
  ["vs yesterday", "invented trend -- the pipeline has no 24-hour window"],
  ["Standard manufacturing specifications logged", "claims specs exist where none do"],
  /* These three pills filtered article.category, which only ever holds a PRODUCT
     category. They matched 0 of 492 articles, so each one emptied the feed. Banned
     because their reappearance means the fixed list came back. */
  ["Sales & Orders", "fixed news pill that matches no served article"],
  /* A share price, a daily move and a mention count were printed for EVERY company,
     including the unlisted ones and the state arsenals with no equity. There is no
     market-data feed in this system. */
  ["1,428.50", "invented share price shown for every company"],
  ["-2.88%", "invented daily price move"],
  ["Share Price", "no market-data feed exists -- a price can only be a literal here"],
  ["Set News Alerts", "button with no handler"],
  ["Set Product News Alerts", "button with no handler"],
  ["Technology & Upgrades", "fixed news pill that matches no served article"],
  ["Testing & Trials", "fixed news pill that matches no served article"],
];

const files = readdirSync(DIST).filter((f) => f.endsWith(".js") || f.endsWith(".css"));
if (!files.length) {
  console.error("no bundle in dist/assets — run the build first");
  process.exit(2);
}

const hits = [];
for (const f of files) {
  const src = readFileSync(join(DIST, f), "utf8");
  for (const [needle, why] of BANNED) {
    if (src.includes(needle)) hits.push({ f, needle, why });
  }
}

if (hits.length) {
  console.error(`FABRICATED CONTENT IN THE BUNDLE — ${hits.length} marker(s):`);
  for (const h of hits) console.error(`  ${h.f}: "${h.needle}"  (${h.why})`);
  console.error("\nThese must come from serving.* data, never from a literal in the app.");
  process.exit(1);
}
console.log(`no fabrication markers in ${files.length} bundle file(s) (${BANNED.length} checked)`);
