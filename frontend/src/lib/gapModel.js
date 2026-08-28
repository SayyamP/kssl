/* ===== GAP ENGINE — descriptive, severity-ranked =====
   Everything the three Gap surfaces show is derived here; nothing is stored.
   Takes the wired dataset explicitly instead of reading globals, so a re-fetch
   rebuilds the model rather than leaving a stale one behind. */
import { computeSpecEdge } from "./edge.js";
import { escAll } from "./html.js";
import { formatCrore } from "../utils/formatNumber.js";
import { logger } from "../utils/logger.js";

/* Tender values arrive in six currencies and two scales, and several already
   carry the rupee equivalent ("US$225 M (~₹1,867 cr)"). Taking the first
   number in the string read "~US$4.69 B" as ₹4.69 cr — a ₹39,000 cr Egyptian
   MRO programme shown as pocket change — and this figure also weights gap
   severity, so it reordered which gaps looked worst. Prefer a stated ₹ crore
   figure; otherwise convert at the documented rate below. */
export const CR_PER_MILLION = { "us$": 8.3, "a$": 5.5, $: 8.3, "€": 9.0, "£": 10.5, aed: 2.26, myr: 1.9 };
export function parseCr(v) {
  if (!v) return 0;
  const s = `${v}`.replace(/,/g, "");
  const inr = s.match(/₹\s*([\d.]+)/);
  if (inr) return parseFloat(inr[1]); // already in crore
  const m = s.match(/(US\$|A\$|\$|€|£|AED|MYR)\s*([\d.]+)\s*(B|bn|billion|M|mn|million)?/i);
  if (!m) return 0; // "n/d", "Undisclosed (LOI stage)" — no figure to size
  const per = CR_PER_MILLION[m[1].toLowerCase()] || 0;
  const inMillions = /^b/i.test(m[3] || "") ? parseFloat(m[2]) * 1000 : parseFloat(m[2]);
  return inMillions * per;
}

