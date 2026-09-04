/* Every tender row exposes the SAME parameters, in the SAME order, and says so when
 * one is not on record.
 *
 *     node test_tender_row.mjs
 *
 * REPORTED: "many have a small basic title, no understanding ... fix per tender row
 * parameters, resolve from each tender and show a consistent flow".
 *
 * Measured on the served corpus (136 tenders, 2026-09-05): the median title is 29
 * characters, 40 titles are 20 characters or fewer and 50 are three words or fewer --
 * "Ammunition", "Firearms", "Eb Tuba". The card under such a title used to print only
 * the fields that happened to be filled, so one row read "buyer · country · category ·
 * value · qty · closes" and the next read "buyer · country · category", and the reader
 * could not tell a field the notice does not publish from one the card forgot.
 *
 * What this pins, on the resolver (src/lib/tenderRow.js) and on the rendered page:
 *
 *   1. FIXED SHAPE: every tender resolves to the same parameter keys in the same order,
 *      whatever the record carries;
 *   2. UNRESOLVED IS EXPLICIT: a parameter the record cannot fill renders the literal
 *      unresolved state with its own class -- never an empty value cell, and never a
 *      guessed value (an empty status is not "Open"; an empty value is not "0");
 *   3. FALLBACK CHAIN: each parameter is drawn from the documented source, in the
 *      documented order, and a computed countdown is never mistaken for a stored date;
 *   4. THE TITLE IS THE STORED TITLE: nothing is composed into it.
 *
 * Hermetic: the resolver is imported directly; the page is bundled with esbuild and
 * server-rendered with the two state hooks stubbed. No network, no dataset dump.
 */
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };
const ok = (m) => console.log("  ok   " + m);

const { resolveTenderRow, TENDER_PARAMS, NOT_ON_RECORD } = await import("./src/lib/tenderRow.js");
const { wireTendersWithRealDays } = await import("./src/lib/tenderCalc.js");

/* ---------------------------------------------------------------- fixture ---- */
/* The shape serving.tender emits. Every optional field starts EMPTY so a test names
   exactly what it fills. */
const tender = (id, over) => ({
  id, title: `Tender ${id}`, issuer: "", country: "", cat: "", value: null, qty: null,
  deadline: null, dl: null, reqNote: null, req: [], matches: [], lean: null,
  leanTxt: null, status: "", url: "", urlKind: "tender", srcs: [], stage: null, ...over,
});

const WANT_KEYS = ["buyer", "country", "category", "value", "quantity", "closing", "status", "source"];

/* ------------------------------------------------------ 1. fixed shape ---- */
{
  const keys = TENDER_PARAMS.map((p) => p.key);
  if (JSON.stringify(keys) !== JSON.stringify(WANT_KEYS))
    fail(`TENDER_PARAMS is ${JSON.stringify(keys)}, want ${JSON.stringify(WANT_KEYS)}`);
  else ok("TENDER_PARAMS is the documented eight, in order");

  const full = tender("full", {
    issuer: "A Ministry", country: "India", cat: "Artillery", value: "EUR 4.0m",
    qty: "20 units", deadline: "22 Jun 2031", status: "open", url: "https://example.test/full",
    srcs: [{ url: "https://example.test/full", label: "Example Portal" }],
  });
  const empty = tender("empty");
  for (const t of [full, empty, { id: "bare" }, null]) {
    const row = resolveTenderRow(t);
    const keys = row.params.map((p) => p.key);
    if (JSON.stringify(keys) !== JSON.stringify(WANT_KEYS))
      fail(`resolveTenderRow(${t && t.id}) exposes ${JSON.stringify(keys)}`);
  }
  ok("a full record, an empty record, a bare {id} and null all resolve to the same eight keys");
}

