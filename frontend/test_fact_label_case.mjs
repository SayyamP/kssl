/* A fact LABEL wears the house capitalisation; a fact VALUE never does.
 *
 *     node test_fact_label_case.mjs
 *
 * Finding 15: "PascalCase convention is not consistently applied where required."
 * The visible instance was the signal drawer, which reads
 *
 *     Company        Leonardo
 *     Category       Protected & Armoured Vehicles
 *     Date           1 Sep 2026
 *     Primary lens   Competitive        <- the odd one
 *
 * Those keys come from two different writers -- serving_fill.py emits "Primary
 * lens", Tenders.jsx emits "Estimated value", "Closing date", "Notice ref." --
 * and `.cd-fk` sets no text-transform, so whatever a writer typed reached the
 * screen. Formatting the key at the render site fixes both writers and every row
 * already stored, without a migration.
 *
 * The value must survive untouched, and that is the half worth guarding: running
 * a label formatter over data would rewrite a publisher's name, a country, or a
 * date. formatLabel lower-cases anything it does not recognise, so
 * "analisidifesa.it" would become "Analisidifesa.it" and "1 Sep 2026" would
 * survive only by luck.
 */
import { formatLabel } from "./src/lib/profile.js";

let bad = 0;
const eq = (got, want, what) => {
  if (got !== want) { bad++; console.log(`  FAIL ${what}\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`); }
};

/* --- the real keys, from both writers --- */
// serving_fill.py
eq(formatLabel("Primary lens"), "Primary Lens", "the reported one");
eq(formatLabel("Company"), "Company", "already correct, unchanged");
eq(formatLabel("Category"), "Category", "already correct, unchanged");
eq(formatLabel("Date"), "Date", "already correct, unchanged");
// Tenders.jsx factRows
eq(formatLabel("Estimated value"), "Estimated Value", "tender key");
eq(formatLabel("Closing date"), "Closing Date", "tender key");
eq(formatLabel("Notice ref."), "Notice Ref.", "trailing punctuation stays put");
eq(formatLabel("Buyer"), "Buyer", "unchanged");
eq(formatLabel("Country"), "Country", "unchanged");
eq(formatLabel("Quantity"), "Quantity", "unchanged");
eq(formatLabel("Source"), "Source", "unchanged");
eq(formatLabel("Status"), "Status", "unchanged");

/* --- idempotent: formatting an already-formatted label changes nothing --- */
for (const k of ["Primary Lens", "Estimated Value", "Closing Date", "Notice Ref."]) {
  eq(formatLabel(k), k, `idempotent: ${k}`);
}

/* --- the guard: this is applied to the KEY only, never the VALUE ---------
 * Not an assertion about formatLabel -- an assertion about what would happen if
 * someone applied it one column to the right. Each of these is a real value from
 * the drawer, and each comes back WRONG, which is why the render site formats
 * f[0] and hands f[1] through untouched.
 */
const VALUES_IT_WOULD_RUIN = [
  ["analisidifesa.it", "a publisher"],
  ["Leonardo", "a company (survives, but only by luck)"],
  ["Protected & Armoured Vehicles", "a category (already Pascal)"],
];
for (const [v, what] of VALUES_IT_WOULD_RUIN) {
  const out = formatLabel(v);
  if (v === "analisidifesa.it" && out === v) {
    bad++;
    console.log(`  FAIL the value guard is pointless if ${what} survives formatting`);
  }
}

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - fact labels, 16 cases, one capitalisation from either writer");
