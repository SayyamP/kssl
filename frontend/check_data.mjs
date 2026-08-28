import fs from "node:fs";
import { wireDataset } from "./src/lib/dataset.js";
import { bucketTenders, navCounts } from "./src/lib/overview.js";
import { buildGapModel } from "./src/lib/gapModel.js";
import { marketSelfCheck, marketMetrics, demandSplit, closingWindows, portalRows } from "./src/lib/marketOverview.js";
import { profileSelfCheck, rosterOf, buildProfile } from "./src/lib/profile.js";

const P = process.argv[2];
const raw = JSON.parse(fs.readFileSync(P, "utf8"));
const d = wireDataset(raw);

console.log("== market ==");
marketSelfCheck(d.tenders);
const { open, awarded, closed } = bucketTenders(d.tenders);
console.log("open/awarded/closed:", open.length, awarded.length, closed.length, "of", d.tenders.length);
console.log("tiles:", marketMetrics(d.tenders).map((m) => `${m.l}=${m.v}${m.unit || ""}`).join("  "));
console.log("split :", demandSplit(open).map((s) => `${s.label} ${s.count}`).join(" | "));
console.log("window:", closingWindows(open).map((w) => `${w.label} ${w.count} (${w.pct}%)`).join(" | "));
console.log("portals:", portalRows(d.tenders).map((p) => `${p.host} ${p.total}/${p.open}`).join(" | "));

console.log("\n== profile ==");
profileSelfCheck(d);
const roster = rosterOf(d);
console.log("rivals:", roster.length, "| with >=1 section:", roster.filter((r) => r.filled).length,
            "| empty:", roster.filter((r) => !r.filled).length);
const rank = roster.slice().sort((a, b) => b.filled - a.filled);
rank.slice(0, 5).concat(rank.slice(-3)).forEach((r) => {
  const p = buildProfile(d, r.cid);
  console.log(`  ${r.name.padEnd(30)} ${r.filled}/${r.total}  ` +
    p.sections.filter((s) => s.rows).map((s) => `${s.key}:${s.rows}`).join(" "));
});
console.log("\n== counts ==");
const c = navCounts(d, buildGapModel(d));
console.log("profile:", c.profile, "m-overview:", c["m-overview"], "overview:", c.overview, "tender:", c.tender);
console.log("\nALL CHECKS PASSED");
