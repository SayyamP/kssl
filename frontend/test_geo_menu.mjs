/* The Geo Footprint's competitor lookup must offer only competitors with a footprint.
 *
 *     node test_geo_menu.mjs
 *
 * FOUND 2026-09-05 (interaction sweep, live dataset): the count line said
 * "77 competitors · 45 markets"; the Competitor dropdown offered 174 rows, 97 of them
 * badged "0 mkts". Picking one opened a detail panel with nothing in it. The menu was
 * data.geoComps unfiltered -- the whole roster -- while the count line counted the
 * companies the footprint data actually covers. An option is a promise of rows.
 *
 * What this pins, on the pure helper the page now reads:
 *   1. a competitor with no served market is not offered;
 *   2. with a country picked, only competitors present in that country are offered;
 *   3. the query narrows by name, case-insensitively;
 *   4. the number offered equals the number the count line counts.
 */
import { geoLookupCompetitors, geoCoveredCompetitors } from "./src/lib/geo.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

const data = {
  geoComps: [
    { id: "a", name: "Alpha Arms" },
    { id: "b", name: "Bravo Systems" },
    { id: "c", name: "Charlie Corp" },
    { id: "z", name: "Zero Footprint Ltd" },
  ],
  geoData: {
    a: { India: [{ name: "x" }], France: [{ name: "y" }] },
    b: { India: [{ name: "q" }] },
    c: {},
  },
};

const ids = (rows) => rows.map((r) => r.id).sort().join(",");

if (ids(geoLookupCompetitors(data, null, "")) !== "a,b") fail(`no country, no query -> ${ids(geoLookupCompetitors(data, null, ""))}, expected a,b (c has an empty footprint, z has none)`);
if (ids(geoLookupCompetitors(data, "France", "")) !== "a") fail(`France -> ${ids(geoLookupCompetitors(data, "France", ""))}, expected a`);
if (ids(geoLookupCompetitors(data, null, "BRAVO")) !== "b") fail(`query BRAVO -> ${ids(geoLookupCompetitors(data, null, "BRAVO"))}, expected b`);
if (ids(geoLookupCompetitors(data, "India", "alpha")) !== "a") fail(`India + alpha -> ${ids(geoLookupCompetitors(data, "India", "alpha"))}, expected a`);
if (geoLookupCompetitors(data, null, "zzqq").length !== 0) fail("a miss must be empty, not the whole roster");
if (geoCoveredCompetitors(data).length !== geoLookupCompetitors(data, null, "").length) fail("the count line and the open menu must count the same companies");
if (geoLookupCompetitors({ geoComps: [], geoData: {} }, null, "").length !== 0) fail("an empty dataset offers nothing");

if (bad) { console.log(`test_geo_menu: ${bad} failure(s)`); process.exit(1); }
console.log("test_geo_menu: ok -- the competitor lookup offers only companies with a served footprint");
