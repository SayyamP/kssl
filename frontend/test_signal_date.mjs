/* A signal must not carry two different dates on one screen.

     node test_signal_date.mjs

   The card aside printed the pipeline's `ago` ("Aug 2026") while the detail panel beside
   it printed the same event's day-precision date ("11 Aug 2026"). Measured on live data,
   730 of 813 cards disagreed with their own panel. The reader sees both at once, so the
   report read it as the dates being wrong -- they were not wrong, they were two answers
   to one question.
*/
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./src/lib/overview.js", import.meta.url), "utf8");
const from = src.indexOf("export function signalDate");
const to = src.indexOf("export const FEED_PAGE_SIZE");
const { signalDate } = await import(
  "data:text/javascript," + encodeURIComponent(src.slice(from, to))
);

const ok = [], bad = [];
const t = (name, got, want) =>
  (String(got) === String(want) ? ok : bad).push(`${name}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`);

const data = {
  details: {
    c1: { facts: [["Company", "Leonardo"], ["Category", "Artillery"], ["Date", "11 Aug 2026"]] },
    c2: { facts: [["Company", "Saab"], ["Date", "Sep 2026"]] },
    c3: { facts: [["Company", "BAE"]] },                    // no Date row at all
    c4: { facts: [["Company", "Thales"], ["Date", ""]] },    // present but empty
  },
};

// the panel's value wins, so the two surfaces agree
t("day precision from the panel", signalDate({ id: "c1", ago: "Aug 2026" }, data), "11 Aug 2026");
// a month-only panel value is still the panel's value
t("month precision", signalDate({ id: "c2", ago: "Sep 2026" }, data), "Sep 2026");
// no Date row -> the card's own value, not blank
t("falls back to ago", signalDate({ id: "c3", ago: "Jul 2026" }, data), "Jul 2026");
// an empty Date must not blank the card
t("empty Date falls back", signalDate({ id: "c4", ago: "Jun 2026" }, data), "Jun 2026");
// unknown card, missing details, missing card: never throw, never render "undefined"
t("unknown card", signalDate({ id: "nope", ago: "May 2026" }, data), "May 2026");
t("no details in dataset", signalDate({ id: "c1", ago: "Apr 2026" }, {}), "Apr 2026");
t("no card at all", signalDate(null, data), "");
t("card with no ago", signalDate({ id: "c3" }, data), "");

if (bad.length) {
  console.log("FAIL\n  " + bad.join("\n  "));
  process.exit(1);
}
console.log(`ok - signalDate, ${ok.length} cases (card and panel cannot disagree)`);
