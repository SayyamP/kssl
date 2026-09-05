/* The competitor filter must answer "from where", not "recorded where".

   The bug this pins, from live data: Bharat Dynamics appeared under "France (6)".
   Its France row came from

       "Bharat Dynamics Limited produces MILAN-2T under license from
        MBDA Missile Systems, France"

   France is the LICENSOR's country. BDL builds MILAN-2T in India. Lockheed Martin
   and MBDA were in the same list for the same class of reason.

   Every fixture below is the real shape of a live row, not an invented one. */
import { companyOrigin, companyCountries } from "./src/lib/countryFacet.js";

let pass = 0, fail = 0;
const ok = (name, cond, detail = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (detail ? ": " + detail : "")); }
};

const d = {
  competitors: {
    "bharat-dynamics": { name: "Bharat Dynamics", hq: "Hyderabad, Telangana", country: "India" },
    "lockheed-martin": { name: "Lockheed Martin", hq: "Bethesda, Md, USA", country: "US" },
    "nexter":          { name: "Nexter", hq: "France", country: "France" },
    "mbda":            { name: "MBDA", hq: "Le Plessis-Robinson, France", country: "France" },
    "no-origin":       { name: "Some Rival", hq: "" },
  },
  /* the live footprint, including the row that caused the report */
  geoData: {
    "bharat-dynamics": { India: [{}], France: [{ note: "produces MILAN-2T under license from MBDA Missile Systems, France" }] },
    "lockheed-martin": { Canada: [{}], Poland: [{}], UK: [{}], USA: [{}] },
    "nexter": { Germany: [{}], Indonesia: [{}] },
  },
  geoCountries: ["India", "France", "Canada", "Poland", "UK", "USA", "Germany", "Indonesia"],
};

/* 1. the reported bug, directly */
ok("Bharat Dynamics does not read as French",
   companyOrigin(d, "bharat-dynamics") === "India",
   companyOrigin(d, "bharat-dynamics"));
ok("...even though it HAS a France footprint row",
   companyCountries(d, "bharat-dynamics").includes("France"));
ok("Lockheed Martin is US, not one of its five footprint countries",
   companyOrigin(d, "lockheed-martin") === "US",
   companyOrigin(d, "lockheed-martin"));

/* 2. origin is not the union: a company operating in Germany is still French */
ok("Nexter is French although it operates in Germany",
   companyOrigin(d, "nexter") === "France"
   && companyCountries(d, "nexter").includes("Germany"));

/* 3. origin is never guessed from an address */
ok("a hq of 'Hyderabad, Telangana' yields no country by itself",
   !companyCountries({ competitors: { x: { hq: "Hyderabad, Telangana" } } }, "x").length);
ok("an unset origin is null, not a guess",
   companyOrigin(d, "no-origin") === null, String(companyOrigin(d, "no-origin")));

/* 4. the France bucket, built the way the sidebar builds it */
const originOf = (cid) => companyOrigin(d, cid) || "Origin not established";
const france = Object.keys(d.competitors).filter((c) => originOf(c) === "France");
ok("the France option holds exactly the French companies",
   france.length === 2 && france.includes("nexter") && france.includes("mbda"),
   france.join(", "));
const unionFrance = Object.keys(d.competitors)
  .filter((c) => companyCountries(d, c).includes("France"));
ok("...where the union would have held more",
   unionFrance.length > france.length,
   "union=" + unionFrance.join(", "));

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
