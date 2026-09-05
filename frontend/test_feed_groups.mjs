/* A feed group heading must describe the cards under it.
 *
 *     node test_feed_groups.mjs
 *
 * Reported: "Live opportunities are being displayed on all pages instead of only on the
 * native Live Opportunities page."
 *
 * The groups were cut by INDEX -- `cards.slice(idx, idx + g.n)`, n = 3 -- so the top
 * three cards of the ranking were captioned "Live Opportunities" whatever they were.
 * The priority sort orders threat, then watch, then fav, and "fav" IS the opportunity
 * direction, so the actual opportunities sorted LAST and could never appear under the
 * heading that names them, while emerging-demand signals routinely did.
 *
 * The fixture below is built to expose exactly that: 2 threats, 3 watch, 2 fav. Under
 * index grouping the first group is threat, threat, watch -- one mislabelled card and
 * both real opportunities missing. It is asserted to behave that way before the fix.
 */
import { buildFeed, cutGroupsByDirection } from "./src/lib/overview.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

const card = (id, dir) => ({ id, dir, ago: "01 Aug 2026", sec: "" });
const CARDS = [
  card("t1", "threat"), card("t2", "threat"),
  card("w1", "watch"), card("w2", "watch"), card("w3", "watch"),
  card("f1", "fav"), card("f2", "fav"),
];
const GROUPS = [
  { h: "Live Opportunities", n: 3, s: "open tenders KSSL can act on now",
    dirs: ["threat", "fav"] },
  { h: "Emerging Demand", n: 99, s: "signals to track", dirs: ["watch"] },
];

const feed = buildFeed({ cards: CARDS, groups: GROUPS }, "priority", {});
const g = (h) => feed.groups.find((x) => x.h === h);
const ids = (h) => (g(h) ? g(h).cards.map((c) => c.id).sort() : []);

// 1. the heading holds what it names
const live = ids("Live Opportunities");
if (live.join() !== "f1,f2,t1,t2")
  fail(`Live Opportunities holds ${live.join()||"nothing"}, expected the 2 threats and 2 favs`);
const emerging = ids("Emerging Demand");
if (emerging.join() !== "w1,w2,w3")
  fail(`Emerging Demand holds ${emerging.join()||"nothing"}, expected the 3 watch cards`);

// 2. no watch card is announced as an opportunity -- the reported defect
if (live.some((id) => id.startsWith("w")))
  fail("an emerging-demand card is captioned Live Opportunities");

// 3. nothing is lost or duplicated: a group split must be a partition
const all = feed.groups.flatMap((x) => x.cards.map((c) => c.id));
if (all.length !== CARDS.length) fail(`${all.length} cards across groups, ${CARDS.length} in`);
if (new Set(all).size !== all.length) fail("a card appears in two groups");
if (feed.total !== CARDS.length) fail(`total says ${feed.total}, dataset has ${CARDS.length}`);

// 4. a direction no group claims still reaches the reader via the last group
const odd = buildFeed(
  { cards: CARDS.concat([card("x1", "other")]), groups: GROUPS }, "priority", {});
const oddAll = odd.groups.flatMap((x) => x.cards.map((c) => c.id));
if (!oddAll.includes("x1"))
  fail("a card whose direction no group claims was dropped from the feed");

// 5. feeds that carry no `dirs` keep the old index behaviour -- competitive and
//    technology still rely on it, so this fix must not reach them
const plain = buildFeed(
  { cards: CARDS, groups: [{ h: "First", n: 3, s: "" }, { h: "Rest", n: 99, s: "" }] },
  "priority", {});
if (plain.groups[0].cards.length !== 3)
  fail(`index grouping changed: first group has ${plain.groups[0].cards.length}, expected 3`);
if (plain.groups[0].cards.map((c) => c.id).join() !== "t1,t2,w1")
  fail("index grouping no longer cuts by position");

// 6. and that untouched index behaviour IS the bug, which is why it had to change:
//    the first group is captioned Live Opportunities yet contains a watch card and
//    neither fav. If this assertion ever fails, the fixture stopped reproducing the
//    reported fault and the rest of this file proves nothing.
if (!plain.groups[0].cards.some((c) => c.dir === "watch")
  || plain.groups[0].cards.some((c) => c.dir === "fav"))
  fail("fixture no longer reproduces the index-grouping fault");

