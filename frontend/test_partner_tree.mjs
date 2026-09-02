/* partnerTree feeds the Partner Network graph. It must never invent a node, never draw
 * the same partner twice, and must spend a capped row on the strongest ties -- the
 * failure that matters is a supply contract crowding out a joint venture.
 *
 *   node test_partner_tree.mjs
 */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./src/pages/competitive/Profile.jsx", import.meta.url), "utf8");
const from = src.indexOf("const TIE_RANK");
const to = src.indexOf("const getCorporateStructureMap");
const { partnerTree } = await import(
  "data:text/javascript," + encodeURIComponent(src.slice(from, to))
);

const ok = [];
const bad = [];
const check = (name, cond) => (cond ? ok : bad).push(name);

check("no partners -> null (graph stays dark, nothing invented)",
  partnerTree({ name: "X", partners: [] }) === null);
check("missing partners key -> null",
  partnerTree({ name: "X" }) === null);

/* Shapes copied from serving.competitors.partners on the live box. */
const adani = {
  name: "Adani Defence",
  partners: [
    { label: "Bharat Forge", ptype: "Supplier / Contract", src: "https://a" },
    { label: "EDGE Group", ptype: "MoU / strategic", src: "https://b" },
    { label: "Leonardo", ptype: "Joint venture", src: "https://c" },
    { label: "DRDO", ptype: "Technology / ToT", src: "https://d" },
  ],
};
const t = partnerTree(adani);
check("equity tie outranks supply, MoU and ToT",
  t.sisters[0].startsWith("Leonardo"));
check("ToT outranks MoU, MoU outranks supply",
  t.sisters[1].startsWith("DRDO") && t.sisters[2].startsWith("EDGE") &&
  t.sisters[3].startsWith("Bharat Forge"));
check("root is the company itself", t.current === "Adani Defence");
check("label carries the relationship type",
  t.sisters[0] === "Leonardo \u00b7 Joint venture");

check("a sourced tie beats an unsourced one of the same class",
  partnerTree({ name: "X", partners: [
    { label: "Unsourced", ptype: "Joint venture" },
    { label: "Sourced", ptype: "Joint venture", src: "https://s" },
  ]}).sisters[0].startsWith("Sourced"));

check("the same partner under two deals is ONE node",
  partnerTree({ name: "X", partners: [
    { label: "Saab", ptype: "Joint venture", src: "https://1" },
    { label: "saab", ptype: "Supplier / Contract", src: "https://2" },
  ]}).sisters.length === 1);

check("a tie with no counterparty name is not a node",
  partnerTree({ name: "X", partners: [
    { label: "", ptype: "Joint venture" }, { label: "  ", ptype: "MoU" },
  ]}) === null);

/* The real reason for the cap: one company on the live box carries 55 ties. */
const many = { name: "Big", partners: Array.from({ length: 55 }, (_, i) =>
  ({ label: "P" + i, ptype: "Supplier / Contract", src: "https://x" })) };
many.partners.push({ label: "TheJV", ptype: "Joint venture", src: "https://jv" });
const big = partnerTree(many);
check("55 ties are capped to 8 nodes", big.sisters.length === 8);
check("the cap does not drop the joint venture", big.sisters[0].startsWith("TheJV"));
check("the count reports what was hidden", big.shown === 8 && big.total === 56);

check("kind is used when ptype is absent",
  partnerTree({ name: "X", partners: [{ label: "P", kind: "Foreign OEM" }] })
    .sisters[0] === "P \u00b7 Foreign OEM");
check("a tie with neither type renders as a bare name",
  partnerTree({ name: "X", partners: [{ label: "P" }] }).sisters[0] === "P");

console.log(bad.length ? "FAIL\n  " + bad.join("\n  ") : `ok - partnerTree, ${ok.length} checks`);
process.exit(bad.length ? 1 : 0);
