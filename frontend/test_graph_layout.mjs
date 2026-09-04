/* The alliance graph must use its canvas and nothing on it may sit on anything else.
 *
 *     node test_graph_layout.mjs            # the layout in src/lib/partners.js
 *     node test_graph_layout.mjs old.js     # any other copy, to show what it failed on
 *
 * Reported (with a screenshot): "utillize the space artound the graph everthing
 * clsutered and overlapped fix it". Seven partners, every node in the upper-left
 * of a 960x540 canvas, circles touching, labels across the cluster, the bottom
 * half and right third empty. The cause was a fixed table of slot coordinates per
 * cluster: the same positions for seven partners as for thirty.
 *
 * This test does not trust the layout's own arithmetic. It renders the SVG the
 * viewer gets and reads the circles and text back out of the markup, then checks
 * the geometry independently:
 *   1. no two node discs (halo included) intersect, the centre OEM included;
 *   2. no two label boxes intersect;
 *   3. no label box sits on any node disc that is not its own;
 *   4. the drawn extent (nodes + labels) covers most of the canvas and is centred
 *      on it -- the complaint was a graph crammed into one corner;
 *   5. everything stays inside the viewBox, below the toolbar and above the hint.
 *
 * Run against the previous partners.js this file reports 30 failures: the
 * seven-partner picture on extent (57% of the width), centring and the toolbar
 * strip; the sixteen-partner one on discs 28px apart and labels across other
 * nodes; and 32 edges drawn for 7 relationships. So a pass here is a pass on the
 * reported picture, not on an empty canvas.
 */
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const file = process.argv[2] || "./src/lib/partners.js";
const mod = await import(pathToFileURL(resolve(file)).href);
const partners = mod.createPartners({
  competitors: {},
  KSSL_PARTNERS: [],
  REL_LABEL: {},
  FIELDSYN: {},
  COMPSYN: {},
  TRACEIDS: {},
  sourceRegistry: {},
});

const W = 960;
const H = 540;
const TOP = 44;      // the view toggles and zoom buttons float over the top strip
const BOTTOM = 32;   // the hint text sits in the bottom strip
const CHAR_W = 6.2;  // 11px mono, same figure the label resolver uses

/* ---- read the markup back ------------------------------------------------ */
const attr = (tag, k) => {
  const m = tag.match(new RegExp(`\\s${k}="([^"]*)"`));
  return m ? m[1] : null;
};
const num = (tag, k) => parseFloat(attr(tag, k));

function readGraph(svg) {
  const nodes = [];
  const rx = /<g class="pg-node ([^"]*)"([^>]*)>([\s\S]*?)<\/g>/g;
  let m;
  while ((m = rx.exec(svg))) {
    const cls = m[1];
    const head = m[2];
    const body = m[3];
    const discM = body.match(/<circle class="net-circle"[^>]*>/);
    if (!discM) continue;
    const disc = discM[0];
    const haloM = body.match(/<circle class="halo[^"]*"[^>]*>/);
    const halo = haloM ? haloM[0] : null;
    const texts = [...body.matchAll(/<text([^>]*)>([^<]*)<\/text>/g)].map((t) => ({
      x: num(t[1], "x"),
      y: num(t[1], "y"),
      anchor: attr(t[1], "text-anchor") || "middle",
      t: t[2],
      size: /center-title/.test(t[1]) ? 13 : /sub/.test(t[1]) ? 9 : 11,
    }));
    nodes.push({
      id: attr(head, "data-id") || attr(head, "data-parent") || "?",
      centre: /center-root/.test(cls),
      sat: /\bsat\b/.test(cls),
      x: num(disc, "cx"),
      y: num(disc, "cy"),
      r: num(disc, "r"),
      halo: halo ? num(halo, "r") : num(disc, "r"),
      texts,
    });
  }
  return nodes;
}

