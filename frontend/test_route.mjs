/* The URL hash is the app's only route, so it has to round-trip.
 *
 *     node test_route.mjs
 *
 * Found by driving the built app (2026-09-05): the router wrote every navigation with
 * history.replaceState and listened to nothing, so
 *
 *   - browser Back after Competitive -> Technology -> Innovation left the site: the
 *     session had one history entry;
 *   - editing the hash in the address bar of an open tab changed nothing on screen;
 *   - #p=technology&v=does-not-exist rendered the rail beside an empty pane, and
 *     because the route is also saved to localStorage it came back on every reload.
 *
 * parseRoute / routeHash are the pure half of the fix: AppState pushes a history entry
 * per navigation and applies popstate through parseRoute, so what these assert is what
 * Back, Forward, a pasted link and a saved route all resolve to. */
import assert from "node:assert/strict";
import { parseRoute, routeHash, isKnownView, DEFAULT_ROUTE } from "./src/lib/route.js";

/* a valid link resolves as written */
assert.deepEqual(parseRoute("#p=technology&v=innovation"), { pillar: "technology", view: "innovation", repaired: false });
assert.deepEqual(parseRoute("#p=market&v=tender"), { pillar: "market", view: "tender", repaired: false });

/* archived views are off the rail but still routed -- a saved link must keep working */
for (const v of ["gap-competitive", "awarded-tenders", "closed-tenders"]) {
  assert.equal(isKnownView(v), true, `${v} should still route`);
}
assert.equal(parseRoute("#p=competitive&v=gap-competitive").repaired, false);

/* an unknown view falls back to the PILLAR'S overview, flagged as repaired, so the
   shell never boots into a pane the switch cannot render */
assert.deepEqual(parseRoute("#p=technology&v=does-not-exist"), { pillar: "technology", view: "t-overview", repaired: true });
assert.deepEqual(parseRoute("#p=market&v=profile"), { pillar: "market", view: "m-overview", repaired: true }, "a view from another pillar is not this pillar's view");

/* an unknown pillar, a missing pair, or no hash at all: nothing to resolve */
assert.equal(parseRoute("#p=nope&v=overview"), null);
assert.equal(parseRoute("#p=technology"), null);
assert.equal(parseRoute(""), null);
assert.equal(parseRoute(null), null);
assert.equal(parseRoute("#foo=bar"), null);

/* the hash the app writes is the hash it reads */
for (const [p, v] of [["competitive", "overview"], ["technology", "innovation"], ["market", "closed-tenders"]]) {
  const h = routeHash(p, v);
  assert.equal(h, `#p=${p}&v=${v}`);
  assert.deepEqual(parseRoute(h), { pillar: p, view: v, repaired: false });
}

/* the fallback route is itself valid */
assert.deepEqual(parseRoute(routeHash(DEFAULT_ROUTE.pillar, DEFAULT_ROUTE.view)), { ...DEFAULT_ROUTE, repaired: false });

console.log("ok - route: valid and archived links resolve, unknown views repair to the pillar overview, unknown pillars resolve to nothing, hash round-trips");