/* -------------------------------------------------- 2. unresolved state ---- */
{
  const row = resolveTenderRow(tender("empty"));
  for (const p of row.params) {
    if (p.value !== null) fail(`empty record: ${p.key} resolved to ${JSON.stringify(p.value)} -- a guess`);
    if (p.text !== NOT_ON_RECORD) fail(`empty record: ${p.key} prints ${JSON.stringify(p.text)}, want the unresolved literal`);
    if (p.from !== null) fail(`empty record: ${p.key} claims source ${JSON.stringify(p.from)}`);
  }
  if (!/not on record/.test(NOT_ON_RECORD)) fail(`NOT_ON_RECORD is ${JSON.stringify(NOT_ON_RECORD)} -- it must SAY the field is absent`);
  ok("an empty record resolves every parameter to the unresolved literal, from no source");

  /* the two guesses the old code made */
  const s = resolveTenderRow(tender("nostatus", { issuer: "X" })).params.find((p) => p.key === "status");
  if (s.value !== null) fail(`empty status was resolved to ${JSON.stringify(s.value)} -- the old default of "Open" is a guess`);
  else ok("an empty status is not defaulted to Open");
  const v = resolveTenderRow(tender("noval", { value: "" })).params.find((p) => p.key === "value");
  if (v.value !== null) fail(`blank value resolved to ${JSON.stringify(v.value)}`);
  else ok("a blank value is unresolved, not zero");
}

/* ---------------------------------------------------- 3. fallback chain ---- */
const pick = (t, key) => resolveTenderRow(t).params.find((p) => p.key === key);
{
  /* buyer: issuer, else a req row that names the buying authority */
  let p = pick(tender("b1", { issuer: "Direct Buyer", req: [["Buyer", "Req Buyer"]] }), "buyer");
  if (p.value !== "Direct Buyer" || p.from !== "issuer") fail(`buyer: issuer should win, got ${JSON.stringify(p)}`);
  p = pick(tender("b2", { req: [["Contracting authority", "Req Buyer"]] }), "buyer");
  if (p.value !== "Req Buyer" || p.from !== "req") fail(`buyer: req fallback, got ${JSON.stringify(p)}`);
  else ok("buyer: issuer, then the requirement row naming the authority");

  /* country and category */
  p = pick(tender("c1", { req: [["Country", "Norway"]] }), "country");
  if (p.value !== "Norway" || p.from !== "req") fail(`country: req fallback, got ${JSON.stringify(p)}`);
  p = pick(tender("c2", { cat: "Ammunition" }), "category");
  if (p.value !== "Ammunition" || p.from !== "cat") fail(`category: cat, got ${JSON.stringify(p)}`);
  else ok("country: country, then req; category: cat");

  /* value and quantity */
  p = pick(tender("v1", { value: "EUR 1m", req: [["Estimated value", "EUR 9m"]] }), "value");
  if (p.value !== "EUR 1m" || p.from !== "value") fail(`value: stored value should win, got ${JSON.stringify(p)}`);
  p = pick(tender("v2", { req: [["Estimated value", "EUR 9m"]] }), "value");
  if (p.value !== "EUR 9m" || p.from !== "req") fail(`value: req fallback, got ${JSON.stringify(p)}`);
  p = pick(tender("q1", { req: [["Quantity", "12 units"]] }), "quantity");
  if (p.value !== "12 units" || p.from !== "req") fail(`quantity: req fallback, got ${JSON.stringify(p)}`);
  else ok("value: value, then req; quantity: qty, then req");

  /* closing date: served deadline (as closingDate after wiring), then req, then stage;
     one formatter; a computed countdown is NEVER a source */
  p = pick(tender("d1", { deadline: "2031-06-22" }), "closing");
  if (p.value !== "22 Jun 2031" || p.from !== "deadline") fail(`closing: served ISO deadline, got ${JSON.stringify(p)}`);
  const wired = wireTendersWithRealDays([tender("d2", { deadline: "22 Jun 2031", status: "open" })])[0];
  p = pick(wired, "closing");
  if (p.value !== "22 Jun 2031" || p.from !== "deadline") fail(`closing: after wiring, the served date (not the countdown) -- got ${JSON.stringify(p)}`);
  const wiredNone = wireTendersWithRealDays([tender("d3", { status: "open" })])[0];
  p = pick(wiredNone, "closing");
  if (p.value !== null) fail(`closing: a wired record with no served date resolved to ${JSON.stringify(p.value)} -- that is the computed placeholder, not a record`);
  p = pick(tender("d4", { deadline: "12 days left" }), "closing");
  if (p.value !== null) fail(`closing: a baked countdown was accepted as a date: ${JSON.stringify(p)}`);
  p = pick(tender("d5", { req: [["Closing date", "1 Sep 2031"]] }), "closing");
  if (p.value !== "1 Sep 2031" || p.from !== "req") fail(`closing: req fallback, got ${JSON.stringify(p)}`);
  p = pick(tender("d6", { stage: "AoN cleared" }), "closing");
  if (p.value !== "AoN cleared" || p.from !== "stage") fail(`closing: stage fallback, got ${JSON.stringify(p)}`);
  p = pick(tender("d7", { deadline: "01 Sept 2031" }), "closing");
  if (p.value !== "1 Sep 2031") fail(`closing: not through the one formatter, got ${JSON.stringify(p.value)}`);
  else ok("closing: served deadline (through formatDate), then req, then stage; countdowns refused");

  /* status: awarded (status or urlKind), closed (status, or a served date now passed),
     else the stored status word */
  p = pick(tender("s1", { status: "awarded" }), "status");
  if (p.value !== "Awarded" || p.from !== "status") fail(`status: awarded, got ${JSON.stringify(p)}`);
  p = pick(tender("s2", { urlKind: "award" }), "status");
  if (p.value !== "Awarded" || p.from !== "urlKind") fail(`status: urlKind=award, got ${JSON.stringify(p)}`);
  p = pick(tender("s3", { status: "closed" }), "status");
  if (p.value !== "Closed" || p.from !== "status") fail(`status: closed, got ${JSON.stringify(p)}`);
  const passed = wireTendersWithRealDays([tender("s4", { status: "open", deadline: "1 Jan 2020" })])[0];
  p = pick(passed, "status");
  if (p.value !== "Closed" || p.from !== "deadline") fail(`status: open with a passed served date must read Closed from the deadline, got ${JSON.stringify(p)}`);
  p = pick(tender("s5", { status: "open" }), "status");
  if (p.value !== "Open" || p.from !== "status") fail(`status: open, got ${JSON.stringify(p)}`);
  else ok("status: awarded (status/urlKind), closed (status/passed date), else the stored word");

  /* source: the portal label, else the host of the url */
  p = pick(tender("p1", { srcs: [{ label: "TED (EU)", url: "https://ted.europa.eu/x" }], url: "https://other.test/y" }), "source");
  if (p.value !== "TED (EU)" || p.from !== "srcs") fail(`source: srcs label, got ${JSON.stringify(p)}`);
  p = pick(tender("p2", { url: "https://www.find-tender.service.gov.uk/Notice/1" }), "source");
  if (p.value !== "find-tender.service.gov.uk" || p.from !== "url") fail(`source: url host fallback, got ${JSON.stringify(p)}`);
  else ok("source: srcs[0].label, then the url host");

  /* the title is the stored title */
  const r = resolveTenderRow(tender("t1", { title: "Ammunition", issuer: "Bundesamt", country: "Germany" }));
  if (r.title !== "Ammunition") fail(`title was rewritten to ${JSON.stringify(r.title)}`);
  else ok("the title is the stored title, untouched");
}