/* one box per node: its title row plus its kind row */
function labelBox(nd) {
  if (!nd.texts.length) return null;
  const w = Math.max(...nd.texts.map((t) => t.t.length * (t.size >= 13 ? 7.6 : CHAR_W)));
  const top = Math.min(...nd.texts.map((t) => t.y - t.size));
  const bot = Math.max(...nd.texts.map((t) => t.y + 3));
  const a = nd.texts[0];
  const x0 = a.anchor === "start" ? a.x : a.anchor === "end" ? a.x - w : a.x - w / 2;
  return { x0: x0 - 2, x1: x0 + w + 2, y0: top - 2, y1: bot + 2, t: a.t };
}
const boxesHit = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
const boxHitsDisc = (b, nd) => {
  const px = Math.max(b.x0, Math.min(nd.x, b.x1));
  const py = Math.max(b.y0, Math.min(nd.y, b.y1));
  return Math.hypot(nd.x - px, nd.y - py) < nd.halo;
};

/* ---- the geometry rules --------------------------------------------------- */
function faults(svg, name, expect) {
  const out = [];
  const nodes = readGraph(svg);
  const ptr = nodes.filter((n) => !n.centre && !n.sat);
  if (ptr.length !== expect)
    out.push(`${name}: ${ptr.length} partner nodes drawn for ${expect} partners`);
  if (!nodes.some((n) => n.centre)) out.push(`${name}: no centre node`);

  // 1. discs
  for (let i = 0; i < nodes.length; i++)
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i];
      const b = nodes[j];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (d < a.halo + b.halo)
        out.push(`${name}: nodes overlap -- ${a.id} and ${b.id} are ${d.toFixed(0)}px apart`);
    }
  // 2. labels vs labels, 3. labels vs other discs
  const boxes = nodes.map((n) => ({ nd: n, box: labelBox(n) })).filter((b) => b.box);
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++)
      if (boxesHit(boxes[i].box, boxes[j].box))
        out.push(`${name}: labels overlap -- "${boxes[i].box.t}" and "${boxes[j].box.t}"`);
    nodes.forEach((n) => {
      if (n === boxes[i].nd) return;
      if (boxHitsDisc(boxes[i].box, n))
        out.push(`${name}: label "${boxes[i].box.t}" sits on node ${n.id}`);
    });
  }
  // 4. extent and centring, over everything that is drawn
  const xs = [];
  const ys = [];
  nodes.forEach((n) => {
    xs.push(n.x - n.halo, n.x + n.halo);
    ys.push(n.y - n.halo, n.y + n.halo);
  });
  boxes.forEach((b) => {
    xs.push(b.box.x0, b.box.x1);
    ys.push(b.box.y0, b.box.y1);
  });
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const y0 = Math.min(...ys);
  const y1 = Math.max(...ys);
  const fw = (x1 - x0) / W;
  const fh = (y1 - y0) / (H - TOP - BOTTOM);
  // the OEM is pinned to the centre, so with one to three partners the drawn box is
  // lopsided by construction; from four up it must fill the canvas and sit on it
  if (ptr.length >= 4) {
    if (fw < 0.75) out.push(`${name}: graph spans only ${(fw * 100).toFixed(0)}% of the canvas width`);
    if (fh < 0.7) out.push(`${name}: graph spans only ${(fh * 100).toFixed(0)}% of the usable height`);
    const mx = (x0 + x1) / 2;
    const my = (y0 + y1) / 2;
    if (Math.abs(mx - W / 2) > W * 0.08 || Math.abs(my - (TOP + (H - BOTTOM)) / 2) > H * 0.08)
      out.push(`${name}: graph is off-centre, drawn box centred at ${mx.toFixed(0)},${my.toFixed(0)}`);
  }
  // 5. inside the viewBox, clear of the toolbar strip and the hint strip
  if (x0 < 0 || x1 > W || y0 < TOP || y1 > H - BOTTOM)
    out.push(`${name}: drawing leaves the canvas [${x0.toFixed(0)}..${x1.toFixed(0)} x ${y0.toFixed(0)}..${y1.toFixed(0)}]`);
  return out;
}

