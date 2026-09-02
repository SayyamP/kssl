/* ==================== GAP ANALYSIS (Competitive) ====================
   Which rivals beat KSSL in this category, on what, and what it wins them.

   WHY THIS DOES NOT USE THE EDGE INDEX AS ITS VERDICT
   The Positioning gauge reduces a matchup to one number by averaging the signed
   advantage across dimensions. That is fine for a gauge that shows its own
   workings, but it cannot answer "does this rival have an advantage", because
   averaging lets advantages on different dimensions CANCEL. Cummins vs KG1-750WS
   is ahead on ground area (11%) and fuel tank (14%) and behind on power-to-weight
   (15%); the mean is -0.03 and the matchup reads 47/100 — parity. 85 matchups
   read parity while the rival led more dimensions than KSSL.
   kW/kg and sq.m/kVA are not fungible: a buyer does not average their spec sheet,
   they buy the machine that wins the dimensions their site cares about.

   So this view aggregates DIMENSION OUTCOMES directly. For each dimension it
   counts how often each side is ahead across the rival's matchups, and reports
   who owns it. Nothing cancels, nothing is averaged twice, and every claim
   carries the denominator it was computed from.

   A dimension is only claimed when there is enough data to claim it: `comparable`
   counts matchups where BOTH products published that spec. Caterpillar India
   looked like it led power-to-weight by 29% in the 376-1500 kVA band — on 1 of
   its 25 matchups. That is a coverage fact, not a competitive one, and it now
   says so. */
import { computeSpecEdge } from "./edge.js";
import { escAll } from "./html.js";

export const GAP_OWN = 0.65; // share of the DECIDED matchups needed to own a dimension
export const GAP_MINDEC = 3; // and at least this many matchups must separate the machines
export const GAP_MINMARGIN = 2; // won by at least this many more than it lost
export const GAP_MINCMP = 3; // and at least this many, and this share of the rival's matchups
export const GAP_MINCOV = 0.4;
export const GAP_THIN = 5; // fewer matchups than this and the whole row is indicative only
const GAP_AXIS = 5; // the bar's domain: net dimensions owned, -5..+5

export const gesc = escAll;
export const gshort = (s) => escAll((s || "").split("·")[0].trim());
const gmed = (xs) => {
  const p = xs.slice().sort((a, b) => a - b);
  return p.length ? p[Math.floor(p.length / 2)] : 0;
};

/* Per-dimension presentation. Noise is scaled against 10 dB inside the index, so
   its raw magnitude is dB*10 — printing it as a percentage would show "55%" for a
   5.5 dB difference. Each dimension carries its own unit and its own ladder,
   because 5% on fuel and 5 dB on noise are not the same size of problem. */
export const GAP_DIM = {
  "Max range": {
    short: "Max range",
    dir: "higher is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [25, 15, 10, 5],
    note: "A range figure is meaningless without projectile type, charge and calibre-length: the same 155 mm barrel gives about 41 km on base-bleed and 55 km on V-LAP, a 33% swing from ammunition alone.",
  },
  "Artillery|Weight": {
    short: "Weight",
    dir: "lower is better",
    arrow: "↓",
    unit: "%",
    scale: 1,
    bins: [30, 20, 10, 5],
    note: "The ladder is set by transport class — C-130J at roughly 19-20 t, A400M at 37 t, CH-47 underslung at 10-12 t — and by bridge Military Load Classification. A 17.7 t against 24 t gap is usually a towed gun against a truck-mounted one, which are different objects rather than a lighter design.",
  },
  Crew: {
    short: "Crew",
    dir: "fewer is better",
    arrow: "↓",
    unit: "%",
    scale: 1,
    bins: [40, 25, 15, 10],
    note: "Crew count is a proxy for automation, on the ladder 8 → 6 → 4 → 3 → 2 (KNDS RCH 155 fires at 2, Archer at 3-4, conventional towed 155 at 6-8). It is an integer axis, so any whole-person difference is real. OEM figures usually exclude the gun position officer and the ammunition party.",
  },
  "Rate of fire": {
    short: "Rate of fire",
    dir: "higher is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [30, 20, 12, 10],
    note: "Burst, intense and sustained rates are three different numbers — ATAGS quotes 6 rounds in 30 s burst against a sustained requirement of 60 rounds in 60 minutes. Only sustained rate predicts rounds delivered across a day-long fire plan.",
  },
  "Combat weight": {
    short: "Combat weight",
    dir: "lower is better",
    arrow: "↓",
    unit: "%",
    scale: 1,
    bins: [40, 25, 15, 5],
    note: "Only comparable at equal STANAG 4569 protection: a lighter Level 2 hull is not ahead of a heavier Level 4 one. Add-on armour alone is typically 10-20% of combat weight, and the growth margin left for future kit often decides the tender.",
  },
  "Crew / pax": {
    short: "Crew / capacity",
    dir: "more capacity is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [50, 25, 15, 10],
    note: "A threshold rather than a magnitude, shown here as a percentage proxy: capacity only pays when it crosses the buyer's section size, because a section that does not fit one hull splits across two and doubles the fleet. Seats beyond it buy nothing, and blast-attenuating seats consume far more volume than bench seating.",
  },
  "Effective range": {
    short: "Effective range",
    dir: "higher is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [50, 30, 20, 15],
    note: "The widest tolerance on this page, because the term has no single definition — the same 5.56×45 round is quoted at 300, 500, 550, 600 and 800 m depending on barrel, sight and whose manual. The class divides are 300→500 m (carbine to rifle) and 500→800 m (rifle to marksman).",
  },
  "Small Arms|Weight": {
    short: "Weight",
    dir: "lower is better",
    arrow: "↓",
    unit: "%",
    scale: 1,
    bins: [25, 15, 10, 5],
    note: "Measured against the doctrinal soldier load — a 48 lb fighting load and 72 lb approach march (ATP 3-21.18). A 0.43 kg rifle delta is about 2% of the fighting load. Optic, laser and loaded magazines add 1.5-2.5 kg, more than any credible difference between two rifles.",
  },
  "UAVs & Drones|Endurance": {
    short: "Endurance",
    dir: "higher is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [50, 30, 20, 10],
    note: "The step changes are orbit arithmetic, not spec noise: airframes per persistent orbit is ceil((24 h + transit + turnaround) / endurance), so 36 h against 20 h takes a standing orbit from three airframes to two. Quoted figures are clean-configuration and reserve-free; a SATCOM ball, turret and weapons cost 20-40%.",
  },
  "Marine / Naval|Endurance": {
    short: "Endurance",
    dir: "higher is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [50, 30, 20, 10],
    note: "Days on station decide patrol cycles and therefore hulls per station, but the figure is quoted at economical speed and says nothing about sea-state limit or crew habitability, which are what actually end a patrol.",
  },
  "UAVs & Drones|Range": {
    short: "Range",
    dir: "higher is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [50, 30, 20, 10],
    note: "Check whether the number is fuel-limited or datalink-limited: line-of-sight control typically walls at 200-250 km, and a SATCOM fit removes that wall entirely — so the figure may be measuring the comms package rather than the aircraft.",
  },
  "Missiles & Air Defence|Range": {
    short: "Range",
    dir: "higher is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [50, 30, 20, 10],
    note: "Only comparable inside one air-defence layer — VSHORAD 5-10 km, SHORAD 10-25 km, medium 25-70 km, long above 100 km. A 25 km against 100 km pairing spans two layers of the same architecture, not a fourfold lead. Headline range is a kinematic maximum against a non-manoeuvring target; the no-escape zone is a fraction of it.",
  },
  Speed: {
    short: "Speed",
    dir: "higher is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [60, 30, 20, 10],
    note: 'The real steps are regime boundaries — subsonic, supersonic, and hypersonic above Mach 5, where the defender needs a new interceptor rather than a better one. Quoted Mach is usually peak at burnout, and Mach is altitude-dependent, so two "Mach 2.5" claims can be different absolute speeds.',
  },
  "Annual capacity": {
    short: "Annual capacity",
    dir: "higher is better",
    arrow: "↑",
    unit: "%",
    scale: 1,
    bins: [100, 50, 25, 10],
    note: "The defining 155mm metric since 2022: demand outruns supply, so stated annual output — current or funded target — is what wins framework contracts. Announced targets and demonstrated output are different numbers; the year attached to a figure matters as much as the figure.",
  },
};
/* Category-scoped resolution, exactly as the source platform did it: 'Weight' means
   a howitzer in Artillery and a rifle in Small Arms, so the scoped entry wins and
   the plain label is the fallback. gapRivals stamps the active category. */
