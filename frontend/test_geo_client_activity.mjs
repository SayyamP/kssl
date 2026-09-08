/* The client's badge must lose the ECHO without losing the ACTIVITY.
 *
 * Measured against production: KSSL has exactly two served geo_presence rows, India
 * and Europe, and BOTH are stored c='lp' ("Local production"). No c='bf' row is
 * served at all -- serving_live filters to origin='pipeline' and every 'bf' row is
 * origin='reference'. The 'bf' the badge sees is created in the BROWSER, by
 * dataset.js stamping p.c='bf' over every client footprint row.
 *
 * That is why the badge read "KSSL Present . KSSL present": actLabel.bf is the string
 * "KSSL present", so the template appended the client's own name to a sentence that
 * already said it. Dropping 'bf' from the activity list fixes the echo -- but on its
 * own it also throws away "Local production", because the overwrite had already
 * destroyed the only copy of the real code. Both halves have to hold at once:
 *
 *     wrong (before)      KSSL Present . KSSL present
 *     wrong (echo fix)    KSSL Present
 *     right               KSSL Present . Local production
 */
import { ownActivityLabels, presenceBadge } from "./src/lib/geoBadge.js";

let fails = 0;
const ck = (name, ok, detail) => {
  console.log(`  ${name.padEnd(68)} ${ok ? "ok" : "FAIL"}${!ok && detail ? "  " + detail : ""}`);
  if (!ok) fails++;
};

// serving.ui_config's real dictionary, for the two codes that matter here
const ACT = { bf: "KSSL present", lp: "Local production", ex: "Export / supply", pt: "Licence / partnership" };

// India exactly as the browser holds it after dataset.js runs: stored 'lp',
// overwritten to 'bf', original kept in c0
const india = [{ c: "bf", c0: "lp", country: "India", src: "https://indiandefencereview.com/x" }];

const labels = ownActivityLabels(india, ACT, "KSSL");
ck("the self-naming 'KSSL present' label is gone", labels.indexOf("KSSL present") < 0, JSON.stringify(labels));
ck("...but the real activity survives the overwrite", labels.indexOf("Local production") >= 0, JSON.stringify(labels));
ck("...and it is the only thing said", labels.length === 1, JSON.stringify(labels));

// a row that never had a real code must not invent one
const bare = ownActivityLabels([{ c: "bf", country: "India" }], ACT, "KSSL");
ck("a client row with no original code says nothing rather than echoing",
   bare.length === 0, JSON.stringify(bare));

// a rival's rows are untouched by any of this
const rival = ownActivityLabels([{ c: "lp" }, { c: "ex" }], ACT, "KSSL");
ck("a non-client row keeps every one of its activities",
   rival.length === 2 && rival.indexOf("Local production") >= 0 && rival.indexOf("Export / supply") >= 0,
   JSON.stringify(rival));

// and the whole badge, which is what the operator actually reads
if (typeof presenceBadge === "function") {
  const badge = presenceBadge(india, ACT, "KSSL");
  const text = typeof badge === "string" ? badge : JSON.stringify(badge);
  ck("the rendered badge never says the client's name twice",
     (text.match(/KSSL present/gi) || []).length <= 1, text);
}

console.log(fails ? `\n${fails} FAILED` : "\nok - the echo is gone and Local production survived");
process.exit(fails ? 1 : 0);