export function buildGapModel(d) {
  const { matchups, tenders, innovations, techCats, competitors, POS_CATS } = d;
  const clientName = (d && d.client && (d.client.short || d.client.name)) || "KSSL";
  const gaps = [];
  let _id = 0;
  const nid = () => `g${++_id}`;
  /* "Live" has to mean live. Every category contains an awarded contract with
     dl:0, which drove urgency to its maximum and printed "tender closes 0d" on
     gaps whose only tender was a contract already signed — in two cases one
     KSSL itself had won. Settled programmes still count as tracked context,
     but they set neither the exposure sum nor the deadline horizon. */
  function expForCat(cat) {
    let val = 0;
    let cnt = 0;
    let tracked = 0;
    let hz = null;
    try {
      tenders.forEach((t) => {
        if ((t.cat || t.category) !== cat) return;
        tracked += parseCr(t.value);
        const settled = (t.status || "").toLowerCase() === "awarded" || t.isLive === false;
        if (settled) return;
        val += parseCr(t.value);
        cnt++;
        const dl = typeof t.dl === "number" ? t.dl : null;
        if (dl !== null && dl > 0) hz = hz === null ? dl : Math.min(hz, dl);
      });
    } catch (e) {
      /* a dataset without tenders simply has no exposure */
    }
    return { value: val, count: cnt, horizon: hz, tracked };
  }
  function rec(pillar, type, koel, bench, mag, dir, cat, basis, exp, extra) {
    const r = {
      id: nid(),
      pillar,
      gap_type: type,
      koel_entity: koel,
      benchmark_entity: bench,
      magnitude: +(Math.max(0, mag) || 0).toFixed(3),
      direction: dir,
      category: cat,
      basis,
      exposure_value: exp ? exp.value : 0,
      exposure_count: exp ? exp.count : 0,
      exposure_horizon: exp ? exp.horizon : null,
      correlates: [],
      source: `derived:${basis}`,
      confidence: 1.0,
      status: "published",
      verified_by: "engine",
      verified_at: null,
      freshness_ts: null,
    };
    if (extra) Object.assign(r, extra);
    return r;
  }

  /* 1. COMPETITIVE — benchmark = rival product. edge 0..90, 50=parity, <50 client behind. */
  try {
    Object.keys(matchups).forEach((muId) => {
      const mu = matchups[muId];
      if (mu.edge === null || mu.edge === undefined) return; // undisclosed -> honest skip
      const behind = (50 - mu.edge) / 50; // >0 behind, <0 ahead
      let dir;
      let mag;
      if (behind > 0.02) {
        dir = "behind";
        mag = behind;
      } else if (behind < -0.02) {
        dir = "ahead";
        mag = -behind; // magnitude of the LEAD (own track)
      } else {
        dir = "at_parity";
        mag = 0;
      }
      let lags = [];
      let leads = [];
      try {
        const dims = computeSpecEdge(mu).dims || [];
        lags = dims
          .filter((x) => x.a < 0)
          .sort((a, b) => a.a - b.a)
          .map((x) => ({ l: x.l, pct: Math.round(-x.raw * 100), perKva: !!x.perKva }));
        leads = dims
          .filter((x) => x.a > 0)
          .sort((a, b) => b.a - a.a)
          .map((x) => ({ l: x.l, pct: Math.round(x.raw * 100), perKva: !!x.perKva }));
      } catch (e) {
        /* a matchup with no measured dims contributes no named lags */
      }
      gaps.push(
        rec(
          "competitive",
          "spec",
          mu.bf || `${clientName} · ${mu.anchor}`,
          mu.comp,
          mag,
          dir,
          mu.cat,
          `matchup.edge=${mu.edge}`,
          expForCat(mu.cat),
          {
            lags,
            leads,
            edge: mu.edge,
            muId,
            rivalCo: (mu.compBy || mu.comp || "").trim(),
          },
        ),
      );
    });
  } catch (e) {
    logger.warn("gap:comp", e);
  }

  /* 2. MARKET — benchmark = demand. fit% nested in tender.matches[].pct. gap=100-bestPct. */
  try {
    tenders.forEach((t) => {
      const ms = t.matches || [];
      let best = null;
      ms.forEach((mm) => {
        const pc = parseInt(`${mm.pct || ""}`.replace(/[^\d]/g, ""), 10);
        if (!Number.isNaN(pc) && (best === null || pc > best.pct))
          best = { pct: pc, n: mm.n, fit: mm.fit };
      });
      if (best === null) return; // no scored bid -> honest skip
      const gv = (100 - best.pct) / 100;
      gaps.push(
        rec(
          "market",
          "demand_fit",
          `${clientName} · ${best.n || "bid"}`,
          t.title,
          gv,
          gv <= 0.02 ? "at_parity" : "behind",
          t.cat || t.category || "—",
          `tender.matches.pct=${best.pct}%`,
          {
            value: parseCr(t.value),
            count: 1,
            horizon: typeof t.dl === "number" ? t.dl : null,
          },
          {
            tenderTitle: t.title,
            tenderValue: t.value,
            deadline: t.deadline,
            fitPct: best.pct,
            fitWord: best.fit,
            lean: t.lean,
          },
        ),
      );
    });
  } catch (e) {
    logger.warn("gap:mkt", e);
  }

  /* 3. TECHNOLOGY — benchmark = frontier (authored gap field). */
  /* The technology pillar names its domains its own way ("Armoured", "Naval",
     "Missiles & AD", "Materials & Forging") while everything else keys off the
     POS_CATS labels ("Protected & Armoured Vehicles", "Marine / Naval", …).
     Mapping id -> techCats.name therefore produced a category string nothing
     else recognised: 9 of 26 technology gaps carried ₹0 exposure and zero
     cross-pillar correlates, and 214 armoured matchups never showed the
     tech-frontier note. Resolve each domain to a POS_CATS label, by id where
     the two vocabularies agree and by an explicit alias where they do not. */
  const TECH_ALIAS = {
    armoured: "pav",
    naval: "naval",
    missiles: "msl",
    materials: "pc",
    artillery: "art",
    smallarms: "sa",
    ammunition: "ammo",
    uav: "uav",
  };
  const TECH_CAT = {};
  try {
    const byKey = Object.fromEntries((POS_CATS || []).map(([k, label]) => [k, label]));
    techCats.forEach((c) => {
      TECH_CAT[c.id] = byKey[TECH_ALIAS[c.id]] || c.name;
    });
  } catch (e) {
    /* no tech areas -> domains stay their own labels */
  }
  try {
    Object.keys(innovations).forEach((domain) => {
      (innovations[domain] || []).forEach((iv) => {
        const g = (iv.gap || "").toLowerCase();
        let mag;
        let dir;
        if (g === "behind") {
          mag = 0.75;
          dir = "behind";
        } else if (g === "ahead") {
          mag = 0.4;
          dir = "ahead";
        } else {
          mag = 0;
          dir = "at_parity";
        }
        // normalize to shared category vocab so exposure + correlates resolve
        const sharedCat = TECH_CAT[domain] || domain;
        gaps.push(
          rec(
            "technology",
            "frontier",
            `${clientName} · ${iv.t || "capability"}`,
            `Frontier · ${iv.mat || "?"}`,
            mag,
            dir,
            sharedCat,
            `innovation.gap=${g}`,
            expForCat(sharedCat),
            {
              techName: iv.t,
              maturity: iv.mat,
              horizon: iv.horizon,
              driver: iv.driver,
              domain,
              whatsNew: iv.whatsNew,
              impact: iv.impact,
              compNote: iv.compNote,
              gapWord: g,
            },
          ),
        );
      });
    });
  } catch (e) {
    logger.warn("gap:tech", e);
  }

  /* 4. ECOSYSTEM / PARTNERSHIP — benchmark = rival alliance depth contesting a client
     category. Derived from competitors[].partners[].mean 'CORE OVERLAP (cat)' flags.
     Contest-density gap. */
  try {
    // overlap phrase -> shared category vocabulary, built from the kVA bands
    const PCAT = {};
    try {
      POS_CATS.forEach((p) => {
        PCAT[p[1].toLowerCase()] = p[1];
        PCAT[p[0]] = p[1];
      });
    } catch (e) {
      /* no bands -> no ecosystem rows, which is the honest outcome */
    }
    const contest = {};
    Object.values(competitors).forEach((c) => {
      (c.partners || []).forEach((pt) => {
        const m = (pt.mean || "") + (pt.insight || "");
        const mm = m.match(/CORE OVERLAP \(([^)]+)\)/i);
        if (mm) {
          mm[1].split(",").forEach((raw) => {
            const key = raw.trim().toLowerCase();
            const cat = PCAT[key] || null;
            if (!cat) return;
            if (!contest[cat]) contest[cat] = { ties: 0, comps: {} };
            contest[cat].ties++;
            contest[cat].comps[c.name] = 1;
          });
        }
      });
    });
    const maxTies = Math.max(1, ...Object.values(contest).map((v) => v.ties));
    Object.keys(contest).forEach((cat) => {
      const v = contest[cat];
      const nComp = Object.keys(v.comps).length;
      const mag = Math.min(1, v.ties / maxTies); // contest density normalized
      gaps.push(
        rec(
          "competitive",
          "ecosystem",
          `${clientName} · ${cat} ecosystem`,
          `${nComp} rivals via ${v.ties} alliances`,
          mag,
          "behind",
          cat,
          `partnerships.core_overlap ties=${v.ties}`,
          expForCat(cat),
          { contestTies: v.ties, contestComps: nComp },
        ),
      );
    });
  } catch (e) {
    logger.warn("gap:ecosystem", e);
  }

  /* severity — ONLY 'behind' gaps ranked. severity = magnitude x exposure-weight.
     urgency (nearest tender deadline) is a DESCRIPTIVE tiebreak, kept as its own
     component so coarse-magnitude ties resolve by imminence without inventing
     precision. */
  const behindGaps = gaps.filter((g) => g.direction === "behind");
  const maxExp = Math.max(1, ...behindGaps.map((g) => g.exposure_value));
  gaps.forEach((g) => {
    if (g.direction === "behind") {
      const expW = 0.35 + 0.65 * (g.exposure_value / maxExp);
      g.severity = +(g.magnitude * expW).toFixed(3);
      g.severity_pct = Math.round(g.severity * 100);
      // urgency: horizon in days -> 0..1 (sooner = higher). >180d or none = 0.
      const hz = g.exposure_horizon;
      g.urgency = hz === null || hz > 180 ? 0 : +(1 - hz / 180).toFixed(3);
      g.urgency_days = hz;
      // rank_score: severity is primary; urgency only breaks ties
      g.rank_score = +(g.severity + g.urgency * 0.08).toFixed(4);
    } else {
      g.severity = 0;
      g.severity_pct = 0;
      g.urgency = 0;
      g.rank_score = 0;
      g.advantage_pct = Math.round(g.magnitude * 100);
    }
  });

  /* correlate chain — link behind-gaps sharing a category across pillars */
  const byCat = {};
  gaps.forEach((g) => {
    (byCat[g.category] = byCat[g.category] || []).push(g);
  });
  /* Correlating on CATEGORY ALONE put the wrong tenders on a dossier: every artillery
     matchup got the first three artillery tenders in insertion order, so a Bharat 45
     comparison could cite a tender whose scored fit is ATAGS. Both sides name the KSSL
     product in koel_entity — the competitive gap carries the matchup anchor, the market
     gap carries the tender's own best-fit product — so correlate on THAT first and fall
     back to the category only when no product-level link exists. */
  const clientPrefix = new RegExp(`^\\s*${clientName}\\s*·\\s*`, "i");
  /* Keep SHORT product names: M4, ATC, LTV, MPV are real designations, and a
     length>2 filter silently dropped "m4" so the M4 dossier never matched the
     tender scored to the Kalyani M4. */
  const prodTokens = (entity) =>
    String(entity || "")
      .replace(clientPrefix, "")
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter(
        (w) =>
          w.length >= 2 &&
          /* brand and filler words */
          !/^(the|and|for|kssl|kalyani|bharat|systems|platforms|no|direct|product|from|core|programme)$/.test(w) &&
          /* GENERIC CLASS NOUNS: sharing "carbine" is not sharing a product — it
             linked the 5.56x30 Protective Carbine to the 5.56x45 CQB tender. A match
             must rest on a designation (atags, marg, m4, ulh, 155, 150), not a class. */
          !/^(carbine|rifle|howitzer|gun|guns|vehicle|vehicles|drone|drones|uav|uas|munition|munitions|platform|ammunition|naval|marine|armoured|armored|protected|mounted|towed|light|heavy|build|bodies)$/.test(w),
      );
  const sharesProduct = (a, b) => {
    const ta = prodTokens(a);
    const tb = prodTokens(b);
    return ta.some((w) => tb.includes(w));
  };

  gaps.forEach((g) => {
    if (g.direction !== "behind") {
      g.correlates = [];
      return;
    }
    const pool = (byCat[g.category] || []).filter(
      (x) => x.pillar !== g.pillar && x.direction === "behind",
    );
    const onProduct = pool.filter((x) => sharesProduct(g.koel_entity, x.koel_entity));
    /* A MARKET chip claims "this live tender bears on this product", so it is only
       honest when the tender's own scored fit names that product. Category-only
       market links put 155mm tenders on a 105mm gun, naval-gun tenders on an AUV
       and the carbine tender on a sniper rifle — those are dropped. Technology
       correlates stay category-level: innovation fronts are category-scoped by
       nature, not product-scoped. */
    const rest = pool
      .filter((x) => !onProduct.includes(x) && x.pillar !== "market")
      .sort((a, b) => (b.magnitude || 0) - (a.magnitude || 0));
    g.correlates = [...onProduct, ...rest].slice(0, 3).map((x) => ({
      id: x.id,
      pillar: x.pillar,
      label: x.benchmark_entity,
      mag: x.magnitude,
      sev: x.severity_pct,
      onProduct: onProduct.includes(x),
    }));
  });
  return gaps;
}

