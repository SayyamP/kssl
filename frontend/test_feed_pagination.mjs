/* Every signal the API serves must be reachable in the feed.
 *
 * The group defs carry fixed sizes (competitive: 6 + 99) written against a demo
 * dataset. Production serves 429 competitive / 235 technology / 128 market signals,
 * and buildFeed used to slice each group to its `n` -- so the feed stopped at 105
 * while its own footer said "429 total". This asserts the two numbers agree, and
 * that walking the pager visits every card exactly once.
 *
 *   node test_feed_pagination.mjs [path/to/dataset.json]
 */
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { buildFeed, paginateFeed, FEED_PAGE_SIZE } from "./src/lib/overview.js";

const path = process.argv[2] || "../../ds_prod.json";
const d = JSON.parse(readFileSync(path, "utf-8"));

const PILLARS = [
  ["competitive", d.competitiveCards],
  ["market", d.marketCards],
  ["technology", d.techCards],
];

let checks = 0;
for (const [pillar, cards] of PILLARS) {
  const cfg = { ...d.overviewConfig[pillar], cards };
  for (const seq of ["priority", "recency", "depth", "category"]) {
    const feed = buildFeed(cfg, seq);

    // 1. every served card is in some group -- nothing silently dropped
    const inGroups = feed.groups.reduce((n, g) => n + g.cards.length, 0);
    assert.equal(
      inGroups, cards.length,
      `${pillar}/${seq}: feed renders ${inGroups} of ${cards.length} cards`,
    );

    // 2. the footer count is the same number the feed can show
    assert.equal(feed.total, cards.length, `${pillar}/${seq}: total disagrees`);

    // 3. walking every page visits each id exactly once
    const seen = [];
    const pageCount = paginateFeed(feed.groups, null, 1).pageCount;
    assert.equal(
      pageCount, Math.max(1, Math.ceil(cards.length / FEED_PAGE_SIZE)),
      `${pillar}/${seq}: wrong page count`,
    );
    for (let p = 1; p <= pageCount; p += 1) {
      const v = paginateFeed(feed.groups, null, p);
      assert.equal(v.page, p);
      v.groups.forEach((g) => g.cards.forEach((c) => seen.push(c.id)));
    }
    assert.equal(seen.length, cards.length, `${pillar}/${seq}: pager visited ${seen.length}`);
    assert.equal(new Set(seen).size, cards.length, `${pillar}/${seq}: a card repeats across pages`);

    // 4. pageOf points at the page that actually holds the card
    const view = paginateFeed(feed.groups, null, 1);
    for (const id of [cards[0].id, cards[cards.length - 1].id, cards[Math.floor(cards.length / 2)].id]) {
      const at = view.pageOf(id);
      assert.ok(at, `${pillar}/${seq}: pageOf(${id}) found nothing`);
      const onThat = paginateFeed(feed.groups, null, at);
      assert.ok(
        onThat.groups.some((g) => g.cards.some((c) => c.id === id)),
        `${pillar}/${seq}: pageOf said page ${at} but the card is not on it`,
      );
    }

    // 5. a filter that empties the list must not leave a page number pointing nowhere
    const none = paginateFeed(feed.groups, () => false, 5);
    assert.equal(none.shown, 0);
    assert.equal(none.page, 1, "an empty filter must clamp back to page 1");

    // 6. an out-of-range page clamps instead of showing a blank feed
    assert.equal(paginateFeed(feed.groups, null, 9999).page, pageCount);
    checks += 1;
  }
}
console.log(`ok — ${checks} pillar/sequence combinations; every served signal reachable`);
