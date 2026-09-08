/* The patent card: an English title, the registry facts, and one key per country.
 *
 *     node test_patent_card_info.mjs
 *
 * THREE FAULTS, ONE CARD, and every one of them invisible to a test that only asked
 * whether the page rendered.
 *
 * 1. THE TITLE WAS UNREADABLE. 169 of the 1,183 stored titles are German, French,
 *    Spanish or Korean. The tab is read in English; a title a reader cannot read is a
 *    row they cannot judge. `title_en` is the translation step's output and the card
 *    leads with it -- but the source title is the legal name the office published the
 *    invention under and the string that finds the record again, so it is kept and
 *    shown underneath. A translation that DESTROYS the original would be the worse
 *    bug, and it is the easy one to write, so it is pinned here.
 *
 * 2. THE REGISTRY FACTS COULD NOT REACH THE CARD. grant_no and pub_kind are columns on
 *    serving.patent that the backend did not select AND that normSample dropped -- two
 *    independent walls, so fixing either alone changes nothing on screen. This drives
 *    the record through searchPatents(), the same path the page uses, rather than
 *    handing patRecCard a hand-built object that would pass with the normaliser still
 *    throwing the fields away.
 *
 * 3. ONE COUNTRY, TWO KEYS. 'India' (21 rows) and 'IN' (10) are the same office, as are
 *    'US' (354) and 'USA' (2). Everything groups on the raw string, so a holder filing
 *    under both spellings was listed in two jurisdictions.
 *
 * And the honesty rule that outranks all three: a field nobody measured must never
 * render as a value. A record recorded as granted with no grant number says so; it does
 * not print an empty "Grant".
 */
import { patRecCard, searchPatents, normCountry } from "./src/lib/patents.js";
import { buildProfile } from "./src/lib/profile.js";

let fails = 0;
const ck = (name, ok, detail) => {
  console.log(`  ${name.padEnd(70)} ${ok ? "ok" : "FAIL"}${!ok && detail ? "  " + detail : ""}`);
  if (!ok) fails++;
};

const meta = { grantStatusKnown: true, relevDiscriminates: false };

// ---------------------------------------------------------------- 1. the title
const de = {
  id: "DE102015016A1",
  title: "Verfahren und Vorrichtung zur Herstellung eines Panzerungsbauteils",
  title_en: "Method and device for producing an armour component",
  status: "filed",
  filed: "2015-12-11",
};
const cardDe = patRecCard(de, false, meta);
ck("the English title is what the card leads with",
   cardDe.includes('class="pat-rec-t">Method and device for producing an armour component'),
   cardDe.slice(0, 200));
ck("... and the office's own title is still on the card",
   cardDe.includes("Verfahren und Vorrichtung zur Herstellung eines Panzerungsbauteils"));
ck("... as the secondary line, not the headline",
   /pat-title-src[^>]*>Verfahren/.test(cardDe));

const en = { id: "US1", title: "Armour plate assembly", status: "filed", filed: "2019-01-01" };
const cardEn = patRecCard(en, false, meta);
ck("an untranslated (already English) title renders exactly once",
   cardEn.split("Armour plate assembly").length === 2, cardEn);
ck("... and draws no empty source line", !cardEn.includes("pat-title-src"));

const same = { id: "US2", title: "Armour plate", title_en: "Armour plate", status: "filed" };
ck("a title the translator returned unchanged is not printed twice",
   !patRecCard(same, false, meta).includes("pat-title-src"));

// ---------------------------------------------------------------- 2. registry facts
const granted = {
  id: "US10254091", title: "Projectile", status: "granted",
  filed: "2016-06-04", published: "2018-12-20", granted: "2019-04-09",
  grant_no: "10254091", pub_kind: "B2",
};
const cardG = patRecCard(granted, false, meta);
ck("the grant number is on the card", /Grant 10254091/.test(cardG), cardG);
ck("the publication kind code is on the card", />B2</.test(cardG), cardG);
ck("both sit in the header, beside the status badge",
   /pat-rec-h[\s\S]*B2[\s\S]*Grant 10254091[\s\S]*pat-badge granted/.test(cardG));
ck("the publication date is shown as well as filing and grant",
   /Filed 2016-06-04 · Published 2018-12-20 · Granted 2019-04-09/.test(cardG), cardG);