/* ---- fixtures ------------------------------------------------------------- */
const row = (i, label, kind, extra) => ({
  id: `p${i}`,
  cid: `c${i}`,
  label,
  kind,
  ptype: kind,
  rel: "tech",
  sig: 1 + (i % 3),
  insight: i % 2 ? "[CORE] tie" : "[ADJACENT] tie",
  ...(extra || {}),
});
const company = (name, parts) => ({ id: name.toLowerCase(), name, partners: parts });

// the reported picture: seven partners, three of them long foreign names
const seven = company("Fixture OEM", [
  row(1, "Rafael Advanced Defence Systems", "Foreign OEM"),
  row(2, "Airbus Helicopters", "Foreign OEM"),
  row(3, "Telephonics Corporation", "Foreign OEM"),
  row(4, "Fixture Radar Systems", "Technology partner"),
  row(5, "Fixture Naval Yard", "Domestic partner"),
  row(6, "Fixture Drone Autonomy", "Domestic partner"),
  row(7, "Fixture Casting Supplier", "Domestic partner", { shared: true }),
]);
// the display cap, every name at the truncation limit: the widest labels possible
const sixteen = company("Fixture Wide OEM",
  Array.from({ length: 16 }, (_, i) =>
    row(i + 1, `Fixture Partner Number ${String(i + 1).padStart(2, "0")} Long`,
      ["Foreign OEM", "Technology partner", "Domestic partner", "Govt / DRDO"][i % 4],
      i % 5 === 0 ? { shared: true } : null)));
// too many to draw: the graph caps at 16, the roster lists the rest
const thirty = company("Fixture Dense OEM",
  Array.from({ length: 30 }, (_, i) => row(i + 1, `Fixture Dense Partner ${i + 1}`, "Domestic partner")));
const three = company("Fixture Small OEM", [
  row(1, "Fixture Alpha", "Foreign OEM"),
  row(2, "Fixture Beta Systems", "Technology partner"),
  row(3, "Fixture Gamma", "Domestic partner"),
]);
const one = company("Fixture Single OEM", [row(1, "Fixture Only Partner", "Foreign OEM")]);

let bad = 0;
const fail = (m) => { bad++; console.log("  FAIL " + m); };

