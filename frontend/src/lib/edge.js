/* ============================ COMPETITIVE EDGE INDEX ============================
   0-100, 50 = parity. Computed from the quantitative specifications rendered
   directly below the gauge and from nothing else, so the number and the bars can
   never disagree.

   The ten comparable spec rows are NOT ten independent facts. Measured across all
   697 matchups in this dataset:
       Power Rating (kW)    = Power Rating (kVA) x 0.8000   (sd 0.0009)
       Engine Output (kW)   = Power Rating (kVA) x 0.8696   (sd 0.0010)
       Engine Output (BHP)  = Engine Output (kW)  x 1.3410  (sd 0.0003)
       Fuel Autonomy (hrs)  = Tank Capacity / Fuel Consumption, exactly (sd 0.0003)
   Treating those as separate evidence multiplied a rating difference by four and
   fuel efficiency by two, then divided the total by ten. That is why the previous
   index reported "near parity" for 686 of 697 matchups while 630 of them had at
   least one spec differing by more than 5%, and why it only ever produced 20
   distinct values. One vote per independent engineering dimension instead.

   RATING is excluded outright. It is the axis matchups are paired on (nearest kVA
   within 25%), so the residual is a pairing artefact: a 3000 kVA set is a different
   product from a 2500 kVA set, not a better one. The residual is reported separately
   as the kVA delta.

   SIZE-DEPENDENT specs are compared per kVA. A 1250 kVA set burns more litres per
   hour than a 1010 kVA set because it makes more power; per kVA that becomes
   specific fuel consumption and power density, which is the like-for-like question.

   dBA is logarithmic, so noise is compared as a difference scaled against 10 dB
   (a perceived doubling of loudness), not as a percentage of the dB number.

   Each dimension gives a signed advantage a, symmetric in the two values
   (|delta| / mean, so which side is larger does not change the magnitude). Below 3%
   is rounding noise and counts as parity. |a| is clamped to 0.40, the ~90th
   percentile gap in this corpus, so one lopsided dimension cannot peg the index.

   The score averages the DECIDED dimensions, not all of them. A spec where both
   sides are identical says nothing about who is stronger, and averaging it in as a
   zero is exactly what manufactured the old all-parity result. Thin evidence is
   handled by a confidence factor instead: d/(d+1), so a single decided dimension
   can move the index at most halfway to the rail.

   Physically impossible values are dropped so one bad cell cannot set the verdict.
   ponytail: no per-dimension weighting — fuel cost probably deserves more than
   footprint, but any weights would be invented here. Equal votes, stated plainly.
   ============================================================================== */

/* The pairing axes. A 155mm gun is a different product from a 105mm gun, a 30-tonne
   MRAP a different product from a 12-tonne LPV — calibre, take-off weight, length and
   barrel length are what matchups are paired ON, so their residual is a pairing
   artefact, not an advantage. Matched by substring so "Calibre" catches
   "Calibre / barrel" and unit-suffixed variants. */
const EDGE_AXIS = ["Calibre", "MTOW", "Length", "Barrel"];
/* Sanity ranges (from the source platform's SPEC_RANGE): a gun crew is 1-15, a
   vehicle carries at most ~20, no naval/land platform here does over 30 kn/kmph-scale
   'Speed' units in this corpus. Out-of-range cells are dropped, not voted. */
const EDGE_RANGE = {
  Crew: [1, 15],
  "Crew / pax": [1, 20],
  Speed: [0.1, 30],
};
export const EDGE_DEADBAND = 0.03;
export const EDGE_CAP = 0.4;
/* Per-dimension parity thresholds (the source platform's SPEC_DEADBAND). A range
   figure without projectile type is soft — ±15% is quoting noise, not an edge; rate
   of fire, endurance and speed carry ±10% between test conditions. */
const EDGE_DEADBAND_BY = {
  "Effective range": 0.15,
  "Rate of fire": 0.1,
  Endurance: 0.1,
  Range: 0.1,
  Speed: 0.1,
};
const isAxisSpec = (l) => EDGE_AXIS.some((a) => (l || "").toLowerCase().includes(a.toLowerCase()));
/* The pipeline decides "level" at a flat 3% (revive_matchups.PARITY_DEADBAND). A
   softer per-dimension threshold here would make the same pair of numbers a lead
   in one place and parity in the other — which is how a stored verdict came to sit
   above a gauge contradicting it. The soft thresholds stay as documentation of
   which figures are noisy; they no longer change the arithmetic. */
const deadbandFor = (_l) => EDGE_DEADBAND;