/* shared: build the cross-pillar correlate + exposure strip for a category.
   `onTenderClick` is a global function NAME, because this returns a string that is
   injected with dangerouslySetInnerHTML — the same trade the original made. */
export function gapCorrelateStrip(model, pillar, matchLabel) {
  try {
    let rec = null;
    if (pillar === "technology") {
      rec = model.find(
        (g) => g.pillar === "technology" && (g.koel_entity === `KSSL · ${matchLabel}` || (g.koel_entity || "").endsWith(matchLabel)),
      );
    } else if (pillar === "market") {
      rec = model.find((g) => g.pillar === "market" && g.tenderTitle === matchLabel);
    }
    if (!rec) return "";
    let h = '<div class="gapx-strip">';
    // exposure line (only if meaningful)
    if (rec.exposure_value > 0) {
      h +=
        `<div class="gapx-exp"><span class="gapx-lbl">₹ exposure</span><span class="gapx-val">${formatCrore(rec.exposure_value)}</span>` +
        `<span class="gapx-note">live tenders in ${escAll(rec.category)} this gap touches</span></div>`;
    }
    // cross-pillar correlates
    if (rec.correlates && rec.correlates.length) {
      h += '<div class="gapx-corr"><span class="gapx-lbl">Reinforced across pillars</span>';
      rec.correlates.forEach((c) => {
        const pn =
          c.pillar === "market"
            ? "Market"
            : c.pillar === "technology"
              ? "Technology"
              : "Competitive";
        const lbl = (c.label || "").replace(/^(KSSL|Kalyani Strategic Systems) · /, "");
        const isMkt = c.pillar === "market";
        h +=
          `<span class="gapx-chip ${c.pillar}${isMkt ? " clickable" : ""}"` +
          (isMkt
            ? ` role="button" tabindex="0" data-tender="${escAll(lbl).replace(/"/g, "&quot;")}" title="Open this tender in Market"`
            : "") +
          `>${pn} · ${escAll(lbl.slice(0, 30))}${isMkt ? " ↗" : ""}</span>`;
      });
      h += "</div>";
    }
    h += "</div>";
    return h === '<div class="gapx-strip"></div>' ? "" : h;
  } catch (e) {
    return "";
  }
}
