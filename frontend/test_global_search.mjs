/* The global search is a pure function over the served dataset.
 *
 *     node test_global_search.mjs
 *
 * FE 25: "the search bar in the top header does not work at all". It had been reduced
 * to a live filter on whichever page was open, so on a page with nothing to filter
 * (Innovation, Geo, Patents) typing did nothing, and no page ever said "no results".
 * searchDataset() is the part a browser is not needed for: given the dataset and a
 * query it returns grouped hits with a navigation target each, or an explicit empty
 * result. Every assertion here runs against a fixture, never the production corpus.
 */
import assert from "node:assert/strict";
import { searchDataset, SEARCH_MIN_CHARS } from "./src/lib/search.js";

const data = {
  client: { id: "KSSL", short: "KSSL", name: "Kalyani Strategic Systems" },
  competitors: {
    saab: { name: "Saab AB", sector: "Aerospace · Missiles", hq: "Stockholm, Sweden", products: ["Gripen E", { name: "Carl-Gustaf M4" }] },
    knds: { name: "KNDS", sector: "Artillery", hq: "Paris, France" },
  },
  matchups: {
    m1: { id: "m1", cat: "Artillery", comp: "KNDS · CAESAR 6x6", compBy: "KNDS", bf: "KSSL · MArG 155", country: "France" },
  },
  competitiveCards: [{ id: "c1", title: "KNDS wins CAESAR order", company: "KNDS", tags: "artillery", sowhat: "so" }],
  marketCards: [{ id: "mk1", title: "Sweden opens howitzer tender", company: "FMV", tags: "" }],
  techCards: [{ id: "t1", title: "Ramjet shell tested", company: "DRDO", tags: "artillery" }],
  tenders: [
    { id: 1, title: "155mm Mounted Gun System", issuer: "Ministry of Defence", country: "India", cat: "Artillery", dl: 9 },
    { id: 2, title: "Naval drone award", issuer: "Navy", country: "India", cat: "UAVs", status: "awarded" },
    { id: 3, title: "Old radar buy", issuer: "IAF", country: "India", cat: "Radar", deadline: "Closed", dl: 0 },
  ],
  techCats: [{ id: "artillery", name: "Artillery" }],
  innovations: {
    artillery: [{ t: "Ramjet-assisted 155mm projectile", driver: "DRDO / IIT Madras", body: "<b>Range</b> extension" }],
  },
};

const groupOf = (res, key) => res.groups.find((g) => g.key === key);

/* a term that hits, across several stores at once */
{
  const res = searchDataset(data, "caesar");
  assert.ok(res.total >= 2, `caesar should hit at least the product and the signal, got ${res.total}`);
  const prod = groupOf(res, "products");
  assert.ok(prod && prod.hits.some((h) => /CAESAR/.test(h.title)), "product hit missing");
  const sig = groupOf(res, "signals");
  assert.ok(sig && sig.hits.some((h) => h.title === "KNDS wins CAESAR order"), "signal hit missing");
  const sigHit = sig.hits.find((h) => h.title === "KNDS wins CAESAR order");
  assert.deepEqual(sigHit.target, { pillar: "competitive", view: "overview", payload: { cardId: "c1" } });
}

/* a term that misses is an explicit empty result, not an empty list of groups the
   caller has to interpret */
{
  const res = searchDataset(data, "zzzz");
  assert.equal(res.total, 0);
  assert.equal(res.groups.length, 0);
  assert.equal(res.query, "zzzz");
}

/* case-insensitive on both sides */
{
  const upper = searchDataset(data, "SAAB");
  const lower = searchDataset(data, "saab");
  assert.equal(upper.total, lower.total);
  assert.ok(upper.total > 0, "SAAB should hit the competitor");
  const comp = groupOf(upper, "competitors");
  assert.deepEqual(comp.hits[0].target, { pillar: "competitive", view: "profile", payload: { cid: "saab" } });
}

