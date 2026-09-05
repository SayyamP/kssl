/* An empty feed must say which control emptied it.
 *
 *     node test_feed_empty_note.mjs
 *
 * FOUND 2026-09-05 (interaction sweep): typing a query that matched nothing into the
 * feed's "Filter cards..." box -- or into the global search while on the overview --
 * showed "— no signals served yet —", the served-nothing message. The note looked
 * only at the tile and the direction pill; the two search boxes, which were added
 * later, were never part of the decision. A reader who mistyped was told the pipeline
 * had produced nothing.
 *
 * What this pins: the note names the query when a query is what emptied the feed,
 * names the filter when a tile or pill did, and says "served yet" only when nothing
 * is filtering at all.
 */
import { emptyFeedNote } from "./src/lib/overview.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

const cases = [
  [{}, /served yet/, "no filter, no query: a served-nothing state"],
  [{ dirFilter: "all" }, /served yet/, "the All pill is not a filter"],
  [{ dirFilter: "threat" }, /match this filter/, "a direction pill"],
  [{ tile: "threat" }, /match this filter/, "a tile"],
  [{ query: "zzqq" }, /zzqq/, "the feed search box names its query"],
  [{ globalQuery: "drone" }, /drone/, "the global search names its query"],
  [{ query: "zzqq", dirFilter: "threat" }, /zzqq/, "a query outranks the pill in the note: it is the narrower cut"],
  [{ query: "   " }, /served yet/, "whitespace is not a query"],
];

cases.forEach(([args, want, why]) => {
  const got = emptyFeedNote(args);
  if (typeof got !== "string" || !want.test(got)) fail(`${why}: ${JSON.stringify(args)} -> ${JSON.stringify(got)}`);
  if (/served yet/.test(got) && (args.query || "").trim()) fail(`${why}: a query emptied the feed but the note blames the pipeline`);
});

if (bad) { console.log(`test_feed_empty_note: ${bad} failure(s)`); process.exit(1); }
console.log("test_feed_empty_note: ok -- an empty feed names the control that emptied it");
