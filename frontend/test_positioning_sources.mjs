/* Positioning shows no sources -- in all THREE of its panels, not one.
 *
 * The operator asked for sources off Spec Comparison, Competitor Detail and Advantages.
 * Only Spec Comparison was off, because provenance reaches the three panels in three
 * different shapes and turning one off says nothing about the others:
 *
 *   Spec Comparison    srcLine() under each value            already off (TASKS #8)
 *   Competitor Detail  a "Sources" row from srcKvRow(m.srcs)  95 of 117 served matchups
 *   Advantages         an inline <a class="adv-src"> per line every line sampled
 *
 * The strings below are the real ones, copied from serving_live.matchup.
 *
 * AND THE REGEX ITSELF IS PINNED. The first version of advantageText carried a literal
 * 0x08 byte where \b was meant -- a backslash eaten while the file was written. It
 * compiled, it never matched, and the panel looked untouched. So this asserts on
 * behaviour AND checks the source file for control bytes, because a regex that silently
 * matches nothing is indistinguishable from a switch that was never wired up.
 */
import { readFileSync } from "node:fs";
import { advantageText, SHOW_POSITIONING_SOURCES } from "./src/lib/specs.js";

let fails = 0;
const ck = (name, ok, detail) => {
  console.log(`  ${name.padEnd(66)} ${ok ? "ok" : "FAIL"}${!ok && detail ? "  " + detail : ""}`);
  if (!ok) fails++;
};

// verbatim from serving_live.matchup 20000
const REAL =
  'Chassis: 4x4 wheeled chassis / HMV <a class="adv-src" href="https://www.kssl.in/our-business-artillery" target="_blank" rel="noopener">kssl.in</a>';

ck("the switch is off", SHOW_POSITIONING_SOURCES === false, String(SHOW_POSITIONING_SOURCES));

const out = advantageText(REAL);
ck("a real advantage line loses its source anchor", !/adv-src/.test(out) && !/<a\b/i.test(out), out);
ck("...and keeps the fact it was making", /4x4 wheeled chassis \/ HMV/.test(out), out);
ck("...with no trailing gap where the chip was", out === out.trim() && !/\s$/.test(out), JSON.stringify(out));

ck("inline emphasis inside an advantage survives",
   advantageText("Weight <b>3.15 kg</b> lower") === "Weight <b>3.15 kg</b> lower");

// a source rendered some other way must stay VISIBLE rather than be silently swallowed
ck("a link that is not the pipeline's source chip is left alone",
   /<a /.test(advantageText('See <a href="https://x">spec</a>')));

ck("an empty advantage is not turned into 'undefined'",
   advantageText(null) === "" && advantageText(undefined) === "",
   JSON.stringify([advantageText(null), advantageText(undefined)]));

// several chips on one line, which the multi-source rows carry
const two = REAL + ' and more <a class="adv-src" href="https://x">x.com</a>';
ck("every chip on a line is removed, not just the first", !/adv-src/.test(advantageText(two)), advantageText(two));

// --- the panels are actually wired to the switch, not just the helper -------------
const dossier = readFileSync(new URL("./src/components/matchupDossier/MatchupDossier.jsx", import.meta.url), "utf8");
ck("Advantages renders through advantageText, not raw html",
   !/__html:\s*a\s*\}/.test(dossier) && /__html:\s*advantageText\(a\)/.test(dossier));
ck("Competitor Detail's Sources row is behind the switch",
   /SHOW_POSITIONING_SOURCES\s*\?\s*srcKvRow\(m\.srcs\)/.test(dossier));

// --- the control-byte guard that would have caught the silent regex ---------------
const specs = readFileSync(new URL("./src/lib/specs.js", import.meta.url), "utf8");
const ctrl = [...specs].filter((c) => {
  const n = c.charCodeAt(0);
  return n < 9 || (n > 10 && n < 32 && n !== 13);
});
ck("specs.js carries no control bytes (a \\b eaten into 0x08 matches nothing)",
   ctrl.length === 0, `${ctrl.length} found: ${ctrl.map((c) => "0x" + c.charCodeAt(0).toString(16)).join(",")}`);

console.log(fails ? `\n${fails} FAILED` : "\nok - all three positioning panels are source-free, and the regex really matches");
process.exit(fails ? 1 : 0);