/* every token must match (AND), so a two-word query narrows rather than widens */
{
  assert.equal(searchDataset(data, "knds gripen").total, 0);
  assert.ok(searchDataset(data, "knds caesar").total >= 1);
}

/* too short to search is not the same as no results */
{
  const res = searchDataset(data, "k");
  assert.equal(res.tooShort, true);
  assert.equal(res.total, 0);
  assert.equal(SEARCH_MIN_CHARS, 2);
}

/* signals route to the pillar whose feed lists them; tenders route to the tab that
   holds them (an awarded tender is not on the open pipeline) */
{
  const tech = groupOf(searchDataset(data, "ramjet shell"), "signals").hits[0];
  assert.equal(tech.target.pillar, "technology");
  assert.equal(tech.target.view, "t-overview");
  const market = groupOf(searchDataset(data, "howitzer"), "signals").hits[0];
  assert.equal(market.target.view, "m-overview");

  const tenders = groupOf(searchDataset(data, "india"), "tenders");
  const byTitle = Object.fromEntries(tenders.hits.map((h) => [h.title, h.target.view]));
  assert.equal(byTitle["155mm Mounted Gun System"], "tender");
  assert.equal(byTitle["Naval drone award"], "awarded-tenders");
  assert.equal(byTitle["Old radar buy"], "closed-tenders");
}

/* innovations carry their domain so the page can open the right tab, and the HTML
   in `body` is searched as text, not as tags */
{
  const inn = groupOf(searchDataset(data, "range extension"), "innovations");
  assert.ok(inn, "innovation body text should be searchable");
  assert.deepEqual(inn.hits[0].target, {
    pillar: "technology",
    view: "innovation",
    payload: { catId: "artillery", title: "Ramjet-assisted 155mm projectile" },
  });
  assert.equal(searchDataset(data, "<b>").total, 0, "markup must not be searchable");
}

/* a roster-listed product opens its maker's catalogue by serving key; a matchup product
   (either side) opens its Positioning dossier by matchup id, which always resolves --
   the catalogue joins by display name and most matchup makers have no roster row */
{
  const res = searchDataset(data, "gripen");
  const prod = groupOf(res, "products");
  assert.deepEqual(prod.hits[0].target, { pillar: "competitive", view: "products", payload: { cid: "saab", productName: "Gripen E" } });
  const marg = groupOf(searchDataset(data, "marg"), "products").hits[0];
  assert.deepEqual(marg.target, { pillar: "competitive", view: "positioning", payload: { matchupId: "m1" } });
  assert.equal(marg.meta, "KSSL · Artillery");
  const caesar = groupOf(searchDataset(data, "caesar"), "products").hits[0];
  assert.deepEqual(caesar.target, { pillar: "competitive", view: "positioning", payload: { matchupId: "m1" } });
  assert.equal(caesar.meta, "KNDS · Artillery");
}

/* the count is the whole match, the hits are the slice shown -- "drone" is 264
   signals in production and showing eight of them must say so */
{
  const many = {
    ...data,
    competitiveCards: Array.from({ length: 20 }, (_, i) => ({ id: `x${i}`, title: `drone story ${i}`, company: "" })),
  };
  const sig = groupOf(searchDataset(many, "drone", { signals: 8 }), "signals");
  assert.equal(sig.count, 20);
  assert.equal(sig.hits.length, 8);
  /* the fixture's "Naval drone award" tender is a 21st hit: the total is the sum of
     every group's full count, never of what is listed */
  const whole = searchDataset(many, "drone", { signals: 8 });
  assert.equal(whole.total, whole.groups.reduce((n, g) => n + g.count, 0));
  assert.equal(whole.total, 21);
}

/* a dataset with stores missing is searched, not crashed on */
{
  const res = searchDataset({ competitors: { a: { name: "Alpha Defence" } } }, "alpha");
  assert.equal(res.total, 1);
}

console.log("global search: all checks passed");
