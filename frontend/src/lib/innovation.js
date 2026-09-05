/* What the Innovation Pipeline prints for a record's analyst fields, and how its list
 * answers the global search box. Pure, so test_innovation_view.mjs runs it under node.
 *
 * `gap`, `mat`, `horizon`, `whatsNew` and `compNote` are analyst fields the served
 * record leaves null when nobody assessed them -- which is a different thing from a
 * neutral verdict. On the live-shape dump (2026-08-25) `gap` is null on EVERY row, and
 * the detail header's pill read `gap === "behind" ? "GAP" : gap === "parity" ? "WATCH"
 * : "AHEAD"`: every innovation opened under a green AHEAD, a verdict nobody gave,
 * above a Status row that correctly said "not assessed". */

export const NOT_ASSESSED = "not assessed";
export const NOT_STATED = "not stated";

export const has = (v) => v != null && String(v).trim() !== "";

/* maturity labels -- one map, covering every `mat` value in the dataset
   (lab / dev / prod / fielded). 'prod' was once missing and rendered `undefined`. */
export const MAT_LAB = {
  lab: "Lab / research",
  dev: "In development",
  prod: "In production",
  fielded: "Fielded / in service",
};

/* A missing maturity says so in words; an unknown non-empty value is shown as served,
   never mapped to something it is not. */
export function maturityLabel(mat) {
  if (!has(mat)) return NOT_STATED;
  return MAT_LAB[mat] || String(mat);
}

/* The header pill is a VERDICT. No assessed position, no pill -- and a value outside
   the vocabulary is not a verdict either. */
const PILL = { behind: "GAP", parity: "WATCH", ahead: "AHEAD" };
export function positionPill(gap) {
  if (!has(gap)) return null;
  const k = String(gap).trim();
  return PILL[k] ? { text: PILL[k], cls: k } : null;
}

const plain = (v) => (v == null ? "" : String(v)).replace(/<[^>]*>/g, " ");

/* The domain's rows that match the global search box: every token somewhere in the
   row's text (title, driver, horizon, background, impact), markup stripped so a
   reader can neither search for nor match on a <b>. Returns [{ item, index }] with
   the ORIGINAL index kept -- selection on this page is by index into the domain
   list, and a filtered view must still select the row the reader clicked. */
export function filterInnovations(list, query) {
  const rows = (list || []).map((item, index) => ({ item, index }));
  const tokens = String(query == null ? "" : query).toLowerCase().trim().split(/\s+/).filter(Boolean);
  if (!tokens.length) return rows;
  return rows.filter(({ item }) => {
    if (!item) return false;
    const hay = [item.t, item.driver, item.horizon, item.body, item.impact].map(plain).join(" ").toLowerCase();
    return tokens.every((t) => hay.includes(t));
  });
}
