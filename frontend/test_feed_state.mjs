/* The overview feed's small state rules, each found broken by driving the built app
 * on 2026-09-05 and each pure enough to pin under node.
 *
 *     node test_feed_state.mjs
 *
 * 1. A global-search hit on a TECHNOLOGY or MARKET signal landed on the right pillar
 *    and opened nothing: Overview.jsx took its pending payload under the literal view
 *    name "overview", which is the competitive pillar's view only. The three overview
 *    views and the view the search routes to must be the same table.
 * 2. A feed search that matched nothing said "no signals served yet" -- the message
 *    for an EMPTY CORPUS -- because the empty-state text looked only at the tile and
 *    the direction filter.
 * 3. The Watch tile's count line read "13 of 26 signals ·" with nothing after the dot:
 *    TILE_LABELS carried no entry for the tile's `act`.
 * 4. The sequence select was React state only, so a reload put the reader back on
 *    "Priority" -- and since the remembered page is keyed by the sequence, the page
 *    that survived the reload was page 1 of a sequence they had not chosen. */
import assert from "node:assert/strict";
import { OVERVIEW_VIEW } from "./src/lib/route.js";
import { searchDataset } from "./src/lib/search.js";
import { emptyNote, TILE_LABELS, readFeedSeq, writeFeedSeq, SEQ_OPTIONS } from "./src/lib/overview.js";

/* 1. the search routes a signal to the view its pillar's Overview answers pending for */
{
  const data = {
    competitors: {}, matchups: {}, tenders: [], techCats: [], innovations: {},
    competitiveCards: [{ id: "c1", title: "alpha signal" }],
    marketCards: [{ id: "m1", title: "alpha tender" }],
    techCards: [{ id: "t1", title: "alpha shell" }],
  };
  const res = searchDataset(data, "alpha");
  const sig = res.groups.find((g) => g.key === "signals");
  assert.ok(sig && sig.hits.length === 3, "fixture: three signal hits");
  for (const h of sig.hits) {
    assert.equal(h.target.view, OVERVIEW_VIEW[h.target.pillar], `${h.target.pillar}: search routes to ${h.target.view}, the feed takes pending for ${OVERVIEW_VIEW[h.target.pillar]}`);
  }
  assert.deepEqual(Object.keys(OVERVIEW_VIEW).sort(), ["competitive", "market", "technology"]);
}

/* 2. the empty state names the cause */
{
  assert.match(emptyNote({}), /served/, "no filter, no query: the corpus is empty");
  assert.match(emptyNote({ dirFilter: "threat" }), /filter/);
  assert.match(emptyNote({ tile: "threat" }), /filter/);
  assert.match(emptyNote({ query: "zqx" }), /search|match/);
  assert.doesNotMatch(emptyNote({ query: "zqx" }), /served/, "a search miss must not read as an empty corpus");
  assert.doesNotMatch(emptyNote({ dirFilter: "all", query: "" }), /filter|search/, "the reset door plus no query is the corpus state");
}

/* 3. every tile the served configs use has a label, and none is blank */
{
  for (const act of ["threat", "watch", "all", "fav", "atstake"]) {
    assert.ok(typeof TILE_LABELS[act] === "string" && TILE_LABELS[act].trim(), `TILE_LABELS.${act} is missing or blank`);
  }
}

/* 4. the sequence is remembered per pillar in a Storage-shaped object and validated */
{
  const mem = new Map();
  const store = { getItem: (k) => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => mem.set(k, String(v)) };
  assert.equal(readFeedSeq(store, "technology"), "priority", "nothing saved: the default");
  writeFeedSeq(store, "technology", "recency");
  assert.equal(readFeedSeq(store, "technology"), "recency");
  assert.equal(readFeedSeq(store, "competitive"), "priority", "another pillar is untouched");
  writeFeedSeq(store, "competitive", "not-a-mode");
  assert.equal(readFeedSeq(store, "competitive"), "priority", "an unknown mode is not restored");
  assert.equal(readFeedSeq(null, "technology"), "priority", "no storage: the default, no throw");
  assert.equal(readFeedSeq({ getItem: () => { throw new Error("denied"); } }, "technology"), "priority");
  for (const [v] of SEQ_OPTIONS) {
    writeFeedSeq(store, "market", v);
    assert.equal(readFeedSeq(store, "market"), v, `every offered option round-trips (${v})`);
  }
}

console.log("ok - feed state: search view == pending view per pillar, empty state names its cause, every tile labelled, sequence remembered per pillar");
