/* The map may not invent where a country is.
 *
 *     node test_geo_map.mjs
 *
 * Reported: "displayed data is not aligned properly ... geolocation elements should be
 * correctly aligned" -- with a screenshot showing dots floating in the Atlantic.
 *
 * They were not misaligned. getDeterministicCoords() HASHED the country name into a
 * position whenever the country was missing from a hand-written table:
 *
 *     lat = 10 + (abs(hash % 50) - 25)          ->  -15 .. 35
 *     lng = 20 + (abs((hash >> 3) % 120) - 60)  ->  -40 .. 80
 *
 * That band is the Atlantic, Africa and the near Middle East, which is exactly where
 * the stray dots were. Sixteen of the fifty-two countries the pipeline actually serves
 * fell through it, so the map asserted that Russia, Norway, Finland and Taiwan are off
 * the coast of West Africa.
 *
 * What this pins:
 *   1. every country the pipeline serves today resolves to real coordinates -- the
 *      regression that lets a new country be noticed instead of hashed;
 *   2. none of the sixteen sits in the old hash band. Checking "Russia has SOME
 *      coordinates" would have passed against the bug, because the bug always produced
 *      coordinates; the test has to check WHERE;
 *   3. an unknown country is not drawn at all AND is reported, so a gap reads as a gap;
 *   4. continent rows are not pinned to a point.
 */
/* 2026-09-06: the table and both rules moved to src/lib/geoCountries.js, so this imports
   the module instead of slicing GeoMap.jsx's source and evaluating the slice. Every
   assertion below is unchanged -- but they now run against the code the app loads, not
   against a fragment that could keep passing while the rest of the file failed to parse. */
import { geoPlotPlan, geoCountryCoords } from "./src/lib/geoCountries.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

/* The exact country vocabulary serving.geo_presence holds today (52 distinct values,
   275 rows). Kept as a literal so this test is hermetic -- it must run in the Docker
   build with no database. */
const SERVED = [
  "Afghanistan", "Africa", "Argentina", "Armenia", "Australia", "Austria", "Bangladesh",
  "Belgium", "Brazil", "Canada", "China", "Czech Republic", "Denmark", "Egypt",
  "Estonia", "Europe", "Finland", "France", "Germany", "Greece", "Hungary", "India",
  "Indonesia", "Israel", "Italy", "Japan", "Kazakhstan", "Kuwait", "Malaysia",
  "Netherlands", "New Zealand", "Norway", "Pakistan", "Philippines", "Poland", "Qatar",
  "Romania", "Russia", "Saudi Arabia", "Singapore", "South Africa", "South Korea",
  "Spain", "Sri Lanka", "Sweden", "Taiwan", "Thailand", "UAE", "UK", "USA", "Ukraine",
  "Vietnam",
];

const plan = geoPlotPlan(SERVED);

// 1. nothing the pipeline serves is left without a position
if (plan.unlocated.length)
  fail(`served countries with no coordinates: ${plan.unlocated.join(", ")}`);
if (plan.plotted.length !== SERVED.length - plan.regions.length)
  fail(`plotted ${plan.plotted.length} of ${SERVED.length - plan.regions.length} countries`);

// 2. the sixteen that used to be hashed are where they belong.
//    inHashBand is the OLD generator's whole output range: if a country lands in it by
//    accident the assertion below is checked against a real centroid instead.
const inHashBand = ([lat, lng]) => lat >= -15 && lat <= 35 && lng >= -40 && lng <= 80;
const WAS_HASHED = {
  Afghanistan: [33.9, 67.7], Austria: [47.5, 14.6], Belgium: [50.5, 4.5],
  "Czech Republic": [49.8, 15.5], Denmark: [56.3, 9.5], Estonia: [58.6, 25.0],
  Finland: [61.9, 25.7], Greece: [39.1, 21.8], Hungary: [47.2, 19.5],
  Kazakhstan: [48.0, 66.9], Netherlands: [52.1, 5.3], "New Zealand": [-40.9, 174.9],
  Norway: [60.5, 8.5], Romania: [45.9, 25.0], Russia: [61.5, 105.3],
  Taiwan: [23.7, 121.0],
};
for (const [ct, [lat, lng]] of Object.entries(WAS_HASHED)) {
  const got = geoCountryCoords(ct);
  if (!got) { fail(`${ct} has no coordinates`); continue; }
  if (Math.abs(got[0] - lat) > 1.5 || Math.abs(got[1] - lng) > 1.5)
    fail(`${ct} is at ${got} but belongs near ${[lat, lng]}`);
  // Afghanistan and Taiwan genuinely sit inside the old band; the check above already
  // placed them, so only flag the ones that should be nowhere near it.
  if (!["Afghanistan", "Taiwan"].includes(ct) && inHashBand(got))
    fail(`${ct} is inside the old hash band ${got} -- that is the bug, not a fix`);
}

// 3. an unknown country is REPORTED, never drawn
const unknown = geoPlotPlan(["Ruritania", "India"]);
if (unknown.plotted.length !== 1 || unknown.plotted[0].ct !== "India")
  fail("an unknown country was still plotted");
if (!unknown.unlocated.includes("Ruritania"))
  fail("an unknown country vanished silently instead of being reported");
if (geoCountryCoords("Ruritania") !== null)
  fail("geoCountryCoords invented a position for an unknown country");
// the same name twice must give the same answer -- and that answer must be "no"
if (geoCountryCoords("Ruritania") !== geoCountryCoords("Ruritania"))
  fail("lookup is not deterministic");

// 4. continents are not points
if (plan.plotted.some((p) => p.ct === "Europe" || p.ct === "Africa"))
  fail("a continent row was pinned to a point");
if (!plan.regions.includes("Europe") || !plan.regions.includes("Africa"))
  fail("continent rows were dropped instead of reported");

// 5. empties do not throw and do not produce a default pin
for (const v of [null, undefined, ""]) {
  if (geoCountryCoords(v) !== null) fail(`geoCountryCoords(${JSON.stringify(v)}) returned a position`);
}
const empty = geoPlotPlan(null);
if (empty.plotted.length || empty.regions.length || empty.unlocated.length)
  fail("an empty country list produced entries");

// 6. aliases resolve to the same place as their canonical spelling
for (const [a, b] of [["UK", "United Kingdom"], ["USA", "United States"],
  ["UAE", "United Arab Emirates"], ["South Korea", "Korea"],
  ["Czech Republic", "Czechia"]]) {
  const x = geoCountryCoords(a), y = geoCountryCoords(b);
  if (!x || !y || x[0] !== y[0] || x[1] !== y[1])
    fail(`${a} and ${b} resolve to different places`);
}

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - geo map: 50 countries located, 2 continent rows reported, "
  + "unknown countries reported and never invented");