let _gapMetaCat = "";
const GAP_ORDER = [...new Set(Object.keys(GAP_DIM).map((k) => k.split("|").pop()))];
export const gdmeta = (l) =>
  GAP_DIM[`${_gapMetaCat}|${l}`] ||
  GAP_DIM[l] || {
    short: String(l).replace(/\s*\(.*\)$/, ""),
    dir: "",
    arrow: "",
    unit: "%",
    scale: 1,
    bins: [40, 20, 8, 1],
  };
export const gval = (l, pct) => {
  const m = gdmeta(l);
  const v = pct * m.scale;
  return (m.scale === 1 ? Math.round(v) : Math.round(v * 10) / 10) + m.unit;
};
const gbin = (l, pct) => {
  const b = gdmeta(l).bins;
  const v = pct * gdmeta(l).scale;
  return v >= b[0] ? 4 : v >= b[1] ? 3 : v >= b[2] ? 2 : v >= b[3] ? 1 : v > 0 ? 1 : 0;
};

/* THE TWO FIGURES MUST BE IN THE SAME UNIT.

   The comparison line printed "13000 kg vs 18 t" and "4.2 vs < 15 t": both are
   what the source page says, and neither reader can subtract them. The conversion
   needs no unit table — the record already carries each figure twice, once as the
   source wrote it and once in a base unit, so the ratio between them IS the
   factor. Anything that does not parse cleanly (a range, a "<" bound) is left
   exactly as its source wrote it; a guessed number would be worse than an awkward
   one. */
const NUM_RX = /-?\d[\d,]*(?:\.\d+)?/;
const unitOf = (v) => {
  const t = String(v == null ? "" : v);
  const m = t.match(NUM_RX);
  if (!m) return null;
  // "30-56 km" leaves "-56 km" behind the first number; the unit is what follows
  // the LAST number, not the rest of the string
  const u = t
    .slice(m.index + m[0].length)
    .replace(/^\s*(?:[-–—]|\bto\b)\s*[\d.,]+/, "")
    .trim();
  return { n: parseFloat(m[0].replace(/,/g, "")), u, pre: t.slice(0, m.index).trim(), raw: t };
};
const fmtNum = (n) =>
  Math.abs(n) >= 100 ? String(Math.round(n)) : String(Math.round(n * 10) / 10);

export function pairVals(x) {
  const rv = x.cv != null ? String(x.cv) : x.cn != null ? String(x.cn) : "—";
  const kv = x.kv != null ? String(x.kv) : x.kn != null ? String(x.kn) : "—";
  const r = unitOf(rv);
  const k = unitOf(kv);
  if (!r || !k || x.cn == null || x.kn == null) return [rv, kv];
  const ru = r.u.toLowerCase();
  const ku = k.u.toLowerCase();
  if (ru === ku) return [rv, kv];
  // the side that names its unit sets the unit; the factor comes from that side's
  // own pair of figures (base value / written value)
  const target = ku ? k : r;
  const targetBase = ku ? x.kn : x.cn;
  if (!target.n || !targetBase) return [rv, kv];
  const factor = targetBase / target.n;
  if (!isFinite(factor) || factor <= 0) return [rv, kv];
  /* A range is not a number. "30-56" parses as 30, and converting it printed
     "30 km" for a gun whose published range runs to 56 -- dropping the upper bound
     silently. A range keeps its own text and only gains the unit. */
  const isRange = (t) => /\d\s*(?:[-–—]|\bto\b)\s*\d/.test(t);
  const conv = (base, own) =>
    isRange(own.raw)
      ? `${own.raw}${own.u || !target.u ? "" : ` ${target.u}`}`
      : `${own.pre ? `${own.pre} ` : ""}${fmtNum(base / factor)}${target.u ? ` ${target.u}` : ""}`;
  return ku ? [conv(x.cn, r), kv] : [rv, conv(x.kn, k)];
}

/* One rival in one band. Ownership decides the verdict (no cancellation); the
   margin, record and worst-case are kept because they are real facts the table
   shows alongside it. */
