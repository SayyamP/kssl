/* The feed pager: page boundaries, and the page surviving a reload or a detour.
 *
 *     node test_feed_page_boundaries.mjs
 *
 * Hermetic -- a 123-card fixture, no dataset dump -- so it can gate the image, where
 * test_feed_pagination.mjs (real data) cannot.
 *
 * FE 29, "pagination is broken / not maintained properly". Two halves:
 *
 *  1. BOUNDARIES. Fifty cards a page, so 123 cards is pages of 50 / 50 / 23. Card 50 is
 *     the last on page 1 and card 51 the first on page 2 -- not 49/50, not 51/52 -- and
 *     the footer range ends at 123, never at 150. A group split by a page edge carries
 *     its header onto the next page. Every card is visited exactly once.
 *
 *  2. MAINTAINED. `page` was React state and nothing else, so a reload, or a detour to
 *     Competitor and back, put the reader on page 1 again: the route remembered the
 *     pillar and the view but not the page. readFeedPage / writeFeedPage remember it
 *     per pillar, and only for the same filter it was saved under -- a page saved on
 *     "All" is not restored onto "Threat", which may be one page long.
 */
import assert from "node:assert/strict";
import {
  buildFeed,
  paginateFeed,
  readFeedPage,
  writeFeedPage,
  FEED_PAGE_SIZE,
} from "./src/lib/overview.js";

assert.equal(FEED_PAGE_SIZE, 50, "the boundaries below are written for 50 a page");

/* 123 cards: 30 threats then 93 watch. Priority groups: 6 + the rest, like production. */
const N = 123;
const cards = Array.from({ length: N }, (_, i) => ({
  id: `c${i + 1}`,
  dir: i < 30 ? "threat" : "watch",
  ago: "Aug 2026",
  sec: [],
  title: `Signal ${i + 1}`,
  sowhat: "",
}));
const cfg = {
  cards,
  groups: [
    { n: 6, h: "Priority", s: "first six" },
    { n: 99, h: "Movement", s: "the rest" },
  ],
};
const feed = buildFeed(cfg, "priority", { details: {} });
const ids = (view) => view.groups.flatMap((g) => g.cards.map((c) => c.id));

/* ---- 1. boundaries ---- */
const p1 = paginateFeed(feed.groups, null, 1);
assert.equal(p1.pageCount, 3, "123 cards is three pages");
assert.equal(p1.from, 1);
assert.equal(p1.to, 50);
assert.equal(ids(p1).length, 50);
assert.equal(ids(p1)[49], "c50", "card 50 is the last card on page 1");
// the priority group is 6 cards and the movement group starts on the same page
assert.deepEqual(p1.groups.map((g) => [g.h, g.cards.length]), [["Priority", 6], ["Movement", 44]]);

const p2 = paginateFeed(feed.groups, null, 2);
assert.equal(p2.from, 51);
assert.equal(p2.to, 100);
assert.equal(ids(p2)[0], "c51", "card 51 opens page 2");
assert.equal(ids(p2)[49], "c100");
// the group that was split by the page edge carries its header onto this page
assert.deepEqual(p2.groups.map((g) => [g.h, g.cards.length]), [["Movement", 50]]);

const p3 = paginateFeed(feed.groups, null, 3);
assert.equal(p3.from, 101);
assert.equal(p3.to, 123, "the last page ends at the corpus, not at a full page");
assert.equal(ids(p3).length, 23);
assert.equal(ids(p3)[22], "c123");

// every card once, in order, across the three pages
const walked = [...ids(p1), ...ids(p2), ...ids(p3)];
assert.deepEqual(walked, cards.map((c) => c.id));

// pageOf agrees with the boundaries above
assert.equal(p1.pageOf("c50"), 1);
assert.equal(p1.pageOf("c51"), 2);
assert.equal(p1.pageOf("c100"), 2);
assert.equal(p1.pageOf("c101"), 3);
assert.equal(p1.pageOf("c123"), 3);
assert.equal(p1.pageOf("nope"), null);

