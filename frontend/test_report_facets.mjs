/* The Market Report's two filters must count the rows they are about to show.
 *
 *     node test_report_facets.mjs
 *
 * FOUND 2026-09-05 (interaction sweep, live dataset): the Category select read
 * "Ammunition (48)" on every tab; picking it listed 35 rows on Active, 11 on Awarded,
 * 2 on Closed. The options were ranked over all 136 tenders while the table showed
 * one lifecycle bucket -- the same fault the Country select had already been fixed
 * for ("All (22)" over an awarded list of 8 countries), left in place on the control
 * beside it. And the note under the active table said "no tender on record publishes
 * a value" as a hard-coded string, on a corpus where 14 do.
 *
 * What this pins, on the pure helper the page now reads:
 *   1. each facet's options are counted over the section's rows with the OTHER facet
 *      applied, so picking an option lists exactly the number it advertised;
 *   2. an option with no row behind it in this section does not exist;
 *   3. the value note is computed: it names how many of the rows publish an amount,
 *      and says "none" only when none do.
 */
import { reportFacets, reportRows, valueNote } from "./src/lib/marketOverview.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

const t = (id, country, cat, over) => ({ id, title: id, country, cat, status: "open", dl: 30, value: null, url: "", ...over });
const open = [
  t("a1", "India", "Ammunition"), t("a2", "India", "Ammunition"), t("a3", "France", "Ammunition"),
  t("u1", "India", "UAVs & Drones"), t("s1", "Egypt", "Small Arms", { value: "₹90 cr" }),
];
const awarded = [t("w1", "Belgium", "Ammunition", { status: "awarded" }), t("w2", "Belgium", "Artillery", { status: "awarded" })];

// 1 + 2: every option is a promise of rows in THIS scope
const checkScope = (scope, label) => {
  const all = reportFacets(scope, { country: "all", cat: null });
  all.countries.forEach((o) => {
    const n = reportRows(scope, { country: o.v, cat: null }).length;
    if (n !== o.n) fail(`${label}: country option ${o.v} (${o.n}) lists ${n}`);
    if (o.n === 0) fail(`${label}: zero-row country option ${o.v}`);
  });
  all.cats.forEach((o) => {
    const n = reportRows(scope, { country: "all", cat: o.v }).length;
    if (n !== o.n) fail(`${label}: category option ${o.v} (${o.n}) lists ${n}`);
    if (o.n === 0) fail(`${label}: zero-row category option ${o.v}`);
  });
  // cross-filtered: with a country picked, the category counts follow it
  const inIndia = reportFacets(scope, { country: "India", cat: null });
  inIndia.cats.forEach((o) => {
    const n = reportRows(scope, { country: "India", cat: o.v }).length;
    if (n !== o.n) fail(`${label}: with India picked, category ${o.v} (${o.n}) lists ${n}`);
  });
  const withCat = reportFacets(scope, { country: "all", cat: "Ammunition" });
  withCat.countries.forEach((o) => {
    const n = reportRows(scope, { country: o.v, cat: "Ammunition" }).length;
    if (n !== o.n) fail(`${label}: with Ammunition picked, country ${o.v} (${o.n}) lists ${n}`);
  });
};
checkScope(open, "open");
checkScope(awarded, "awarded");

// an option must not leak in from another section
const aw = reportFacets(awarded, { country: "all", cat: null });
if (aw.cats.some((o) => o.v === "UAVs & Drones")) fail("awarded: UAVs & Drones has no awarded row and must not be offered");
if (aw.cats.find((o) => o.v === "Ammunition")?.n !== 1) fail("awarded: Ammunition should count the ONE awarded row, not every tender");
if (aw.countries.some((o) => o.v === "India")) fail("awarded: India has no awarded row and must not be offered");

// 3: the value note is measured
if (!/1 of 5/.test(valueNote(open))) fail(`valueNote(open) = ${JSON.stringify(valueNote(open))}, expected to say 1 of 5 publish a value`);
if (!/no .*publishes/.test(valueNote(awarded))) fail(`valueNote(awarded) = ${JSON.stringify(valueNote(awarded))}, expected to say none do`);
if (/no .*publishes/.test(valueNote(open))) fail("valueNote(open) claims none publish a value while one does");

if (bad) { console.log(`test_report_facets: ${bad} failure(s)`); process.exit(1); }
console.log("test_report_facets: ok -- every report filter option lists exactly what it advertised, and the value note is measured");