export function gapRivals(matchups, cat, clientName = "KSSL") {
  _gapMetaCat = cat || "";
  const by = {};
  Object.keys(matchups).forEach((id) => {
    const m = matchups[id];
    if (m.cat !== cat || m.edge == null) return;
    const co = (m.compBy || m.comp || "—").trim();
    const r = (by[co] = by[co] || { co, rows: [], d: {} });
    const dims = computeSpecEdge(m).dims || [];
    r.rows.push({ id, m, dims, lead: 50 - m.edge, edge: m.edge });
    dims.forEach((x) => {
      const s = (r.d[x.l] = r.d[x.l] || {
        win: 0,
        loss: 0,
        level: 0,
        winMag: [],
        lossMag: [],
      });
      if (x.a < 0) {
        s.win++;
        s.winMag.push(-x.raw * 100);
      } else if (x.a > 0) {
        s.loss++;
        s.lossMag.push(x.raw * 100);
      } else s.level++;
    });
  });
  return Object.values(by)
    .map((r) => {
      const n = r.rows.length;
      const presentLabels = Object.keys(r.d);
      const activeOrder = GAP_ORDER.filter((l) => presentLabels.includes(l));
      const orderList = activeOrder.length ? activeOrder : GAP_ORDER;

      const all = orderList.map((l) => {
        const s = r.d[l];
        if (!s)
          return {
            l,
            own: "nodata",
            comparable: 0,
            cover: 0,
            n,
            win: 0,
            loss: 0,
            level: 0,
            wr: 0,
            lr: 0,
            med: 0,
            medLoss: 0,
          };
        const comparable = s.win + s.loss + s.level;
        const cover = n ? comparable / n : 0;
        const minCmp = n < 3 ? 1 : GAP_MINCMP;
        const enough = comparable >= minCmp && (cover >= GAP_MINCOV || n < 3);
        const decided = s.win + s.loss;
        const wr = decided ? s.win / decided : 0;
        const lr = decided ? s.loss / decided : 0;
        let own;
        /* Apply the rule the screen publishes. The methodology note and the
           scale caption both state 65% of decided matchups with a margin; the
           test here was a bare 50% and no margin, so a dimension won 3-2 was
           reported to the CEO as "owned" by a rival. */
        if (!enough) own = "nodata";
        else if (decided < GAP_MINDEC) own = "contested";
        else if (wr >= GAP_OWN && s.win - s.loss >= GAP_MINMARGIN) own = "rival";
        else if (lr >= GAP_OWN && s.loss - s.win >= GAP_MINMARGIN) own = "koel";
        else own = "contested";
        return {
          l,
          own,
          comparable,
          cover: Math.round(cover * 100),
          n,
          win: s.win,
          loss: s.loss,
          level: s.level,
          wr: Math.round(wr * 100),
          lr: Math.round(lr * 100),
          med: Math.round(gmed(s.winMag)),
          medLoss: Math.round(gmed(s.lossMag)),
        };
      });
      const rivalOwns = all.filter((d) => d.own === "rival");
      const koelOwns = all.filter((d) => d.own === "koel");
      const contested = all.filter((d) => d.own === "contested").length;
      const nodata = all.filter((d) => d.own === "nodata").length;
      let k;
      let w;
      // Per-matchup outcome also has to come from dimensions. Classifying by the index
      // (lead>8) reintroduced the cancellation: Greaves Cotton owns 2 dimensions to
      // KSSL's 1 in the 16-75 kVA band, yet its index margin is -9.3, so the bar and
      // the record bar both pointed at KSSL on a row verdicted "KSSL behind".
      // A matchup goes to whichever side is ahead on more dimensions.
      const rivalWins = r.rows.filter(
        (x) => x.dims.filter((dd) => dd.a < 0).length > x.dims.filter((dd) => dd.a > 0).length,
      ).length;
      const koelWins = r.rows.filter(
        (x) => x.dims.filter((dd) => dd.a > 0).length > x.dims.filter((dd) => dd.a < 0).length,
      ).length;
      // the bar plots the ownership balance, which is exactly what the verdict compares,
      // so its direction can never contradict the verdict
      const balance = rivalOwns.length - koelOwns.length;
      if (nodata === all.length) {
        k = "nodata";
        w = "Not enough data";
      } else if (rivalOwns.length > koelOwns.length) {
        k = "behind";
        w = `${clientName} behind`;
      } else if (koelOwns.length > rivalOwns.length) {
        k = "ahead";
        w = `${clientName} ahead`;
      } else if (!rivalOwns.length && !koelOwns.length) {
        k = "contested";
        w = "No clear edge";
      } else {
        k = "contested";
        w = "Traded";
      }
      // A one-dimension ownership margin is weak evidence. If the matchup-by-matchup
      // count points the other way, the two granularities disagree and neither should
      // claim a direction — say Traded rather than let the table contradict itself.
      if (
        Math.abs(balance) === 1 &&
        ((balance > 0 && rivalWins < koelWins) || (balance < 0 && rivalWins > koelWins))
      ) {
        k = "contested";
        w = "Traded";
      }
      // open the matchup where the rival takes the most dimensions outright
      const scored = r.rows.map((x) => ({
        ...x,
        net: x.dims.filter((d) => d.a < 0).length - x.dims.filter((d) => d.a > 0).length,
      }));
      const worst = scored.reduce(
        (a, b) => (b.net > a.net || (b.net === a.net && b.edge < a.edge) ? b : a),
        scored[0],
      );
      return {
        co: r.co,
        n,
        // the individual comparisons behind `n`, so the page can list what it counts
        rows: r.rows,
        all,
        rivalOwns,
        koelOwns,
        contested,
        nodata,
        verdict: { k, w },
        balance,
        rivalWins,
        koelWins,
        parity: n - rivalWins - koelWins,
        worst,
        thin: n < GAP_THIN,
        masked: k !== "behind" && worst.edge < 42,
        severity: rivalOwns.reduce((t, d) => t + gbin(d.l, d.med), 0),
        dims: rivalOwns
          .slice()
          .sort((a, b) => gbin(b.l, b.med) - gbin(a.l, a.med) || b.med - a.med),
      };
    })
    .sort((a, b) => {
      const rank = { behind: 0, contested: 1, ahead: 2, nodata: 3 };
      return (
        rank[a.verdict.k] - rank[b.verdict.k] ||
        b.rivalOwns.length -
          b.koelOwns.length -
          (a.rivalOwns.length - a.koelOwns.length) ||
        b.severity - a.severity ||
        b.rivalWins - b.koelWins - (a.rivalWins - a.koelWins) ||
        b.n - a.n
      );
    });
}

export function gapCategories(matchups) {
  const by = {};
  Object.keys(matchups).forEach((id) => {
    const m = matchups[id];
    if (m.edge == null) return;
    const c = (by[m.cat] = by[m.cat] || { n: 0 });
    c.n++;
  });
  return Object.keys(by)
    .map((cat) => {
      const rv = gapRivals(matchups, cat);
      return {
        cat,
        n: by[cat].n,
        rivals: rv.length,
        behind: rv.filter((r) => r.verdict.k === "behind").length,
        ahead: rv.filter((r) => r.verdict.k === "ahead").length,
        balance: rv.reduce((t, r) => t + r.balance, 0),
      };
    })
    .sort(
      (a, b) =>
        b.behind / (b.rivals || 1) - a.behind / (a.rivals || 1) ||
        b.behind - a.behind ||
        b.n - a.n,
    );
}

function gapDimRows(rivals) {
  const activeOrder = GAP_ORDER.filter((l) =>
    rivals.some((r) => r.all && r.all.some((x) => x.l === l && x.own !== "nodata")),
  );
  const orderList = activeOrder.length ? activeOrder : GAP_ORDER;

  return orderList
    .map((l) => {
      const cells = rivals.map((r) => ({ co: r.co, d: r.all.find((x) => x.l === l) }));
      const owned = cells.filter((c) => c.d && c.d.own === "rival");
      return {
        l,
        cells,
        rivalOwns: owned.length,
        koelOwns: cells.filter((c) => c.d && c.d.own === "koel").length,
        med: owned.length ? Math.round(gmed(owned.map((c) => c.d.med))) : 0,
      };
    })
    .filter((row) => row.cells.some((c) => c.d && c.d.own !== "nodata"))
    .sort((a, b) => b.rivalOwns - a.rivalOwns || b.med - a.med);
}