// THE HONESTY RULE. Granted, but no number captured -- and the card must not imply one.
const noNo = { id: "KR1", title: "T", status: "granted", filed: "2018-01-01", granted: "2021-01-01" };
const cardN = patRecCard(noNo, false, meta);
ck("a grant with no number captured says so", /grant no\. not captured/.test(cardN), cardN);
ck("... visibly differently from a real one (dashed, not a value)",
   /pat-chip missing/.test(cardN) && !/Grant <\/span>/.test(cardN));
// ...and a record nobody asked about claims nothing about a kind code either way
ck("a record with no kind code draws no kind chip",
   (cardN.match(/pat-chip(?! missing)/g) || []).length === 0, cardN);

// ---------------------------------------------------------------- the normaliser path
// searchPatents -> normSample is where the fields were being dropped. Same path the page
// takes: a hand-built record handed straight to patRecCard would pass regardless.
const d = {
  PATENTS: {
    _meta: meta,
    byCompetitor: {
      c1: {
        records: [
          { id: "US10254091", title: "Projectile", title_en: "Projectile",
            status: "granted", filed: "2016-06-04", published: "2018-12-20",
            granted: "2019-04-09", grant_no: "10254091", pub_kind: "B2",
            jurisdiction: "USA" },
          { id: "IN1", title: "Kanone", title_en: "Cannon", status: "filed",
            filed: "2020-02-02", jurisdiction: "India" },
        ],
      },
    },
  },
};
const res = await searchPatents(d, { competitor: "c1" });
const [r0, r1] = res.results;
ck("normSample carries published through", r0.published === "2018-12-20", JSON.stringify(r0));
ck("normSample carries grant_no through", r0.grant_no === "10254091");
ck("normSample carries pub_kind through", r0.pub_kind === "B2");
ck("normSample carries title_en through", r1.title_en === "Cannon");
ck("normSample keeps the source title", r1.title === "Kanone");

// ---------------------------------------------------------------- 3. one country, one key
ck("normSample folds 'USA' onto the ISO code", r0.jurisdiction === "US", r0.jurisdiction);
ck("normSample folds 'India' onto the ISO code", r1.jurisdiction === "IN", r1.jurisdiction);
ck("'India' and 'IN' are one country", normCountry("India") === normCountry("IN"));
ck("'US' and 'USA' are one country", normCountry("USA") === normCountry("US"));
ck("case and padding do not make a second country", normCountry("  india ") === "IN");
ck("a two-letter code is canonicalised to upper case", normCountry("de") === "DE");
// NOTHING IS INVENTED. An office this map has never seen is passed through as it came:
// guessing a code for an unknown string would publish a jurisdiction nobody recorded.
ck("an unmapped country is passed through unchanged",
   normCountry("Chinese Taipei") === "Chinese Taipei");
ck("empty stays empty (absence is not a country)", normCountry("") === "" && normCountry(null) === "");

/* ---------------------------------------------------------- 4. the OTHER consumer
 * The company Profile panel reads the same index, and read it as a list. adaptPatents
 * builds byCompetitor[cid] as { stats, records } -- an object -- so `patents.length` was
 * undefined, the Profile's "Patents" section counted nothing for every rival that HAS
 * filings, and profileSelfCheck's array contract threw on the first one. DataProvider
 * catches that, so the whole self-check suite ended in a logged error instead of
 * "self-checks complete". A rival with no filings took the `|| []` branch and looked
 * perfect, which is why it survived: it was broken exactly where there was data.
 */
const prof = buildProfile(
  {
    competitors: { c1: { name: "Rival One", products: [], partners: [] } },
    compOrder: ["c1"],
    PATENTS: { byCompetitor: { c1: { stats: null, records: [{ id: "US1", title: "T" }] } } },
  },
  "c1",
);
ck("the profile panel gets an ARRAY of filings, as its self-check requires",
   Array.isArray(prof.patents), typeof prof.patents);
ck("... holding the records, not the index entry",
   prof.patents.length === 1 && prof.patents[0].id === "US1", JSON.stringify(prof.patents));
ck("... so the Profile's Patents section counts them",
   prof.sections.find((x) => x.key === "patents").rows === 1,
   JSON.stringify(prof.sections.find((x) => x.key === "patents")));

console.log(fails ? `\ntest_patent_card_info: ${fails} FAILED` : "\ntest_patent_card_info: ok");
process.exit(fails ? 1 : 0);
