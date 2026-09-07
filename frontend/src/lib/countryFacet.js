/* ONE answer to "which countries is this company in", and ONE way to turn a list of
   rows into a filter's options.

   Three sidebars offered a country filter over the same competitor roster and each
   derived the country its own way: Products split the hq string on a comma and kept
   the tail, Partnerships offered the raw hq string ("Arlington, Virginia") under the
   heading "HQ Countries", and the Competitor page offered nothing. Meanwhile the Geo
   pages counted the served footprint (serving.geo_presence, 45 countries live) and the
   report read that as "the country filter advertises 49 countries and lists 5". Both
   numbers were honest about their own source; the sources were different.

   Measured live on 2026-09-05: 11 of 42 rivals carry an hq at all, 0 carry
   global_locations, and 27 carry footprint rows. The hq split alone yielded three
   values -- India, Norway and "Virginia" -- because a "City, Region" hq puts a region in
   its tail and a bare "Israel" has no tail at all.

   So a company's countries are the UNION of what the dataset records about it, and an
   hq fragment counts only when the dataset itself uses that word as a country somewhere
   -- a footprint key, the geo vocabulary, a tender's country. That admits "Israel" and
   "USA" and refuses "Virginia" and "Gujarat" without a hand-typed country list, which
   check_no_fabrication would rightly refuse. */

import { countrySpellings } from "./geoCountries.js";

const clean = (v) => String(v == null ? "" : v).trim();

/* Every word the dataset uses AS a country. Built once per dataset object and cached
   on it, because the roster pages call companyCountries per row per render. */
export function countryVocabulary(d) {
  if (d && d.__countryVocab) return d.__countryVocab;
  const vocab = new Set();
  Object.values((d && d.geoData) || {}).forEach((byCountry) =>
    Object.keys(byCountry || {}).forEach((c) => vocab.add(clean(c))),
  );
  ((d && d.geoCountries) || []).forEach((c) => vocab.add(clean(c)));
  ((d && d.tpAllCountries) || []).forEach((c) => vocab.add(clean(c)));
  ((d && d.tenders) || []).forEach((t) => t && t.country && vocab.add(clean(t.country)));
  Object.values((d && d.matchups) || {}).forEach((m) => m && m.country && vocab.add(clean(m.country)));
  vocab.delete("");
  if (d && typeof d === "object") {
    try {
      Object.defineProperty(d, "__countryVocab", { value: vocab, enumerable: false, writable: true });
    } catch (e) {
      /* a frozen dataset just recomputes */
    }
  }
  return vocab;
}

/* HQ AT ONE GRANULARITY. Moved here from pages/competitive/Profile.jsx on 2026-09-06,
   byte for byte, because a SECOND reader appeared: the map's "Head office" badge
   compared geo_comp.hq to a country name with raw full-string equality. A reference row
   stores a bare "Germany" and matched; a pipeline row stores "Ahmedabad, Gujarat, India"
   and never could, so the badge silently never fired for ANY pipeline competitor -- and
   silence there is indistinguishable from "this is not their head office". The fix is to
   reuse this rule, not to grow a second normaliser beside it.

   The rule only REMOVES -- street lines, postcodes, parenthetical asides, a second clause
   after a semicolon -- and keeps the last three components. tidyHq.test.mjs pins every
   case against real production values. */
const HQ_STREET = /\b(street|st\.?|road|rd\.?|marg|avenue|ave\.?|blvd|boulevard|lane|drive|dr\.?|strasse|stra\u00dfe|via|viale|gardens|house|bhavan|tower|plot|suite|floor|block|sy\s*no|industrial area|link road|estate|po box|p\.o\.)\b/i;
const HQ_HOUSE = /^\s*(no\.?\s*)?\d+[a-z]?[-/]?\d*\s+\S/i;
const HQ_POST = /\b(\d{4,6}|[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2})\b/g;

export const tidyHq = (raw) => {
  if (!raw) return null;
  const head = String(raw).split(";")[0].replace(/\([^)]*\)/g, " ");
  const parts = head
    .split(",")
    .map((p) => p.replace(HQ_POST, "").replace(/\s{2,}/g, " ").trim())
    .filter(Boolean);
  const kept = parts.filter((p) => !(HQ_STREET.test(p) || HQ_HOUSE.test(p)));
  const use = kept.length ? kept : parts;
  return use.slice(-3).join(", ") || String(raw).trim();
};