/* Diverging bar drawn INSIDE each table row, so the ranking chart and the table
   are the same eleven rows rather than eleven rows printed twice. Fixed +/-5
   domain on every category so bands are directly comparable. Raw SVG — no chart
   library for two rectangles and a rule. */
function gapBar(lead, thin) {
  const W = 200;
  const H = 20;
  const MID = W / 2;
  const HALF = W / 2 - 6;
  const x = (v) => MID + (Math.max(-GAP_AXIS, Math.min(GAP_AXIS, v)) / GAP_AXIS) * HALF;
  let s = `<svg class="ga-bar" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">`;
  const o = thin ? ' opacity="0.45"' : "";
  if (Math.abs(lead) < 0.5) {
    // exact ownership tie
    s += `<rect x="${MID - 1.5}" y="5" width="3" height="10" class="ga-b-level"${o}/>`;
  } else if (lead > 0) {
    s += `<rect x="${MID}" y="5" width="${Math.max(x(lead) - MID, 1)}" height="10" rx="2" class="ga-b-rival"${o}/>`;
  } else {
    s += `<rect x="${x(lead)}" y="5" width="${Math.max(MID - x(lead), 1)}" height="10" rx="2" class="ga-b-koel"${o}/>`;
  }
  if (lead > GAP_AXIS)
    s += `<path d="M${W - 6} 6 L${W - 1} 10 L${W - 6} 14 Z" class="ga-b-rival"/>`;
  if (lead < -GAP_AXIS) s += '<path d="M6 6 L1 10 L6 14 Z" class="ga-b-koel"/>';
  s += `<line x1="${MID}" y1="2" x2="${MID}" y2="18" class="ga-zero" shape-rendering="crispEdges"/>`;
  return `${s}</svg>`;
}
function gapBarAxis() {
  const W = 200;
  const H = 16;
  const MID = W / 2;
  const HALF = W / 2 - 6;
  let s = `<svg class="ga-bar" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">`;
  [-5, -3, 0, 3, 5].forEach((t) => {
    const gx = MID + (t / GAP_AXIS) * HALF;
    s += `<line x1="${gx}" y1="10" x2="${gx}" y2="14" class="ga-tick"/>`;
    s += `<text x="${gx}" y="7" class="ga-tickl" text-anchor="middle">${t > 0 ? "+" : ""}${t}</text>`;
  });
  return `${s}</svg>`;
}

function gapDimGrid(rivals, clientName = "KSSL") {
  const rows = gapDimRows(rivals);
  if (!rows.length)
    return '<div class="gd-note">No dimension has enough published data in this band to judge.</div>';
  let h =
    `<div class="ws-sec-l">▸ What they beat ${gesc(clientName)} on <span class="ws-sec-note">median size of the lead, and which competitors own each dimension</span></div>`;
  h += '<div class="ga-acc-container">';

  rows.forEach((row, index) => {
    const m = gdmeta(row.l);
    const title = gesc(m.short);
    const isOpen = index === 0 ? " open" : "";

    const bin = gbin(row.l, row.med);
    const sevClass = bin >= 4 ? "crit" : bin >= 3 ? "high" : bin >= 2 ? "med" : "low";
    const sevName =
      row.rivalOwns === 0
        ? "Low"
        : bin >= 4
        ? "Critical"
        : bin >= 3
        ? "High"
        : bin >= 2
        ? "Moderate"
        : "Low";

    const gapVal = row.rivalOwns > 0 ? gval(row.l, row.med) : "—";
    const compCount = row.rivalOwns;

    const ownedCells = row.cells.filter((c) => c.d && c.d.own === "rival");
    const sortedOwned = ownedCells
      .slice()
      .sort((a, b) => (b.d ? b.d.med : 0) - (a.d ? a.d.med : 0));
    const topRivalObj = sortedOwned[0];
    const topRival = topRivalObj ? gshort(topRivalObj.co) : row.rivalOwns > 0 ? "—" : "None";

    const whyObj = GAP_WHY[`${_gapMetaCat}|${row.l}`] || GAP_WHY[row.l];
    let whyText = "";
    if (whyObj && whyObj.one) {
      whyText = gesc(whyObj.one);
    } else if (m.note) {
      whyText = gesc(m.note);
    } else {
      whyText = "Impacts overall competitive positioning in this category.";
    }

    h += `<details class="ga-acc-item"${isOpen}>`;
    h += `<summary class="ga-acc-summary">`;
    h += `<span class="ga-acc-arrow"></span>`;
    h += `<span class="ga-acc-title">${title}</span>`;
    h += `</summary>`;

    /* the record and coverage for this dimension across every rival in the
       category — real numbers that balance the rival list on the right */
    const tot = { win: 0, loss: 0, level: 0, comparable: 0 };
    row.cells.forEach((c) => {
      if (!c.d) return;
      tot.win += c.d.win || 0;
      tot.loss += c.d.loss || 0;
      tot.level += c.d.level || 0;
      tot.comparable += c.d.comparable || 0;
    });
    const ksslOwnCells = row.cells.filter((c) => c.d && c.d.own === "koel").length;

    h += `<div class="ga-acc-body">`;
    h += `<div class="ga-acc-left">`;
    h += `<div class="ga-acc-grid">`;
    h += `<span class="ga-acc-label">Severity</span><span class="ga-acc-val ${sevClass}">${sevName}</span>`;
    h += `<span class="ga-acc-label">Gap</span><span class="ga-acc-val">${gapVal}</span>`;
    h += `<span class="ga-acc-label">Competitors</span><span class="ga-acc-val">${compCount}</span>`;
    h += `<span class="ga-acc-label">Top Rival</span><span class="ga-acc-val">${topRival}</span>`;
    h += `<span class="ga-acc-label">Record</span><span class="ga-acc-val">rival ${tot.win} · level ${tot.level} · KSSL ${tot.loss}</span>`;
    h += `<span class="ga-acc-label">KSSL owns vs</span><span class="ga-acc-val">${ksslOwnCells} of ${row.cells.filter((c) => c.d && c.d.own !== "nodata").length} rivals</span>`;
    h += `<span class="ga-acc-label">Coverage</span><span class="ga-acc-val">${tot.comparable} matchups publish both sides</span>`;

    h += `<div class="ga-acc-why">`;
    h += `<span class="ga-acc-label">Why It Matters</span>`;
    h += `<div class="ga-acc-why-desc">${whyText}</div>`;
    if (whyObj && whyObj.why) h += `<div class="ga-acc-why-desc" style="margin-top:6px;color:var(--d-txt-3)">${gesc(whyObj.why)}</div>`;
    if (m.note) h += `<div class="ga-acc-why-desc" style="margin-top:6px;font-size:11px;color:var(--d-txt-3)"><b>How to read it:</b> ${gesc(m.note)}</div>`;
    if (whyObj && whyObj.not) h += `<div class="ga-acc-why-desc" style="margin-top:6px;font-size:11px;color:var(--d-txt-4)">${gesc(whyObj.not)}</div>`;
    h += `</div>`;
    h += `</div>`;
    h += `</div>`;

    h += `<div class="ga-acc-right">`;
    if (sortedOwned.length > 0) {
      h += `<span class="ga-acc-label ga-acc-right-heading">Competitors Leading in this Gap</span>`;
      h += `<div class="ga-acc-rivals-list">`;
      sortedOwned.forEach((c) => {
        const rivalName = gesc(c.co);
        const rGap = gval(row.l, c.d.med);
        const rRec = `leads in ${c.d.win}/${c.d.comparable} matchups`;
        h += `<div class="ga-acc-rival-row">`;
        h += `<span class="ga-acc-rival-name">${rivalName}</span>`;
        h += `<span class="ga-acc-rival-gap">${rGap} <i style="font-weight:normal;font-size:11px;color:var(--d-txt-3);font-style:normal;">(${rRec})</i></span>`;
        h += `</div>`;
      });
      h += `</div>`;
    } else {
      h += `<span class="ga-acc-label ga-acc-right-heading">Competitors</span>`;
      h += `<div style="font-size:12px;color:var(--d-txt-3);font-style:italic;margin-top:2px;">No rival currently owns a spec lead in this dimension.</div>`;
    }
    h += `</div>`;

    h += `</div>`;
    h += `</details>`;
  });

  h += "</div>";
  return h;
}

