/* The trail: a running story rendered as one card with its history, and a
   syndicated reprint folded into the article it copies.

   The two failures this guards are opposite and both are shipped bugs elsewhere in
   this repo: a chain that claims a continuity the sources never asserted, and a
   collapse that LOSES articles. So every check below either proves a link is right
   or proves nothing went missing across it. */
import { collapseThreads } from "./src/lib/news.js";

let bad = 0;
const ck = (name, ok, d) => {
  console.log(`  ${name.padEnd(64)} ${ok ? "PASS" : "FAIL"}${d !== undefined && !ok ? "  " + JSON.stringify(d) : ""}`);
  if (!ok) bad++;
};

const A = (url, storyKey, extra = {}) => ({
  url, title: url, date: extra.date || "2026-01-01", storyKey, ...extra,
});

// Newest first, as the backend serves them.
const rows = [
  A("u/3", "nlaw", { date: "2026-03-01" }),
  A("u/2", "nlaw", { date: "2026-02-01", continuesUrl: "u/1" }),
  A("u/2b", "nlaw", { date: "2026-02-02", duplicateOfUrl: "u/2" }),
  A("u/1", "nlaw", { date: "2026-01-01" }),
  A("solo", undefined, { date: "2026-02-15" }),
  A("sky/2", "skyranger", { date: "2026-02-20" }),
  A("sky/1", "skyranger", { date: "2026-02-10" }),
];

const out = collapseThreads(rows);
const urls = out.map((a) => a.url);

ck("a story renders as one card, not three", urls.filter((u) => u.startsWith("u/")).length === 1, urls);
ck("the newest article of the story is the one shown", urls.includes("u/3"));
ck("an article in no story is untouched", urls.includes("solo"));
ck("a second story is a second card", urls.includes("sky/2") && !urls.includes("sky/1"));

const head = out.find((a) => a.url === "u/3");
ck("the head carries the earlier articles as a trail", (head.trail || []).length === 2, head.trail);
ck("the trail is the rest of the story, newest first",
  (head.trail || []).map((a) => a.url).join(",") === "u/2,u/1");
ck("a reprint is NOT in the trail: it is not a development",
  !(head.trail || []).some((a) => a.url === "u/2b"));

const orig = (head.trail || []).find((a) => a.url === "u/2");
ck("the reprint folds into the article it copies",
  (rows.find((r) => r.url === "u/2b") && collapseThreads([rows[1], rows[2]])[0].alsoIn || []).length === 1);

// NOTHING MAY BE LOST. The full News section lists every article; the feed collapses.
const reachable = new Set();
out.forEach((a) => {
  reachable.add(a.url);
  (a.trail || []).forEach((t) => { reachable.add(t.url); (t.alsoIn || []).forEach((d) => reachable.add(d.url)); });
  (a.alsoIn || []).forEach((d) => reachable.add(d.url));
});
ck("every article is still reachable after the collapse",
  rows.every((r) => reachable.has(r.url)),
  rows.filter((r) => !reachable.has(r.url)).map((r) => r.url));

// A duplicate whose original is absent must survive on its own.
const orphan = collapseThreads([A("x/1", "nlaw", { duplicateOfUrl: "gone" }), A("x/2", "nlaw")]);
ck("a reprint whose original is not in the list is still shown",
  orphan.some((a) => a.url === "x/1") || (orphan[0].trail || []).some((a) => a.url === "x/1"),
  orphan.map((a) => a.url));

// THE UNMIGRATED BACKEND. Without the chain columns every article stands alone, and
// the feed must look exactly as it did before this existed.
const plain = [A("p/1", undefined), A("p/2", undefined), A("p/3", undefined)];
const flat = collapseThreads(plain);
ck("with no chain data nothing is collapsed", flat.length === 3);
ck("... and no empty trail is invented", flat.every((a) => a.trail === undefined));

ck("garbage in is an empty list, not a crash",
  collapseThreads(null).length === 0 && collapseThreads(undefined).length === 0);

console.log(bad ? `\n${bad} FAILED` : "\nall checks passed");
process.exit(bad ? 1 : 0);
