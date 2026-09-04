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
eq(formatLabel("defense services and solutions"), "Defence Services And Solutions",
   "Pascal case: every word capitalised, connectors included; defense -> Defence");
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

/* --- FE 12 / FE 34 / T 20: an acronym is whole, a designation keeps its own case ---
 * These are the real sector strings from serving.competitors.sector and the real
 * company/product strings the acceptance sheet named. formatLabel lower-cased every
 * word it did not know, so "ARI" printed as "Ari" and "UAVs" as "UAVS" in the sector
 * dropdown while the profile heading printed them correctly. */
eq(formatLabel("ARI"), "ARI", "FE 34: a three-letter company acronym is not calmed to 'Ari'");
eq(formatLabel("sam systems"), "SAM Systems", "T 20: a defence acronym typed in lower case is raised whole");
eq(formatLabel("Unmanned Aerial Vehicles (UAVs), Counter-Unmanned Aircraft Systems (C-UAS)"),
   "Unmanned Aerial Vehicles (UAVs), Counter-Unmanned Aircraft Systems (C-UAS)",
   "FE 12: a plural acronym keeps its small s -- UAVs, not UAVS and not Uavs");
eq(formatLabel("armored vehicles, MRAPs, counter-drone systems"),
   "Armored Vehicles, MRAPs, Counter-Drone Systems", "FE 12: MRAPs");
eq(formatLabel("Synthetic Aperture Radar (SAR) satellites, Intelligence, Surveillance and Reconnaissance (ISR)"),
   "Synthetic Aperture Radar (SAR) Satellites, Intelligence, Surveillance And Reconnaissance (ISR)",
   "FE 12: SAR and ISR survive inside brackets");
eq(formatLabel("C4ISR systems"), "C4ISR Systems", "alphanumeric acronym");
eq(formatLabel("P3TS military satellite navigation receiver"),
   "P3TS Military Satellite Navigation Receiver",
   "FE 32: a designation with a digit in it keeps its own case, list or no list");
eq(formatLabel("IP67 rated"), "IP67 Rated", "designation");
eq(formatLabel("Defence &amp; Aerospace, Maritime Systems, Simulation &amp; Training"),
   "Defence & Aerospace, Maritime Systems, Simulation & Training", "entity decoded");

/* --- FE 31: a stray separator is not a word --- */
eq(formatLabel("Naval,, Land Defense"), "Naval, Land Defence", "FE 31: a double comma collapses to one");
eq(formatLabel("Naval , Land Defense"), "Naval, Land Defence", "a floating comma is reattached");
eq(formatLabel("Naval Defense,"), "Naval Defence", "a trailing comma is dropped");

/* --- Pascal case: a connector is capitalised wherever it sits --- */
eq(formatLabel("and beyond"), "And Beyond", "leading connector");
eq(formatLabel("air and land"), "Air And Land", "middle connector is capitalised too");
eq(formatLabel("ministry of defence"), "Ministry Of Defence", "of is capitalised");

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
console.log("ok - formatLabel, 36 cases, one rule for Product and Competitive alike");
