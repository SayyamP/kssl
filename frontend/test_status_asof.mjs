/* "active" from a 2010 article is not "active today".
 *
 * Oshkosh Defense and General Dynamics Land Systems-Canada "have teamed up" for the
 * Canadian TAPV programme -- read out of a 2010 article, stored `active`, and drawn
 * on the graph identically to a tie read last week. Textron won TAPV in 2012. The
 * enrichment stamps the document's own date on every tie; until this, nothing read it.
 *
 *   node frontend/test_status_asof.mjs        (no build, no browser)
 */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./src/lib/partners.js", import.meta.url), "utf8");
// lift the two helpers out of the module rather than importing it: partners.js pulls in
// the whole dataset layer, and this is about one function's arithmetic.
const start = src.indexOf("const STALE_YEARS");
const end = src.indexOf("const CONF_TAG");
if (start < 0 || end < 0) {
  console.log("FAIL could not lift statusTag out of partners.js");
  process.exit(1);
}
const esc = (s) => String(s);
const body = src.slice(start, end).replace(/^const statusTag =/m, "var statusTag =");
const statusTag = new Function("esc", body + "\nreturn statusTag;")(esc);

const YEAR = new Date().getFullYear();
let fail = 0;
const check = (name, got, want) => {
  const ok = typeof want === "string" ? got.includes(want) : want(got);
  console.log(`  ${ok ? "ok  " : "FAIL"} ${name}${ok ? "" : `\n    got ${JSON.stringify(got)}`}`);
  if (!ok) fail++;
};

// THE CASE THIS EXISTS FOR.
check("a 2010 article does not assert a live alliance",
      statusTag({ status: "active", as_of: "2010-03-15" }), "last seen 2010");
check("  and it says so in the title attribute",
      statusTag({ status: "active", as_of: "2010" }), "Nothing since says");
check("  and carries the stale class, not the live one",
      statusTag({ status: "active", as_of: "2010" }), "tie-tag stale");

// A recent article may say active, and shows when.
check("this year's article reads as current",
      statusTag({ status: "active", as_of: `${YEAR}-01-02` }), `as of ${YEAR}`);
check("last year's too", statusTag({ status: "active", as_of: `${YEAR - 1}` }),
      `as of ${YEAR - 1}`);
// The boundary: two years is stale.
check("two years old is stale", statusTag({ status: "active", as_of: `${YEAR - 2}` }),
      "last seen");

// ENDED DOES NOT GO STALE. The source says it is over; age changes nothing.
check("an ended tie still says ended, whatever its age",
      statusTag({ status: "ended", ended: "2013", as_of: "2009" }), "ended 2013");
check("  and never says last seen",
      statusTag({ status: "ended", ended: "2013", as_of: "2009" }),
      (s) => !s.includes("last seen"));

// Announced carries its year; an old announcement is a stale one.
check("a recent announcement shows its year",
      statusTag({ status: "announced", as_of: `${YEAR}` }), `announced ${YEAR}`);
check("an old announcement is stale, not announced",
      statusTag({ status: "announced", as_of: "2011" }), "last seen 2011");

// No date is not a crash, and must not invent currency.
check("no as_of renders no date", statusTag({ status: "active" }), (s) => s === "");
check("a junk as_of is ignored", statusTag({ status: "active", as_of: "n/d" }),
      (s) => s === "");
check("a null tie is survivable", statusTag(null), (s) => s === "");

console.log();
if (fail) { console.log(`${fail} failure(s)`); process.exit(1); }
console.log("ok - a tie is only ever active as of the article it was read from");
