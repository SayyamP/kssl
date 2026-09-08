/* The geographic footprint map may not say more than its rows do.
 *
 *     node test_geo_badge.mjs
 *
 * Three faults reported against the live map on 2026-09-06. Every fixture below is a
 * real serving.geo_presence / serving.geo_comp shape, measured on production the same
 * day, and every assertion fails against the code as it was.
 *
 * 1. THE BADGE PARROTED THE CLIENT'S OWN NAME. Reported verbatim: "why geo footprint
 *    KSSL present KSSL present written 2 time in india". GeoMap built the badge as
 *    `${clientLabel} Present` and then appended the LABELS of the client's own rows;
 *    serving.ui_config maps actLabel.bf = "KSSL present", and KSSL carries four c='bf'
 *    product rows in India, so the badge read
 *        "KSSL Present · KSSL present / Local production".
 *    'bf' is a WHO -- it marks the row as the client's -- and the first half of the
 *    badge already says it. "Local production" is a WHAT and must survive.
 *
 * 2. AN ESTIMATE WAS DRAWN AS A MEASUREMENT. serving.geo_presence.src holds a URL, or
 *    the literal "syn" when the row is an analytical estimate (val='estimate').
 *    pages/competitive/Geo.jsx has always marked those; GeoMap.jsx never read src, so
 *    KSSL's Saudi Arabia pin -- one src='syn' row -- was the identical solid green dot
 *    with the identical wording as India, which four cited rows support. This is the
 *    house rule "not measured must not look like zero" in its other direction.
 *
 * 3. THE HEAD OFFICE BADGE NEVER FIRED. It was a raw full-string equality between
 *    geo_comp.hq and the country name. The archived reference rows store a bare
 *    "Germany" and matched; every pipeline row stores a chain ("Ahmedabad, Gujarat,
 *    India", "London, United Kingdom") and could not, so the badge had quietly stopped
 *    firing for the entire live roster -- and no badge reads as "not their head office".
 */
import { readFileSync } from "node:fs";
import {
  activityLabels,
  clientFootprintNote,
  companyRole,
  echoesPresence,
  evidenceOf,
  isEstimate,
  ownActivityLabels,
  presenceBadge,
} from "./src/lib/geoBadge.js";
import { geoPlotPlan, hqCountry, isHeadOffice, sameCountry } from "./src/lib/geoCountries.js";

