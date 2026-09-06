/* The trail, the reprints and the patents, against the LIVE dataset.
 *
 *     KSSL_DATASET=/path/to/dataset.json node test_profile_live_render.mjs
 *
 * Every hermetic check on this work passes with three invented articles. The shapes
 * that matter only exist on deployed data: 61 Rheinmetall articles in 30 threads with
 * 8 reprints, 1,157 patents over 24 companies, and rows whose optional fields the
 * backend OMITS rather than sends as null. "Presence is not shape" has blanked this
 * dashboard twice and a fixture said it was fine both times.
 *
 * Skipped, loudly, without a dump -- so it sits beside the hermetic checks without
 * needing one in the Docker build context. Run it against staging before believing a
 * deploy.
 */
import { readFileSync } from "node:fs";
import { companyNews, collapseThreads, feedSplit, FEED_N } from "./src/lib/news.js";
import { wireDataset } from "./src/lib/dataset.js";

const path = process.env.KSSL_DATASET;
if (!path) {
  console.log("SKIP  test_profile_live_render: set KSSL_DATASET to a dataset dump");
  process.exit(0);
}

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };
const ok = (m) => console.log("  ok   " + m);

const d = wireDataset(JSON.parse(readFileSync(path, "utf8")));

/* ---- the news the trail is built from ----------------------------------- */
const cids = Object.keys(d.competitorNews || {});
ok(`${cids.length} companies carry news`);

let threaded = 0, reprints = 0, trails = 0, biggest = 0, biggestCid = null;
for (const cid of cids) {
  const arts = companyNews(d, cid);
  const collapsed = collapseThreads(arts);

  /* NOTHING MAY BE LOST ACROSS THE COLLAPSE -- on the real feed, not three rows.
     The feed shows a story once; the full News section below shows every article.
     An article reachable from neither is simply gone, which is the one outcome
     capping the feed was supposed to prevent. */
  const seen = new Set();
  for (const a of collapsed) {
    seen.add(a.url);
    for (const t of a.trail || []) {
      seen.add(t.url);
      for (const x of t.alsoIn || []) seen.add(x.url);
    }
    for (const x of a.alsoIn || []) seen.add(x.url);
    if ((a.trail || []).length) trails += 1;
    /* Each trail row renders a date and a headline. A missing `ago` prints
       "undefined" beside a real story. */
    for (const t of a.trail || []) {
      if (typeof t.ago !== "string") fail(`${cid}: a trail entry has no rendered date`);
      if (!t.title) fail(`${cid}: a trail entry has no title`);
    }
  }
  const lost = arts.filter((a) => a.url && !seen.has(a.url));
  if (lost.length) fail(`${cid}: ${lost.length} article(s) unreachable after the collapse`);

  threaded += arts.filter((a) => a.storyKey).length;
  reprints += arts.filter((a) => a.duplicateOfUrl).length;
  if (arts.length > biggest) { biggest = arts.length; biggestCid = cid; }

  if (feedSplit(collapsed).feed.length > FEED_N)
    fail(`${cid}: the feed is not capped`);
}

if (threaded > 0) ok(`${threaded} threaded articles, ${reprints} reprints, ${trails} trails`);
else fail("nothing on the live dataset is threaded -- the columns are not reaching the page");
ok(`largest feed: ${biggestCid}, ${biggest} articles, capped at ${FEED_N}`);

/* A thread must never be one article: that is a label with nothing behind it. */
const sizes = {};
for (const cid of cids)
  for (const a of companyNews(d, cid))
    if (a.storyKey) sizes[cid + "|" + a.storyKey] = (sizes[cid + "|" + a.storyKey] || 0) + 1;
const singles = Object.entries(sizes).filter(([, n]) => n < 2);
if (singles.length) fail(`${singles.length} thread(s) hold a single article: ${singles.slice(0, 4).map(([k]) => k)}`);
else ok(`${Object.keys(sizes).length} threads, none of them a thread of one`);

/* ---- patents reach a competitor ----------------------------------------- */
const P = d.PATENTS || {};
const total = Object.values(P.byArea || {}).reduce((n, v) => n + v.length, 0);
const placed = Object.values(P.byCompetitor || {})
  .reduce((n, v) => n + (v.records || []).length, 0);
if (total) {
  ok(`${total} patents served, ${placed} placed under a competitor`);
  if (placed < total)
    fail(`${total - placed} patent(s) belong to no competitor the page can show`);
  const ids = new Set();
  Object.values(P.byCompetitor || {}).forEach((v) =>
    (v.records || []).forEach((r) => ids.add(r.id)));
  if (ids.size !== placed)
    fail(`${placed - ids.size} patent(s) are placed under more than one competitor`);
  else ok("no patent is counted twice");
} else {
  console.log("  --   no patents in this dump");
}

console.log(bad ? `\n${bad} FAILED` : "\nall checks passed");
process.exit(bad ? 1 : 0);