/* What a measured edge actually buys the rival. Interpretation, not measurement,
   and labelled as such. One entry per dimension, reused across every band. */
const GAP_WHY = {
  "Max range": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "The rival shoots from outside the range at which KSSL's gun can reply, so the exchange is one-way.",
    "why": "It is a step function at the opponent's maximum range rather than a gradient, and the same lead pays twice: it also puts the gun outside the counter-battery envelope and cuts the number of firing positions a fire plan needs.",
    "seg": "Army artillery directorates, mountain and border formations, export customers facing peer artillery",
    "seg1": "It is the headline number in a GSQR, so it sells before it is ever fired.",
    "not": "It barely matters in counter-insurgency and internal security, where rules of engagement and observation cap the engagement well inside the gun's reach."
  },
  "Artillery|Weight": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "The rival's gun is lighter, so it can be flown, lifted or driven where the heavier one cannot go at all.",
    "why": "Deployability appears in an RFP as a hard gate, not a preference — the saving is only banked when it crosses an airlifter, helicopter or bridge class limit, and is nearly worthless inside a band.",
    "seg": "Rapid-reaction and mountain formations, expeditionary buyers, northern-border requirements",
    "seg1": "A gun that fits the transport the customer already owns avoids buying new lift alongside the artillery.",
    "not": "It barely matters to static coastal and garrison artillery moved once by tank transporter."
  },
  "Crew": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "The rival's gun fights with fewer soldiers, which is an automation claim and a survivability claim in the same number.",
    "why": "It compounds unusually hard: the autoloader that removes crew also raises burst rate and cuts emplacement time, so one investment sells three specs. Counter-battery radar produces a firing solution in seconds and return fire arrives inside two minutes, so time into and out of action is survival.",
    "seg": "Manpower-constrained European, Gulf and East Asian armies, and anyone facing counter-battery radar or loitering munitions",
    "seg1": "Personnel dominate a regiment's whole-life cost — three fewer crew across a hundred guns is three hundred trained soldiers, which is why it wins lifecycle-scored tenders.",
    "not": "It matters least to conscript-manned, manpower-rich armies, and it cuts the other way when the autoloader fails: a small crew has no manual fallback and no relief for 24-hour operations."
  },
  "Rate of fire": {
    "kind": "tech",
    "k1": "Technology",
    "one": "The rival puts more rounds on the target per exposure, which is what makes shoot-and-scoot viable rather than just louder.",
    "why": "The genuine steps are the burst counts written into the qualitative requirement — three rounds in fifteen seconds, six in thirty — and multiple-rounds-simultaneous-impact capability, which is binary rather than incremental.",
    "seg": "Manoeuvre-support artillery, counter-battery and MRSI missions",
    "seg1": "Rounds per exposure is survivability arithmetic: the gun that empties its mission faster spends less time where the radar can see it.",
    "not": "It barely matters in sustained interdiction, where the ammunition resupply chain binds long before the gun's cyclic rate does."
  },
  "Combat weight": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "At the same protection level the rival carries the same crew for less mass, which buys airlift, bridges and fuel.",
    "why": "It compounds through growth margin: a vehicle that starts light absorbs ten years of add-on armour, jammers and remote weapon stations, while one already at its gross limit needs a redesign to accept any of them.",
    "seg": "Airmobile and rapid-deployment forces, expeditionary and UN users, weak-bridge and mountain-road theatres",
    "seg1": "Landing under an airlift or bridge class limit satisfies a deployability clause that is pass/fail in the RFP.",
    "not": "Read it with the protection level: below equal STANAG 4569, lower mass is not an advantage, it is less armour."
  },
  "Crew / pax": {
    "kind": "sales",
    "k1": "Sales",
    "one": "The rival fits more dismounts in one hull, so the customer needs fewer vehicles to lift the same infantry.",
    "why": "This is arithmetic on the order book rather than a spec win — if a section does not fit in one vehicle it splits across two, loses cohesion and doubles the fleet. The payoff is a step at the customer's section size and flat either side of it.",
    "seg": "Mechanised infantry and APC tenders, troop-lift and internal-security fleets",
    "seg1": "Fleet size sets total contract value, so seats convert into revenue more directly than any other figure here.",
    "not": "It is meaningless on command, recce and weapon-carrier variants, where the seat count is fixed by the role."
  },
  "Effective range": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "The rival's weapon is credited with hitting at a distance where KSSL's is not.",
    "why": "It only converts if the customer also buys the optic and the marksmanship training; without them it is a datasheet number that never appears in the field. The real step is a section-wide move from red-dot to low-power variable optic.",
    "seg": "Infantry rifle tenders in open terrain, desert and high-altitude formations, designated-marksman requirements",
    "seg1": "Treat the figure with suspicion — it is a doctrinal statement about a trained shooter, not a ballistic limit, and every maker picks the flattering definition.",
    "not": "It barely matters in close-quarter battle, for vehicle crews and for police, where nearly every engagement is inside 100 m."
  },
  "Small Arms|Weight": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "The rival's weapon is lighter in the hand, which is where small-arms competitions are actually won.",
    "why": "It does not compound — it is a perception threshold in user trials, roughly a third of a kilogram on a rifle, and it only becomes decisive when it is the difference between carrying another magazine or another plate.",
    "seg": "Infantry, airborne and mountain tenders, and paramilitary bulk buys with long foot patrols",
    "seg1": "Indian and most Western small-arms competitions are decided in endurance-march and ergonomics scoring, not on the datasheet.",
    "not": "It is irrelevant to vehicle crews and static guards, and it inverts in support roles where mass is wanted for recoil control."
  },
  "UAVs & Drones|Endurance": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "The rival keeps an aircraft on station longer, so it covers the same area with fewer airframes.",
    "why": "It compounds harder than any other figure on this page: fewer airframes per persistent orbit means fewer crews, fewer ground control stations, less basing and less maintenance, so the rival bids a smaller fleet at a lower price for the same claimed coverage.",
    "seg": "Maritime patrol, exclusive-economic-zone and border surveillance, ISR supporting strike",
    "seg1": "Crossing 24 hours means one airframe covers a full day, which is the single largest step on the ladder.",
    "not": "It barely matters for small tactical reconnaissance, artillery spotting and loitering munitions, where the mission lasts minutes."
  },
  "Marine / Naval|Endurance": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "The rival's craft stays out longer, so fewer hulls hold the same station.",
    "why": "Patrol cycles are the unit of account — days on station divided into the required coverage gives hulls, crews and refit slots, and each of those is a line in the bid.",
    "seg": "Coast guards, EEZ and offshore patrol requirements, long-range surveillance",
    "seg1": "Fuel and stores endurance also decide how far from a friendly port the customer can operate at all.",
    "not": "It barely matters for inshore and riverine craft returning to base each day."
  },
  "UAVs & Drones|Range": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "The rival reaches targets and patrol boxes that KSSL's aircraft cannot be tasked against.",
    "why": "Reach is worth checking before it is believed: line-of-sight control walls at roughly 200-250 km and a satellite datalink removes the wall, so a large lead is often a comms fit rather than an airframe.",
    "seg": "Maritime domain awareness, deep border surveillance, standoff ISR",
    "seg1": "Range is what decides which basing options the customer needs, and basing is usually the expensive half of the programme.",
    "not": "It barely matters to short-range tactical users already bound by terrain line-of-sight."
  },
  "Missiles & Air Defence|Range": {
    "kind": "both",
    "k1": "Technology + sales",
    "one": "The rival engages from outside the envelope in which it can be engaged back, and defends more ground per fire unit.",
    "why": "Defended area scales with the square of range, so a 30% reach advantage is roughly a 70% area advantage — that arithmetic, not the kilometres, is what wins the architecture argument and reduces fire units per defended asset.",
    "seg": "Air-defence architecture buyers, standoff strike, maritime domain awareness",
    "seg1": "Compare inside one layer: a short-range system and a medium-range system are complements in the same architecture, not competitors.",
    "not": "It barely matters for point defence of a single asset, where reaction time beats reach."
  },
   "Annual capacity": {
    "kind": "sales",
    "k1": "Sales",
    "one": "The rival can commit more rounds per year than KSSL's shell-body line feeds, so framework buyers size contracts around the rival's output.",
    "why": "Since 2022 artillery ammunition is capacity-constrained, not spec-constrained: multi-year framework agreements go to whoever can guarantee volume, and capacity announcements move orders before a single round is delivered.",
    "seg": "Framework and stockpile-replenishment buyers, NATO joint procurement, export customers rebuilding warstocks",
    "seg1": "KSSL's ~500k empty bodies a year feed other fillers' lines — capacity upstream converts only when filling capacity exists downstream.",
    "not": "It matters least for precision niches (Excalibur, Katana), where integration and seekers bind long before shell volume does."
  },
  "Speed": {
    "kind": "tech",
    "k1": "Technology",
    "one": "The rival's round arrives sooner, cutting the time the defender has to detect, decide and shoot.",
    "why": "It pays as a step the moment time-of-flight falls inside the defender's reaction cycle, and again at the hypersonic boundary, where the defender must field a new interceptor rather than a better one. Inside a regime the returns diminish quickly.",
    "seg": "Anti-ship and land-attack strike, interceptors chasing fast targets, suppression of enemy air defences",
    "seg1": "Time-of-flight and available g at intercept drive kill probability far more than headline Mach does.",
    "not": "It is not an advantage at all for loitering munitions and non-line-of-sight systems, where slow flight is the design intent."
  }
};

