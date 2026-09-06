/* Signal cards are sequenced by SEVERITY then RECENCY, everywhere, by ONE comparator.
 *
 *     node test_card_order.mjs
 *
 * The operator: "based on threat severity do sequencing of signal card everywhere where
 * severity is high and recent show it first".
 *
 * Three things had to be true and none of them was.
 *
 * 1. THERE WAS NO SEVERITY. serving.signal_card has no such column; the feed sorted on
 *    direction and date, so 74 threat cards arrived in an order nobody chose. Severity is
 *    now derived by the backend (threat_gate.severity_of) and travels on the card as
 *    `severityRank` -- an integer, already in sort position.
 *
 * 2. THE BROWSER MUST NOT DERIVE IT AGAIN. This repo has already paid for a number
 *    computed on both sides: the frontend silently overwrote the served value and a 1-0
 *    winner was scored as behind. So the test below hands the comparator a card whose
 *    `severity` word and `severityRank` number DISAGREE, and requires the number to win.
 *    Nothing in lib/ may re-derive a rank from the word.
 *
 * 3. "EVERYWHERE" MEANS EVERYWHERE. The overview feed and a competitor's own profile are
 *    two different render paths over the same rows, and the profile list was in serve
 *    order -- signal_card.ord, a storage order. Both now call compareCards.
 */
import {
  buildFeed,
  compareCards,
  severityRankOf,
  SEVERITY_UNASSESSED_RANK,
  NO_DATE_LABEL,
} from "./src/lib/overview.js";
import { buildProfile } from "./src/lib/profile.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };
const ids = (list) => list.map((c) => c.id).join(",");

/* Severity ranks as the backend serves them (threat_gate.SEVERITY_RANK):
   high 0, medium 1, low 2, not assessed 3. */
const HIGH = 0, MED = 1, LOW = 2, NONE = 3;

const card = (id, over = {}) => ({
  id,
  dir: "threat",
  company: "Rheinmetall",
  sec: [1],
  ...over,
});

/* ---- 1. severity leads, recency breaks the tie ------------------------------- */
const cards = [
  card("low-new", { severity: "low", severityRank: LOW, ago: "5 Sep 2026" }),
  card("high-old", { severity: "high", severityRank: HIGH, ago: "1 Aug 2026" }),
  card("high-new", { severity: "high", severityRank: HIGH, ago: "4 Sep 2026" }),
  card("med-new", { severity: "medium", severityRank: MED, ago: "5 Sep 2026" }),
  card("unassessed-newest", { severity: null, severityRank: NONE, ago: "6 Sep 2026" }),
];
const data = { details: {} };
const cfg = { cards, groups: [{ n: 99, h: "All", s: "" }] };
const feed = buildFeed(cfg, "priority", data).groups.flatMap((g) => g.cards);
const want = "high-new,high-old,med-new,low-new,unassessed-newest";
if (ids(feed) !== want) fail(`priority order\n    got  ${ids(feed)}\n    want ${want}`);

/* The newest card in the set is the one we could not grade, and it must NOT lead the
   feed. "We did not measure this" is not a reason to show it first, and it is not a
   reason to hide it either -- it is last, and it is still there. */
if (feed[feed.length - 1].id !== "unassessed-newest") {
  fail("an ungraded card must sort last, not by its date alone");
}
if (feed.length !== cards.length) fail("no card may be dropped by the ordering");

/* ---- 2. 'not assessed' is not 'low' ------------------------------------------ */
if (severityRankOf({ severityRank: LOW }) === SEVERITY_UNASSESSED_RANK) {
  fail("low and 'not assessed' must not share a rank");
}
if (severityRankOf({}) !== SEVERITY_UNASSESSED_RANK) {
  fail("a card with no served rank is UNASSESSED, not high");
}
if (severityRankOf({ severityRank: null }) !== SEVERITY_UNASSESSED_RANK) {
  fail("a null rank is unassessed, not 0");
}
/* A frontend-synthesised card (dataset.js builds market cards out of tenders) carries no
   rank at all. It must not be promoted to the top of the feed by a missing field. */
const synth = [card("served-high", { severity: "high", severityRank: HIGH, ago: "1 Aug 2026" }),
               card("synthesised", { ago: "6 Sep 2026" })];
const sorted = synth.slice().sort(compareCards(data));
if (sorted[0].id !== "served-high") fail("a card with no severity must not lead a graded one");

/* ---- 3. the SERVED number decides, not the word ------------------------------ */
/* If anything in lib/ ever re-derives a rank from `severity`, this pair flips. */
const disagree = [
  card("word-says-high", { severity: "high", severityRank: LOW, ago: "1 Sep 2026" }),
  card("word-says-low", { severity: "low", severityRank: HIGH, ago: "1 Sep 2026" }),
].sort(compareCards(data));
if (disagree[0].id !== "word-says-low") {
  fail("the served severityRank must win over the display word -- the frontend must " +
       "not recompute the rank it was given");
}

/* ---- 4. direction still leads ------------------------------------------------ */
const mixed = [
  card("watch-high", { dir: "watch", severity: "high", severityRank: HIGH, ago: "6 Sep 2026" }),
  card("threat-low", { severity: "low", severityRank: LOW, ago: "1 Aug 2026" }),
].sort(compareCards(data));
if (mixed[0].id !== "threat-low") fail("a threat still outranks a watch");

/* ---- 5. an undated card sorts last of its band, and says so ------------------ */
const undated = [
  card("no-date", { severity: "high", severityRank: HIGH, ago: "" }),
  card("dated", { severity: "high", severityRank: HIGH, ago: "1 Jan 2020" }),
].sort(compareCards(data));
if (undated[0].id !== "dated") {
  fail("a card with no date must sort below a dated one, not as though it were today");
}
if (NO_DATE_LABEL !== "date not known") fail("the undated card needs a word for it");

/* ---- 6. EVERYWHERE: the profile list uses the same comparator ---------------- */
const dataset = {
  details: {},
  competitors: { rheinmetall: { name: "Rheinmetall", products: [], partners: [] } },
  competitiveCards: cards,
  marketCards: [],
  techCards: [],
  matchups: {},
  innovations: {},
  geoPresence: [],
  companySources: {},
};
const profile = buildProfile(dataset, "rheinmetall");
if (ids(profile.cards) !== want) {
  fail(`the profile card list must use the same order as the feed\n` +
       `    got  ${ids(profile.cards)}\n    want ${want}`);
}

/* ---- 7. the other sequence modes end in the same comparator ------------------ */
/* "Most recent" is a different lead key, not a different definition of worse: two cards
   published the same day still order by severity. */
const sameDay = [
  card("sd-low", { severity: "low", severityRank: LOW, ago: "5 Sep 2026" }),
  card("sd-high", { severity: "high", severityRank: HIGH, ago: "5 Sep 2026" }),
];
const rec = buildFeed({ cards: sameDay, groups: [{ n: 99, h: "All", s: "" }] },
                      "recency", data).groups.flatMap((g) => g.cards);
if (rec[0].id !== "sd-high") fail("severity must still break a tie inside 'most recent'");

if (bad) {
  console.log(`\n${bad} failure(s)`);
  process.exit(1);
}
console.log("ok - one comparator: severity then recency, served rank never recomputed, " +
            "unassessed is not low and sorts last, feed and profile agree");
