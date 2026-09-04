/* No emoji in the UI. TASKS #4: "Remove emojis from the UI and use consistent
 * professional icons/text where required."
 *
 *   node check_no_emoji.mjs
 *
 * WHAT COUNTS. Emoji_Presentation -- the characters a browser renders in COLOUR from
 * the emoji font, ignoring the page's palette entirely -- plus anything followed by
 * U+FE0F, which forces colour onto a glyph that would otherwise be text.
 *
 * WHAT DOES NOT. The typographic marks this UI is built from stay: arrows, the
 * disclosure triangles, the section bullets, the geometric overlap markers. They take
 * `color` from the cascade, scale with the type, and are the "professional icons"
 * the task asks for -- a checker that swept them out would be enforcing the opposite
 * of the request. This is the whole reason the rule is Emoji_Presentation and not a
 * block range: U+25B8 and U+1F4E6 sit in different worlds, and only one of them
 * ignores your stylesheet.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const RX = /(\p{Emoji_Presentation}|\p{Extended_Pictographic}\uFE0F)/gu;

const walk = (d) =>
  readdirSync(d).flatMap((f) => {
    const p = join(d, f);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });

let bad = 0;
let scanned = 0;
for (const p of walk("src")) {
  if (!/\.(jsx?|css)$/.test(p)) continue;
  scanned++;
  readFileSync(p, "utf8").split("\n").forEach((line, i) => {
    for (const m of line.matchAll(RX)) {
      bad++;
      console.log(`  ${p}:${i + 1}  ${m[0]}  ${line.trim().slice(0, 80)}`);
    }
  });
}

if (bad) {
  console.log(`\n${bad} emoji in the UI source -- use a styled element or plain text`);
  process.exit(1);
}
console.log(`no emoji in ${scanned} source file(s)`);