function gapWhyBlock(rivals, clientName = "KSSL") {
  const rows = gapDimRows(rivals).filter((r) => r.rivalOwns > 0);
  if (!rows.length)
    return '<div class="gd-note">No rival owns a measured dimension in this band, so there is no spec-side advantage to interpret.</div>';
  let h =
    '<div class="ws-sec-l">▸ What the edge buys them <span class="ws-sec-note">interpretation — the commercial consequence of each dimension a rival owns</span></div>';
  h += '<div class="gk-why">';
  rows.forEach((row) => {
    const w = GAP_WHY[`${_gapMetaCat}|${row.l}`] || GAP_WHY[row.l];
    const m = gdmeta(row.l);
    if (!w) return;
    const bin = gbin(row.l, row.med);
    const size =
      bin >= 4
        ? "decisive"
        : bin >= 3
          ? "notable"
          : bin >= 2
            ? "worth watching"
            : "inside normal tolerance";
    h +=
      '<div class="gk-why-row">' +
      `<div class="gkw-h"><span class="gkw-dim">${gesc(m.short)}</span>` +
      `<span class="gkw-kind ${w.kind}">${w.k1}</span>` +
      `<span class="gkw-size b${bin}">${size} at ${gval(row.l, row.med)}</span>` +
      `<span class="gkw-mag">${row.rivalOwns} of ${rivals.length} rivals own this dimension</span></div>` +
      `<div class="gkw-b">${gesc(w.one.replace(/KSSL/g, clientName))} <span class="gkw-mut">${gesc(w.why.replace(/KSSL/g, clientName))}</span></div>` +
      `<div class="gkw-seg"><b>Matters most to:</b> ${w.seg}. ${w.seg1}` +
      `${w.not ? ` <span class="gkw-mut">${gesc(w.not)}</span>` : ""}` +
      `${m.note ? ` <span class="gkw-mut">${m.note}</span>` : ""}</div></div>`;
  });
  h += "</div>";
  h +=
    '<div class="gv-lag-read"><b>Read:</b> these dimensions do not carry equal weight. <b>Deployability figures — artillery weight, ' +
    "combat weight, UAV endurance — pay out as step functions</b> at an airlift, bridge or orbit boundary, and are " +
    "worth almost nothing inside a band; check which side of the step the gap actually falls. <b>Crew count is the " +
    "most under-read number here</b>, because it is an automation proxy that sells as whole-life cost and buys " +
    "survivability at the same time. <b>Range and speed are worth only what the layer allows</b> — outranging a peer " +
    "is decisive, outranging a system in a different air-defence layer is a category error. <b>Effective range and " +
    "seat counts are the softest</b>: one has no agreed definition, the other pays only when it crosses the buyer's " +
    "section size. And none of it is the order. Indian procurement qualifies on specification and then decides on " +
    "price among everyone who qualified, after trials in Ladakh and Rajasthan that regularly overturn the datasheet. " +
    "A spec sheet wins the technical evaluation. It rarely wins the contract.</div>";
  return h;
}