export function computeSpecEdge(m) {
  const specs = m.specs || [];
  const dims = [];
  specs.forEach((s) => {
    if (isAxisSpec(s.l)) return;
    /* A class axis is an axis: `classAxis` says the corpus calls these two products
       different kinds of machine (a tracked self-propelled howitzer against a towed
       gun), so their masses differ by what they ARE. Counting it made the ATAGS
       "beat" the K9 Thunder by 29 tonnes of hull and engine. The number still
       renders — see the dims list — it just cannot decide the comparison. */
    if (s.classAxis) return;
    if (s.cn == null || s.kn == null || s.hi == null) return;
    const lim = EDGE_RANGE[s.l];
    if (lim && (s.cn < lim[0] || s.cn > lim[1] || s.kn < lim[0] || s.kn > lim[1]))
      return; // bad cell
    const c = s.cn;
    const k = s.kn;
    const mean = (c + k) / 2;
    if (!mean) return;
    let a = ((k - c) / mean) * (s.hi ? 1 : -1);
    if (Math.abs(a) < deadbandFor(s.l)) a = 0;
    // `a` is clamped for the index so one lopsided dimension cannot peg it. `raw` keeps
    // the true signed gap, because a report that says "worst 40%" when the real deficit
    // is 140% is just showing you the clamp.
    dims.push({
      l: s.l,
      a: Math.max(-EDGE_CAP, Math.min(EDGE_CAP, a)),
      raw: a,
      perKva: false,
      /* The two figures this advantage was computed from. Gap Analysis could say a
         rival led on weight but never what the two weights were, so the eleven
         head-to-head comparisons its own subtitle counted were nowhere on the page. */
      cn: c,
      kn: k,
      cv: s.cv,
      kv: s.kv,
    });
  });
  if (!dims.length) return { edge: null, n: 0, decided: 0, dims: [] };
  const dec = dims.filter((d) => d.a !== 0);
  /* ONE DEFINITION OF THE INDEX, SHARED WITH THE PIPELINE.

     This used to average the signed magnitudes; `revive_matchups.py` counts the
     dimensions each side leads. Two formulas for one number, and the wiring
     overwrote the served value with this one on load — so the figure in the
     database, the figure in /api/dataset and the figure on the screen were not
     the same number. They disagreed on 7 of 219 matchups and flipped one verdict
     (50 "level" served, 47 "rival ahead" shown).

     The pipeline's definition wins, because averaging lets a lead on one dimension
     cancel a deficit on another — kW/kg and sq.m/kVA are not fungible, which is
     the argument Gap Analysis is built on. Counted, never averaged:
         edge = 50 + (100·leadClient/comparable − 50) · n/(n+1)
     and NO verdict at all when nothing separated the two machines. */
  if (!dec.length) return { edge: null, n: dims.length, decided: 0, dims };
  /* The share is taken over the DECIDED dimensions, not every comparable one.
     Dividing by all of them let ties vote: one dimension led by the client and
     three matched read 25/100 — the client behind, on a comparison it wins and
     never loses. A dimension both machines match on separates nobody. */
  const leadK = dec.filter((d) => d.a > 0).length;
  const raw = (100 * leadK) / dec.length;
  const edge = Math.round(50 + (raw - 50) * (dec.length / (dec.length + 1)));
  return {
    edge: Math.max(2, Math.min(98, edge)),
    n: dims.length,
    decided: dec.length,
    dims,
  };
}

/* One verdict per index value. The gauge used 58/42 while the report and the chat
   used 60/48, so an index of 45 read "near parity" on the gauge and "competitor
   holds the edge" three panels over. Symmetric band of +/-8 around parity: a single
   decided dimension needs a ~13% gap to move the verdict off parity. */
export function edgeVerdict(e, clientName = "KSSL") {
  const short = (clientName || "KSSL").toUpperCase();
  const name = clientName || "KSSL";
  if (e == null)
    return {
      cls: "parity",
      word: "INSUFFICIENT MEASURED DATA",
      phrase: "no measured basis",
    };
  if (e >= 58) return { cls: "ahead", word: `${short} AHEAD`, phrase: `${name} holds the edge` };
  if (e >= 42) return { cls: "parity", word: "NEAR PARITY", phrase: "near parity" };
  return { cls: "behind", word: `${short} BEHIND`, phrase: "competitor holds the edge" };
}

/* Show exactly which dimensions produced the number, so the gauge is auditable
   against the bars underneath it. */
export function edgeBasis(ce) {
  const esc = (s) =>
    `${s == null ? "" : s}`.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  if (ce.edge == null)
    return '<div class="eg-note">No independent quantitative dimension is measured on both sides, so no index is computed.</div>';
  const dec = ce.dims
    .filter((d) => d.a !== 0)
    .sort((a, b) => Math.abs(b.a) - Math.abs(a.a));
  let h =
    `<div class="eg-note"><b>${ce.n}</b> independent dimension${ce.n === 1 ? "" : "s"}` +
    ` compared, <b>${ce.decided}</b> decided${
      ce.decided
        ? ":"
        : ". Every measured dimension is level, so the index is exactly parity."
    }`;
  if (dec.length) {
    h += `<div class="eg-dims">${dec
      .map((d) => {
        const pct = Math.round(Math.abs(d.a) * 100);
        return (
          `<span class="eg-dim ${d.a > 0 ? "up" : "down"}">${d.a > 0 ? "▲" : "▼"} ` +
          `${esc(d.l.replace(/\s*\(.*\)$/, ""))}` +
          ` <i>${pct}%${Math.abs(d.a) >= EDGE_CAP ? "+" : ""}</i></span>`
        );
      })
      .join("")}</div>`;
    const lvl = ce.n - ce.decided;
    h +=
      (lvl ? `${lvl} dimension${lvl === 1 ? "" : "s"} level. ` : "") +
      `Averaged over the decided dimensions and shrunk by ${ce.decided}/${ce.decided + 1}` +
      " for evidence depth.";
  }
  h +=
    " Calibre, length and weight-class axes are excluded — they are what this pair is matched on, not an advantage." +
    " Qualitative and undisclosed factors are not included.</div>";
  return h;
}