// 7. non-priority modes collapse to a single group and are unaffected
const rec = buildFeed({ cards: CARDS, groups: GROUPS }, "recency", {});
if (rec.groups.length !== 1)
  fail(`recency should be one group, got ${rec.groups.length}`);

// 8. THE SAME FAULT ON THE OTHER TWO PILLARS. Found 2026-09-05 by driving the built
//    app on the live-shape dump: every served technology card is dir=watch, and the
//    heading over all five of them read "Priority -- Capability Gaps -- rivals
//    advancing in KSSL categories" (n: 13, cut by index). With 254 cards the other
//    way round: 37 threats sat under "Capability-Frontier Moves". Case 5 above is
//    kept as written -- buildFeed's index fallback is unchanged -- and the fix is in
//    the WIRING: dataset.js now stamps `dirs` onto every pillar's priority groups
//    through cutGroupsByDirection, so the heading that names threats holds threats.
const TECH_GROUPS = [
  { n: 13, h: "Priority -- Capability Gaps", s: "rivals advancing" },
  { n: 99, h: "Capability-Frontier Moves", s: "trajectory" },
];
const allWatch = ["w1", "w2", "w3", "w4", "w5"].map((id) => card(id, "watch"));
// the fixture reproduces the fault under the untouched index cut
const faulty = buildFeed({ cards: allWatch, groups: TECH_GROUPS }, "priority", {});
if (!(faulty.groups[0] && faulty.groups[0].h.startsWith("Priority") && faulty.groups[0].cards.length === 5))
  fail("fixture no longer reproduces the fault: an all-watch feed should land under Priority when cut by index");
// the wired groups: the first group claims the threat direction, the last takes the rest
const wired = cutGroupsByDirection(TECH_GROUPS);
if (!Array.isArray(wired[0].dirs) || wired[0].dirs.join() !== "threat")
  fail(`first priority group should claim threat, claims ${JSON.stringify(wired[0].dirs)}`);
if (wired.length !== TECH_GROUPS.length || wired[0].h !== TECH_GROUPS[0].h || wired[0].n !== 13)
  fail("cutGroupsByDirection must keep heading, strapline and n");
if (TECH_GROUPS[0].dirs) fail("cutGroupsByDirection mutated its input");
const fixed = buildFeed({ cards: allWatch, groups: wired }, "priority", {});
if (fixed.groups.some((x) => x.h.startsWith("Priority")))
  fail("an all-watch feed still shows a Priority heading");
if (fixed.groups.flatMap((x) => x.cards).length !== 5) fail("cards lost when the first group is empty");
// and the many-threats shape: no threat may fall under the second heading
const many = [];
for (let i = 0; i < 20; i += 1) many.push(card(`t${i}`, "threat"));
many.push(card("w9", "watch"));
const big = buildFeed({ cards: many, groups: wired }, "priority", {});
const second = big.groups.find((x) => !x.h.startsWith("Priority"));
if (!second || second.cards.some((c) => c.dir === "threat"))
  fail("a threat card is captioned Capability-Frontier Moves");
if (big.groups[0].cards.length !== 20) fail(`Priority group holds ${big.groups[0].cards.length} of 20 threats: n must not cap it`);
// a config with one group, or none, is passed through
if (cutGroupsByDirection([]).length !== 0) fail("empty groups");
if (cutGroupsByDirection(null).length !== 0) fail("null groups");
if (cutGroupsByDirection([{ h: "Only", n: 99 }])[0].dirs) fail("a single group has nothing to split from and keeps taking everything");
// groups that already carry dirs (market) are left exactly as declared
const already = cutGroupsByDirection(GROUPS);
if (already[0].dirs.join() !== "threat,fav") fail("market's declared dirs were overwritten");

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - feed groups cut by content: headings hold what they name, "
  + "partition preserved, index grouping untouched where no dirs are declared, "
  + "competitive and technology priority groups wired by direction");