/* The whole right-hand canvas for one kVA band, as one string. Rows carry
   data-mu so the React page can delegate the click through to Positioning. */
/* Every comparison the subtitle counts, one line each.

   The table above holds ONE row per rival, and clicking it opens only that rival's
   WORST pairing -- so of the eleven head-to-head comparisons the header advertised
   in Artillery, six were unreachable and none of the underlying numbers appeared
   anywhere. A count the reader cannot open is a claim, not evidence. */
function gapComparisons(rivals, clientName = "KSSL", held = 0) {
  const total = rivals.reduce((t, r) => t + r.n, 0);
  if (!total) return "";
  let h =
    '<div class="ws-sec-l">▸ Every head-to-head comparison ' +
    `<span class="ws-sec-note">the ${total} that the count above is made of` +
    (held > total
      ? ` · ${held - total} further pairing${held - total === 1 ? "" : "s"} in this ` +
        "category publish too little on both sides to compare"
      : "") +
    " · click a line to open it in Positioning</span></div>";
  h += '<div class="ga-cmps">';
  rivals.forEach((r) => {
    h += `<div class="ga-cmp-co">${gesc(r.co)}<i>${r.n} comparison${r.n === 1 ? "" : "s"}</i></div>`;
    r.rows
      .slice()
      .sort((x, y) => x.edge - y.edge)
      .forEach((row) => {
        const m = row.m;
        /* Name the products, not the makers: the maker is already the group heading,
           and "Hanwha vs KSSL" does not say which gun. */
        const rivalProduct = gesc(String(m.comp || "").split("·").pop().trim());
        const ourProduct = gesc(String(m.bf || "").split("·").pop().trim());
        const who =
          row.edge < 50 ? "rival ahead" : row.edge > 50 ? `${gesc(clientName)} ahead` : "level";
        const dims = row.dims
          .map((x) => {
            const lab = gesc(gdmeta(x.l).short);
            const pair = pairVals(x);
            const rv = gesc(pair[0]);
            const kv = gesc(pair[1]);
            const lead = x.a === 0 ? "level" : x.a < 0 ? "rival" : "client";
            return `<i class="ga-cmp-d ${lead}">${lab} <b>${rv}</b> vs <b>${kv}</b></i>`;
          })
          .join("");
        h +=
          `<div class="ga-cmp" role="button" tabindex="0" data-mu="${gesc(row.id)}"` +
          ` aria-label="${rivalProduct} against ${ourProduct}, ${row.edge} of 100. Opens in Positioning.">` +
          `<span class="ga-cmp-p">${rivalProduct} <i>vs</i> ${ourProduct}</span>` +
          `<span class="ga-cmp-dims">${dims || '<i class="ga-none">no dimension decided</i>'}</span>` +
          `<span class="num ga-cmp-e ${row.edge < 50 ? "behind" : row.edge > 50 ? "ahead" : "level"}">` +
          `${row.edge}<i>/100</i></span><span class="ga-cmp-w">${who}</span>` +
          '<span class="ga-go">↗</span></div>';
      });
  });
  return h + "</div>";
}