/* The geographic components of one hq, broadest LAST: ["Ahmedabad","Gujarat","India"].
   It never says which of them is a country -- promoting a component is how "Virginia"
   became one. The caller decides, against a list it already has. */
export function hqParts(raw) {
  const t = tidyHq(raw);
  return t ? t.split(",").map(clean).filter(Boolean) : [];
}


/* WHERE A COMPANY IS FROM. One country, or null.

   companyCountries below answers a different question -- "which countries is this
   company RECORDED IN" -- and unions the geo footprint, global_locations and the
   country-parts of hq to answer it. That is the right answer for a presence map and
   the wrong one for a roster filter: it put Bharat Dynamics under "France (6)",
   earned from the sentence "Bharat Dynamics Limited produces MILAN-2T under license
   from MBDA Missile Systems, France". France is the LICENSOR's country. BDL builds
   MILAN-2T in India.

   Origin is not derivable from hq either. 37 of 155 competitors carry an hq, and its
   comma-tail is "USA" for Lockheed and "Telangana" for Bharat Dynamics -- promoting a
   region to a country is how "Virginia" once became one. So origin is a stated column,
   filled from the audited competitor workbook, and null when nobody has established it.

   Null is a real answer here: such a company is listed under "origin not established",
   never quietly filed under someone else's flag. */
export function companyOrigin(d, cid) {
  const co = ((d && d.competitors) || {})[cid] || {};
  const v = clean(co.country);
  return v || null;
}

/* The countries one company is recorded in: footprint rows, catalogued locations, and
   the parts of its hq string the dataset knows as countries. Sorted, deduped. */
/* The countries a free-text line NAMES, as whole words.

   Whole words matter more than it looks: "India" is inside "Indiana", and this data
   carries both an India and an "Andhra Pradesh". A substring test would read Indiana as
   India. Longest first, so "South Korea" is not also reported as "Korea". */
const words = (s) =>
  clean(s)
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);

export function countriesNamedIn(text, vocab) {
  const toks = words(text);
  if (!toks.length) return [];
  /* Phrases first, so "South Korea" is read as one country rather than also reporting
     "Korea", and the tokens it consumed are not offered to a shorter name. */
  const terms = [...(vocab || [])]
    .filter(Boolean)
    .map((c) => ({ c, w: words(c) }))
    .filter((t) => t.w.length)
    .sort((a, b) => b.w.length - a.w.length);
  const used = new Array(toks.length).fill(false);
  const out = [];
  terms.forEach(({ c, w }) => {
    for (let i = 0; i + w.length <= toks.length; i += 1) {
      if (used.slice(i, i + w.length).some(Boolean)) continue;
      let hit = true;
      for (let j = 0; j < w.length; j += 1) {
        if (toks[i + j] !== w[j]) {
          hit = false;
          break;
        }
      }
      if (hit) {
        out.push(c);
        for (let j = 0; j < w.length; j += 1) used[i + j] = true;
        return;
      }
    }
  });
  return out;
}

function rawCountries(d, cid) {
  const co = ((d && d.competitors) || {})[cid] || {};
  const vocab = countryVocabulary(d);
  const out = new Set();
  Object.keys(((d && d.geoData) || {})[cid] || {}).forEach((c) => c && out.add(clean(c)));
  /* global_locations IS PROSE, NOT A COUNTRY LIST.
     This branch took each entry whole. When it was written that was harmless -- the
     note above records the measurement: "0 carry global_locations" -- so nothing ever
     came through it. The field has since been served, and the Partnerships filter
     filled with 208 options that are sentences:

        "12 commercial offices in Europe, the US and Brazil"
        "161 offices and production sites in more than 30 countries across Europe"
        "Approximately 180,000 employees in 52 countries"
        "Alabama", "Andhra Pradesh"

     A branch that is correct only because its input is empty is a bug waiting for the
     input. The entries are read for the countries they NAME, against the same
     vocabulary hq is already checked against, so nothing is admitted that the dataset
     does not itself use as a country -- "Alabama" and "Andhra Pradesh" are refused for
     the same reason "Virginia" always was. */
  (Array.isArray(co.global_locations) ? co.global_locations : []).forEach((g) => {
    const v = clean(g && typeof g === "object" ? g.value || g.country : g);
    if (!v) return;
    if (vocab.has(v)) {
      out.add(v);                       // already exactly a country
      return;
    }
    countriesNamedIn(v, vocab).forEach((c) => out.add(c));
  });
  clean(co.hq)
    .split(",")
    .map(clean)
    .filter((part) => part && vocab.has(part))
    .forEach((part) => out.add(part));
  out.delete("");
  return [...out].sort((a, b) => a.localeCompare(b));
}

