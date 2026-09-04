/* Every news item must reach its original source.
 *
 *     node test_source_link.mjs
 *
 * Reported: "News items do not consistently redirect to the original source."
 *
 * Inconsistently is exactly right. Three drawers read the same `url` field: the Geo one
 * rendered an <a>, the competitor profile and the product drawer printed the publisher
 * as plain text. 1,171 of the 1,177 served signal cards carry a url, so the link was
 * there and simply was not drawn.
 *
 * The grep at the end is the check that holds. A shared component is easy to add and
 * easy to walk around -- walking around it is how three drawers reading one field came
 * to behave three different ways.
 */
import { readFileSync } from "node:fs";

const src = readFileSync("./src/components/sourceLink/SourceLink.jsx", "utf8");
const from = src.indexOf("export function sourceHref");
const to = src.indexOf("\n}", from) + 2;
const { sourceHref } = await import(
  "data:text/javascript," + encodeURIComponent(src.slice(from, to)));

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

// 1. a real article url is linked
for (const u of ["https://janes.com/a", "http://idrw.org/b", "HTTPS://X.TEST/C"]) {
  if (sourceHref(u) !== u) fail(`${u} was not turned into a link`);
}

// 2. anything that is not a fetchable article is not linked, and is not thrown away
//    silently either -- the component renders "no source link on file" for these
for (const u of [null, undefined, "", "   ", 42, {}, "example.test/a", "/relative",
  "javascript:alert(1)", "data:text/html,x", "mailto:a@b.c"]) {
  if (sourceHref(u) !== null)
    fail(`${JSON.stringify(u)} was turned into an href`);
}

// 3. no drawer may print the publisher as inert text again
const PAGES = [
  "./src/pages/competitive/Profile.jsx",
  "./src/pages/competitive/Products.jsx",
];
for (const f of PAGES) {
  const text = readFileSync(f, "utf8");
  if (/Source Publisher:\s*<span/.test(text))
    fail(`${f} prints the publisher as plain text instead of SourceLink`);
  if (!text.includes("SourceLink"))
    fail(`${f} does not use SourceLink`);
}

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - source links: article urls link out, non-urls are reported rather "
  + "than linked, no drawer left printing the publisher as inert text");