/* ------------------------------------------------------ 4. rendered page ---- */
const here = resolve(new URL(".", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const tmp = mkdtempSync(join(tmpdir(), "kssl-tender-row-"));
const stubs = {
  DataProvider: `export function useData() { return globalThis.__KSSL_TEST__; }`,
  AppState: `export function useAppState() {
    return { searchQuery: "", setScope() {}, takePending() { return null; }, jumpTo() {},
             pillar: "market", view: "tender", setView() {}, setChatCtx() {} };
  }
  export const RAIL = {}; export const PILLARS = []; export const isOverview = () => false;
  export function useHeaderReport() {}
  export const PILLAR_LABEL = { competitive: "Competitive", market: "Market", technology: "Technology" };`,
};
const entry = `
  import React from "react";
  import { renderToStaticMarkup } from "react-dom/server";
  import Tenders from "./src/pages/market/Tenders.jsx";
  export function render(data) {
    globalThis.__KSSL_TEST__ = { data, gapModel: [], counts: {}, viewMeta: {} };
    return renderToStaticMarkup(React.createElement(Tenders, { mode: "tender" }));
  }`;
const out = join(tmp, "page.mjs");
await build({
  stdin: { contents: entry, resolveDir: here, loader: "jsx" },
  bundle: true, platform: "node", format: "esm", jsx: "automatic", outfile: out,
  logLevel: "silent", loader: { ".css": "empty" },
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

const { render } = await import(pathToFileURL(out).href);
const rows = wireTendersWithRealDays([
  /* the shape the corpus mostly has: a one-word title, no value, no qty, no date */
  tender("bare", { title: "Ammunition", issuer: "Bundesamt", country: "Germany", cat: "Ammunition", status: "open",
                   url: "https://ted.europa.eu/1", srcs: [{ label: "TED (EU)", url: "https://ted.europa.eu/1" }] }),
  /* everything filled */
  tender("full", { title: "155mm HE shells", issuer: "A Ministry", country: "India", cat: "Ammunition",
                   value: "EUR 4.0m", qty: "20 units", deadline: "22 Jun 2031", status: "open",
                   url: "https://example.test/full", srcs: [{ label: "Example Portal", url: "https://example.test/full" }] }),
  /* nothing but a title and an open status -- must still show all eight, all unresolved but status */
  tender("thin", { title: "Firearms", status: "open" }),
]);
const html = render({ tenders: rows, tpAllCountries: [], tpAllCats: [], client: { short: "CC" } });
rmSync(tmp, { recursive: true, force: true });

const cards = [...html.matchAll(/<div class="tcard[^"]*"[\s\S]*?(?=<div class="tcard|<div class="tp-asmt")/g)].map((m) => m[0]);
if (cards.length !== 3) fail(`rendered ${cards.length} cards, want 3`);
const labelsOf = (card) => [...card.matchAll(/class="tpk"[^>]*>([^<]*)</g)].map((m) => m[1].trim().toLowerCase());
const wantLabels = TENDER_PARAMS.map((p) => p.label.toLowerCase());
for (const card of cards) {
  const title = (card.match(/class="ttl"[^>]*>([^<]*)</) || [])[1];
  const labels = labelsOf(card);
  if (JSON.stringify(labels) !== JSON.stringify(wantLabels))
    fail(`card "${title}": parameters are ${JSON.stringify(labels)}, want ${JSON.stringify(wantLabels)} in that order`);
  /* a value cell is never empty: it holds a value or the classed unresolved state */
  const cells = [...card.matchAll(/<span class="tpv( na)?"[^>]*>([\s\S]*?)<\/span>/g)];
  if (cells.length !== TENDER_PARAMS.length) fail(`card "${title}": ${cells.length} value cells, want ${TENDER_PARAMS.length}`);
  for (const c of cells) {
    const txt = c[2].replace(/<[^>]+>/g, "").trim();
    if (!txt) fail(`card "${title}": an empty value cell -- blank and unknown must look different`);
    if (c[1] && txt !== NOT_ON_RECORD) fail(`card "${title}": unresolved cell prints ${JSON.stringify(txt)}`);
    if (!c[1] && txt === NOT_ON_RECORD) fail(`card "${title}": the unresolved literal without its class -- it would look like data`);
  }
}
const thin = cards.find((c) => /class="ttl"[^>]*>Firearms</.test(c)) || "";
const thinNa = (thin.match(/class="tpv na"/g) || []).length;
if (thinNa !== 7) fail(`title-only card: ${thinNa} unresolved cells, want 7 (everything but status)`);
else ok("rendered: every card carries the eight labels in order; unresolved cells are classed and say so");
const bareCard = cards.find((c) => /class="ttl"[^>]*>Ammunition</.test(c)) || "";
if (!/class="tpv"[^>]*>Bundesamt</.test(bareCard) || !/class="tpv"[^>]*>TED \(EU\)</.test(bareCard))
  fail("one-word title card: buyer and source were not composed around the title");
else ok("rendered: a one-word title is surrounded by the buyer, country, category and source the record carries");

console.log(bad ? `\n${bad} FAILED` : "\nall passed");
process.exit(bad ? 1 : 0);
