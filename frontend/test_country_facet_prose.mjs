/* A COUNTRY FILTER MUST OFFER COUNTRIES.
 *
 * Reported on the Partnerships rail: "All countries (208)", and the list underneath was
 * sentences --
 *
 *     "12 commercial offices in Europe, the US and Brazil"
 *     "161 offices and production sites in more than 30 countries across Europe"
 *     "Approximately 180,000 employees in 52 countries"
 *     "Alabama", "Andhra Pradesh", "Africa"
 *
 * companyCountries checked hq against the dataset's own country vocabulary and took
 * global_locations WHOLE. That was harmless when it was written, and countryFacet.js
 * says why in its own header: "0 carry global_locations". The field is served now, so a
 * branch that was correct only because its input was empty became 208 filter options.
 *
 * The fix reads those entries for the countries they NAME, against the same vocabulary.
 * These checks are about what must NOT get in.
 */
import { companyCountries, countriesNamedIn, countryVocabulary,
         facetOptionsByName } from "./src/lib/countryFacet.js";

let fails = 0;
const ck = (name, ok, detail) => {
  console.log(`  ${String(name).padEnd(66)} ${ok ? "ok" : "FAIL"}${!ok && detail ? "  " + detail : ""}`);
  if (!ok) fails++;
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const VOCAB = new Set(["India", "Brazil", "Europe", "Israel", "South Korea", "Korea",
                       "USA", "United States", "France"]);

/* ---- the real strings from the served roster ---------------------------------- */
ck("a location line yields the country it names",
   same(countriesNamedIn("12 production units across India: Khadki", VOCAB), ["India"]));
ck("...and a sentence with several yields each",
   same(countriesNamedIn("12 commercial offices in Europe, the US and Brazil", VOCAB).sort(),
        ["Brazil", "Europe"]));

/* THE TRAP THIS DATA ACTUALLY CONTAINS: the roster carries India AND Andhra Pradesh,
   and "India" is a substring of "Indiana". A substring test files Indiana under India. */
ck("'Indiana' is not India", same(countriesNamedIn("Indiana", VOCAB), []));
ck("'Andhra Pradesh' is not a country", same(countriesNamedIn("Andhra Pradesh", VOCAB), []));
ck("'Alabama' is not a country", same(countriesNamedIn("Alabama", VOCAB), []));

/* A sentence ABOUT countries names none of them. */
ck("'employees in 52 countries' names no country",
   same(countriesNamedIn("Approximately 180,000 employees in 52 countries", VOCAB), []));
ck("'340+ facilities' names no country",
   same(countriesNamedIn("340+ facilities", VOCAB), []));

/* A multi-word country is one country, not two. */
ck("'South Korea' is one country and not also 'Korea'",
   same(countriesNamedIn("offices in South Korea", VOCAB), ["South Korea"]));

ck("empty text names nothing", same(countriesNamedIn("", VOCAB), []));
ck("an empty vocabulary admits nothing", same(countriesNamedIn("India", new Set()), []));

/* ---- end to end, through companyCountries ------------------------------------- */
const d = {
  geoData: { anduril: { USA: [{}] } },
  geoCountries: ["India", "Brazil", "Europe", "USA", "France"],
  competitors: {
    anduril: {
      hq: "Costa Mesa, California",
      global_locations: ["Approximately 180,000 employees in 52 countries",
                         "12 production units across India: Khadki",
                         "Alabama"],
    },
    plain: { hq: "Israel", global_locations: [] },
  },
};
const got = companyCountries(d, "anduril");
ck("the prose entries no longer appear as options",
   !got.some((v) => v.length > 24), JSON.stringify(got));
ck("...but the country named inside one of them does", got.indexOf("India") >= 0, JSON.stringify(got));
ck("...and the footprint country survives", got.indexOf("USA") >= 0, JSON.stringify(got));
ck("'California' is still refused, as 'Virginia' always was",
   got.indexOf("California") < 0, JSON.stringify(got));
ck("a company with no locations is unaffected",
   same(companyCountries(d, "plain"), []), JSON.stringify(companyCountries(d, "plain")));

/* The vocabulary is what makes this safe -- it comes from the dataset, never a list
   typed by hand, which check_no_fabrication would refuse. */
ck("the vocabulary is built from the dataset", countryVocabulary(d).has("India"));
ck("...and does not contain a US state", !countryVocabulary(d).has("Alabama"));

/* ---- one spelling per country -------------------------------------------------
   The fixed filter still listed "UK (8)" beside "United Kingdom (2)" and "USA (13)"
   beside "United States (8)" -- one country twice, so picking either hid the companies
   filed under the other. The winner is the spelling more companies use, not one
   chosen here. */
const spell = {
  geoData: { a: { UK: [{}] }, b: { UK: [{}] }, c: { "United Kingdom": [{}] },
             d: { USA: [{}] }, e: { "United States": [{}] } },
  geoCountries: ["UK", "United Kingdom", "USA", "United States"],
  competitors: { a: {}, b: {}, c: {}, d: {}, e: {} },
};
const opts = facetOptionsByName(["a", "b", "c", "d", "e"], (k) => companyCountries(spell, k));
ck("UK and United Kingdom are one option", opts.filter((o) => /kingdom|^UK$/i.test(o.v)).length === 1,
   JSON.stringify(opts));
ck("...and it is the spelling more companies use", opts.some((o) => o.v === "UK" && o.n === 3),
   JSON.stringify(opts));
ck("a 1-1 tie still folds, and breaks alphabetically rather than on which was seen first",
   opts.filter((o) => /^(USA|United States)$/.test(o.v)).length === 1
   && opts.some((o) => o.v === "United States" && o.n === 2), JSON.stringify(opts));
ck("a company carrying BOTH spellings counts once",
   companyCountries({ ...spell, competitors: { ...spell.competitors, z: {} },
                      geoData: { ...spell.geoData, z: { UK: [{}], "United Kingdom": [{}] } } },
                    "z").length === 1);
ck("two countries the table does not know are never folded together",
   companyCountries({ geoCountries: ["Xland", "Yland"],
                      competitors: { q: { hq: "Xland" }, r: { hq: "Yland" } } }, "q")[0] === "Xland");

console.log(fails ? `\n${fails} FAILED` : "\nok - the filter offers countries, and refuses prose, states and Indiana");
process.exit(fails ? 1 : 0);