[[seven, 7], [sixteen, 16], [thirty, 16], [three, 3], [one, 1]].forEach(([c, n]) => {
  const svg = partners.graphSvg(c);
  if (!svg) { fail(`${c.name}: no svg`); return; }
  faults(svg, c.name, n).forEach(fail);
  // every partner keeps its own group with its own label inside it: the hover,
  // dim and select rules key on that nesting
  const drawn = Math.min(n, 16);
  const groups = [...svg.matchAll(/<g class="pg-node ptr[^"]*" data-id="([^"]+)"[^>]*>[\s\S]*?<text[\s\S]*?<\/g>/g)];
  if (groups.length !== drawn)
    fail(`${c.name}: ${groups.length} partner groups carry a label inside them, expected ${drawn}`);
});

// the layout must not draw anything the dataset does not hold: one disc per
// partner plus the centre, and one edge per partner, nothing decorative
{
  const svg = partners.graphSvg(seven);
  const discs = (svg.match(/<circle class="net-circle"/g) || []).length;
  if (discs !== 8) fail(`seven partners drew ${discs} discs, expected 8 (7 partners + centre)`);
  const edges = (svg.match(/<line class="pg-edge/g) || []).length;
  if (edges !== 7) fail(`seven partners drew ${edges} edges, expected 7 -- an edge must be a relationship on file`);
}

// labels extend away from the graph: right half starts at the node, left half ends at it
{
  const nodes = readGraph(partners.graphSvg(sixteen)).filter((n) => !n.centre);
  nodes.forEach((n) => {
    const a = n.texts[0];
    if (!a) return;
    if (n.x > W / 2 + 60 && a.anchor !== "start")
      fail(`${n.id} sits right of centre but its label is anchored "${a.anchor}"`);
    if (n.x < W / 2 - 60 && a.anchor !== "end")
      fail(`${n.id} sits left of centre but its label is anchored "${a.anchor}"`);
  });
}

// when one ring cannot hold the count without something touching, the layout
// must overflow to a second ring and come out clean -- never nudge nodes onto
// each other. Two fixtures: more nodes than the display cap on the real canvas,
// and the cap's worth of short names on a canvas two thirds the size. Each is
// asserted to NEED the second ring (the search only moves a node when the single
// ring has a fault), so a layout that never overflows cannot pass here.
if (mod.pgRadialLayout && mod.pgLayoutFaults) {
  const mk = (n, len, sub) => Array.from({ length: n }, (_, i) => ({
    id: `p${i + 1}`, label: `Node ${String(i + 1).padStart(2, "0")}`.padEnd(len, "x").slice(0, len),
    sub, r: i % 4 ? 15 : 19, cluster: ["amber", "purple", "teal", "coral"][i % 4],
  }));
  [
    ["24 partners on the 960x540 canvas", mk(24, 12, "Partner kind"), null],
    ["16 partners on a 640x400 canvas", mk(16, 8, "Partner"), { w: 640, h: 400 }],
  ].forEach(([name, items, view]) => {
    const lay = mod.pgRadialLayout(items, view, "Fixture OEM");
    if (lay.rings < 2) fail(`${name}: stayed on one ring -- overflow never happened, so this fixture proves nothing`);
    if (lay.nodes.length !== items.length) fail(`${name}: ${lay.nodes.length} nodes placed for ${items.length}`);
    if (lay.faults.length) fail(`${name}: layout still reports ${lay.faults.length} fault(s): ${lay.faults.slice(0, 3).join("; ")}`);
    // and independently of the layout's own checker
    for (let i = 0; i < lay.nodes.length; i++)
      for (let j = i + 1; j < lay.nodes.length; j++) {
        const p = lay.nodes[i];
        const q = lay.nodes[j];
        if (Math.hypot(p.x - q.x, p.y - q.y) < p.r + q.r + 12) fail(`${name}: ${p.id} and ${q.id} overlap after overflow`);
      }
    lay.nodes.forEach((n) => {
      if (Math.hypot(n.x - lay.cx, n.y - lay.cy) < 24 + 40 + n.r) fail(`${name}: ${n.id} landed on the centre node`);
      const sameSector = items.filter((it) => it.cluster === n.cluster).length;
      if (sameSector && !n.cluster) fail(`${name}: ${n.id} lost its cluster`);
    });
    // an inner node keeps its cluster's sector: it sits between two outer nodes of
    // the same cluster, or at that sector's edge
    const outer = lay.nodes.filter((n) => !n.ring).sort((p, q) => p.ang - q.ang);
    lay.nodes.filter((n) => n.ring).forEach((n) => {
      const before = outer.filter((o) => o.ang <= n.ang).pop() || outer[outer.length - 1];
      const after = outer.find((o) => o.ang > n.ang) || outer[0];
      if (before.cluster !== n.cluster && after.cluster !== n.cluster)
        fail(`${name}: inner node ${n.id} (${n.cluster}) sits between ${before.id} (${before.cluster}) and ${after.id} (${after.cluster}), outside its sector`);
    });
  });
} else {
  fail("pgRadialLayout / pgLayoutFaults are not exported -- the overflow path cannot be tested");
}

if (bad) { console.log(`\n${bad} failure(s) in ${file}`); process.exit(1); }
console.log("ok - graph layout: 7/16/30/3/1 partners fill the canvas, no disc on a disc, "
  + "no label on a label or a disc, labels point outward, overflow takes a second ring");
