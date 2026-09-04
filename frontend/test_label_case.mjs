/* One capitalisation rule for every category, sector and product label.
 *
 *     node test_label_case.mjs
 *
 * Finding 19: "Text styling is inconsistent between Product and Competitive views.
 * Some portfolio categories are shown in lowercase while others use pascal case."
 *
 * Three formatters were doing this job with three different acronym lists, and they
 * disagreed on more than case: lib/profile.js defaulted an empty value to
 * 'Defence & Aerospace' while Products.jsx defaulted to 'Defense Systems', so the same
 * blank field read British in one view and American in the next.
 *
 * The empty-input case is the important one. The sector formatter answered
 * 'Defence & Aerospace' for "", and profile.js ran the HEADQUARTERS field through it,
 * so every competitor without a recorded HQ displayed 'Defence & Aerospace' as its head
 * office. 136 of 178 served competitors have no hq value.
 */
import { formatLabel, formatSectorName } from "./src/lib/profile.js";

let bad = 0;
const eq = (got, want, what) => {
  if (got !== want) { bad++; console.log(`  FAIL ${what}\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`); }
};

/* --- the real values from serving.competitors.sector --- */
eq(formatLabel("defense services and solutions"), "Defence Services and Solutions",
   "lower-case sector is title-cased, 'and' stays small, defense -> Defence");
eq(formatLabel("Defence manufacturing"), "Defence Manufacturing", "mixed case");
eq(formatLabel("DEFENSE MANUFACTURING"), "Defence Manufacturing", "shouting is calmed");
eq(formatLabel("Artillery · Ammunition · Small Arms"), "Artillery · Ammunition · Small Arms",
   "already correct, and the separator survives");
eq(formatLabel("Electronics/EW · Naval · Artillery"), "Electronics/EW · Naval · Artillery",
   "EW keeps its case inside a slash pair");
eq(formatLabel("missile defense systems"), "Missile Defence Systems", "defense -> Defence");
eq(formatLabel("defense, security, emergency solutions"),
   "Defence, Security, Emergency Solutions", "commas");

/* --- one spelling, one case, whichever view asks --- */
eq(formatLabel("defence"), "Defence", "defence");
eq(formatLabel("defense"), "Defence", "defense");
eq(formatLabel("uav swarms"), "UAV Swarms", "acronym");
eq(formatLabel("bmp-2 upgrade"), "BMP-2 Upgrade", "platform designation keeps its case");
eq(formatLabel("mk1 turret"), "MK1 Turret", "MK1, not Mk1");
eq(formatLabel("r&d"), "R&D", "ampersand acronym");

/* --- a connector is only small in the middle --- */
eq(formatLabel("and beyond"), "And Beyond", "a leading connector is still capitalised");
eq(formatLabel("air and land"), "Air and Land", "a middle connector is not");

/* --- the empty case: a shared formatter must not invent a value --- */
eq(formatLabel(""), "", "empty in, empty out");
eq(formatLabel(null), "", "null in, empty out");
eq(formatLabel(undefined), "", "undefined in, empty out");
if (formatLabel("") === "Defence & Aerospace") {
  bad++; console.log("  FAIL an empty HQ must never render as a sector name");
}

/* --- sector, and only sector, carries the industry default --- */
eq(formatSectorName(""), "Defence & Aerospace", "sector keeps its default");
eq(formatSectorName("naval systems"), "Naval Systems", "sector still formats");

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - formatLabel, 22 cases, one rule for Product and Competitive alike");
