/* What the Innovation Pipeline prints for a record's analyst fields, and how its list
 * answers the global search box.
 *
 *     node test_innovation_view.mjs
 *
 * Driven against the live-shape dump (ds.json, 2026-08-25) on 2026-09-05: `gap` is
 * null on EVERY served innovation, and the detail header's pill was
 *
 *     iv.gap === "behind" ? "GAP" : iv.gap === "parity" ? "WATCH" : "AHEAD"
 *
 * so every one of them opened under a green AHEAD pill -- a verdict nobody assessed,
 * on a page whose Status rows correctly said "not assessed" two inches lower. The
 * maturity row had the same shape of fault: `MAT_LAB[iv.mat] || iv.mat` printed the
 * word "null" for the rows that carry no maturity (15 of 1,101 on production).
 *
 * And the global search box's footer promises "the open page is filtered to this
 * query where it has a list"; the Innovation list ignored the query entirely. */
import assert from "node:assert/strict";
import { positionPill, maturityLabel, filterInnovations, MAT_LAB } from "./src/lib/innovation.js";

/* the pill is a verdict: absent position, absent pill */
assert.equal(positionPill(null), null);
assert.equal(positionPill(undefined), null);
assert.equal(positionPill(""), null);
assert.equal(positionPill("  "), null);
assert.equal(positionPill("unexpected-value"), null, "a value the vocabulary does not know is not a verdict either");
assert.deepEqual(positionPill("behind"), { text: "GAP", cls: "behind" });
assert.deepEqual(positionPill("parity"), { text: "WATCH", cls: "parity" });
assert.deepEqual(positionPill("ahead"), { text: "AHEAD", cls: "ahead" });

/* maturity: every served value has a label, and a missing one says so in words */
for (const m of ["lab", "dev", "prod", "fielded"]) assert.ok(MAT_LAB[m], `MAT_LAB.${m}`);
assert.equal(maturityLabel("prod"), "In production");
assert.equal(maturityLabel(null), "not stated");
assert.equal(maturityLabel(undefined), "not stated");
assert.equal(maturityLabel(""), "not stated");
assert.equal(maturityLabel("weird"), "weird", "an unknown non-empty value is shown as served, never invented");
assert.doesNotMatch(maturityLabel(null), /null|undefined/);

/* the list filter: every token somewhere in the row's text, markup ignored, index kept */
const rows = [
  { t: "Ramjet-assisted 155mm projectile", driver: "DRDO / IIT Madras", body: "<b>Range</b> extension for ATAGS", impact: "Kalyani behind on propulsion" },
  { t: "Loitering munition swarm", driver: "Solar Industries", body: "Nagastra-1 family", impact: null, horizon: "2027" },
  { t: "Composite gun barrel", driver: null, body: null, impact: "<b>[Analysis]</b> weight" },
];
const idsOf = (r) => r.map((x) => x.index);
assert.deepEqual(idsOf(filterInnovations(rows, "")), [0, 1, 2], "no query: every row, in order");
assert.deepEqual(idsOf(filterInnovations(rows, "   ")), [0, 1, 2]);
assert.deepEqual(idsOf(filterInnovations(rows, "ramjet")), [0]);
assert.deepEqual(idsOf(filterInnovations(rows, "RAMJET atags")), [0], "case-insensitive, all tokens must hit");
assert.deepEqual(idsOf(filterInnovations(rows, "solar 2027")), [1], "driver and horizon are searched");
assert.deepEqual(idsOf(filterInnovations(rows, "weight")), [2], "impact is searched, null fields do not throw");
assert.deepEqual(idsOf(filterInnovations(rows, "<b>")), [], "markup is not searchable text");
assert.deepEqual(idsOf(filterInnovations(rows, "zqxjv")), []);
assert.equal(filterInnovations(rows, "ramjet")[0].item, rows[0], "the row object is handed back untouched");

console.log("ok - innovation view: no pill without a position, no 'null' maturity, list filter honours the global query");