export function gapCategoryBody(rivals, clientName = "KSSL", held = 0) {
  if (!rivals.length)
    return (
      '<div class="pat-empty"><div class="pe-ic">⊘</div><div class="pe-t">No measured matchups in this band</div>' +
      '<div class="pe-s">Products here have no rival paired on rating.</div></div>'
    );
  const total = rivals.reduce((t, r) => t + r.n, 0);
  const behind = rivals.filter((r) => r.verdict.k === "behind");
  const ahead = rivals.filter((r) => r.verdict.k === "ahead");
  const traded = rivals.filter((r) => r.verdict.k === "contested");
  const nodata = rivals.filter((r) => r.verdict.k === "nodata");
  const masked = rivals.filter((r) => r.masked);
  const deepest = rivals.reduce((a, b) => (b.worst.edge < a.worst.edge ? b : a), rivals[0]);

  let h = '<div class="ga-wrap">';
  const top = behind[0];
  /* THE HERO NUMBER MUST AGREE WITH THE ROWS UNDERNEATH IT.

     "Owning" a dimension needs GAP_MINDEC comparisons before it can be claimed, so
     with a thin category the hero read "0/5 rivals hold an edge" directly above a
     list in which four of those five rivals win a comparison outright. Both
     statements were true and the pair of them was a lie. When nothing is owned yet,
     the hero reports what the comparisons themselves say, and says which measure it
     is using. */
  const leadOne = rivals.filter((r) => r.masked);
  const useOwn = behind.length > 0 || leadOne.length === 0;
  const heroN = useOwn ? behind.length : leadOne.length;
  h +=
    `<div class="gk-hero ${heroN ? (heroN >= rivals.length / 2 ? "crit" : "high") : "even"}">` +
    `<div class="gk-hero-l"><div class="gk-big">${heroN}<span>/${rivals.length}</span></div>` +
    `<div class="gk-cap">${useOwn ? "rivals hold<br>an edge" : "rivals win a<br>comparison"}</div></div>` +
    `<div class="gk-hero-r"><div class="gk-line">` +
    (behind.length
      ? `<b>${behind.length} of ${rivals.length}</b> rivals own more measured dimensions than ${clientName} in this category` +
        (top && top.dims.length
          ? `, led by <b>${gshort(top.co)}</b> — ahead on ${top.rivalOwns.length}` +
            ` of ${top.all.length}, widest on ${gesc(gdmeta(top.dims[0].l).short).toLowerCase()} by ${gval(top.dims[0].l, top.dims[0].med)}` +
            ` in ${top.dims[0].win} of ${top.dims[0].comparable} comparable matchups`
          : "") +
        "."
      : leadOne.length
        ? `<b>${leadOne.length} of ${rivals.length}</b> rivals take at least one comparison outright, but none has enough ` +
          `matchups yet to own a dimension outright — that needs ${GAP_MINDEC} comparisons on the same spec. ` +
          `The comparisons themselves are listed below, with both figures.`
        : `No rival owns more measured dimensions than ${clientName} in this category.`) +
    ` ${traded.length}${traded.length === 1 ? " trades" : " trade"} dimensions evenly, ` +
    `${ahead.length}${ahead.length === 1 ? " is" : " are"} behind ${clientName}` +
    (nodata.length
      ? `, ${nodata.length}${nodata.length === 1 ? " publishes" : " publish"} too little to judge`
      : "") +
    `. The deepest single loss is <b>${deepest.worst.edge}/100</b> against ${gshort(deepest.co)}.</div>` +
    `<div class="gk-scale">A rival <b>owns</b> a dimension when it leads in at least ${Math.round(GAP_OWN * 100)}` +
    "% of the matchups where both machines publish that spec. Dimensions are counted, never averaged against " +
    "each other." +
    (masked.length && useOwn
      ? ` <b>${masked.length}</b> rival${masked.length !== 1 ? "s" : ""}${masked.length === 1 ? " still takes" : " still take"} at least one comparison outright — marked ⚠.`
      : "") +
    "</div></div></div>";

  h +=
    `<div class="ws-sec-l">▸ Every rival in this category <span class="ws-sec-note">ranked by dimensions owned · click a row to open its worst comparison in Positioning</span></div>`;
  h +=
    '<div class="ga-tbl" role="table">' +
    '<div class="ga-row ga-hd" role="row">' +
    '<span role="columnheader">#</span><span role="columnheader">Rival</span>' +
    '<span role="columnheader">Verdict</span>' +
    // Left is negative lead, which is clientName ahead; right is positive, the rival ahead.
    `<span role="columnheader" class="ga-axh"><span class="ga-poles"><i>← ${clientName} owns more</i><i>rival owns more →</i></span>${gapBarAxis()}</span>` +
    '<span role="columnheader" class="num">Owns</span>' +
    '<span role="columnheader" class="num">Worst</span>' +
    '<span role="columnheader">Record</span>' +
    '<span role="columnheader" class="num">N</span>' +
    '<span role="columnheader">Biggest edge</span><span></span></div>';
  rivals.forEach((r, i) => {
    const v = r.verdict;
    const tot = r.n || 1;
    const aria =
      `${gesc(r.co)}. ${v.w} — owns ${r.rivalOwns.length} of ${r.all.length} measured dimensions, ${clientName} owns ` +
      `${r.koelOwns.length}. Ahead on more dimensions in ${r.rivalWins} of ${r.n}` +
      ` comparisons, behind in ${r.koelWins}. Worst comparison ${r.worst.edge}` +
      ` of 100 across ${r.n} comparisons. Opens the worst comparison.`;
    h +=
      `<div class="ga-row ${v.k}" role="row" tabindex="0" data-mu="${gesc(r.worst.id)}" aria-label="${aria}">` +
      `<span class="ga-i">${i + 1 < 10 ? "0" : ""}${i + 1}</span>` +
      `<span class="ga-co">${gesc(r.co)}</span>` +
      `<span><i class="ga-chip ${v.k}" title="${r.rivalOwns.length} dimensions to the rival, ${r.koelOwns.length}` +
      ` to ${clientName}, ${r.contested} split, ${r.nodata} not enough data">${v.w}${r.masked ? " ⚠" : ""}</i></span>` +
      `<span class="ga-barc">${gapBar(r.balance, r.thin)}</span>` +
      `<span class="num ga-owns"><b class="${v.k}">${r.rivalOwns.length}</b><i>vs ${r.koelOwns.length}</i></span>` +
      `<span class="num ga-worst" data-b="${r.worst.edge < 25 ? 4 : r.worst.edge < 35 ? 3 : r.worst.edge < 42 ? 2 : r.worst.edge < 50 ? 1 : 0}">${r.worst.edge}<i>/100</i></span>` +
      `<span class="ga-rec" title="${r.rivalWins} rival wins · ${r.parity} level · ${r.koelWins} ${clientName} wins">` +
      `<i class="rw" style="width:${(r.rivalWins / tot) * 100}%"></i>` +
      `<i class="pw" style="width:${(r.parity / tot) * 100}%"></i>` +
      `<i class="kw" style="width:${(r.koelWins / tot) * 100}%"></i></span>` +
      `<span class="num ga-n${r.thin ? " thin" : ""}" ${r.thin ? `title="Only ${r.n} comparisons — indicative only"` : ""}>${r.n}${r.thin ? " ⚠" : ""}</span>` +
      `<span class="ga-lo">${
        r.dims.length
          ? `${gesc(gdmeta(r.dims[0].l).short)} <b>${gval(r.dims[0].l, r.dims[0].med)}</b>` +
            `<i class="ga-freq"> in ${r.dims[0].win}/${r.dims[0].comparable}</i>`
          : '<i class="ga-none">none owned</i>'
      }</span>` +
      '<span class="ga-go">↗</span></div>';
  });
  h += "</div>";
  h +=
    '<div class="ga-key"><span><i class="k-riv"></i> rival owns more dimensions</span>' +
    `<span><i class="k-koel"></i> ${clientName} owns more</span>` +
    "<span>bar = net dimensions owned, the same count the verdict uses</span>" +
    `<span>⚠ at least one comparison is a clear loss, or fewer than ${GAP_THIN} comparisons</span></div>`;
  h += gapComparisons(rivals, clientName, held);
  h += gapDimGrid(rivals, clientName);
  h += gapWhyBlock(rivals, clientName);
  h +=
    '<div class="gd-note">The verdict counts dimensions: a rival owns one when it leads in at least ' +
    `${Math.round(GAP_OWN * 100)}% of the matchups where both products publish that spec, with at least ${GAP_MINCMP}` +
    ` such matchups covering ${Math.round(GAP_MINCOV * 100)}% of the pairing. Advantages are never averaged against ` +
    "each other, because tonnes and kilometres are not interchangeable. The bar and the record both count dimensions, " +
    "so neither can point against the verdict. <b>Worst</b> is the single hardest comparison on the Positioning index " +
    "(0-100, 50 = parity, below 50 the rival is stronger), read from the same computation the dossier shows. " +
    "<b>Calibre, MTOW, naval length and barrel length are excluded</b>: each is the class axis the two products were " +
    "paired on, so scoring it would be circular — 155 against 155 and 5.56 against 5.56 carry no information, and " +
    "155 against 70 means the products are not comparable at all. " +
    "What decides Indian defence orders is mostly outside this comparison: DAP 2020 categorisation and indigenous " +
    "content thresholds, Positive Indigenisation List embargoes, L1 price among all technically-compliant bidders, " +
    "how the GSQR was written, field evaluation trials run at no cost and no commitment in desert and high-altitude " +
    "conditions, offset obligations, lifecycle support and spares pricing, integrity-pact and blacklisting status, " +
    "and SCOMET, ITAR or MTCR export clearance.</div></div>";
  return h;
}

export function gapCategorySub(rivals, held = 0) {
  const total = rivals.reduce((t, r) => t + r.n, 0);
  /* Say the denominator. "11 head-to-head comparisons" read as though the category
     held eleven pairings; it holds 91, and 80 of them publish too little on both
     sides to compare. Hiding that makes thin coverage look like a complete picture. */
  return rivals.length
    ? `${rivals.length} rivals · ${total}${held > total ? ` of ${held}` : ""} head-to-head comparisons · ` +
        `${Math.max(...rivals.map((r) => r.all.length))} measured spec dimensions`
    : "No measured comparisons in this band";
}
