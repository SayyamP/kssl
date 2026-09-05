/* A served field that carries inline markup must render its markup, not print it.
 *
 *     node test_rich_text.mjs
 *
 * FOUND 2026-09-05 (interaction sweep, live dataset): the Partnerships relationship
 * card's "Partnership strategic impact" box read, verbatim, "<b>Threat:</b> Drishti-10
 * is Adani's flagship..." -- the pipeline writes the partner's `mean` with <b> labels
 * (the drawer's own synthesis path parses those very tags), and the card escaped the
 * whole string. Two renderers of one field, one of them printing the other's markup.
 *
 * What this pins: escRich keeps the inline tags a served field is allowed to carry
 * (b, i, em, strong, br), escapes everything else, and never lets a script or an
 * attribute through -- a served string is data, not code.
 */
import { escRich } from "./src/lib/html.js";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

const cases = [
  ["<b>Threat:</b> Drishti-10 is Adani's win", "<b>Threat:</b> Drishti-10 is Adani's win", "bold label survives"],
  ["a <i>quiet</i> <em>tie</em> <strong>held</strong>", "a <i>quiet</i> <em>tie</em> <strong>held</strong>", "the inline set survives"],
  ["line<br>break<br/>too", "line<br>break<br>too", "br in both spellings, normalised"],
  ["<b>open and never closed", "&lt;b&gt;open and never closed", "an unbalanced opener is text"],
  ["<b>x <b onclick=\"y()\">y</b> z</b>", "<b>x &lt;b onclick=\"y()\"&gt;y</b> z&lt;/b&gt;", "a stray closer never closes a legitimate bold further up"],
  ["<script>alert(1)</script>x", "&lt;script&gt;alert(1)&lt;/script&gt;x", "a script tag is text"],
  ['<b onclick="x()">bold</b>', '&lt;b onclick="x()"&gt;bold&lt;/b&gt;', "a whitelisted tag with an attribute is text"],
  ["<a href='u'>link</a>", "&lt;a href='u'&gt;link&lt;/a&gt;", "an anchor is text"],
  ["5 < 6 & 7 > 2", "5 &lt; 6 &amp; 7 &gt; 2", "bare operators are escaped"],
  ["", "", "empty stays empty"],
  [null, "", "null is empty"],
];
cases.forEach(([inp, want, why]) => {
  const got = escRich(inp);
  if (got !== want) fail(`${why}: ${JSON.stringify(inp)} -> ${JSON.stringify(got)}, wanted ${JSON.stringify(want)}`);
});

if (bad) { console.log(`test_rich_text: ${bad} failure(s)`); process.exit(1); }
console.log("test_rich_text: ok -- served inline markup renders, everything else is text");
