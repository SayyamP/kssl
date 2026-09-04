/* A spec value shows its unit when the RECORD holds one, and never otherwise.
 *
 *     node test_spec_units.mjs
 *
 * T 7: "specification values do not consistently show measurement units". The
 * matchup record carries the unit in its own field (`u`), and the paired-bar view
 * printed it in the row label -- but the product page and the no-edge branch of
 * the dossier printed the bare value, so "Max range 40+" sat next to "Max range
 * 41 km" for the product one line down.
 *
 * The half that matters is the refusal. A unit that is not in the record is not
 * known: appending "mm" to a bare "3" because the label says calibre is a
 * fabricated figure, and check_no_fabrication.mjs exists for exactly that class.
 * So the rule reads the stored unit only, and only onto a value that is a number
 * with nothing else in it. Measured over the served snapshots: 64 values in the
 * reference archive and 28 in the deployed set gain their stored unit; 602 and 17
 * bare numbers have no unit on record and are left bare.
 */
import { specValueWithUnit } from "./src/lib/specs.js";

let bad = 0;
const eq = (got, want, what) => {
  if (got !== want) { bad++; console.log(`  FAIL ${what}\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`); }
};

/* --- the stored unit reaches a bare number --- */
eq(specValueWithUnit("40+", "km"), "40+ km", "T 7: the reported shape, a bare figure with the unit on the record");
eq(specValueWithUnit("30-56", "km"), "30-56 km", "a range");
eq(specValueWithUnit("1,000", "hp"), "1,000 hp", "a thousands separator is still a number");
eq(specValueWithUnit(41.2, "km"), "41.2 km", "a numeric value, not a string");
eq(specValueWithUnit("< 15", "t"), "< 15 t", "a bound");

/* --- a value that already carries its unit is not doubled --- */
eq(specValueWithUnit("41 km", "km"), "41 km", "already qualified");
eq(specValueWithUnit("155mm / 52 Cal mm", "mm"), "155mm / 52 Cal mm", "unit present inside the text");
eq(specValueWithUnit("over 67 km/h km/h", "km/h"), "over 67 km/h", "a unit the record repeated is printed once");
eq(specValueWithUnit("46.3 tonnes tonnes", "tonnes"), "46.3 tonnes", "same, spelled out");

/* --- NEVER invented: no unit on the record means no unit on screen --- */
eq(specValueWithUnit("3", ""), "3", "a crew count has no unit and gets none");
eq(specValueWithUnit("3", null), "3", "null unit");
eq(specValueWithUnit("3", undefined), "3", "missing unit");
eq(specValueWithUnit("6x6", ""), "6x6", "a configuration is not a quantity");

/* --- a stored unit does not attach to something that is not a plain number --- */
eq(specValueWithUnit("Minimum 30 minutes", "hours"), "Minimum 30 minutes",
   "the record says hours but the value says minutes: appending would state a wrong unit");
eq(specValueWithUnit("no published figure", "kg"), "no published figure", "a placeholder");
eq(specValueWithUnit("n/a — empty shell body", "km"), "n/a — empty shell body", "a placeholder");
eq(specValueWithUnit("57 & 127mm (76/30 in test)", "kg"), "57 & 127mm (76/30 in test)",
   "a value with its own units in it takes nothing from the record");

/* --- empties --- */
eq(specValueWithUnit(null, "km"), "", "null value");
eq(specValueWithUnit("", "km"), "", "empty value");
eq(specValueWithUnit(undefined, "km"), "", "missing value");

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - specValueWithUnit, 20 cases, stored unit shown once and never invented");
