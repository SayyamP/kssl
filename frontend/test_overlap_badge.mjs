/* "Direct Partner" was the else branch of a two-state badge, and the only branch that
 * could run.
 *
 * The badge answers one question -- is this rival's partner also KSSL's? -- and had
 * two answers for it: red "Overlapping Partner" if shared, green "Direct Partner"
 * otherwise. The overlap join (mark_shared.py) was wired into no pass and its roster
 * query filtered on origin='pipeline', which returns none of KSSL's 11 reference-only
 * roster rows. So `shared` was never set, and every partner of every competitor on the
 * tab wore the green badge -- including Rafael, which is KSSL's own KRAS JV partner
 * AND Mahindra Defence's, and is the single most valuable line on the page.
 *
 *   node frontend/test_overlap_badge.mjs        (no build, no browser, no data)
 */
import { overlapState, overlapBadge, tieKind, tieKindShort } from "./src/lib/partners.js";

let fail = 0;
const check = (name, got, want) => {
  const ok = typeof want === "function" ? want(got) : got === want || String(got).includes(want);
  console.log(`  ${ok ? "ok  " : "FAIL"} ${name}${ok ? "" : `\n    got ${JSON.stringify(got)}`}`);
  if (!ok) fail++;
};

// --- the three states are actually three -------------------------------------
check("a tie the client also holds is shared", overlapState({ koel: { rel: "jv" } }), "shared");
check("  `shared` alone is enough (a rival partnering the client direct)",
      overlapState({ shared: true, clientTie: true }), "shared");
check("  and an overlap on any underlying row counts",
      overlapState({ rows: [{ cid: "x" }, { koel: {} }] }), "shared");
check("a keyed tie with no overlap is direct", overlapState({ cid: "anduril" }), "direct");
check("  keyed on an underlying row counts too", overlapState({ rows: [{ cid: "anduril" }] }), "direct");

// THE CASE THIS FILE EXISTS FOR. No cid means mark_shared never reached this tie.
// Absence of evidence is not evidence of absence, and the badge must not say it is.
check("an unkeyed tie is UNCHECKED, not direct", overlapState({ label: "Anduril Industries" }), "unchecked");
check("  a bare object is unchecked", overlapState({}), "unchecked");
check("  and nothing at all does not throw", overlapState(null), "unchecked");
check("  an empty rows array is not a check having run",
      overlapState({ label: "Ultra Electronics", rows: [] }), "unchecked");

// --- what each state renders --------------------------------------------------
check("shared renders the red badge", overlapBadge({ label: "Rafael", koel: {} }, "KSSL"), "Overlapping Partner");
check("  and names the client in the tooltip",
      overlapBadge({ label: "Rafael", koel: {} }, "KSSL"), "also on KSSL's own partner roster");
// A BADGE ON EVERY CARD IS NOT A BADGE. Eight of 42 staging ties overlap; the other
// 34 wore a green "Direct Partner" in the card's most prominent slot, which is how the
// relationship type ended up with nowhere to print. The norm is now the absence of one.
check("the normal case prints no badge at all",
      overlapBadge({ label: "Anduril", cid: "anduril" }, "KSSL"), (h) => h === "");
check("unchecked does not claim a direct tie",
      overlapBadge({ label: "Anduril" }, "KSSL"), (h) => !h.includes("Direct Partner"));
check("  it says the overlap is unknown", overlapBadge({ label: "Anduril" }, "KSSL"), "Overlap Unchecked");
check("  and is neutral, not green -- green is a claim",
      overlapBadge({ label: "Anduril" }, "KSSL"), (h) => !h.includes("#16a34a"));

// each state is separable in CSS and in a DOM test
check("every state carries its own class", overlapBadge({ label: "A" }, "KSSL"), "ov-badge ov-unchecked");
check("  shared too", overlapBadge({ label: "A", shared: true }, "KSSL"), "ov-badge ov-shared");

// a quote in a model-written label must not break out of title="..."
check("a quoted label is attribute-escaped",
      overlapBadge({ label: 'Rheinmetall "Skyranger" GmbH', koel: {} }, "KSSL"),
      (h) => h.includes("&quot;Skyranger&quot;") && h.split('title="')[1].split('"')[0].length > 20);

// a missing client name must not print "undefined's roster" at the user
check("no client name degrades to prose, not undefined",
      overlapBadge({ label: "A" }, ""), (h) => h.includes("the client") && !h.includes("undefined"));

// THE REGRESSION: the exact staging shape. 0 of 42 ties carried cid, so under the old
// two-state badge all 42 -- Rafael included -- rendered as confirmed direct partners.
const staging = [
  { label: "Rafael Advanced Defense Systems" }, { label: "Anduril Industries" },
  { label: "BAE Systems" }, { label: "Bharat Electronics Ltd. (BEL)" },
  { label: "Telephonics Corporation" }, { label: "Ultra Electronics" },
  { label: "Airbus Helicopters" },
];
check("Mahindra's 7 unmarked ties claim nothing",
      staging.every((p) => overlapState(p) === "unchecked"), true);
check("  and not one of them renders as Direct Partner",
      staging.some((p) => overlapBadge(p, "KSSL").includes("Direct Partner")), false);

// --- what the tie IS, not what kind of company the partner is -----------------
// Every card and every node read p.kind first, and kind is "Foreign OEM" / "Domestic"
// -- printed beside the country that already says it. A 51/49 JV, an MoU and a supply
// agreement all rendered identically, and the tab's whole subject appeared nowhere.
const tele = { label: "Telephonics Corporation", kind: "Foreign OEM", rel: "jv",
               ptype: "Joint Venture (51% Mahindra, 49% Telephonics)", country: "United States" };
check("the card shows the relationship, not the company category",
      tieKind(tele), "Joint Venture (51% Mahindra, 49% Telephonics)");
check("  and never falls back to kind while ptype exists",
      tieKind(tele).includes("Foreign OEM"), false);
check("a graph node gets the canonical label, not truncated free text",
      tieKindShort(tele), "Joint venture");
check("  and it fits the node", tieKindShort(tele).length <= 22, true);
check("  a long ptype with no rel is trimmed, not overflowed",
      tieKindShort({ ptype: "Licensed Component Manufacturing & Technical Data Exchange" }),
      (t) => t.length <= 22 && t.endsWith("\u2026"));

// The ten types the pipeline writes must all resolve. REL_LABEL held five, so the
// other five printed their raw key -- "rnd", "manufacturing" -- on the tab.
["supply", "manufacturing", "technology", "licensing", "rnd", "distribution", "jv",
 "integration", "strategic"].forEach((r) => {
  check(`  rel "${r}" has a label`, tieKindShort({ rel: r }),
        (t) => t !== r && t !== "Partner" && t.length > 2);
});
check("legacy rel keys still resolve", tieKindShort({ rel: "mou" }), "MoU");
check("an unknown rel with no ptype degrades to Partner", tieKind({ rel: "zzz" }), "Partner");
check("kind is the last resort, not the first", tieKind({ kind: "Foreign OEM" }), "Foreign OEM");
check("nothing at all does not throw", tieKind(null), "Partner");

console.log(fail ? `\n${fail} failed` : "\nok - the badge marks the exception, the chip names the tie");
process.exit(fail ? 1 : 0);
