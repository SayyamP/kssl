/* A count and the list it labels are one expression.
 *
 *     node test_filter_counts.mjs
 *
 * Acceptance findings FE 14, FE 10 and T 3, observed live: a country filter that
 * advertised 49 countries and offered 5; a tender filter whose options and counts did
 * not describe the rows beneath them; a competitor list with no country filter at all.
 *
 * Each was the same defect. The number a surface advertises was computed from one
 * source (the geo footprint; every tender; a config vocabulary) while the dropdown was
 * built from another (an hq string split on a comma; the rows of the open tab), so the
 * two disagreed and the reader could not tell which one lied. This renders the real
 * pages against a fixture and holds every filter to three things:
 *
 *   1. the number in the "All ..." label equals the number of options under it;
 *   2. every option matches at least one listed row -- nothing is padded in from a
 *      config list or a vocabulary (no "Kenya" over a corpus with no Kenyan tender);
 *   3. every value the listed rows carry is offered -- nothing is dropped because it
 *      came from a column the option builder did not read.
 *
 * And, from the same finding: a closing date reads as a DATE, in one format, on every
 * surface that prints one -- never "2 days left" in a slot every other card fills with
 * "11 Aug 2026".
 *
 * Hermetic: the pages are bundled with esbuild (a dependency of vite, so present after
 * npm ci) and server-rendered with the two state hooks stubbed. No network, no dataset
 * dump, no browser.
 */
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };
const ok = (m) => console.log("  ok   " + m);

/* ---------------------------------------------------------------- fixture ---- */
const co = (name, over) => ({
  name, dir: "rival", sector: null, hq: null, threat: "watch", assess: "", updates: [],
  center: null, partners: [], site: null, srcs: [], products: [], threatNote: "",
  leadership: [], facilities: [], sales: [], ...over,
});
const row = (name) => [{ name, c: "sv", val: null, since: null, qty: null, stage: null, note: "", src: "" }];
const tender = (id, over) => ({
  id, title: `Tender ${id}`, issuer: "A Ministry", country: "India", cat: "Artillery",
  value: null, qty: null, deadline: null, dl: null, reqNote: null, req: [], matches: [],
  lean: null, leanTxt: null, status: "open", url: `https://example.test/${id}`,
  urlKind: "tender", srcs: [{ url: `https://example.test/${id}`, label: "Example" }], ...over,
});

export const fixture = {
  POS_CATS: [["art", "Artillery"], ["ammo", "Ammunition"], ["sa", "Small Arms"]],
  CAT_KEY: { Artillery: "art", Ammunition: "ammo", "Small Arms": "sa" },
  client: { id: "client-co", name: "Client Co", short: "CC" },
  compOrder: ["alpha", "beta", "gamma", "delta", "client-co"],
  competitors: {
    /* hq names a country the dataset knows, and the footprint adds a second */
    alpha: co("Alpha Systems", { sector: "Artillery", hq: "Paris, France" }),
    /* no hq at all: only the footprint says where it is */
    beta: co("Beta Dynamics", { sector: "Ammunition" }),
    /* hq tail is a REGION -- "Virginia" is not a country and must not be offered */
    gamma: co("Gamma Defense", { sector: "artillery", hq: "Arlington, Virginia" }),
    /* hq with no comma: the whole string is the country */
    delta: co("Delta Arms", { sector: "Small Arms", hq: "Israel" }),
    "client-co": co("Client Co", { dir: "client", sector: "Artillery", hq: "Pune, India" }),
  },
  geoComps: [
    { id: "alpha", name: "Alpha Systems", dir: "rival", hq: null, isBf: false },
    { id: "beta", name: "Beta Dynamics", dir: "rival", hq: null, isBf: false },
    { id: "gamma", name: "Gamma Defense", dir: "rival", hq: null, isBf: false },
    { id: "client-co", name: "Client Co", dir: "client", hq: null, isBf: true },
  ],
  geoData: {
    alpha: { France: row("Alpha plant"), Germany: row("Alpha office") },
    beta: { India: row("Beta JV") },
    gamma: { USA: row("Gamma HQ") },
    "client-co": { India: row("Client works") },
  },
  geoCountries: ["India", "France", "Germany", "USA", "Israel"],
  /* a config vocabulary that names a country NO tender carries */
  tpAllCountries: ["Kenya", "India", "Canada"],
  tpAllCats: ["Artillery", "Ammunition", "Armoured Vehicle MRO"],
  tenders: [
    tender("t-open-in", { deadline: "1 Sep 2031" }),
    tender("t-open-ca", { country: "Canada", cat: "Ammunition", deadline: "22 Jun 2031", value: "EUR 4.0m" }),
    tender("t-open-ca2", { country: "Canada", cat: "Marine / Naval" }),
    tender("t-closed-in", { deadline: "1 Jan 2020" }),
    tender("t-award-be", { country: "Belgium", cat: "Ammunition", status: "awarded", urlKind: "award" }),
  ],
  matchups: {
    m1: { cat: "Artillery", anchor: "Gun A", comp: "Alpha Systems · Howitzer X", compBy: "Alpha Systems", bf: "CC · Gun A", country: "France", specs: [], srcs: [], global: null, dir: "watch" },
    m2: { cat: "Ammunition", anchor: "Shell B", comp: "Beta Dynamics · Round Y", compBy: "Beta Dynamics", bf: "CC · Shell B", country: "India", specs: [], srcs: [], global: null, dir: "watch" },
  },
  details: {},
  competitiveCards: [],
  marketCards: [],
  techCards: [],
  overviewConfig: { competitive: {}, market: { cnt: "0 demand signals" }, technology: {} },
  techCats: [], innovations: {}, techAreaMeta: {}, competitorNews: {},
  KSSL_PARTNERS: [], PATENTS: null, sourceRegistry: [], companySources: {},
};

