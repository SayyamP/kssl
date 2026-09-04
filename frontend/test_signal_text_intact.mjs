/* A signal's text reaches the screen exactly as it was served.
 *
 *     node test_signal_text_intact.mjs
 *
 * FE 28: "a signal is not shown properly -- sentence ended arbitrarily". The reported card
 * reads "Saab's contract strengthens its." on screen, and that is the STORED sowhat
 * (serving.signal_card, 17 rows end on a stranded possessive; 9 more end in
 * "; <Category>"). The cut happened in serving_fill.py's strip_kssl_tail, which now
 * walks back to a clause boundary; the served rows predate that fix.
 *
 * This test pins the other half of the question: the frontend must neither shorten
 * nor "repair" what it was given. A render-side clamp would have been the cheap
 * explanation, and a render-side patch would be the cheap cover-up -- both are what
 * check_no_fabrication.mjs exists to forbid. So:
 *
 *   1. the data path (wireDataset's title casing, buildFeed, paginateFeed) hands every
 *      character of title and sowhat through, markup and entities included;
 *   2. the card component and its stylesheet carry no slice, substring, line-clamp,
 *      text-overflow or fixed height on the title or the sowhat -- a long sowhat wraps,
 *      it is never elided.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildFeed, paginateFeed } from "./src/lib/overview.js";
import { titleCaseHeadline } from "./src/lib/profile.js";

const strip = (s) => String(s).replace(/<[^>]+>/g, "");

/* ---- 1. the data path ---- */
const longSowhat =
  (
    "The Centauro II represents a significant advancement in armored vehicle technology, " +
    "equipped with <b>advanced features</b> like the HITFACT MkII turret &amp; a 720 HP " +
    "propulsion system. "
  ).repeat(4) +
  "Rheinmetall's order highlights its expertise in artillery systems and strengthens its.";
assert.ok(longSowhat.length > 600, "the fixture must be longer than any plausible clamp");

const cards = [
  { id: "a", dir: "threat", ago: "Sep 2026", sec: [], title: "leonardo wins centauro II contract with brazilian army", sowhat: longSowhat },
  { id: "b", dir: "watch", ago: "Aug 2026", sec: [], title: "French Procurement Agency orders 25,000 40mm rounds", sowhat: "Saab's contract strengthens its." },
  { id: "c", dir: "watch", ago: "Aug 2026", sec: [], title: "UK Defence Investment Plan for Type 31 Frigates", sowhat: "The plan enhances the lethality of Type 31 frigates; Marine / Naval" },
];
const feed = buildFeed({ cards, groups: [{ n: 99, h: "All", s: "" }] }, "priority", { details: {} });
const view = paginateFeed(feed.groups, null, 1);
const shown = Object.fromEntries(view.groups.flatMap((g) => g.cards).map((c) => [c.id, c]));

for (const c of cards) {
  assert.equal(shown[c.id].sowhat, c.sowhat, `${c.id}: sowhat altered on the feed path`);
  assert.equal(shown[c.id].title, c.title, `${c.id}: title altered on the feed path`);
}
// the long one is intact to the last character, markup and entity included
assert.equal(shown.a.sowhat.length, longSowhat.length);
assert.ok(shown.a.sowhat.endsWith("strengthens its."));
assert.ok(shown.a.sowhat.includes("<b>advanced features</b>"));
assert.ok(shown.a.sowhat.includes("&amp;"));
// the fragment the client saw is passed through, not silently "repaired" here --
// repairing served text on the client is inventing content
assert.equal(shown.b.sowhat, "Saab's contract strengthens its.");

// wireDataset cases the headline for display: case only, every character kept
const cased = titleCaseHeadline(cards[0].title);
assert.equal(cased.length, cards[0].title.length, "title casing must not add or drop a character");
assert.equal(cased.toLowerCase(), cards[0].title.toLowerCase());
const withMarkup = "Saab &amp; <b>BAE</b> deliver 12 M4 guns";
assert.equal(strip(titleCaseHeadline(withMarkup)).length, strip(withMarkup).length);
assert.ok(titleCaseHeadline(withMarkup).includes("&amp;"), "entities survive casing");
assert.ok(titleCaseHeadline(withMarkup).includes("<b>BAE</b>"), "markup survives casing");

/* ---- 2. the component and its stylesheet ---- */
const card = readFileSync("src/components/signalCard/SignalCard.jsx", "utf8");
assert.ok(card.includes("__html: card.title"), "the title is rendered from card.title as served");
assert.ok(card.includes("__html: card.sowhat"), "the sowhat is rendered from card.sowhat as served");
assert.ok(!/\.(slice|substr|substring)\(/.test(card), "SignalCard must not shorten a served string");
assert.ok(!/\.\.\.["'`]/.test(card) && !/…/.test(card), "SignalCard must not append an ellipsis");

/* The feed's card rules. Pull every declaration block whose selector names the
   title or the sowhat inside .alert, and refuse the properties that elide text. */
const css = readFileSync("src/styles/shell.css", "utf8");
const blocks = [...css.matchAll(/([^{}]*\.alert[^{}]*\.(?:ttl|sowhat|body)[^{}]*)\{([^}]*)\}/g)];
assert.ok(blocks.length >= 3, "expected the .alert .body / .ttl / .sowhat rules in shell.css");
for (const [, sel, decl] of blocks) {
  const d = decl.replace(/\s+/g, "");
  // property-start anchored, so `line-height` is not mistaken for `height`
  for (const bad of ["line-clamp", "text-overflow", "max-height", "overflow:hidden", "white-space:nowrap", "height:"]) {
    assert.ok(!new RegExp(`(^|;)(-webkit-)?${bad}`).test(d), `${sel.trim()} must not carry ${bad}`);
  }
}

console.log("ok - a served signal reaches the card whole; no slice, clamp or ellipsis on the render path");
