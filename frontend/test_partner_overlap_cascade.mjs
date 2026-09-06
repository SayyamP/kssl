/* The overlap node must WIN THE CASCADE, not merely contain the red somewhere.
 *
 * WHY THIS TEST EXISTS, AND WHY THE LAST ONE WAS NOT ENOUGH.
 * test_partner_overlap_red.mjs asserts the emitted SVG string carries #e8483a on the
 * overlapping node. It passed. Production drew the node blue anyway, because
 * `fill="#e8483a"` on an SVG element is a PRESENTATION ATTRIBUTE, not inline style:
 * it sits below every stylesheet rule in the cascade. `.pg-node.ptr.rel-supply
 * circle{fill:#1d3147}` in partnerships.css therefore beat it on Saab -- the single
 * overlapping partner on the Anduril graph, whose tie is a supply agreement -- while
 * the caption underneath went on saying "red above".
 *
 * A string test cannot see that. This one reads the real stylesheet, resolves the
 * cascade the way a browser would for the exact class set graphSvg puts on an
 * overlapping node, and asserts the winning fill is the red. It fails if anyone
 * removes the !important rule, adds a later rel-* rule that outranks it, or renames
 * the class -- which is the whole family of ways this bug comes back.
 */
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./src/styles/partnerships.css", import.meta.url), "utf8");

let fails = 0;
const ck = (name, ok, detail) => {
  console.log(`  ${name.padEnd(70)} ${ok ? "ok" : "FAIL"}${!ok && detail ? "  " + detail : ""}`);
  if (!ok) fails++;
};

/* A deliberately small cascade resolver: enough for the descendant selectors this
   stylesheet uses (".a.b.c circle.d"), and nothing more. */
function parseRules(text) {
  const rules = [];
  const stripped = text.replace(/\/\*[\s\S]*?\*\//g, "");
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  let order = 0;
  while ((m = re.exec(stripped))) {
    const decls = m[2];
    m[1].split(",").forEach((sel) => {
      const s = sel.trim();
      if (s) rules.push({ sel: s, decls, order: order++ });
    });
  }
  return rules;
}

// element under test: <circle class="net-circle"> inside
// <g class="pg-node ptr overlap rel-supply">
const EL = { tag: "circle", classes: ["net-circle"] };
const ANCESTOR = ["pg-node", "ptr", "overlap", "rel-supply"];

function partMatches(part, el, classes) {
  const tag = (part.match(/^[a-z]+/) || [""])[0];
  if (tag && tag !== el.tag) return false;
  const want = (part.match(/\.[-\w]+/g) || []).map((c) => c.slice(1));
  return want.every((c) => classes.indexOf(c) >= 0);
}

function matches(sel) {
  const parts = sel.split(/\s+/).filter(Boolean);
  if (parts.some((p) => /[>+~:]/.test(p))) return false; // out of scope, treat as no match
  const last = parts[parts.length - 1];
  if (!partMatches(last, EL, EL.classes)) return false;
  // every remaining part must match the single ancestor <g>
  return parts.slice(0, -1).every((p) => partMatches(p, { tag: "g" }, ANCESTOR));
}

function specificity(sel) {
  return (sel.match(/\.[-\w]+/g) || []).length * 10 + (sel.match(/(^|\s)[a-z]+/g) || []).length;
}

function winner(prop) {
  let best = null;
  parseRules(css).forEach((r) => {
    if (!matches(r.sel)) return;
    const d = new RegExp(`(?:^|;)\\s*${prop}\\s*:([^;]+)`, "i").exec(r.decls);
    if (!d) return;
    const raw = d[1].trim();
    const important = /!important/i.test(raw);
    const value = raw.replace(/!important/i, "").trim();
    const rank = [important ? 1 : 0, specificity(r.sel), r.order];
    if (!best || rank[0] > best.rank[0]
      || (rank[0] === best.rank[0] && rank[1] > best.rank[1])
      || (rank[0] === best.rank[0] && rank[1] === best.rank[1] && rank[2] > best.rank[2])) {
      best = { value, rank, sel: r.sel };
    }
  });
  return best;
}

// --- the resolver itself has to be trustworthy, so prove it reproduces the BUG ---
const relSupply = parseRules(css).filter((r) => /rel-supply circle$/.test(r.sel));
ck("the rel-supply rule that caused the bug is still in the file",
   relSupply.length === 1, `found ${relSupply.length}`);
ck("...and the resolver agrees it would match an overlap node's circle",
   matches(".pg-node.ptr.rel-supply circle"));

// --- the actual claim ---
const fill = winner("fill");
ck("an overlapping node's fill resolves to the overlap red",
   !!fill && /#e8483a/i.test(fill.value), fill ? `${fill.value} from "${fill.sel}"` : "no rule set fill");
ck("...and it wins by !important, not by source order alone",
   !!fill && fill.rank[0] === 1, fill ? `important=${fill.rank[0]}` : "");

const halo = (() => {
  const saved = EL.classes;
  EL.classes = ["halo"];
  const w = winner("stroke");
  EL.classes = saved;
  return w;
})();
ck("the halo ring around an overlapping node is red too",
   !!halo && /#e8483a/i.test(halo.value), halo ? halo.value : "no rule set stroke");

// --- and an ORDINARY node must NOT be red, or the mark means nothing ---
const plain = (() => {
  const i = ANCESTOR.indexOf("overlap");
  ANCESTOR.splice(i, 1);
  const w = winner("fill");
  ANCESTOR.splice(i, 0, "overlap");
  return w;
})();
ck("a non-overlapping supply partner still draws in its tie colour, not red",
   !!plain && !/#e8483a/i.test(plain.value), plain ? plain.value : "no rule set fill");

console.log(fails ? `\n${fails} FAILED` : "\nok - the overlap red wins the cascade on the node itself");
process.exit(fails ? 1 : 0);