/* ONE SPELLING PER COUNTRY.

   The fixed filter offered 49 options over 44 rivals, and two pairs of them were one
   country twice: "UK (8)" beside "United Kingdom (2)", "USA (13)" beside "United
   States (8)". Picking one hid the companies filed under the other, and neither count
   was the real one.

   The dataset spells a country however its source did, and no spelling is wrong. So
   the fold is decided by the data rather than by a preference typed here: the spelling
   the most companies use wins, ties broken alphabetically so the choice is stable
   across renders. Which spellings ARE one country is not a new judgement either --
   geoCountries.countrySpellings reads the same coordinate rows sameCountry does, so
   the filter and the map cannot disagree about the United Kingdom.

   Built once per dataset and cached beside the vocabulary, for the same reason. */
export function countryCanon(d) {
  if (d && d.__countryCanon) return d.__countryCanon;
  const uses = new Map();
  Object.keys((d && d.competitors) || {}).forEach((cid) =>
    rawCountries(d, cid).forEach((c) => uses.set(c, (uses.get(c) || 0) + 1)),
  );
  const canon = new Map();
  [...uses.keys()].forEach((c) => {
    if (canon.has(c)) return;
    const group = countrySpellings(c).filter((s2) => uses.has(s2));
    if (group.length < 2) return;                    // nothing to fold
    const win = group.slice().sort(
      (a, b) => (uses.get(b) || 0) - (uses.get(a) || 0) || a.localeCompare(b),
    )[0];
    group.forEach((s2) => canon.set(s2, win));
  });
  if (d && typeof d === "object") {
    try {
      Object.defineProperty(d, "__countryCanon", { value: canon, enumerable: false, writable: true });
    } catch (e) {
      /* a frozen dataset just recomputes */
    }
  }
  return canon;
}

/* The countries one company is recorded in, one option per country. */
export function companyCountries(d, cid) {
  const canon = countryCanon(d);
  const out = new Set(rawCountries(d, cid).map((c) => canon.get(c) || c));
  return [...out].sort((a, b) => a.localeCompare(b));
}

/* rows -> [{ v, n }] : every distinct value the rows carry, with how many rows carry it.
   `valuesOf(row)` returns one value or a list of them. Nothing is added from outside
   the rows, so an option always has at least one row behind it; `order` only sorts.
   Sorted by count, then the caller's order, then name -- the caller prints
   options.length as the advertised total, so the number and the list cannot drift. */
export function facetOptions(rows, valuesOf, order = []) {
  const counts = new Map();
  (rows || []).forEach((r) => {
    const vs = valuesOf(r);
    const list = Array.isArray(vs) ? vs : [vs];
    new Set(list.map(clean).filter(Boolean)).forEach((v) => counts.set(v, (counts.get(v) || 0) + 1));
  });
  const ix = (v) => {
    const i = order.indexOf(v);
    return i < 0 ? order.length : i;
  };
  return [...counts.entries()]
    .map(([v, n]) => ({ v, n }))
    .sort((a, b) => b.n - a.n || ix(a.v) - ix(b.v) || a.v.localeCompare(b.v));
}

/* The same list, alphabetical -- for a <select>, where the reader scans by name. */
export function facetOptionsByName(rows, valuesOf) {
  return facetOptions(rows, valuesOf).sort((a, b) => a.v.localeCompare(b.v));
}
