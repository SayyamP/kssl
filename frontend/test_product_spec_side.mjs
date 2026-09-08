/* A PRODUCT PAGE SHOWS ONE PRODUCT'S NUMBERS.

 * Reported from the dashboard: BAE Systems' Archer listed 15 technical specifications
 * on the Products tab, while Positioning showed the same rival as "not sourced" on most
 * of the same fields. The two pages were reading the same matchup rows and disagreeing.
 *
 * Positioning was right. A matchup spec row carries BOTH products -- `cv` is the rival's
 * value and `kv` is KSSL's -- and the Products page read `s.cv || s.kv` for competitors,
 * so a field the rival had not published fell back to KSSL's figure and printed it under
 * the rival's name, unmarked. "9,391 x 2,650 x 3,160 mm" occurs nowhere in the served
 * payload except as a KSSL `kv`; it was on screen as a BAE Systems dimension.
 *
 * These checks are about attribution, not formatting.
 */
import { productSpecs } from "./src/lib/specs.js";

let fails = 0;
const ck = (name, ok, detail) => {
  console.log(`  ${String(name).padEnd(68)} ${ok ? "ok" : "FAIL"}${!ok && detail ? "  " + detail : ""}`);
  if (!ok) fails++;
};

/* One artillery matchup, shaped like the real ones: the rival published a calibre and a
   rate of fire, KSSL published a full sheet. */
const SPECS = [
  { l: "Calibre", cv: "155 mm / 52 calibre", kv: "155 mm / 39 calibre", u: "" },
  { l: "Rate of fire", cv: "up to 8 rounds/min", kv: "burst 3 rounds / 30 sec", u: "" },
  { l: "Length", cv: null, kv: "9,391 x 2,650 x 3,160 mm", u: "" },
  { l: "Weight", cv: null, kv: "18 tonnes (all-up weight)", u: "" },
  { l: "Direct fire", cv: "up to 2,000 m", kv: null, u: "" },
  { l: "Muzzle velocity", cv: null, kv: "no published figure", u: "" },
];

const comp = productSpecs(SPECS, "comp");
const client = productSpecs(SPECS, "client");

ck("the rival keeps the fields it published", comp.Calibre === "155 mm / 52 calibre");
ck("...including one KSSL has no counterpart for", comp["Direct fire"] === "up to 2,000 m");

/* THE BUG. Each of these was KSSL's number, on screen as the rival's. */
ck("a field the rival did not publish is ABSENT, not KSSL's value",
   !("Length" in comp), JSON.stringify(comp.Length));
ck("...and that holds for every such field", !("Weight" in comp), JSON.stringify(comp.Weight));
ck("no KSSL value appears anywhere on the rival's sheet",
   !Object.values(comp).some((v) => Object.values(client).includes(v)), JSON.stringify(comp));

/* The client side was already correct and must stay so -- it never reads cv. */
ck("KSSL's sheet is KSSL's values", client.Length === "9,391 x 2,650 x 3,160 mm");
ck("...and never borrows the rival's", client.Calibre === "155 mm / 39 calibre");
ck("KSSL does not gain a field only the rival published", !("Direct fire" in client));

/* "no published figure" is a statement that there is no number, not a number. */
ck("a not-published sentinel is not rendered as a value", !("Muzzle velocity" in client));

ck("an empty matchup yields an empty sheet, not a throw",
   Object.keys(productSpecs(null, "comp")).length === 0);
ck("a label formatter is applied when given",
   productSpecs([{ l: "calibre", cv: "x", u: "" }], "comp", (l) => l.toUpperCase()).CALIBRE === "x");

console.log("");
console.log(fails ? fails + " FAILED"
                 : "ok - each product page shows only its own product's numbers");
process.exit(fails ? 1 : 0);
