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
import { buildFeed } from "./src/lib/overview.js";

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

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - feed groups cut by content: headings hold what they name, "
  + "partition preserved, index grouping untouched where no dirs are declared");
