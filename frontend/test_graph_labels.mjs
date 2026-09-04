/* Alliance-graph labels must not land on top of each other.
 *
 *     node test_graph_labels.mjs
 *
 * Reported: "text is overlapping not visible properly". Each label was drawn at a fixed
 * offset from its slot with no idea any other label existed, so "Rafael Advanced
 * Defen..." sat on "Airbus Helicopters" wherever two clusters crowd.
 *
 * The resolver is pure geometry, so it is tested as geometry: build overlapping label
 * boxes, resolve, assert no two boxes intersect. The important case is the THIRD label
 * in a stack -- pushing B off A can push it straight onto C, which is why the resolver
 * re-checks from the start after every move and why that is asserted here.
 */
import { readFileSync } from "node:fs";

const src = readFileSync("./src/lib/partners.js", "utf8");
const from = src.indexOf("function pgResolveLabelCollisions");
if (from < 0) { console.log("  FAIL resolver not found in partners.js"); process.exit(1); }
const to = src.indexOf("\n}", from) + 2;
const { pgResolveLabelCollisions: resolve } = await import(
  "data:text/javascript," + encodeURIComponent(
    src.slice(from, to).replace("function pgResolveLabelCollisions",
      "export function pgResolveLabelCollisions")));

const CHAR_W = 6.2, H = 24, PAD = 3;
const box = (p) => {
  const w = Math.max(String(p.text || "").length, String(p.sub || "").length) * CHAR_W;
  const x = p.anchor === "start" ? p.x : p.anchor === "end" ? p.x - w : p.x - w / 2;
  return { x1: x - PAD, x2: x + w + PAD, y1: p.y - 11 - PAD, y2: p.y + H - 11 + PAD };
};
const overlaps = (p, q) => {
  const a = box(p), b = box(q);
  return a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1;
};
const countOverlaps = (plan) => {
  let n = 0;
  for (let i = 0; i < plan.length; i++)
    for (let j = i + 1; j < plan.length; j++) if (overlaps(plan[i], plan[j])) n++;
  return n;
};

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

// the real collision from the report: two long names, near-identical position
const reported = [
  { id: "a", x: 570, y: 396, anchor: "middle", text: "Rafael Advanced Defen", sub: "Foreign OEM" },
  { id: "b", x: 605, y: 420, anchor: "middle", text: "Airbus Helicopters", sub: "Foreign OEM" },
  { id: "c", x: 590, y: 405, anchor: "middle", text: "Ultra Electronics", sub: "Foreign OEM" },
];
if (countOverlaps(reported) === 0) fail("fixture does not actually overlap -- test is vacuous");
resolve(reported);
if (countOverlaps(reported) !== 0)
  fail(`the reported 3-label pile still overlaps (${countOverlaps(reported)} pair(s))`);

// a dense stack: pushing B off A must not drop it onto C
const stack = Array.from({ length: 8 }, (_, i) => ({
  id: `n${i}`, x: 400, y: 300 + i * 3, anchor: "middle",
  text: `Partner Company ${i}`, sub: "Foreign OEM",
}));
if (countOverlaps(stack) === 0) fail("stack fixture does not overlap -- test is vacuous");
resolve(stack);
if (countOverlaps(stack) !== 0)
  fail(`dense stack still overlaps (${countOverlaps(stack)} pair(s))`);

// labels that never touched must not be moved -- a resolver that shuffles everything
// destroys the hemisphere anchoring the layout depends on
const apart = [
  { id: "l", x: 100, y: 100, anchor: "end", text: "Left One", sub: "Domestic" },
  { id: "r", x: 800, y: 480, anchor: "start", text: "Right One", sub: "Foreign OEM" },
];
const before = apart.map((p) => p.y);
resolve(apart);
if (apart.some((p, i) => p.y !== before[i]))
  fail("labels that did not collide were moved anyway");

// only ever downward: a label must never be pushed above its node
const two = [
  { id: "p", x: 300, y: 200, anchor: "middle", text: "Alpha Systems", sub: "Foreign OEM" },
  { id: "q", x: 300, y: 205, anchor: "middle", text: "Beta Systems", sub: "Foreign OEM" },
];
resolve(two);
if (two.some((p, i) => p.y < [200, 205][i])) fail("a label was pushed upward, off its node");

if (bad) { console.log(`\n${bad} failure(s)`); process.exit(1); }
console.log("ok - graph labels: reported pile and a dense stack both resolve, "
  + "non-colliding labels untouched, movement is downward only");
