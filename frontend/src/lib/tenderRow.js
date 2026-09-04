/* THE FIXED PARAMETER SET OF A TENDER ROW.
 *
 * REPORTED: "many have a small basic title, no understanding ... fix per tender row
 * parameters, resolve from each tender and show a consistent flow".
 *
 * Measured on the served corpus (136 tenders, 2026-09-05): the median title is 29
 * characters, 40 titles are 20 characters or fewer, 50 are three words or fewer --
 * "Ammunition", "Firearms", "Eb Tuba", "Vane,Large". The card under such a title used
 * to print whichever of six fields happened to be filled, so one row read six parts and
 * the next three, and a reader could not tell a field the notice does not publish from
 * one the card forgot. The title is not rewritten (a composed title is an invented one);
 * instead the SAME eight parameters are resolved for EVERY tender, in the same order,
 * and each one either carries a stored value or says, in its own visual state, that
 * the record does not hold it.
 *
 * What the served record can fill (origin=pipeline, n=136):
 *   issuer / country / cat / status / url / srcs   136   always
 *   deadline                                         79   "d Mon yyyy" strings
 *   value                                            23
 *   qty                                               7
 *   req / stage / dl / matches                        0   only the 22 reference rows
 *
 * So Value, Quantity and Closing date are unresolved on most rows. That is the fact the
 * row must state, not hide: "not on record" is data; a blank is not.
 *
 * Each parameter names the field it was resolved FROM (`from`), so a reader of the
 * report, a test, or the next engineer can see which link of the chain fired.
 */
import { formatDate } from "../utils/formatDate.js";

export const NOT_ON_RECORD = "not on record";

/* The fixed set, in display order. `label` is what the row prints. */
export const TENDER_PARAMS = [
  { key: "buyer", label: "Buyer" },
  { key: "country", label: "Country" },
  { key: "category", label: "Category" },
  { key: "value", label: "Value" },
  { key: "quantity", label: "Quantity" },
  { key: "closing", label: "Closing date" },
  { key: "status", label: "Status" },
  { key: "source", label: "Source" },
];

const has = (v) => v != null && String(v).trim() !== "";
const str = (v) => String(v).trim();

/* A requirement row whose LABEL matches -- the reference rows carry [label, value]
   pairs like ["Closing date", "12 Mar 2027"]. The pipeline rows carry none (0/136),
   so this link is documented and tested but idle in production today. */
const reqRow = (t, re) => {
  if (!t || !Array.isArray(t.req)) return null;
  const pair = t.req.find((r) => Array.isArray(r) && has(r[0]) && re.test(str(r[0])) && has(r[1]));
  return pair ? str(pair[1]) : null;
};

/* wireTendersWithRealDays overwrites `deadline` with a countdown and keeps the served
   string on `closingDate`. Before wiring there is no closingDate key and `deadline` IS
   the served string. Read whichever holds the record, and refuse anything that is a
   computation: a countdown, the "no deadline on record" placeholder, or the stage text
   the wiring copies into the deadline slot. */
const COMPUTED_DEADLINE = /days?\s+left|closes in|no deadline on record|closed \/ expired|awarded \/ settled/i;
const servedDeadline = (t) => {
  if (Object.prototype.hasOwnProperty.call(t, "closingDate")) return has(t.closingDate) ? str(t.closingDate) : null;
  if (!has(t.deadline)) return null;
  const d = str(t.deadline);
  if (COMPUTED_DEADLINE.test(d)) return null;
  if (has(t.stage) && d === str(t.stage)) return null;
  return d;
};

const urlHost = (u) => {
  if (!has(u)) return null;
  const h = str(u).replace(/^https?:\/\/(www\.)?/i, "").split("/")[0];
  return h || null;
};

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

/* ------------------------------------------------------------- resolvers ----
   Each returns { value, from } -- value null when nothing on the record fills it. A
   resolver reads STORED fields only; the one computation allowed is "the served closing
   date has passed", which tenderCalc already makes and the Closed tab already relies on.
   The chain order is the documentation. */
const RESOLVE = {
  buyer: (t) =>
    has(t.issuer) ? { value: str(t.issuer), from: "issuer" }
    : first(reqRow(t, /buyer|issuer|contracting authority|purchaser|procuring/i), "req"),
  country: (t) =>
    has(t.country) ? { value: str(t.country), from: "country" }
    : first(reqRow(t, /^country/i), "req"),
  category: (t) => (has(t.cat) ? { value: str(t.cat), from: "cat" } : none()),
  value: (t) =>
    has(t.value) ? { value: str(t.value), from: "value" }
    : first(reqRow(t, /value|budget|estimated cost/i), "req"),
  quantity: (t) =>
    has(t.qty) ? { value: str(t.qty), from: "qty" }
    : first(reqRow(t, /quantity|qty/i), "req"),
  closing: (t) => {
    const d = servedDeadline(t);
    if (d) return { value: formatDate(d), from: "deadline" };
    const r = reqRow(t, /closing date|due date|deadline|submission/i);
    if (r) return { value: formatDate(r), from: "req" };
    if (has(t.stage)) return { value: str(t.stage), from: "stage" };
    return none();
  },
  status: (t) => {
    const s = has(t.status) ? str(t.status).toLowerCase() : "";
    if (s === "awarded") return { value: "Awarded", from: "status" };
    if (t.urlKind === "award") return { value: "Awarded", from: "urlKind" };
    if (s === "closed") return { value: "Closed", from: "status" };
    /* the served date has passed: tenderCalc set isLive=false from closingDate */
    if (t.isLive === false && servedDeadline(t)) return { value: "Closed", from: "deadline" };
    if (s) return { value: cap(s), from: "status" };
    return none();
  },
  source: (t) => {
    const lbl = Array.isArray(t.srcs) && t.srcs[0] && has(t.srcs[0].label) ? str(t.srcs[0].label) : null;
    if (lbl) return { value: lbl, from: "srcs" };
    const h = urlHost(t.url) || urlHost(Array.isArray(t.srcs) && t.srcs[0] && t.srcs[0].url);
    return h ? { value: h, from: "url" } : none();
  },
};
const none = () => ({ value: null, from: null });
const first = (v, from) => (v ? { value: v, from } : none());

/**
 * Resolve one tender to its fixed row shape.
 *
 * @returns {{ title: string, params: Array<{key, label, value: string|null, from: string|null, text: string}> }}
 *   `value` is the resolved string or null; `text` is what to print -- the value, or
 *   NOT_ON_RECORD. `title` is the stored title, untouched.
 */
export function resolveTenderRow(t) {
  const rec = t && typeof t === "object" ? t : {};
  return {
    title: has(rec.title) ? str(rec.title) : "",
    params: TENDER_PARAMS.map(({ key, label }) => {
      const { value, from } = RESOLVE[key](rec);
      return { key, label, value, from, text: value == null ? NOT_ON_RECORD : value };
    }),
  };
}

/* The same eight, as [label, text, resolved] rows -- for report tables and any surface
   that prints facts as pairs. Never filtered: the unresolved ones are the point. */
export function tenderFactRows(t) {
  return resolveTenderRow(t).params.map((p) => [p.label, p.text, p.value != null]);
}
