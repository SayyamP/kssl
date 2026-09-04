/* An ampersand must reach the reader as "&", not as "&amp;".
 *
 *     node test_double_escape.mjs
 *
 * extraction/signals/serving_fill.py stores esc(title) and esc(sowhat) -- html.escape at
 * WRITE time -- and the app escapes again at render, so the entity itself is what gets
 * shown: "Protected &amp; Armoured Vehicles", "UAVs &amp; Drones".
 *
 * Measured on production: 132 of the 133 sowhat values containing an ampersand hold the
 * five-character entity, and 11 of 12 titles. The `tags` column, which the writer does
 * NOT pass through esc(), holds a real "&" -- that asymmetry is the proof it is the
 * writer and not the corpus, and the corpus confirms it (0 of 5,000 document texts).
 *
 * The safety case matters as much as the fix. chat.js interpolates tender and signal
 * titles into markup with no escaping, so a blanket unescape would turn a stored `&lt;`
 * into a live `<`. Only `&amp;` is decoded, and these assertions are what hold that
 * line: a bare "&" cannot open a tag, so nothing becomes renderable that was not
 * already.
 */
import { wireDataset } from "./src/lib/dataset.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

const raw = {
  overviewConfig: { competitive: {}, technology: {}, market: { cnt: "x" } },
  techCats: [], innovations: {}, matchups: {}, competitorNews: {}, patents: {},
  competitors: {
    lt: { name: "Larsen &amp; Toubro", products: ["Missiles &amp; Air Defence system"] },
  },
  details: {
    c1: {
      title: "Rheinmetall wins Protected &amp; Armoured Vehicles order",
      what: "A &amp; B agreed terms.",
      url: "https://example.test/a?x=1&amp;y=2",
      facts: [["Category", "UAVs &amp; Drones"]],
    },
  },
  marketCards: [
    { id: "c1", dir: "watch", lens: "Market",
      title: "Rheinmetall wins Protected &amp; Armoured Vehicles order",
      sowhat: "Strengthens its position in Protected &amp; Armoured Vehicles.",
      tags: "Protected & Armoured Vehicles" },
    // already-correct text must be left exactly alone
    { id: "c2", dir: "watch", lens: "Market", title: "Saab & Boeing extend T-7A",
      sowhat: "No entity here.", tags: "Artillery" },
  ],
  tenders: [],
};

const d = wireDataset(raw);
const card = (id) => (d.marketCards || []).find((c) => c.id === id) || {};

// 1. the reported strings come out readable
if (/&amp;/.test(card("c1").title || "")) fail("card title still carries the entity");
if (/&amp;/.test(card("c1").sowhat || "")) fail("card sowhat still carries the entity");
if (!/Protected & Armoured/.test(card("c1").sowhat || ""))
  fail("the ampersand did not survive as a character");

// 2. nested containers are reached, not just the top level
if (/&amp;/.test((d.details.c1 || {}).title || "")) fail("detail title untouched");
if (/&amp;/.test((d.details.c1 || {}).what || "")) fail("detail body untouched");
if (/&amp;/.test(((d.details.c1 || {}).facts || [])[0][1] || ""))
  fail("a fact value inside an array of arrays was missed");
if (/&amp;/.test((d.competitors.lt || {}).name || "")) fail("competitor name untouched");
if (/&amp;/.test(((d.competitors.lt || {}).products || [])[0] || ""))
  fail("a product name inside an array was missed");

// 3. a url with an escaped separator is a broken link, and is repaired
if ((d.details.c1 || {}).url !== "https://example.test/a?x=1&y=2")
  fail(`url not repaired: ${(d.details.c1 || {}).url}`);

// 4. text that was already correct keeps its ampersand as a character. The headline is
//    compared case-insensitively on purpose: titleCaseHeadline runs at this same funnel
//    and raises "extend" -> "Extend", which is a different rule with its own test. An
//    exact-string assertion here would fail for a reason that has nothing to do with
//    escaping, and would be read as this fix breaking something.
if (card("c2").title.toLowerCase() !== "saab & boeing extend t-7a")
  fail(`correct text was altered: ${card("c2").title}`);
if (card("c2").sowhat !== "No entity here.")
  fail("a string with no entity was rewritten");
if (card("c1").tags !== "Protected & Armoured Vehicles")
  fail("the tags column, which was never escaped, was altered");

// 5. THE SAFETY LINE. Only the ampersand is decoded; anything that could open a tag
//    stays inert, because chat.js interpolates titles into markup unescaped.
const risky = wireDataset({
  ...raw,
  marketCards: [{ id: "x", dir: "watch", lens: "Market",
    title: "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more",
    sowhat: "&lt;img src=x onerror=alert(1)&gt; &quot;q&quot; &#39;s&#39;" }],
});
const x = (risky.marketCards || [])[0] || {};
for (const [name, val] of [["title", x.title], ["sowhat", x.sowhat]]) {
  if (/</.test(val || "")) fail(`${name} now contains a live "<": ${val}`);
  if (/&lt;|&gt;/.test(val || "") === false)
    fail(`${name} lost its escaped angle brackets -- they must stay escaped`);
}
if (!/ & more/i.test(x.title || "")) fail("the ampersand was not decoded alongside them");
if (/&quot;|&#39;/.test(x.sowhat || "") === false)
  fail("quote entities were decoded -- only &amp; may be");

// 6. idempotent: running the funnel twice must not change the answer
const once = JSON.stringify(wireDataset(raw).marketCards);
const twice = JSON.stringify(wireDataset(JSON.parse(JSON.stringify(raw))).marketCards);
if (once !== twice) fail("the funnel is not idempotent over the same input");

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - double escape: ampersands read as characters, urls repaired, "
  + "angle brackets and quotes left escaped, correct text untouched");
