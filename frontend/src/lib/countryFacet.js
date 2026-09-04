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

/* The countries one company is recorded in: footprint rows, catalogued locations, and
   the parts of its hq string the dataset knows as countries. Sorted, deduped. */
export function companyCountries(d, cid) {
  const co = ((d && d.competitors) || {})[cid] || {};
  const vocab = countryVocabulary(d);
  const out = new Set();
  Object.keys(((d && d.geoData) || {})[cid] || {}).forEach((c) => c && out.add(clean(c)));
  (Array.isArray(co.global_locations) ? co.global_locations : []).forEach((g) => {
    const v = clean(g && typeof g === "object" ? g.value || g.country : g);
    if (v) out.add(v);
  });
  clean(co.hq)
    .split(",")
    .map(clean)
    .filter((part) => part && vocab.has(part))
    .forEach((part) => out.add(part));
  out.delete("");
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
