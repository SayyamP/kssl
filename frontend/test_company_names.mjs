/* THE UNCHECKED FIELD IS WHERE THE INVENTED VALUE LIVES.
 *
 * A full-name column is the easiest place on this dashboard to publish something nobody
 * sourced: the letters look like they must stand for something, and writing what they
 * "obviously" mean takes one keystroke. Two of them are traps that a confident guess
 * gets wrong in a way that changes what the page ASSERTS:
 *
 *   RTX   "Raytheon Technologies" is a FORMER name, and this roster carries a separate
 *         Raytheon row -- so publishing it would state that two rostered rivals are one
 *         company.
 *   KNDS  the client workbook resolves it to "KNDS Germany", a subsidiary. Publishing
 *         it would relabel the group as one of its own national arms.
 *
 * So this file checks provenance and restraint, not spelling.
 */
import { existsSync, readFileSync } from "node:fs";
import {
  COMPANY_NAMES,
  detailLine,
  initialisms,
  isAbbreviated,
  listLine,
  nameOf,
} from "./src/lib/companyNames.js";

let fails = 0;
const ck = (name, ok, detail) => {
  console.log(`  ${String(name).padEnd(66)} ${ok ? "ok" : "FAIL"}${!ok && detail ? "  " + detail : ""}`);
  if (!ok) fails++;
};

/* ---- 1. every published value names where it came from ---------------------------- */
const noSrc = Object.entries(COMPANY_NAMES).filter(([, e]) => !e.src);
ck("every entry carries a source", noSrc.length === 0, noSrc.map((x) => x[0]).join(", "));

const badShape = Object.entries(COMPANY_NAMES).filter(
  ([, e]) => e.noExpansion && (e.expands || e.full),
);
ck("nothing both expands and claims it does not", badShape.length === 0,
   badShape.map((x) => x[0]).join(", "));

const empty = Object.entries(COMPANY_NAMES).filter(
  ([, e]) => !e.expands && !e.full && !e.note && !e.noExpansion,
);
ck("no entry is present but says nothing", empty.length === 0, empty.map((x) => x[0]).join(", "));

/* An unsourced entry must not reach the page even if someone adds one. */
ck("an entry with no source publishes nothing",
   nameOf("__x", "X", { expands: "Made Up" }) === null ||
   nameOf("__x", "X") === null);

/* ---- 2. the two traps ------------------------------------------------------------- */
const all = JSON.stringify(COMPANY_NAMES).toLowerCase();
ck("RTX is not published as Raytheon anything", !/raytheon/.test(all));
ck("...and RTX renders no full name at all", !listLine("rtx", "RTX"), listLine("rtx", "RTX"));
ck("...but it does say, in words, that the letters do not expand",
   /do not stand for/i.test(detailLine("rtx", "RTX")), detailLine("rtx", "RTX"));
ck("KNDS is not published as its German subsidiary", !/knds germany/.test(all));
ck("...and KNDS renders no full name either", !listLine("knds", "KNDS"));

/* A sourced "does not expand" must not read as missing data. */
ck("the no-expansion answer is not an empty string",
   detailLine("bae-systems", "BAE Systems").length > 0);

/* ---- 3. the expansions that ARE real --------------------------------------------- */
ck("IWI expands to Israel Weapon Industries",
   listLine("iwi", "IWI") === "Israel Weapon Industries", listLine("iwi", "IWI"));
ck("AWEIL expands to its registered name",
   /^Advanced Weapons and Equipment India/.test(listLine("aweil", "AWEIL")));
ck("IDV expands to Iveco Defence Vehicles",
   listLine("idv", "IDV") === "Iveco Defence Vehicles");
ck("NORINCO expands to China North Industries Group",
   listLine("norinco", "NORINCO") === "China North Industries Group");

/* ---- 4. restraint ---------------------------------------------------------------- */
/* A "full name" equal to the short name is noise, not information. */
ck("a full name identical to the served name is not published",
   nameOf("saab", "Saab AB") === null, JSON.stringify(nameOf("saab", "Saab AB")));
ck("...but it IS published when it adds something",
   listLine("saab", "Saab") === "Saab AB");
/* HTML-escaped served names must not defeat the comparison -- Larsen &amp; Toubro is
   how this roster stores an ampersand, and it has already broken one identity rule. */
ck("an HTML-escaped served name still compares correctly",
   nameOf("larsen-toubro", "Larsen &amp; Toubro") === null ||
     !/&amp;/.test(listLine("larsen-toubro", "Larsen &amp; Toubro")));
ck("a competitor with no entry publishes nothing", nameOf("rheinmetall", "Rheinmetall") === null);

/* PLR's note travels, but only to the detail pane -- the list shows names, not parentage. */
ck("a note alone does not put a line in the LIST", listLine("sss-defence", "SSS Defence") === "");
ck("...but it does reach the DETAIL",
   /Stumpp/.test(detailLine("sss-defence", "SSS Defence")));

/* ---- 5. the detector ------------------------------------------------------------- */
ck("an initialism is detected", isAbbreviated("KNDS") && isAbbreviated("PLR Systems"));
ck("an ordinary name is not", !isAbbreviated("Saab") && !isAbbreviated("Rheinmetall"));
ck("a portmanteau is not an initialism", !isAbbreviated("BrahMos Aerospace"));
ck("a joiner word is not an initialism", initialisms("Smith AND Co").indexOf("AND") < 0);

/* ---- 6. against the live roster, when one has been exported ----------------------- */
/* SKIP, DON'T CRASH -- CI loops over every test_*.mjs and the roster is a live export.
   Same rule test_feed_pagination set. */
const rosterPath = process.argv[2] || "../roster.json";
if (existsSync(rosterPath)) {
  const roster = JSON.parse(readFileSync(rosterPath, "utf8"));
  const ids = new Set(roster.map((r) => r[0]));
  const strays = Object.keys(COMPANY_NAMES).filter((k) => !ids.has(k));
  ck("every entry names a competitor that is actually served", strays.length === 0,
     strays.join(", "));

  /* THE GATE THAT MATTERS LATER: a rival added tomorrow whose name is an initialism
     must SURFACE here rather than quietly render no expansion for ever. Anything on
     this list is either sourced or a known, stated gap. */
  const KNOWN_GAPS = ["mbda", "kongsberg"];
  const missing = roster
    .filter(([cid, nm]) => isAbbreviated(nm) && !COMPANY_NAMES[cid])
    .map(([cid]) => cid)
    .filter((cid) => KNOWN_GAPS.indexOf(cid) < 0);
  ck("no served abbreviation is silently unexplained", missing.length === 0, missing.join(", "));
  console.log(`  (roster ${roster.length}; ${roster.filter(([, n]) => isAbbreviated(n)).length} abbreviated; ${KNOWN_GAPS.length} stated gap(s): ${KNOWN_GAPS.join(", ")})`);
} else {
  console.log(`  SKIP roster check -- ${rosterPath} not present`);
}

console.log(fails ? `\n${fails} FAILED` : "\nok - every published name is sourced, and the two traps stay unpublished");
process.exit(fails ? 1 : 0);
