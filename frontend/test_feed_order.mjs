/* The signal feed must be ordered by the date it PRINTS.
 *
 *     node test_feed_order.mjs
 *
 * The reported list read: Sep 2026, 11 Aug 2026, 30 Aug 2026, 11 Aug 2026, 20 Aug 2026,
 * 4 Aug 2026. Two separate faults produced it.
 *
 * First, buildFeed sorted on card.ago while the card printed signalDate(card, data),
 * which prefers the day-precision date held in the detail panel. Sorting one field and
 * showing another cannot look sorted except by accident.
 *
 * Second, the date comparator was month-precision (year*12 + month), so every August
 * date was the same number and the August cards fell back to whatever order the
 * secondary key gave them.
 *
 * The cards below carry the exact dates from that screenshot, with `ago` and the panel
 * date deliberately disagreeing the way production does.
 */
import { buildFeed, dateVal, signalDate } from "./src/lib/overview.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

/* --- dateVal: day precision, and month-only ordered against it --- */
const V = dateVal;
if (!(V("30 Aug 2026") > V("11 Aug 2026"))) fail("30 Aug must outrank 11 Aug");
if (!(V("11 Aug 2026") > V("4 Aug 2026"))) fail("11 Aug must outrank 4 Aug");
if (!(V("Sep 2026") > V("30 Aug 2026"))) fail("Sep 2026 must outrank all of August");
if (!(V("1 Sep 2026") > V("Sep 2026"))) fail("a dated September beats month-only September");
if (!(V("Jan 2027") > V("Dec 2026"))) fail("year rollover");
if (!(V("1d ago") > V("Sep 2026"))) fail("'1d ago' is newer than any printed date");
if (V("") !== 0 || V(null) !== 0) fail("empty date must be 0, not NaN");
if (!(V("2026-08-30") > V("2026-08-11"))) fail("ISO dates");

/* --- signalDate: the panel's day-precision date wins over the card's month --- */
const data = {
  details: {
    c1: { facts: [["Country", "Brazil"], ["Date", "2 Sep 2026"]] },
    c2: { facts: [["Date", "11 Aug 2026"]] },
    c3: { facts: [["Date", "30 Aug 2026"]] },
    c4: { facts: [["Date", "11 Aug 2026"]] },
    c5: { facts: [["Date", "20 Aug 2026"]] },
    c6: { facts: [["Date", "4 Aug 2026"]] },
    c7: { facts: [] },
  },
};
if (signalDate({ id: "c3", ago: "Aug 2026" }, data) !== "30 Aug 2026") {
  fail("panel date must win over card ago");
}
if (signalDate({ id: "c7", ago: "Sep 2026" }, data) !== "Sep 2026") {
  fail("ago is the fallback when the panel has no Date");
}

/* --- the feed itself, in the order the screenshot showed --- */
const cards = [
  { id: "c1", dir: "threat", ago: "Sep 2026", sec: [1, 2, 3], t: "Leonardo Centauro II" },
  { id: "c2", dir: "threat", ago: "Aug 2026", sec: [1, 2], t: "Otokar COBRA II" },
  { id: "c3", dir: "threat", ago: "Aug 2026", sec: [1], t: "BAE Archer 8x8" },
  { id: "c4", dir: "threat", ago: "Aug 2026", sec: [1], t: "Thales Minerva" },
  { id: "c5", dir: "threat", ago: "Aug 2026", sec: [1], t: "KONGSBERG PROTECTOR" },
  { id: "c6", dir: "threat", ago: "Aug 2026", sec: [1], t: "Anduril C-sUAS" },
  { id: "c7", dir: "watch", ago: "Sep 2026", sec: [1], t: "a watch signal" },
];
const cfg = { cards, groups: [{ n: 99, h: "All", s: "" }] };

const flat = buildFeed(cfg, "priority", data).groups.flatMap((g) => g.cards);
const seen = flat.map((c) => signalDate(c, data));
const want = ["2 Sep 2026", "30 Aug 2026", "20 Aug 2026", "11 Aug 2026", "11 Aug 2026",
              "4 Aug 2026", "Sep 2026"];
if (JSON.stringify(seen) !== JSON.stringify(want)) {
  fail("priority order\n    got  " + JSON.stringify(seen) +
       "\n    want " + JSON.stringify(want));
}

// threats still come before watch even though the watch card is the newest month
if (flat[flat.length - 1].dir !== "watch") fail("priority must still put threats first");

// and the printed rank must follow the sorted order, not the input order
if (flat[0].rank !== "01" || flat[1].rank !== "02") fail("ranks re-numbered after sort");

const rec = buildFeed(cfg, "recency", data).groups.flatMap((g) => g.cards);
const recSeen = rec.map((c) => signalDate(c, data));
// month-only 'Sep 2026' takes day 0, so it follows the dated 2 Sep and still leads
// every August date -- the rule dateVal documents, asserted here so it cannot drift
const recWant = ["2 Sep 2026", "Sep 2026", "30 Aug 2026", "20 Aug 2026", "11 Aug 2026",
                 "11 Aug 2026", "4 Aug 2026"];
if (JSON.stringify(recSeen) !== JSON.stringify(recWant)) {
  fail("recency order\n    got  " + JSON.stringify(recSeen) +
       "\n    want " + JSON.stringify(recWant));
}

if (bad) {
  console.log(`\n${bad} failure(s)`);
  process.exit(1);
}
console.log("ok - feed sorts on the date it prints, day-precision, threats first");
