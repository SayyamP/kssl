/* THE SAME QUESTION, ASKED OF PRODUCTION'S OWN ROW.
 *
 * test_positioning_sources.mjs asserts against a string I pasted into it. That is the
 * shape of check that already failed once on this page: the overlap-red test asserted
 * on HTML that genuinely did contain the red, and the colour still never reached the
 * screen. A hand-written fixture can only prove the function does what I think it does.
 *
 * This one takes the matchup the operator photographed -- KNDS / CAESAR 6x6 against
 * KSSL / MArG 155, 19 sources, 6 advantage lines -- straight out of /api/dataset on the
 * production backend, and runs the SHIPPED lib functions over it. If a source survives
 * in the served data, it fails here.
 *
 *   node test_positioning_sources_live.mjs ../caesar.json
 */
import { readFileSync } from "node:fs";
import { advantageText, SHOW_POSITIONING_SOURCES } from "./src/lib/specs.js";
import { srcKvRow } from "./src/lib/html.js";

const path = process.argv[2] || "../caesar.json";
/* SKIP, DON'T CRASH, WHEN THE PAYLOAD IS NOT HERE -- the same rule test_feed_pagination
   follows, and for the same reason: CI loops over every test_*.mjs, so a file that reads
   a live export and THROWS fails the whole frontend job. It did exactly that on the run
   that shipped it. The payload is a matchup pulled from /api/dataset and is not tracked;
   pass a path to run this against any row you have exported. */
let m;
try {
  m = JSON.parse(readFileSync(path, "utf8"));
} catch {
  console.log(`SKIP ${path} not present -- export a matchup from /api/dataset to run this`);
  process.exit(0);
}

let fails = 0;
const ck = (name, ok, detail) => {
  console.log(`  ${String(name).padEnd(64)} ${ok ? "ok" : "FAIL"}${!ok && detail ? "  " + detail : ""}`);
  if (!ok) fails++;
};

console.log(`live matchup: ${m.comp}  vs  ${m.bf}`);
console.log(`  ${(m.srcs || []).length} source doc(s), ${(m.advBf || []).length} KSSL advantage line(s)\n`);

/* The row has to actually carry sources, or this file proves nothing at all. */
ck("the served row really does carry sources to remove", (m.srcs || []).length > 0,
   `${(m.srcs || []).length}`);
const rawAdv = (m.advBf || []).concat(m.advComp || []);
const withAnchors = rawAdv.filter((a) => /<a[^>]*adv-src/i.test(String(a)));
ck("...and advantage lines that really do carry <a class=adv-src>", withAnchors.length > 0,
   `${withAnchors.length} of ${rawAdv.length}`);

/* PANEL 3 -- Advantages. */
const rendered = rawAdv.map(advantageText);
ck("no advantage line renders an anchor", !rendered.some((h) => /<a\b/i.test(h)),
   rendered.find((h) => /<a\b/i.test(h)));
ck("...and none renders a bare publisher host either",
   !rendered.some((h) => /\b[a-z0-9-]+\.(in|com|eu|org|br|net)\b/i.test(h)),
   rendered.find((h) => /\b[a-z0-9-]+\.(in|com|eu|org|br|net)\b/i.test(h)));

/* The strip must not eat the sentence it was attached to. */
ck("the advantage TEXT survives the strip", rendered.every((h) => h.trim().length > 0));
ck("...and 'Zone 5' is still on the panel",
   rendered.some((h) => /Zone\s*5/i.test(h)), JSON.stringify(rendered.slice(0, 2)));

/* PANEL 2 -- Competitor Detail. Exactly the expression MatchupDossier.jsx builds. */
const detHtml =
  (Array.isArray(m.det) ? m.det : [])
    .map((dd) => `<div class="kv"><span class="k">${dd[0]}</span><span class="v">${dd[1]}</span></div>`)
    .join("") + (SHOW_POSITIONING_SOURCES ? srcKvRow(m.srcs) : "");
ck("Competitor Detail renders no source chips", !/srcchip/.test(detHtml));
ck("...and no link to a publisher", !/<a\b/i.test(detHtml));
/* The COUNT row is a det row from the pipeline and is meant to stay -- it says how many
   documents back the panel without naming them. Losing it would be over-stripping. */
ck("...but the 'N document(s)' count row is still there",
   /\d+\s*document\(s\)/.test(detHtml), detHtml.slice(0, 120));

console.log(fails ? `\n${fails} FAILED` : "\nok - production's own row renders no sources on any panel");
process.exit(fails ? 1 : 0);
