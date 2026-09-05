/* The feed shows a handful; the full list below shows everything.
 *
 * Profile grew its feed by six per click with no ceiling (Profile.jsx:692) and
 * Products had no slice at all (Products.jsx:1042), so a competitor with 56
 * articles pushed every section under the feed off the page. These assert the
 * boundary, and that nothing is lost across it -- an article that leaves the feed
 * has to still be reachable, or the fix hides news instead of organising it.
 */
import { feedSplit, FEED_N } from "./src/lib/news.js";

let fail = 0;
const ck = (name, ok, d) => {
  console.log(`  ${name.padEnd(58)} ${ok ? "PASS" : "FAIL"}${d !== undefined && !ok ? "  " + JSON.stringify(d) : ""}`);
  if (!ok) fail++;
};

const mk = (n) => Array.from({ length: n }, (_, i) => ({ id: i, title: `a${i}` }));

ck("the feed is 5-8 items, as asked", FEED_N >= 5 && FEED_N <= 8, FEED_N);

const big = feedSplit(mk(56));
ck("56 articles put 6 in the feed", big.feed.length === 6, big.feed.length);
ck("the other 50 go below", big.rest.length === 50, big.rest.length);
ck("nothing is lost across the split",
   big.feed.length + big.rest.length === 56);
ck("the full list holds every article, feed included", big.all.length === 56);
ck("the feed keeps the NEWEST, in order",
   big.feed[0].id === 0 && big.feed[5].id === 5);
ck("the remainder continues where the feed stopped", big.rest[0].id === 6);

const small = feedSplit(mk(3));
ck("3 articles need no second section",
   small.feed.length === 3 && small.rest.length === 0);
const none = feedSplit([]);
ck("no articles is not an error",
   none.feed.length === 0 && none.rest.length === 0 && none.total === 0);
ck("a missing list is not an error", feedSplit(undefined).total === 0);
ck("exactly FEED_N articles leaves nothing below",
   feedSplit(mk(FEED_N)).rest.length === 0);
ck("one more than FEED_N puts exactly one below",
   feedSplit(mk(FEED_N + 1)).rest.length === 1);

console.log(fail ? `\n${fail} FAILED` : "\nall checks passed");
process.exit(fail ? 1 : 0);
