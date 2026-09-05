/* The detail panel's statement block must never be handed a surprise.
 *
 *     node test_statements.mjs
 *
 * `signal_detail.lens` is written by two populations and has already shipped in three
 * different shapes. One of them -- a bare string, "SPEC RANK" -- took the whole
 * application to a blank page, because a string is truthy, has a `.length`, and has no
 * `.map` (see ErrorBoundary). Nothing rendered `lens` after that, which is why six
 * evidence-backed statements per card sat unread.
 *
 * So the contract is not "it usually works": statementRows returns an array of strings
 * for every shape the record has ever held, and the caller can map over it blind.
 */
import { statementRows } from "./src/lib/detail.js";

let bad = 0;
const eq = (got, want, what) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { bad++; console.log(`  FAIL ${what}\n    got  ${g}\n    want ${w}`); }
};

/* --- the pipeline shape, from a real row (Leonardo / Centauro II) --- */
const real = [
  ["STATEMENT", "Leonardo signed with Esercito Brasiliano — <i>&ldquo;…&rdquo;</i>"],
  ["STATEMENT", "sette veicoli 8×8 Centauro II are forniti — <i>&ldquo;…&rdquo;</i>"],
];
eq(statementRows(real),
   ["Leonardo signed with Esercito Brasiliano — <i>&ldquo;…&rdquo;</i>",
    "sette veicoli 8×8 Centauro II are forniti — <i>&ldquo;…&rdquo;</i>"],
   "pipeline rows keep their html, in order");

/* --- the shapes that must not throw and must not render --- */
eq(statementRows("SPEC RANK"), [], "the bare string that blanked the app");
eq(statementRows(undefined), [], "absent");
eq(statementRows(null), [], "null");
eq(statementRows({ 0: ["STATEMENT", "x"] }), [], "an object is not a list of rows");
eq(statementRows([["STATEMENT"], ["STATEMENT", ""], ["STATEMENT", "   "]]), [],
   "a row with no text renders nothing rather than an empty rule");
eq(statementRows([["STATEMENT", null], ["STATEMENT", 42], ["STATEMENT", "kept"]]), ["kept"],
   "non-string cells are dropped, the good one survives");

/* --- a flat list of strings is accepted too: the reference population writes that --- */
eq(statementRows(["a", "b"]), ["a", "b"], "flat strings");

/* --- the cap is real: a panel is not a transcript --- */
const many = Array.from({ length: 12 }, (_, i) => ["STATEMENT", `s${i}`]);
eq(statementRows(many).length, 6, "capped at six by default");
eq(statementRows(many, 2), ["s0", "s1"], "and the cap is the caller's to set");

/* --- every element is a string, whatever went in: this is what lets the caller
       map without a guard of its own --- */
const mixed = statementRows([["S", "a"], "b", ["S", null], 7, [], ["S", "c"]]);
if (!Array.isArray(mixed) || mixed.some((s) => typeof s !== "string")) {
  bad++; console.log("  FAIL not every element is a string:", JSON.stringify(mixed));
}

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - statementRows returns an array of strings for every stored shape");
