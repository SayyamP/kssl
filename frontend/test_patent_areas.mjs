/* The Patents page's "By technology field" lens must list the fields the filings are
 * indexed under.
 *
 *     node test_patent_areas.mjs
 *
 * FOUND 2026-09-05 (interaction sweep, reference dataset): 21 filings indexed by
 * rival, and the field lens listed nine fields every one reading 0. The lens listed
 * PATENTS.techAreas -- the ui_config vocabulary ("Loitering munitions", "Missiles &
 * seekers") -- while the filings are indexed in PATENTS.byTechnology under the areas
 * the harvest assigned ("Unmanned Systems & Drones", "Missiles & Precision
 * Guidance"). Two vocabularies; the lens read the one with no filings in it, so the
 * whole lens was scaffolding around nothing while the other lens held 21 records.
 *
 * What this pins, on the pure helper the page now reads:
 *   1. when filings are indexed by technology, the lens lists THOSE keys, most-filed
 *      first, and every one carries at least one record;
 *   2. with no filings indexed, it falls back to the configured areas, then to the
 *      tracked technology categories -- so the lens still names real fields, each
 *      with its own empty state;
 *   3. nothing is invented: a key the data does not hold is never listed.
 */
import { patentAreas } from "./src/lib/patents.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

const techCats = [{ id: "a", name: "Cat A" }, { id: "b", name: "Cat B" }];
const withFilings = {
  techAreas: ["Loitering munitions", "Missiles & seekers"],
  byTechnology: {
    "Small Arms": { records: [{ id: 1 }] },
    "Unmanned Systems & Drones": { records: [{ id: 2 }, { id: 3 }, { id: 4 }] },
    "Empty Area": { records: [] },
  },
};

const got = patentAreas(withFilings, techCats);
if (JSON.stringify(got) !== JSON.stringify(["Unmanned Systems & Drones", "Small Arms"]))
  fail(`with filings indexed, expected the indexed areas most-filed first, got ${JSON.stringify(got)}`);
if (got.includes("Loitering munitions")) fail("a configured area with no filing must not be listed while filings exist elsewhere");
if (got.includes("Empty Area")) fail("an indexed key with zero records is not a field with filings");

const noFilings = { techAreas: ["Loitering munitions"], byTechnology: {} };
if (JSON.stringify(patentAreas(noFilings, techCats)) !== JSON.stringify(["Loitering munitions"]))
  fail(`with nothing indexed, expected the configured areas, got ${JSON.stringify(patentAreas(noFilings, techCats))}`);
if (JSON.stringify(patentAreas({}, techCats)) !== JSON.stringify(["Cat A", "Cat B"]))
  fail(`with nothing configured either, expected the tracked categories, got ${JSON.stringify(patentAreas({}, techCats))}`);
if (patentAreas(null, []).length !== 0) fail("no data at all lists nothing");

if (bad) { console.log(`test_patent_areas: ${bad} failure(s)`); process.exit(1); }
console.log("test_patent_areas: ok -- the field lens lists the fields the filings are indexed under");