// out of range clamps to a real page rather than a blank feed
assert.equal(paginateFeed(feed.groups, null, 0).page, 1);
assert.equal(paginateFeed(feed.groups, null, 99).page, 3);
assert.equal(paginateFeed(feed.groups, null, undefined).page, 1);

// exactly one full page is ONE page, not one page and an empty second
const fifty = buildFeed({ cards: cards.slice(0, 50), groups: cfg.groups }, "priority", { details: {} });
assert.equal(paginateFeed(fifty.groups, null, 1).pageCount, 1);
assert.equal(paginateFeed(fifty.groups, null, 1).to, 50);
const fiftyOne = buildFeed({ cards: cards.slice(0, 51), groups: cfg.groups }, "priority", { details: {} });
assert.equal(paginateFeed(fiftyOne.groups, null, 1).pageCount, 2);
assert.equal(paginateFeed(fiftyOne.groups, null, 2).from, 51);
assert.equal(paginateFeed(fiftyOne.groups, null, 2).to, 51);

// a filter re-pages the kept set: 30 threats is one page, and the footer says 30
const threats = paginateFeed(feed.groups, (c) => c.dir === "threat", 1);
assert.equal(threats.pageCount, 1);
assert.equal(threats.shown, 30);
assert.equal(threats.to, 30);
// 93 watch cards: 50 + 43, and page 2 opens on the 51st WATCH card, which is c81
const watch2 = paginateFeed(feed.groups, (c) => c.dir === "watch", 2);
assert.equal(watch2.pageCount, 2);
assert.equal(ids(watch2)[0], "c81");
assert.equal(watch2.to, 93);

// an empty result is page 1 of 1 with a 0-0 range, never "1-0"
const none = paginateFeed(feed.groups, () => false, 3);
assert.equal(none.page, 1);
assert.equal(none.from, 0);
assert.equal(none.to, 0);

/* ---- 2. the page is maintained ---- */
// a Storage-shaped fake; sessionStorage in the browser
const store = (() => {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
  };
})();

// nothing saved yet -> page 1
assert.equal(readFeedPage(store, "competitive", "all"), 1);

// saved on this pillar under this filter -> restored
writeFeedPage(store, "competitive", "all", 3);
assert.equal(readFeedPage(store, "competitive", "all"), 3, "the page survives a remount");

// another pillar is another feed
assert.equal(readFeedPage(store, "market", "all"), 1);
writeFeedPage(store, "market", "all", 2);
assert.equal(readFeedPage(store, "competitive", "all"), 3, "pillars do not share a page");
assert.equal(readFeedPage(store, "market", "all"), 2);

// a different filter is a different list -- do not land page 3 on a one-page filter
assert.equal(readFeedPage(store, "competitive", "threat"), 1);

// garbage in storage is page 1, not NaN and not a throw
store.setItem("kssl_feed_page", "{not json");
assert.equal(readFeedPage(store, "competitive", "all"), 1);
store.setItem("kssl_feed_page", JSON.stringify({ competitive: { key: "all", page: -4 } }));
assert.equal(readFeedPage(store, "competitive", "all"), 1);
store.setItem("kssl_feed_page", JSON.stringify({ competitive: { key: "all", page: "7" } }));
assert.equal(readFeedPage(store, "competitive", "all"), 7);

// no storage at all (private mode throws on access) -> page 1, no throw
assert.equal(readFeedPage(null, "competitive", "all"), 1);
assert.doesNotThrow(() => writeFeedPage(null, "competitive", "all", 2));
const throwing = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
assert.equal(readFeedPage(throwing, "competitive", "all"), 1);
assert.doesNotThrow(() => writeFeedPage(throwing, "competitive", "all", 2));

// a restored page beyond the corpus is clamped by the pager, not shown blank
writeFeedPage(store, "competitive", "all", 9);
assert.equal(paginateFeed(feed.groups, null, readFeedPage(store, "competitive", "all")).page, 3);

console.log("ok - page edges at 50/51 and 100/101, last page ends at the corpus, page remembered per pillar and filter");
