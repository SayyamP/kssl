/* revenueOf: the panel's Annual revenue / sales string.
   Mirrors Profile.jsx so the contract is testable without a browser. */
const DASH = "—";
const firstValue = (v) => {
  if (!v) return null;
  if (Array.isArray(v)) {
    const hit = v.find((x) => x && (typeof x === "string" ? x.trim() : x.value));
    if (!hit) return null;
    return typeof hit === "string" ? hit : hit.value || null;
  }
  return typeof v === "string" ? v.trim() || null : null;
};
const revenueOf = (v) => {
  if (!Array.isArray(v) || !v.length) return firstValue(v);
  const hit = v.find((x) => x && (typeof x === "string" ? x.trim() : x.value));
  if (!hit) return null;
  if (typeof hit === "string") return hit.trim() || null;
  const d = String(hit.detail || "").trim();
  const fy = d.match(/(?:FY\s*-?\s*)?20\d\d\s*[-/]\s*\d{2,4}/i);
  const yr = d.match(/20\d\d/);
  const period = fy ? fy[0].replace(/\s+/g, " ") : yr ? yr[0] : null;
  return period ? `${hit.value} (${period})` : hit.value || null;
};
let n = 0;
const eq = (got, want, why) => {
  if (got !== want) { console.error(`FAIL ${why}\n  got  ${got}\n  want ${want}`); process.exit(1); }
  n++; console.log(`  ok  ${why}`);
};
/* the two figures a live harvest produced, in the shape promote.py writes */
eq(revenueOf([{ value: "EUR 1,086.7 million", detail: "in 2025",
                url: "https://www.patriagroup.com/about-us/patria-in-brief", line: "..." }]),
   "EUR 1,086.7 million (2025)", "Patria: amount carries its reporting year");
eq(revenueOf([{ value: "€4.4 billion", detail: "in 2025", url: "https://knds.com/en/about-us", line: "..." }]),
   "€4.4 billion (2025)", "KNDS: non-ASCII currency symbol survives");
eq(revenueOf([{ value: "Rs. 1,250 crore", detail: "FY 2024-25", url: "u", line: "l" }]),
   "Rs. 1,250 crore (FY 2024-25)", "Indian FY shown verbatim, not halved to 2024");
/* newest first is the extractor's contract; the panel renders entry [0] */
eq(revenueOf([{ value: "EUR 1,100 million", detail: "in 2025", url: "u", line: "l" },
              { value: "EUR 900 million", detail: "in 2023", url: "u", line: "l" }]),
   "EUR 1,100 million (2025)", "latest of several annual figures wins");
/* MISSING DATA MUST NOT BREAK THE PAGE - every shape the API can emit */
eq(revenueOf([]) || DASH, DASH, "empty array -> dash");
eq(revenueOf(null) || DASH, DASH, "null -> dash");
eq(revenueOf(undefined) || DASH, DASH, "undefined -> dash");
eq(revenueOf([{ value: "", detail: "in 2025" }]) || DASH, DASH, "blank value -> dash");
eq(revenueOf([{ value: "$5 billion", detail: "" }]), "$5 billion", "no period -> amount alone, no fake year");
eq(revenueOf(["Rs. 900 crore"]), "Rs. 900 crore", "legacy bare-string shape still renders");
console.log(`\nall ${n} revenue-meta checks passed`);
