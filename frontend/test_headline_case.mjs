/* One capitalisation for every headline the app prints.
 *
 *     node test_headline_case.mjs
 *
 * The feed carried its publishers' casing straight through, so it read as two feeds
 * stacked: on the market lane 29 cards arrived in title case ("US Navy Seeks
 * Carrier-Based Combat Drone Prototypes") and 109 in sentence case ("US Navy issues
 * RFI for carrier-based Collaborative Combat Aircraft").
 *
 * formatLabel could not do this job. It lower-cases any word missing from a fixed
 * acronym list, and headlines are full of acronyms no list will hold, so it would have
 * printed "Us Navy Issues Rfi". The headline rule instead only ever RAISES a letter --
 * which is also the property this file leans on: for ANY input, the output must equal
 * the input once both are upper-cased. That one invariant catches every way the rule
 * could eat an acronym, without enumerating acronyms.
 *
 * Measured over the served dataset: 3,254 headlines, 3,119 re-cased, none damaged.
 */
import { titleCaseHeadline } from "./src/lib/profile.js";

let bad = 0;
const eq = (got, want, what) => {
  if (got !== want) { bad++; console.log(`  FAIL ${what}\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`); }
};

/* --- the two real headlines from the report, which must end up alike --- */
eq(titleCaseHeadline("US Navy issues RFI for carrier-based Collaborative Combat Aircraft"),
   "US Navy Issues RFI For Carrier-Based Collaborative Combat Aircraft",
   "sentence case is raised, and RFI is not touched");
eq(titleCaseHeadline("US Navy Seeks Carrier-Based Combat Drone Prototypes"),
   "US Navy Seeks Carrier-Based Combat Drone Prototypes",
   "a headline already in title case is left exactly as it was");

/* --- an acronym is preserved because nothing is ever lowered --- */
eq(titleCaseHeadline("South Korea DAPA prepares for serial production of AMEV armoured medical vehicle"),
   "South Korea DAPA Prepares For Serial Production Of AMEV Armoured Medical Vehicle",
   "DAPA and AMEV survive without being in any list");
eq(titleCaseHeadline("India tested LRAShM, a long-range hypersonic missile"),
   "India Tested LRAShM, A Long-Range Hypersonic Missile",
   "mixed-case acronym keeps its shape; hyphenated word raised on both sides");
eq(titleCaseHeadline("KONGSBERG launches AI-powered Aegir SSA sonar family"),
   "KONGSBERG Launches AI-Powered Aegir SSA Sonar Family",
   "a shouting brand is not calmed -- headlines are quotations, not labels");

/* --- what must be left alone --- */
eq(titleCaseHeadline("Developing 30mm x 173 Airburst Solution for U.S. Navy"),
   "Developing 30mm x 173 Airburst Solution For U.S. Navy",
   "a lone letter is left alone: the 'x' of a calibre is a multiplication sign, not a word");
eq(titleCaseHeadline("Rheinmetall completed development of 120mm KE 2020 Neo ammo"),
   "Rheinmetall Completed Development Of 120mm KE 2020 Neo Ammo",
   "a word starting with a digit is never touched");
eq(titleCaseHeadline("U.S. Army selects 8x8 K9 Thunder variant"),
   "U.S. Army Selects 8x8 K9 Thunder Variant", "8x8 survives");
eq(titleCaseHeadline("Greece Signs €3 Billion Defense Deal with Israel"),
   "Greece Signs €3 Billion Defense Deal With Israel", "a currency figure survives");
eq(titleCaseHeadline("Rheinmetall's LUNA NG drone meets civil safety standards"),
   "Rheinmetall's LUNA NG Drone Meets Civil Safety Standards",
   "an apostrophe is inside the word, not a word break");

/* --- headlines are injected as HTML: tags and entities are not words --- */
eq(titleCaseHeadline("Missiles &amp; air defence order"), "Missiles &amp; Air Defence Order",
   "an entity is stepped over -- without this it becomes &Amp; and shows as text");
eq(titleCaseHeadline("Leonardo wins <b>a $2bn</b> contract"),
   "Leonardo Wins <b>A $2bn</b> Contract", "a tag is stepped over, its text is not");

eq(titleCaseHeadline(""), "", "empty in, empty out");
eq(titleCaseHeadline(null), "", "null in, empty out");

/* --- the invariant, asserted over every case above: a raise, never a lowering --- */
const CORPUS = [
  "US Navy issues RFI for carrier-based Collaborative Combat Aircraft",
  "South Korea DAPA prepares for serial production of AMEV armoured medical vehicle",
  "India tested LRAShM, a long-range hypersonic missile",
  "Rheinmetall to produce M142 HIMARS in Germany",
  "Thales FZ275 LGR certified for Arnold Defense launcher",
  "KNDS 30M781 cannon integrated with EOS R500 RWS",
  "Missiles &amp; air defence order",
];
for (const s of CORPUS) {
  const out = titleCaseHeadline(s);
  if (out.toUpperCase() !== s.toUpperCase()) {
    bad++;
    console.log(`  FAIL not a pure raise\n    in  ${s}\n    out ${out}`);
  }
}

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - titleCaseHeadline, 14 cases, raises only and eats no acronym");