/* What the fixture's rows actually carry, written out by hand so the oracle is not the
   code under test. Rivals only -- the client's own row is not a competitor. */
const WANT = {
  companyCountries: ["France", "Germany", "India", "Israel", "USA"],
  companyCategories: ["Ammunition", "Artillery", "Small Arms"],
  openTenderCountries: { Canada: 2, India: 1 },
  openTenderCats: { Ammunition: 1, Artillery: 1, "Marine / Naval": 1 },
};

/* ---------------------------------------------------------- render pages ---- */
const here = resolve(new URL(".", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const tmp = mkdtempSync(join(tmpdir(), "kssl-filter-test-"));
const stubs = {
  DataProvider: `export function useData() { return globalThis.__KSSL_TEST__; }`,
  AppState: `export function useAppState() {
    return { searchQuery: "", setScope() {}, takePending() { return null; }, jumpTo() {},
             pillar: "competitive", view: "products", setView() {}, setChatCtx() {} };
  }
  export const RAIL = {}; export const PILLARS = []; export const isOverview = () => false;`,
};
const entry = `
  import React from "react";
  import { renderToStaticMarkup } from "react-dom/server";
  import Products from "./src/pages/competitive/Products.jsx";
  import Profile from "./src/pages/competitive/Profile.jsx";
  import Partnerships from "./src/pages/competitive/Partnerships.jsx";
  import Tenders from "./src/pages/market/Tenders.jsx";
  import MarketOverview from "./src/pages/market/MarketOverview.jsx";
  import { createGeo } from "./src/lib/geo.js";
  import { createPartners } from "./src/lib/partners.js";
  export function render(data) {
    /* the same value shape DataProvider builds, minus the fetch */
    globalThis.__KSSL_TEST__ = { data, gapModel: [], geo: createGeo(data),
                                 partners: createPartners(data), counts: {}, viewMeta: {} };
    const r = (el) => renderToStaticMarkup(el);
    return {
      products: r(React.createElement(Products)),
      profile: r(React.createElement(Profile)),
      partnerships: r(React.createElement(Partnerships)),
      tenders: r(React.createElement(Tenders, { mode: "tender" })),
      market: r(React.createElement(MarketOverview)),
    };
  }`;
const out = join(tmp, "pages.mjs");
await build({
  stdin: { contents: entry, resolveDir: here, loader: "jsx" },
  bundle: true, platform: "node", format: "esm", jsx: "automatic", outfile: out,
  logLevel: "silent", loader: { ".css": "empty" },
  /* react-dom/server requires node builtins by name; an ESM bundle needs a require */
  banner: { js: 'import { createRequire as __cr } from "node:module"; const require = __cr(import.meta.url);' },
  plugins: [{
    name: "stub-state",
    setup(b) {
      b.onResolve({ filter: /state\/(DataProvider|AppState)$/ }, (a) => ({
        path: a.path.replace(/.*\//, ""), namespace: "stub",
      }));
      b.onLoad({ filter: /.*/, namespace: "stub" }, (a) => ({ contents: stubs[a.path], loader: "js" }));
    },
  }],
});
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { location: { hash: "" }, addEventListener() {}, removeEventListener() {} };
globalThis.document = { addEventListener() {}, removeEventListener() {} };

const { wireDataset } = await import("./src/lib/dataset.js");
const { render } = await import(pathToFileURL(out).href);
const data = wireDataset(JSON.parse(JSON.stringify(fixture)));
const html = render(data);
rmSync(tmp, { recursive: true, force: true });

/* ------------------------------------------------------------- readers ---- */
const unesc = (s) => s.replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/&quot;/g, '"');
/* a <select aria-label="..."> -> its option texts, first one being the "All" label */
const selectOptions = (page, label) => {
  const m = html[page].match(new RegExp(`<select[^>]*aria-label="${label}"[^>]*>([\\s\\S]*?)</select>`));
  if (!m) return null;
  return [...m[1].matchAll(/<option[^>]*>([^<]*)<\/option>/g)].map((o) => unesc(o[1]).trim());
};
/* the tender page's custom menu -> its row texts and whether a row is greyed out */
const menuRows = (page, which) => {
  const m = html[page].match(new RegExp(`data-tpdd="${which}"[\\s\\S]*?<div class="tp-dd-menu[^"]*">([\\s\\S]*?)(?=<div class="tp-dd" data-tpdd=|<span class="sortnote")`));
  if (!m) return null;
  return [...m[1].matchAll(/<div class="tp-dd-pick( tp-dd-all)?( zero)?"[^>]*>([\s\S]*?)<\/div>/g)].map((r) => ({
    text: unesc(r[3].replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim(),
    all: !!r[1], zero: !!r[2],
  }));
};
const advertised = (text) => {
  const m = /\((\d+)\)/.exec(text || "");
  return m ? Number(m[1]) : null;
};
/* "France (3)", "France · 3", "France 3", "Kenya —" -> "France" */
const optionName = (text) => text.replace(/\s*(\(\d+\)|·\s*\d+|\d+|—)\s*$/, "").trim();
const optionCount = (text) => { const m = /\((\d+)\)\s*$/.exec(text); return m ? Number(m[1]) : null; };

/* ------------------------------------------------------- 1. company pages ---- */
for (const [page, label, want, what] of [
  ["products", "Filter companies by country", WANT.companyCountries, "country"],
  ["profile", "Filter competitors by country", WANT.companyCountries, "country"],
  ["partnerships", "Filter competitors by country", WANT.companyCountries, "country"],
  ["products", "Filter companies by category", WANT.companyCategories, "category"],
]) {
  const opts = selectOptions(page, label);
  if (!opts) { fail(`${page}: no ${what} filter (aria-label "${label}")`); continue; }
  const [all, ...rest] = opts;
  const n = advertised(all);
  if (n == null) fail(`${page} ${what}: the "All" option advertises no count ("${all}")`);
  else if (n !== rest.length) fail(`${page} ${what}: advertises ${n}, offers ${rest.length}`);
  else ok(`${page} ${what}: "${all}" over ${rest.length} options`);
  const names = rest.map(optionName);
  const missing = want.filter((w) => !names.includes(w));
  const padded = names.filter((x) => !want.includes(x));
  if (missing.length) fail(`${page} ${what}: rows carry ${JSON.stringify(missing)} but the filter does not offer them`);
  if (padded.length) fail(`${page} ${what}: offers ${JSON.stringify(padded)}, which no listed row carries`);
  if (!missing.length && !padded.length) ok(`${page} ${what}: options are exactly what the rows carry`);
}

/* ------------------------------------------------------ 2. tender pipeline ---- */
for (const [which, want] of [["country", WANT.openTenderCountries], ["cat", WANT.openTenderCats]]) {
  const rows = menuRows("tenders", which);
  if (!rows) { fail(`tenders: no ${which} menu`); continue; }
  const all = rows.find((r) => r.all);
  const items = rows.filter((r) => !r.all);
  const n = advertised(all && all.text);
  if (n == null) fail(`tenders ${which}: the "All" row advertises no count ("${all && all.text}")`);
  else if (n !== items.length) fail(`tenders ${which}: advertises ${n}, offers ${items.length}`);
  else ok(`tenders ${which}: "${all.text}" over ${items.length} options`);
  const zero = items.filter((r) => r.zero || /\b0\s*$/.test(r.text));
  if (zero.length) fail(`tenders ${which}: ${JSON.stringify(zero.map((r) => r.text))} offered with no rows behind them`);
  const got = Object.fromEntries(items.map((r) => [optionName(r.text), Number((r.text.match(/(\d+)\s*$/) || [])[1])]));
  for (const [k, v] of Object.entries(want)) {
    if (got[k] !== v) fail(`tenders ${which}: ${k} should count ${v}, got ${got[k]}`);
  }
  const padded = Object.keys(got).filter((k) => !(k in want));
  if (padded.length) fail(`tenders ${which}: offers ${JSON.stringify(padded)}, which no open tender carries`);
  if (!padded.length && Object.entries(want).every(([k, v]) => got[k] === v)) ok(`tenders ${which}: every option counts its own rows`);
}

/* -------------------------------------------------------- 3. market report ---- */
{
  const opts = selectOptions("market", "Filter by country");
  if (!opts) fail("market: no country filter");
  else {
    const [all, ...rest] = opts;
    const n = advertised(all);
    const want = Object.keys(WANT.openTenderCountries).sort();
    if (n !== rest.length) fail(`market country: advertises ${n} ("${all}"), offers ${rest.length}`);
    const names = rest.map(optionName);
    if (JSON.stringify(names) !== JSON.stringify(want))
      fail(`market country: offers ${JSON.stringify(names)}, the open rows carry ${JSON.stringify(want)}`);
    else if (n === rest.length) ok(`market country: "${all}" over exactly the open rows' countries`);
    const counts = rest.map(optionCount);
    if (counts.some((c) => c == null)) fail("market country: an option carries no row count");
    else if (counts.some((c, i) => c !== WANT.openTenderCountries[names[i]]))
      fail(`market country: counts ${JSON.stringify(counts)} disagree with the rows`);
  }
}

/* ---------------------------------------------------------- 4. closing dates ---- */
{
  const DATE = /^\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}$/;
  /* the promoted tender cards in the market feed: the date slot and the Closing fact */
  const cards = (data.marketCards || []).filter((c) => c.id.startsWith("tender_"));
  if (!cards.length) fail("no tender was promoted into the market feed");
  for (const c of cards) {
    const t = data.tenders.find((x) => `tender_${x.id}` === c.id);
    const det = data.details[c.id] || {};
    const closing = (det.facts || []).find((f) => f[0] === "Closing");
    if (t.closingDate) {
      if (!DATE.test(c.ago)) fail(`market card ${c.id}: date slot reads "${c.ago}", not a date`);
      if (!closing || !DATE.test(closing[1])) fail(`market card ${c.id}: Closing fact reads "${closing && closing[1]}", not a date`);
      if (/days? left|closes in/i.test(c.sowhat)) fail(`market card ${c.id}: so-what carries a countdown: "${c.sowhat}"`);
    } else {
      if (closing) fail(`market card ${c.id}: has a Closing fact ("${closing[1]}") with no closing date on record`);
      if (c.ago) fail(`market card ${c.id}: date slot reads "${c.ago}" with no closing date on record`);
    }
  }
  if (cards.length && !bad) ok(`market feed: ${cards.length} promoted tenders carry a real date or none`);
  /* the tender pipeline card prints the closing date, formatted once */
  const printed = [...html.tenders.matchAll(/Closes (\d{1,2} \w+ \d{4})/g)].map((m) => m[1]);
  if (printed.length !== 2) fail(`tenders: expected 2 cards to print a closing date, found ${printed.length}`);
  for (const p of printed) if (!DATE.test(p)) fail(`tenders: closing date "${p}" is not in house format`);
  /* the market report's Closes column */
  const cells = [...html.market.matchAll(/<td class="num">([^<]*)<\/td>/g)].map((m) => m[1]).filter((v) => /\d{4}/.test(v));
  for (const v of cells) if (!DATE.test(v)) fail(`market report: Closes cell "${v}" is not in house format`);
  /* the formatter itself never emits ICU's "Sept" and passes a descriptive value through */
  const { formatDate } = await import("./src/utils/formatDate.js");
  const cases = [["1 Sep 2026", "1 Sep 2026"], ["2026-09-05", "5 Sep 2026"], ["22 Jun 2026", "22 Jun 2026"],
                 ["01 Sept 2026", "1 Sep 2026"], ["Q4 2026 expected", "Q4 2026 expected"], [new Date(2026, 8, 1), "1 Sep 2026"]];
  for (const [inp, want] of cases) {
    const got = formatDate(inp);
    if (got !== want) fail(`formatDate(${JSON.stringify(inp)}) = ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  }
}

if (bad) {
  console.log(`\nFAIL - ${bad} filter/count invariant(s) broken`);
  process.exit(1);
}
console.log("\nok - every advertised count is the length of the list it labels");