/* shared: a value is a real statistic only if its displayed value leads with a number */
export function isNumericVal(v) {
  if (v == null) return false;
  const t = String(v).trim();
  if (!/\d/.test(t)) return false;
  return /^[~$<>]?\s*\d/.test(t);
}

/* One runnable check on the logic above: symmetry, the parity floor, direction, the
   dedupe, and the confidence ordering. Runs on load; logs only on failure. */
export function edgeSelfCheck() {
  const S = (l, cn, kn, hi) => ({ l, cn, kn, hi });
  const CAL = (a, b) => S("Calibre", a, b, true); // pairing axis — must never vote
  const MR = (a, b) => S("Max range", a, b, true);
  const W = (a, b) => S("Combat weight", a, b, false);
  const RF = (a, b) => S("Rate of fire", a, b, true);
  const CR = (a, b) => S("Crew", a, b, false);
  const e = (sp) => computeSpecEdge({ specs: sp }).edge;
  const fail = [];
  const ok = (c, msg) => {
    if (!c) fail.push(msg);
  };
  // identical specs -> exact parity
  // identical specs decide nothing, so there is no index to assert -- the same
  // answer the pipeline stores, and the dossier says "level on every field"
  ok(e([CAL(155, 155), MR(40, 40), W(30, 30)]) === null, "identical specs decide nothing");
  // a class axis is excluded like the pairing axis: the corpus says these two are
  // different kinds of machine, so their masses are not a comparison
  ok(
    e([{ l: "Weight", cn: 47000, kn: 18000, hi: false, classAxis: "towed vs SP" }]) === null,
    "a class axis must not decide a comparison",
  );
  // the pairing axes alone must not move the index
  ok(
    e([CAL(155, 105), S("MTOW (kg)", 450, 380, true)]) === null,
    "axis-only specs must yield no index",
  );
  // direction: KSSL shooting shorter must read below 50, further must read above
  ok(e([CAL(155, 155), MR(48, 40)]) < 50, "KSSL worse on range must be <50");
  ok(e([CAL(155, 155), MR(40, 48)]) > 50, "KSSL better on range must be >50");
  // symmetry: mirroring the two sides mirrors the index around 50
  ok(
    e([CAL(155, 155), MR(48, 40)]) + e([CAL(155, 155), MR(40, 48)]) === 100,
    "index must be symmetric about 50",
  );
  // deadband: a sub-3% difference is noise, and noise decides nothing
  ok(e([CAL(155, 155), W(30, 30.5)]) === null, "a sub-3% gap decides nothing");
  /* ONE deadband, the pipeline's 3%. A softer per-dimension threshold here made
     the same two numbers a lead in the database and parity on the screen; a 10%
     range difference now counts on both sides of that line. The soft bands remain
     documented in EDGE_DEADBAND_BY as a note about which figures are noisy. */
  ok(e([CAL(155, 155), S("Effective range", 40, 36, true)]) !== null,
     "a 10% range gap decides, as it does in the pipeline");
  ok(e([CAL(155, 155), S("Effective range", 48, 36, true)]) < 50, "a 28% range gap must vote");
  // confidence: two dimensions agreeing must read further from parity than one alone
  ok(
    e([CAL(155, 155), MR(48, 40), W(28, 33)]) < e([CAL(155, 155), MR(48, 40)]),
    "more agreeing evidence must move further",
  );
  // padding with level dimensions must not dilute a real gap into "near parity"
  ok(
    e([CAL(155, 155), MR(48, 40), W(30, 30), RF(6, 6)]) < 42,
    "level dimensions must not dilute a decided gap",
  );
  ok(
    e([CAL(155, 155), MR(48, 40), W(30, 30), RF(6, 6)]) === e([CAL(155, 155), MR(48, 40)]),
    "adding level dimensions must not change the index at all",
  );
  // impossible values are dropped rather than driving the verdict
  ok(e([CAL(155, 155), CR(45, 5)]) === null, "implausible crew count must be dropped");
  if (fail.length) console.error("computeSpecEdge self-check FAILED:", fail);
  return fail;
}
