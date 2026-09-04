/* The ONE date formatter: "5 Aug 2026" -- day, three-letter month, year, no padding.

   It used to call toLocaleDateString("en-GB", { month: "short" }), which is not one
   format: the ICU data in Node 20+ and current Chrome spells September "Sept", so a
   report dated in September read "1 Sept 2026" beside pipeline dates that read
   "1 Sep 2026". The month table below is the one the served signal dates use, so
   every date in the app comes out of one spelling.

   Accepts a Date, an ISO string ("2026-09-05" or a full timestamp), a printed date in
   the house style ("1 Sep 2026", "01 Sept 2026"), or anything Date can parse. A string
   that is not a date at all ("Q4 2026 expected", "AoN cleared") is returned as it came:
   a served descriptive deadline is information, and a dash in its place would be a
   silent deletion. Only a non-string that fails to parse prints the dash. */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatDate(value = new Date()) {
  if (value instanceof Date) return fromDate(value);
  if (typeof value === "string") {
    const s = value.trim();
    if (!s) return "";
    let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    if (m) return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] || m[2]} ${m[1]}`;
    m = /^(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{4})$/.exec(s);
    if (m) {
      const mi = MONTHS.findIndex((x) => x.toLowerCase() === m[2].toLowerCase());
      if (mi >= 0) return `${Number(m[1])} ${MONTHS[mi]} ${m[3]}`;
    }
    const parsed = new Date(s);
    return Number.isNaN(parsed.getTime()) ? s : fromDate(parsed);
  }
  return fromDate(new Date(value));
}

function fromDate(date) {
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}
