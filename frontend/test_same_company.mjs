/* sameCompany() joins a matchup to a roster company.

     node test_same_company.mjs

   The old test was `a.includes(b) || b.includes(a)` on normalised display names, which
   stranded 40 of 160 matchups -- a quarter of the corpus's only spec data. Every TRUE
   case below is a pair that join dropped; every FALSE case is a pair a looser rule would
   wrongly merge, which is the failure that matters more: showing one company's products
   under another's name.
*/
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./src/pages/competitive/Products.jsx", import.meta.url), "utf8");
const from = src.indexOf("function nameKey");
const to = src.indexOf("/* Product news,");
const { sameCompany } = await import(
  "data:text/javascript," + encodeURIComponent(src.slice(from, to))
);

const ok = [], bad = [];
const t = (a, b, want, why) => {
  const got = sameCompany(a, b);
  (got === want ? ok : bad).push(`${got === want ? "" : "WRONG "}${why}: ${a} <> ${b}`);
};

/* Pairs the substring join dropped. The first is taken from the LIVE roster, which
   serves this company as the bare acronym -- an earlier version of this test used a
   plausible-looking full name the roster does not actually have, so it passed while
   AWEIL stayed stranded in production. Test the strings the API serves. */
t("Advanced Weapons and Equipment India Limited", "AWEIL", true, "bare acronym (live roster)");
t("Advanced Weapons and Equipment India Limited", "Advanced Weapons & Equipment India (AWEIL)",
  true, "ampersand + trailing acronym");
t("Larsen & Toubro", "Larsen and Toubro Ltd", true, "ampersand vs 'and'");
t("Yugoimport SDPR", "Yugoimport-SDPR J.P.", true, "punctuation and legal form");
t("Mechanical and Chemical Industry Corporation", "Mechanical & Chemical Industry Corp",
  true, "abbreviated legal suffix");
t("Bharat Dynamics", "Bharat Dynamics Limited", true, "legal suffix only");
t("Saab", "Saab AB", true, "single distinctive token");

// pairs that must NOT merge
t("Bharat Dynamics", "Bharat Electronics", false, "shared first word, different company");
t("General Dynamics", "General Atomics", false, "shared generic first word");
t("Adani Defence", "Adani Ports", false, "same group, different company");
t("Tata Advanced Systems", "Tata Motors", false, "same group, different company");
t("Israel Aerospace Industries", "India Aerospace Industries", false, "one token apart");
// the noise list must not reduce a name to nothing and then match everything
t("India Limited", "Europe Holdings Ltd", false, "both are entirely noise words");
/* The live roster carries four Hanwha entries. "Hanwha Group" reduces to {hanwha},
   a subset of all its siblings, so a plain subset test listed Hanwha Aerospace's
   products under three other companies as well. */
t("Hanwha Aerospace", "Hanwha Group", false, "sibling under a group name");
t("Hanwha Aerospace", "Hanwha Ocean", false, "two siblings");
t("Hanwha Aerospace", "Hanwha Defense USA", false, "two siblings");
t("Hanwha Aerospace", "Hanwha Aerospace", true, "the same company still matches");
t("Saab", "Saab AB", true, "single token both sides, legal suffix only");

if (bad.length) {
  console.log("FAIL\n  " + bad.join("\n  "));
  process.exit(1);
}
console.log(`ok - sameCompany, ${ok.length} cases`);
