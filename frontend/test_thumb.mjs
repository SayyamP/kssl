/* A missing image must look different from a broken page.
 *
 *     node test_thumb.mjs
 *
 * Reported: "Images for Allen Control Systems and similarly affected entries are not
 * displayed. Missing images should use a defined fallback rather than a broken or blank
 * area."
 *
 * Two faults produced the same broken box:
 *   1. no url at all -- five sites wrote `<img src={item.image} />` unguarded, and
 *      `<img src={undefined}>` is drawn as the browser's broken glyph. Measured on
 *      production: 123 of 1,175 served signal cards carry no image, and Allen Control
 *      Systems is one of them (2 cards, 1 image);
 *   2. a url that will not load -- a publisher blocking hotlinking, or a rotted link.
 *      No site had an onError.
 *
 * Also pinned here: no render site may go back to a bare <img> on an article image.
 * That is the check that actually holds -- a helper is easy to add and easy to bypass,
 * and bypassing it is exactly how five sites came to differ from partners.js, which had
 * had the fallback all along.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const src = readFileSync("./src/components/thumb/Thumb.jsx", "utf8");
const from = src.indexOf("const FAILED = new Set();");
const to = src.indexOf("export default function Thumb");
const { thumbUsable, thumbMarkFailed } = await import(
  "data:text/javascript," + encodeURIComponent(src.slice(from, to)));

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

// 1. a real url is used
if (!thumbUsable("https://example.test/a.jpg", new Set()))
  fail("a plain https image was rejected");
if (!thumbUsable("http://example.test/a.jpg", new Set()))
  fail("a plain http image was rejected");

// 2. every shape of "no image" falls back, none of them reaching an <img>
for (const v of [undefined, null, "", "   ", 0, false, {}, []]) {
  if (thumbUsable(v, new Set()))
    fail(`${JSON.stringify(v)} was treated as a usable image url`);
}
// a bare path is not something this app publishes, and cannot be fetched as given
if (thumbUsable("/local/a.jpg", new Set())) fail("a relative path was treated as usable");
if (thumbUsable("javascript:alert(1)", new Set())) fail("a javascript: url was allowed");
if (thumbUsable("data:image/png;base64,AAAA", new Set())) fail("a data: url was allowed");

// 3. a url that failed once is not requested again -- the whole of the caching that is
//    possible from the client for third-party images
const failed = new Set();
const u = "https://blocked.test/hotlink.jpg";
if (!thumbUsable(u, failed)) fail("a fresh url was refused before it had failed");
thumbMarkFailed(u, failed);
if (thumbUsable(u, failed)) fail("a url that already failed was requested again");
// and a different url is unaffected by its neighbour's failure
if (!thumbUsable("https://ok.test/b.jpg", failed))
  fail("one failed url poisoned an unrelated one");
// marking rubbish must not grow the set
const n = failed.size;
thumbMarkFailed(null, failed);
thumbMarkFailed("", failed);
if (failed.size !== n) fail("a non-url was recorded as a failed url");

// 4. no render site may reintroduce a bare <img> on an article image
const walk = (dir) => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? walk(p) : [p];
});
const offenders = [];
for (const f of walk("./src")) {
  if (!/\.(jsx|js)$/.test(f)) continue;
  if (f.includes("thumb")) continue;
  const text = readFileSync(f, "utf8");
  // a JSX <img> whose src is an expression -- string-built markup is checked separately
  const m = text.match(/<img\s+src=\{[^}]*\}/g) || [];
  if (m.length) offenders.push(`${f}: ${m.join(", ")}`);
  // a string-built <img> on an article image must carry an onerror fallback
  const s2 = text.match(/<img src="\$\{[^"]*image[^"]*\}"(?![^`]*onerror)/g) || [];
  if (s2.length) offenders.push(`${f}: string img with no onerror`);
}
if (offenders.length)
  fail("unguarded image sites:\n    " + offenders.join("\n    "));

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - thumbnails: every no-image shape falls back, failed urls are not "
  + "re-requested, no render site left with a bare <img>");
