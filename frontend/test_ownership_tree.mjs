/* ownershipTree feeds the Corporate Structure graph from serving.competitor_structure.
 *
 * The failure that matters here is specific and this page has already had it once: the
 * graph was fed an if-chain of hand-typed parents and subsidiaries for about six firms,
 * and 95f781c replaced all of it with null. So the rules are (a) no rows, no graph --
 * never a partner drawn under an ownership heading, and (b) no number that a source did
 * not state.
 *
 *   node test_ownership_tree.mjs
 */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./src/pages/competitive/Profile.jsx", import.meta.url), "utf8");
const from = src.indexOf("const TIE_RANK");
const to = src.indexOf("const getCorporateStructureMap");
const { ownershipTree, partnerTree } = await import(
  "data:text/javascript," + encodeURIComponent(src.slice(from, to))
);

const ok = [];
const bad = [];
const check = (name, cond) => (cond ? ok : bad).push(name);

const p = { name: "Nexter Systems" };

check("no edges -> null, so the page falls back to the partner network",
  ownershipTree(p, []) === null);
check("missing edges -> null",
  ownershipTree(p, undefined) === null);
check("a row with no entity name is not a node",
  ownershipTree(p, [{ relationship_type: "parent", entity_name: "" }]) === null);

/* Shape copied from GET /api/dataset competitorStructure, verified against the table. */
const edges = [
  { entity_id: "knds", entity_name: "KNDS", relationship_type: "parent",
    ownership_pct: 51, source_url: "https://example/a" },
  { entity_id: "cta", entity_name: "CTA International", relationship_type: "subsidiary",
    ownership_pct: null, source_url: "https://example/b" },
  { entity_id: "kmw", entity_name: "Krauss-Maffei Wegmann", relationship_type: "sister",
    ownership_pct: null, source_url: "https://example/c" },
];

const t = ownershipTree(p, edges);
check("ownership is labelled as ownership, not as partners", t.kind === "ownership");
check("the company itself is the root", t.current === "Nexter Systems");
check("the parent sorts first -- it is the fact that orders the rest",
  t.sisters[0] === "KNDS · Parent 51%");
check("a stated percentage is printed",
  t.sisters[0].includes("51%"));
check("an unstated percentage prints nothing at all, not 0% and not 'unknown'",
  t.sisters[1] === "CTA International · Subsidiary" && !t.sisters[1].includes("%"));
check("subsidiary before sister", t.sisters[2].startsWith("Krauss-Maffei Wegmann"));
check("every edge is a node", t.shown === 3 && t.total === 3);

/* The same company named as both a parent and a subsidiary is two different claims and
   stays two nodes; the same claim arriving twice is one. */
const dup = ownershipTree(p, [
  { entity_name: "KNDS", relationship_type: "parent", source_url: "https://a" },
  { entity_name: "KNDS", relationship_type: "parent", source_url: "https://b" },
  { entity_name: "KNDS", relationship_type: "subsidiary", source_url: "https://c" },
]);
check("the same edge twice is one node", dup.total === 2);

const capped = ownershipTree(
  p,
  Array.from({ length: 12 }, (_, i) => ({
    entity_name: `Sub ${String(i).padStart(2, "0")}`,
    relationship_type: "subsidiary",
    source_url: "https://x",
  })),
);
check("the node cap holds and the total still tells the truth",
  capped.shown === 8 && capped.total === 12);

/* The two graphs must never mix: an ownership tree is drawn only from ownership rows,
   and partnerTree keeps its own heading. */
check("partnerTree still returns its own shape and no ownership kind",
  partnerTree({ name: "X", partners: [{ label: "Y", ptype: "MoU / strategic" }] }).kind
    === undefined);

console.log(ok.map((n) => "  ok   " + n).join("\n"));
if (bad.length) {
  console.error(bad.map((n) => "  FAIL " + n).join("\n"));
  process.exit(1);
}
console.log(`ownershipTree: ${ok.length} checks passed`);
