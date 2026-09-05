/* Deep links: the view in a pasted or hand-edited URL must resolve to a page.
 *
 *     node test_route.mjs
 *
 * FOUND 2026-09-05 (interaction sweep): #p=competitive&v=nonsense booted into a
 * permanently blank pane -- rail drawn, no row active, heading fell back to
 * "Competitive Intelligence", nothing beneath it. getInitialAppState validated the
 * pillar and never the view, and Layout's switch has `default: null`. The same route
 * was then saved to localStorage, so the blank pane came back on every later visit
 * until the reader clicked a rail row. A hand edit of the hash in the address bar was
 * ignored outright: the hash was read once at boot and no hashchange listener existed.
 *
 * What this pins, on the pure resolver AppState now uses:
 *   1. a known view in a known pillar resolves as written, archived routes included;
 *   2. an unknown view resolves to that pillar's overview, never to nothing;
 *   3. an unknown pillar falls through to the saved route, then to the default;
 *   4. a saved route with a stale view also lands on its pillar's overview;
 *   5. a view that belongs to another pillar is corrected to the pillar it belongs to.
 */
import assert from "node:assert/strict";
import { parseRoute, resolveRoute, DEFAULT_ROUTE } from "./src/lib/route.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };
const same = (a, b) => a && b && a.pillar === b.pillar && a.view === b.view;

const cases = [
  ["#p=competitive&v=profile", null, { pillar: "competitive", view: "profile" }, "a rail view resolves as written"],
  ["#p=market&v=awarded-tenders", null, { pillar: "market", view: "awarded-tenders" }, "an archived route still resolves"],
  ["#p=competitive&v=gap-competitive", null, { pillar: "competitive", view: "gap-competitive" }, "gap-competitive still resolves"],
  ["#p=competitive&v=nonsense", null, { pillar: "competitive", view: "overview" }, "an unknown view lands on the pillar overview"],
  ["#p=market&v=", null, { pillar: "market", view: "m-overview" }, "an empty view lands on the pillar overview"],
  ["#p=nowhere&v=profile", { pillar: "market", view: "tender" }, { pillar: "competitive", view: "profile" }, "a known view under an unknown pillar lands on the view's own pillar"],
  ["#p=nowhere&v=alsonowhere", { pillar: "market", view: "tender" }, { pillar: "market", view: "tender" }, "an unknown pillar and view fall through to the saved route"],
  ["", { pillar: "market", view: "stale-view" }, { pillar: "market", view: "m-overview" }, "a saved route with a stale view lands on its overview"],
  ["", { pillar: "bogus", view: "overview" }, DEFAULT_ROUTE, "a saved route with a bad pillar falls to the default"],
  ["", null, DEFAULT_ROUTE, "nothing saved, nothing in the hash: the default"],
  ["#p=competitive&v=tender", null, { pillar: "market", view: "tender" }, "a view under the wrong pillar is corrected to its own"],
  ["#v=geo", null, { pillar: "competitive", view: "geo" }, "a hash naming only the view still resolves"],
];

cases.forEach(([hash, saved, want, why]) => {
  const got = resolveRoute(hash, saved);
  if (!same(got, want)) fail(`${why}: ${hash || "(no hash)"} + saved ${JSON.stringify(saved)} -> ${JSON.stringify(got)}, wanted ${JSON.stringify(want)}`);
});

// parseRoute alone: null for anything that is not a route, so a hashchange to
// "#section" on the page does not navigate anywhere
if (parseRoute("#foo") !== null) fail("parseRoute('#foo') should be null");
if (parseRoute("") !== null) fail("parseRoute('') should be null");
if (parseRoute(null) !== null) fail("parseRoute(null) should be null");

if (bad) { console.log(`test_route: ${bad} failure(s)`); process.exit(1); }
console.log("test_route: ok -- every deep link resolves to a page, and a bad one lands on an overview");