let bad = 0;
const fail = (m) => { bad += 1; console.log("  FAIL " + m); };
const eq = (got, want, what) => {
  if (got !== want) fail(`${what}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
};

/* serving.ui_config.actLabel, verbatim from production. */
const ACT = {
  bf: "KSSL present",
  ex: "Export / supply",
  lp: "Local production",
  pt: "Partnership / licence",
  sv: "Service / MRO",
};
const CLIENT = "KSSL";

/* KSSL's own eight geo_presence rows, as they stand live: five in India, one in
   Saudi Arabia, two under "Europe" (which is not a country and is not plotted). */
const KSSL_INDIA = [
  { name: "ATAGS / Bharat 52 (155/52)", c: "bf", val: "offered", src: "src" },
  { name: "Kalyani M4 / Maverick", c: "bf", val: "in service", src: "src" },
  { name: "Bharat 150 / Omega", c: "bf", val: "portfolio", src: "src" },
  { name: "Underwater systems / MRAUV", c: "bf", val: "contracted", src: "src" },
  { name: "Local production", c: "lp", src: "https://example.gov.in/atags" },
];
const KSSL_SAUDI = [
  { name: "Artillery / forgings (offered)", c: "ex", val: "estimate", src: "syn" },
];

/* ------------------------------------------------------------------ 1. the echo --- */

// The reported string, exactly. It must not be producible any more.
const india = presenceBadge({ clientLabel: CLIENT, rows: KSSL_INDIA, rivalCount: 3, actLabel: ACT });
if (/KSSL present/i.test(india.text.replace(/^KSSL Present/, "")))
  fail(`the badge still repeats the client's name: ${JSON.stringify(india.text)}`);
eq(india.text, "KSSL Present · Local production", "India badge");

// ...and the informative half is not thrown away with it.
if (!india.text.includes("Local production"))
  fail("dropping 'bf' also dropped the local-production row, which is the useful half");

// 'bf' alone leaves nothing to add -- the badge is the client's name and stops there.
eq(
  presenceBadge({ clientLabel: CLIENT, rows: KSSL_INDIA.slice(0, 4), rivalCount: 0, actLabel: ACT }).text,
  "KSSL Present",
  "badge with only bf rows",
);
eq(ownActivityLabels(KSSL_INDIA, ACT, CLIENT).join(" / "), "Local production", "own activities");

// A rival's rows are NOT filtered this way: 'bf' never appears on one, and every label
// a rival's rows carry is information about the rival.
eq(activityLabels([{ c: "ex" }, { c: "sv" }, { c: "ex" }], ACT).join(" / "),
  "Export / supply / Service / MRO", "rival activity labels, deduped, in row order");

// The guard survives a rewritten label dictionary: the rule is the CODE plus a check
// that the words are not just the client's name again.
if (!echoesPresence("KSSL present", CLIENT)) fail("'KSSL present' not recognised as an echo");
if (!echoesPresence("Kssl  Presence", CLIENT)) fail("case or spacing defeats the echo check");
if (echoesPresence("Local production", CLIENT)) fail("a real activity was mistaken for an echo");
eq(
  presenceBadge({
    clientLabel: CLIENT,
    rows: [{ c: "lp", src: "https://x.test" }],
    rivalCount: 0,
    actLabel: { ...ACT, lp: "KSSL present" },   // dictionary sabotage
  }).text,
  "KSSL Present",
  "a relabelled code cannot smuggle the echo back",
);

// Absence is unchanged, and "contested" still needs a real rival row.
eq(presenceBadge({ clientLabel: CLIENT, rows: [], rivalCount: 2, actLabel: ACT }).text,
  "KSSL Absent · Contested Market ⚠", "absent, contested");
eq(presenceBadge({ clientLabel: CLIENT, rows: [], rivalCount: 0, actLabel: ACT }).text,
  "No activity on file", "absent, uncontested");

/* -------------------------------------------------------------- 2. the estimate --- */

if (!isEstimate({ src: "syn" })) fail("src='syn' is not being read as an estimate");
if (isEstimate({ src: "https://asdnews.com/x" })) fail("a sourced row was called an estimate");
if (isEstimate({ src: "src" })) fail("the archive's 'src' placeholder is not 'syn'");

const saudi = presenceBadge({ clientLabel: CLIENT, rows: KSSL_SAUDI, rivalCount: 1, actLabel: ACT });
if (!saudi.estimated) fail("an all-estimate presence did not report itself as estimated");
if (saudi.cls === india.cls)
  fail(`an estimated presence renders exactly like a sourced one (cls ${saudi.cls})`);
if (!/estimat/i.test(saudi.text))
  fail(`the badge does not say the presence is an estimate: ${JSON.stringify(saudi.text)}`);
eq(saudi.cls, "present est", "estimate class");
eq(india.cls, "present", "sourced class");
if (india.estimated) fail("India's four sourced rows were flagged as estimates");

// A MIX is not an all-estimate: the sourced rows earn the green badge, and the
// estimated ones are still counted out loud rather than absorbed into it.
const mixed = presenceBadge({
  clientLabel: CLIENT,
  rows: [{ c: "lp", src: "https://x.test" }, { c: "ex", src: "syn" }],
  rivalCount: 0,
  actLabel: ACT,
});
eq(mixed.cls, "present", "mixed evidence keeps the sourced class");
eq(mixed.note, "1 of 2 rows is an analytical estimate", "mixed evidence note");
if (india.note !== null) fail("a fully sourced country carried an estimate note");
const ev = evidenceOf(KSSL_INDIA);
eq(ev.sourced, 5, "India sourced rows");
eq(ev.estimated, 0, "India estimated rows");

/* --- 2b. "is KSSL only India?" -- the map could not answer its own headline question --- */

/* KSSL's whole footprint as it stands live: India (5 rows, sourced), Saudi Arabia (1
   row, src='syn'), Europe (an estimate under a CONTINENT, which is deliberately never
   pinned). One green dot appears, over India, and the reader concludes India-only. */
const OWN = { India: KSSL_INDIA, "Saudi Arabia": KSSL_SAUDI, Europe: [{ c: "ex", src: "syn" }] };
const footprint = clientFootprintNote({
  clientLabel: CLIENT,
  ownByCountry: OWN,
  plan: geoPlotPlan(Object.keys(OWN)),
});
if (!footprint) fail("the client's footprint is not stated anywhere beside the map");
const fp = footprint || "";
for (const must of ["India", "Saudi Arabia", "Europe"])
  if (!fp.includes(must))
    fail(`the footprint note does not mention ${must}: ${JSON.stringify(footprint)}`);
if (!fp.includes("Saudi Arabia (estimated)"))
  fail("an estimated country is listed as though it were sourced");
if (fp.includes("India (estimated)"))
  fail("India's four sourced rows were called an estimate");
if (!/not a country/i.test(fp))
  fail("Europe is listed without saying why it is not on the map");
// It never promotes a region to somewhere drawable to make the answer look better.
if (geoPlotPlan(Object.keys(OWN)).plotted.some((p) => p.ct === "Europe"))
  fail("Europe was pinned to a point");
// A client with no rows at all says so, rather than saying nothing.
eq(clientFootprintNote({ clientLabel: CLIENT, ownByCountry: {}, plan: geoPlotPlan([]) }),
  null, "no footprint rows at all");
if (!/no footprint row in any country/.test(
  clientFootprintNote({
    clientLabel: CLIENT,
    ownByCountry: { Europe: [{ c: "ex", src: "syn" }] },
    plan: geoPlotPlan(["Europe"]),
  }) || ""))
  fail("a client whose only row is a region reads as if it had no rows at all");

/* ------------------------------------------------------------ 3. the head office --- */

// Real serving.geo_comp.hq values, both storage styles.
eq(hqCountry("Ahmedabad, Gujarat, India"), "India", "hq chain -> country");
eq(hqCountry("London, United Kingdom"), "United Kingdom", "hq chain -> country");
eq(hqCountry("Germany"), "Germany", "bare country hq");
eq(hqCountry("Payerne, Switzerland (HQ moved to Hengelo, Netherlands, Nov 2024)"),
  "Switzerland", "parenthetical aside is not the head office");
eq(hqCountry("Krauss-Maffei-Strasse 11, 80997 Munich, Germany"), "Germany", "postal address");
// ...and nothing is promoted to a country to make a badge appear.
eq(hqCountry("Orlando, Florida"), null, "a region is not a country");
eq(hqCountry("Madrid"), null, "a city we have no country for stays null");
eq(hqCountry(""), null, "empty hq");
eq(hqCountry(null), null, "absent hq");

// The pipeline rows that could never match before.
for (const [hq, ct] of [
  ["Ahmedabad, Gujarat, India", "India"],
  ["London, United Kingdom", "UK"],          // alias: the map's own table says they are one
  ["Bengaluru, Karnataka, India", "India"],
  ["Seodaemun-gu, Seoul, South Korea", "South Korea"],
  ["Bethesda, MD, USA", "United States"],
]) {
  if (!isHeadOffice(ct, { origin: null, hq }))
    fail(`head office missed: hq ${JSON.stringify(hq)} in ${ct}`);
}
// The reference rows that DID match must go on matching.
if (!isHeadOffice("Germany", { origin: null, hq: "Germany" })) fail("bare-country hq stopped matching");
// And a company that is merely present is still not headquartered there.
if (isHeadOffice("Canada", { origin: null, hq: "London, United Kingdom" }))
  fail("a presence was captioned as a head office");
if (isHeadOffice("India", { origin: null, hq: null }))
  fail("a company with no hq was given a head office");

// The STATED origin column wins when the dataset carries one -- an audited value beats
// a parsed string, and countryFacet.companyOrigin is where it comes from.
if (!isHeadOffice("India", { origin: "India", hq: "Pune" }))
  fail("the stated origin country was ignored");

// Aliases resolve through the coordinate table, not a second list.
if (!sameCountry("UK", "United Kingdom")) fail("UK / United Kingdom read as two countries");
if (!sameCountry("usa", "USA")) fail("case defeats sameCountry");
if (sameCountry("India", "Indonesia")) fail("two different countries read as one");
if (sameCountry("Ruritania", "Freedonia"))
  fail("two unknown names were declared equal -- an unknown may only equal itself");
if (!sameCountry("Ruritania", "Ruritania")) fail("an unknown name is not equal to itself");
if (sameCountry("", "")) fail("two empties were called the same country");

/* --------------------------------------------------- the company list's role line --- */

eq(
  companyRole({
    comp: { id: "bae-systems", name: "BAE Systems", isBf: false },
    rows: [{ c: "ex" }],
    actLabel: ACT,
    clientLabel: CLIENT,
    isHq: isHeadOffice("UK", { origin: null, hq: "London, United Kingdom" }),
  }),
  "Head office · Export / supply",
  "pipeline competitor in its own home country",
);
eq(
  companyRole({
    comp: { id: "KSSL", name: "Kalyani Strategic Systems", isBf: true },
    rows: KSSL_INDIA,
    actLabel: ACT,
    clientLabel: CLIENT,
    isHq: isHeadOffice("India", { origin: "India", hq: "India" }),
  }),
  "Head office · Local production",
  "the client's own row does not print its own name as an activity",
);
eq(
  companyRole({
    comp: { id: "x", name: "Somebody", isBf: false },
    rows: [],
    actLabel: ACT,
    clientLabel: CLIENT,
    isHq: false,
  }),
  "Competitor",
  "a company with no rows here",
);

/* ------------------------------------------------------- and the map actually uses it --- */

/* A pure module can be right while the component goes on doing it the old way -- that is
   how the head-office comparison survived a rewrite of everything around it. So the
   caller is checked too: it must reach these rules, and it must no longer carry the raw
   comparison or the label-append that produced the reported string. */
const MAP = readFileSync("./src/components/geoMap/GeoMap.jsx", "utf8");
for (const call of ["presenceBadge(", "companyRole(", "isHeadOffice(", "clientFootprintNote("])
  if (!MAP.includes(call)) fail(`GeoMap.jsx never calls ${call})`);
if (/String\(c\.hq\)\.toLowerCase\(\)\s*===\s*String\(ct\)/.test(MAP))
  fail("GeoMap.jsx still compares the whole hq string to the country name");
if (/\$\{clientLabel\} Present\$\{/.test(MAP))
  fail("GeoMap.jsx still builds the presence badge by appending its own activity labels");

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log(
  "ok - geo badge: the client's name is not an activity, an estimate does not render as "
  + "a measurement, and a head office is found at either storage granularity",
);
