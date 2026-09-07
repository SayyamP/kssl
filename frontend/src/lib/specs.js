/* Paired-bar spec renderer for the Positioning dossier, plus the gap block that sits
   under the verdict. Kept as string builders because they are dense read-only markup
   with no interaction beyond the container — the same trade the original made. */
import { computeSpecEdge, edgeBasis, edgeVerdict, isNumericVal } from "./edge.js";
import { escAll } from "./html.js";
import { formatCrore } from "../utils/formatNumber.js";

/* A spec value with the unit the RECORD holds for it -- and never any other.

   T 7: the paired-bar rows print the unit in their label, but the product page and
   the no-edge branch below printed the bare value, so "Max range 40+" sat beside
   "Max range 41 km" on the product one line down. The matchup row carries the unit
   in its own field (`u`), which is the only place a unit can honestly come from: a
   unit read off the LABEL ("calibre, so mm") is a fabricated figure, and
   check_no_fabrication.mjs exists for that class.

   So: the stored unit, once, and only onto a value that is a plain figure -- a
   number, a range, a bound, a plus. A value that already names a unit is left as it
   is ("Minimum 30 minutes" under a record that says hours would otherwise print
   "Minimum 30 minutes hours"), a placeholder is left as it is, and no unit on the
   record means no unit on screen. The one thing removed is a unit the record
   repeated ("over 67 km/h km/h"). */
export function specValueWithUnit(v, u) {
  if (v == null) return "";
  const s = String(v).trim();
  if (!s) return "";
  const unit = u == null ? "" : String(u).trim();
  if (!unit) return s;
  const esc = unit.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const once = s.replace(new RegExp(`(${esc})(?:\\s+${esc})+$`, "i"), "$1");
  if (new RegExp(`(^|[^A-Za-z])${esc}([^A-Za-z]|$)`, "i").test(once)) return once;
  if (/^[<>~]?\s*\d[\d.,]*(?:\s*[-–]\s*\d[\d.,]*)?\s*\+?$/.test(once)) return `${once} ${unit}`;
  return once;
}

function parseSpecNum(v, fallback) {
  if (v != null) {
    const m = String(v).match(/(\d+(?:\.\d+)?)/);
    if (m) return parseFloat(m[1]);
  }
  return fallback != null ? fallback : 0;
}

/* one comparable row */
function specRow(s, compName) {
  // per-side provenance dot (only when synthetic)
  const dot = (pv) => (pv === "s" ? "" : '<span class="provdot x"></span>');
  const cpv = s.cp || s.p;
  const kpv = s.kp || s.p;

  // Non-comparable (one side has no number) -> show both as chips, no bars, no false winner
  if (s.cn == null || s.kn == null) {
    return (
      `<div class="specbar"><div class="sb-label">${s.l}${s.u ? ` <span class="sb-unit">(${s.u})</span>` : ""}</div>` +
      '<div class="sb-pair">' +
      `<div class="sb-side bf"><span class="sb-who">KSSL</span><span class="sb-num">${specValueWithUnit(s.kv, s.u) || s.kv}${dot(kpv)}</span></div>` +
      `<div class="sb-side comp"><span class="sb-who">${compName || "Competitor"}</span><span class="sb-num">${specValueWithUnit(s.cv, s.u) || s.cv}${dot(cpv)}</span></div>` +
      "</div></div>"
    );
  }

  // Comparable: Baseline graph — the highest value fills 100% (full width),
  // and the smaller value fills proportionally smaller relative to the 100% baseline.
  // The stored numbers are authoritative; parsing the display text is only a
  // fallback — "LR2 5.5 km" must compare as 5.5, not as the 2 in the model name.
  const cn = typeof s.cn === "number" ? s.cn : parseSpecNum(s.cv, s.cn);
  const kn = typeof s.kn === "number" ? s.kn : parseSpecNum(s.kv, s.kn);
  const axisMax = Math.max(cn, kn, 0.0001); // 100% baseline for highest value
  const cw = Math.max(4, Math.round((cn / axisMax) * 100));
  const kw = Math.max(4, Math.round((kn / axisMax) * 100));
  // MAGNITUDE of the gap, relative to the larger value — this drives emphasis.
  const hiVal = Math.max(cn, kn);
  const loVal = Math.min(cn, kn);
  const gapPct = hiVal > 0 ? Math.round(((hiVal - loVal) / hiVal) * 100) : 0;
  // Who leads by direction — but a sub-5% difference is treated as PARITY, not a lead.
  let lead = null;
  if (s.hi !== null && cn !== kn && gapPct >= 5) {
    lead = s.hi ? (cn > kn ? "comp" : "bf") : cn < kn ? "comp" : "bf";
  }
  const compWin = lead === "comp";
  const bfWin = lead === "bf";
  const parity = s.cn === s.kn || lead === null; // includes sub-5% near-ties
  // emphasis tier scales with magnitude
  const tier =
    gapPct >= 35 ? "decisive" : gapPct >= 15 ? "clear" : gapPct >= 5 ? "marginal" : "parity";
  const leadWord = tier === "decisive" || tier === "clear" ? "leads" : "";
  const badge = (w) => (w && leadWord ? `<span class="sb-lead ${tier}">${leadWord}</span>` : "");
  const parityTag = parity ? '<span class="sb-parity">parity</span>' : "";
  const dirNote = s.hi === false ? '<span class="sb-dir">lower is better</span>' : "";

  return (
    '<div class="specbar">' +
    `<div class="sb-label">${s.l}${s.u ? ` <span class="sb-unit">(${s.u})</span>` : ""}${parityTag}${dirNote}</div>` +
    `<div class="sb-cmprow${bfWin ? " win" : ""}">` +
    '<span class="sb-who bf">KSSL</span>' +
    `<div class="sb-track"><div class="sb-fill bf${bfWin ? ` win ${tier}` : ""}" style="width:${kw}%"></div></div>` +
    `<span class="sb-val${bfWin ? " win" : ""}">${s.kv}${dot(kpv)}${badge(bfWin)}</span>` +
    "</div>" +
    `<div class="sb-cmprow${compWin ? " win" : ""}">` +
    `<span class="sb-who comp">${compName || "Competitor"}</span>` +
    `<div class="sb-track"><div class="sb-fill comp${compWin ? ` win ${tier}` : ""}" style="width:${cw}%"></div></div>` +
    `<span class="sb-val${compWin ? " win" : ""}">${s.cv}${dot(cpv)}${badge(compWin)}</span>` +
    "</div>" +
    "</div>"
  );
}

/* qualitative rows: labelled chips (no misleading bars); orange dot only on synthetic */
/* Where a value came from, shown under the value itself.
   A number about a real weapon has to name its source, and the source has to be
   reachable — so each publisher is a link, and the tier ("manufacturer" vs
   "corroborated by N") is stated rather than implied. A value with no surviving
   source is rendered "not sourced", never as a bare dash that reads like zero. */
/* TASKS #8: "Remove sources from specs comparison page." Off at the one function all
   four call sites go through, rather than deleted from each -- flip this back to true
   and the provenance returns exactly as it was.
   Worth knowing what the switch costs, since the comment above is the page's own rule:
   the VALUES stay sourced (nothing about extraction changes, and srcs are still on the
   record and still shown in Competitor Detail), but the reader can no longer see WHICH
   publisher a given number came from without leaving the comparison. */
/* WHOSE NUMBER IS THIS? One side of a matchup row, never the other.

   A matchup spec row carries both products' values -- `cv` is the rival's, `kv` is
   KSSL's -- and a product page shows ONE product. The competitor branch of the Products
   page read `s.cv || s.kv`, so on every field the rival had not published it printed
   KSSL's figure as the rival's, under the rival's name, with no mark of any kind.

   BAE Systems' Archer showed 15 fields. Seven were Archer's. The rest were MArG 155's:
   "9,391 x 2,650 x 3,160 mm" is a value that exists nowhere in the payload except as a
   KSSL `kv`, and it was being read as a BAE dimension. Positioning had it right all
   along -- it prints "not sourced" on that side, which is why the two pages disagreed.

   A fallback is the wrong shape for this question. There is no sense in which KSSL's
   weight is an estimate of the rival's, so an absent `cv` has exactly one honest
   rendering: the field is not shown for that product. */
const NOT_PUBLISHED = new Set(["no published figure", "not published"]);

export function productSpecs(specs, side, labelOf) {
  const key = side === "client" ? "kv" : "cv";
  const label = labelOf || ((l) => l);
  const out = {};
  (specs || []).forEach((s) => {
    if (!s || !s.l) return;
    const v = s[key];
    if (!v || NOT_PUBLISHED.has(String(v).trim().toLowerCase())) return;
    out[label(s.l)] = specValueWithUnit(v, s.u);
  });
  return out;
}

export const SHOW_POSITIONING_SOURCES = false;
/* Kept as the old name so the four call sites below read unchanged. */
const SHOW_SPEC_SOURCES = SHOW_POSITIONING_SOURCES;

/* THE SAME REQUEST, THE OTHER TWO PANELS.
   Sources come off Positioning in three different shapes, and turning one off left the
   other two on:
     Spec Comparison   srcLine() under each value                -- off since TASKS #8
     Competitor Detail a "Sources" row appended by srcKvRow      -- 95 of 117 matchups
     Advantages        an inline <a class="adv-src"> per line    -- every line
   All three now read one switch, so they cannot drift apart again, and flipping it to
   true restores the provenance in all three exactly as it was.

   Stripping is DISPLAY ONLY and deliberately narrow: serving.matchup keeps srcs, and
   the anchors stay in the stored advantage strings. Only an <a> carrying the pipeline's
   own adv-src class is removed, so inline emphasis inside an advantage survives -- and
   a source rendered any other way stays visible rather than being silently swallowed. */
export function advantageText(html) {
  if (SHOW_POSITIONING_SOURCES) return html;
  return String(html == null ? "" : html)
    .replace(/\s*<a[^>]*class\s*=\s*"[^"]*adv-src[^"]*"[^>]*>[\s\S]*?<\/a>/gi, "")
    .replace(/[ 	]+$/g, "")
    .trim();
}

/* THE PAGE MUST NOT PROMISE A CITATION IT DOES NOT SHOW.

   revive_matchups.py closes every pairing-logic paragraph with "Every number below
   names the page it came from." That was true while the spec panel printed a source
   line under each value; it has been false since SHOW_SPEC_SOURCES went to false for
   TASKS #8, and the sentence has sat over a comparison with no visible provenance ever
   since -- on every matchup, in the dossier, in the Products drawer and in the
   exported report.

   The sentence is dropped rather than the switch flipped back, because turning the
   source lines on would silently reverse the client's own request. Flip
   SHOW_SPEC_SOURCES to true and the sentence survives untouched, so the copy and the
   panel can no longer disagree. The deeper fix is upstream and not ours to make: a
   pipeline should not be writing claims about what a UI displays. */
export function pairingReason(reason) {
  const s = String(reason == null ? "" : reason);
  if (SHOW_SPEC_SOURCES || !s) return s;
  return s
    .replace(/\s*Every\s+number\s+below\s+names\s+the\s+page\s+it\s+came\s+from\.\s*/gi, " ")
    .trim();
}

function srcLine(urls, why, tier) {
  if (!SHOW_SPEC_SOURCES) return "";
  if (!urls || !urls.length) return "";
  const host = (u) => {
    try {
      return new URL(u).hostname.replace(/^www\./, "");
    } catch (e) {
      return u;
    }
  };
  const label = tier === "official" ? "manufacturer / official" : why || "sourced";
  const links = urls
    .map((u) => `<a class="sb-src" href="${u}" target="_blank" rel="noopener">${host(u)}</a>`)
    .join('<span class="sb-src-sep">·</span>');
  return `<div class="sb-prov"><span class="sb-prov-why">${label}</span>${links}</div>`;
}

function specRowQual(s) {
  const dot = (pv) => (pv === "s" ? "" : '<span class="provdot x"></span>');
  const cpv = s.cp || s.p;
  const kpv = s.kp || s.p;
  const has = (v) => v != null && v !== "" && v !== "—";
  /* "not sourced" and "nobody published one" are two different facts about an empty
     rival column, and the panel used to print the first over both. `noCounterpart` is
     set by extraction/signals/spec_join.py on a value KSSL publishes and the rival
     simply does not state -- 27 of the 28 specifications on the CQB Carbine's own page.
     Saying "not sourced" there reads as a failure of ours; it is an absence of theirs,
     and either way it scores for nobody (cn stays null, so the row never becomes a
     bar). */
  const missing = s.noCounterpart
    ? '<span class="sb-nosrc">no counterpart published</span>'
    : '<span class="sb-nosrc">not sourced</span>';
  const cv = has(s.cv) ? specValueWithUnit(s.cv, s.u) : missing;
  const kv = has(s.kv) ? specValueWithUnit(s.kv, s.u) : '<span class="sb-nosrc">not sourced</span>';
  return (
    `<div class="specbar"><div class="sb-label">${s.l}</div>` +
    `<div class="sb-text">` +
    `<div class="sb-cell"><div class="sb-chip comp">${cv}${has(s.cv) ? dot(cpv) : ""}</div>` +
    `${srcLine(s.srcC, s.whyC, s.tierC)}</div>` +
    `<div class="sb-cell"><div class="sb-chip bf">${kv}${has(s.kv) ? dot(kpv) : ""}</div>` +
    `${srcLine(s.srcK, s.whyK, s.tierK)}</div>` +
    `</div></div>`
  );
}

export function specBars(specs, compName) {
  const META = ["Product (sourced)", "Subcategory", "End user"];
  const quant = [];
  specs.forEach((s) => {
    if (META.indexOf(s.l) > -1) return;
    /* A row is quantitative when both sides carry a stored number and a direction.
       The display text is NOT required to lead with a digit — "LR2 5.5 km (family…)"
       is a perfectly numeric 5.5 wearing a product name. */
    const numeric = typeof s.cn === "number" && typeof s.kn === "number" && s.hi !== null;
    if (numeric) quant.push(s);
  });
  let html = "";
  // ---- QUANTITATIVE (paired bars) ----
  html +=
    '<div class="sb-sect">Quantitative specifications <span class="sb-sect-note">— measured / comparative</span></div>';
  html += quant.length
    ? quant.map((s) => specRow(s, compName)).join("")
    : '<div class="sb-empty">No comparable quantitative metrics for this matchup.</div>';
  // ---- QUALITATIVE (chips) ----
  html +=
    '<div class="sb-sect">Qualitative assessment <span class="sb-sect-note">— comprehensive specification comparison</span></div>';
  html += specs.length
    ? specs.map(specRowQual).join("")
    : '<div class="sb-empty">No qualitative dimensions recorded for this matchup.</div>';
  return html;
}

/* The whole Spec Comparison panel body for one matchup. */
export function specPanelHtml(m) {
  const compName = (m.compBy || m.comp || "Competitor").split("·")[0].trim();
  if (m.edge == null) {
    /* No edge is computable: either KSSL's specs are undisclosed, or the two
       products are not like-for-like at spec level (an empty shell forging
       against a complete filled round). Show every KSSL value that IS known
       rather than stamping "undisclosed" over real data. */
    const specs = m.specs || [];
    const kvKnown = (s) => s.kv != null && s.kv !== "—" && !/undisclosed/i.test(String(s.kv));
    const anyKnown = specs.some(kvKnown);
    /* No spec rows at all is a THIRD case. The copy below promised "competitor
       specifications below are real and sourced" over an empty table — describing
       figures the panel does not have. Say what was actually found. */
    if (!specs.length) {
      return (
        '<div class="edge-gauge undisclosed"><span class="eg-word" style="background:#555;color:#fff;padding:3px 9px;border-radius:3px">NO SPECIFICATIONS ON RECORD</span>' +
        '<div style="font-size:11px;color:var(--l-txt-3);margin-top:8px;line-height:1.5">No comparable specification figures were found in the sources for either product, so there is nothing to compare and no edge index is computed.</div></div>' +
        '<div class="sb-empty">No specification rows on record for this matchup.</div>'
      );
    }
    let h =
      `<div class="edge-gauge undisclosed"><span class="eg-word" style="background:#555;color:#fff;padding:3px 9px;border-radius:3px">NO SPEC-LEVEL EDGE</span><div style="font-size:11px;color:var(--l-txt-3);margin-top:8px;line-height:1.5">Competitor specifications below are real and sourced. ${
        anyKnown
          ? "KSSL values are shown where known, but no directly comparable measured dimension exists between these two products, so no edge index is computed."
          : "KSSL has not publicly disclosed specs for its counterpart, so each KSSL value is marked undisclosed and no spec-level edge is computed."
      }</div></div>`;
    h += `<div class="sb-legend"><span class="sb-key"><i class="k-comp"></i> ${compName.split(" ")[0]}</span><span class="sb-key"><i class="k-bf"></i> KSSL</span></div>`;
    h += `<div class="sb-sect">Competitor specifications <span class="sb-sect-note">— sourced; ${anyKnown ? "not like-for-like with KSSL" : "KSSL undisclosed"}</span></div>`;
    h += specs
      .map((s) => {
        /* This branch renders most matchups (no computable edge), so the source
           line has to appear here too — putting it only on the paired-bar path
           left the majority of values on screen with no visible provenance. */
        const dot = (s.kp || s.p) === "s" || s.kv == null ? "" : kvKnown(s) ? '<span class="provdot x"></span>' : "";
        const cKnown = s.cv != null && s.cv !== "" && s.cv !== "—";
        const cChip = cKnown
          ? `<div class="sb-chip comp">${specValueWithUnit(s.cv, s.u)}</div>`
          : s.noCounterpart
            ? '<div class="sb-chip comp undisc">no counterpart published</div>'
            : '<div class="sb-chip comp undisc">not sourced</div>';
        const kChip = kvKnown(s)
          ? `<div class="sb-chip bf">${specValueWithUnit(s.kv, s.u)}${dot}</div>`
          : '<div class="sb-chip bf undisc">KSSL — not sourced</div>';
        return (
          `<div class="specbar"><div class="sb-label">${s.l}</div><div class="sb-text">` +
          `<div class="sb-cell">${cChip}${cKnown ? srcLine(s.srcC, s.whyC, s.tierC) : ""}</div>` +
          `<div class="sb-cell">${kChip}${kvKnown(s) ? srcLine(s.srcK, s.whyK, s.tierK) : ""}</div>` +
          `</div></div>`
        );
      })
      .join("");
    return h;
  }
  const ce = computeSpecEdge(m);
  const specEdge = ce.edge;
  const v = edgeVerdict(specEdge);
  const gPos = specEdge == null ? 50 : specEdge;
  return (
    `<div class="edge-gauge ${v.cls}">` +
    `<div class="eg-top"><span class="eg-lab">Competitive edge index <span class="eg-sub">— from the quantitative specs below</span></span><span class="eg-word">${v.word}${specEdge != null ? ` · ${specEdge}` : ""}</span></div>` +
    `<div class="eg-track"><div class="eg-mid"></div><div class="eg-marker" style="left:${gPos}%"></div></div>` +
    '<div class="eg-scale"><span>Competitor stronger</span><span>Parity</span><span>KSSL stronger</span></div>' +
    edgeBasis(ce) +
    "</div>" +
    `<div class="sb-legend"><span class="sb-key"><i class="k-comp"></i> ${compName.split(" ")[0]}</span><span class="sb-key"><i class="k-bf"></i> KSSL</span><span class="sb-key"><i class="k-win"></i> leads metric</span></div>` +
    specBars(m.specs, compName)
  );
}

/* GAP BLOCK — this matchup's gap in context, under the verdict. */
export function matchupGapHtml(m, model) {
  const edge = m.edge;
  const esc = escAll;
  if (edge === null || edge === undefined) {
    return '<div class="mug-none">No measured gap on this matchup — specs undisclosed on one or both sides. Where fields aren\'t published, no gap is asserted.</div>';
  }
  const behind = (50 - edge) / 50; // >0 KSSL behind
  // find THIS matchup's gap record (match by koel+bench)
  const rec = model.find(
    (g) =>
      g.pillar === "competitive" &&
      g.benchmark_entity === m.comp &&
      (g.koel_entity === m.bf || g.koel_entity === `KSSL · ${m.anchor}`),
  );
  const clientProd = (m.bf || `KSSL · ${m.anchor}`).replace(/^(KSSL|Kalyani Strategic Systems) · /, "");
  let dir;
  let mag;
  if (behind > 0.02) {
    dir = "behind";
    mag = Math.round(behind * 100);
  } else if (behind < -0.02) {
    dir = "ahead";
    mag = Math.round(-behind * 100);
  } else {
    dir = "parity";
    mag = 0;
  }
  const band =
    dir !== "behind"
      ? dir === "ahead"
        ? "lead"
        : "par"
      : mag >= 70
        ? "crit"
        : mag >= 40
          ? "high"
          : "med";
  const word =
    dir === "behind"
      ? `${mag >= 70 ? "Critical" : mag >= 40 ? "High" : "Moderate"} gap`
      : dir === "ahead"
        ? "KSSL leads"
        : "At parity";
  const sev = rec ? rec.severity_pct : mag;
  const exp = rec ? rec.exposure_value : 0;
  const urg = rec ? rec.exposure_horizon : null;

  let h = `<div class="mug ${band}">`;
  h += `<div class="mug-head"><span class="mug-verdict ${band}">${word}${dir === "behind" ? ` · ${sev}` : ""}</span>`;
  if (dir === "behind" && exp > 0)
    h += `<span class="mug-exp">${formatCrore(exp)} exposed</span>`;
  if (dir === "behind" && urg !== null && urg <= 30)
    h += `<span class="mug-urg">tender closes ${urg}d</span>`;
  h += "</div>";
  h += `<div class="mug-line"><b>${esc(clientProd)}</b> vs <b>${esc(m.comp)}</b></div>`;
  if (dir === "behind") {
    h += `<div class="mug-desc">On the directly-measured fields in the Spec Comparison, ${esc(m.comp)} leads. Gap magnitude ${mag}% (matchup edge ${edge}). Sized against ₹ of live tenders in ${esc(m.cat)}.</div>`;
  } else if (dir === "ahead") {
    h += `<div class="mug-desc">KSSL leads on measured fields here (edge ${edge}). Recorded as an advantage, not a gap.</div>`;
  } else {
    h += `<div class="mug-desc">Near-parity on measured fields (edge ${edge}). No material gap either way.</div>`;
  }
  /* cross-pillar correlates — plain-language, first-time-user friendly */
  if (rec && rec.correlates && rec.correlates.length) {
    const mktC = rec.correlates.filter((c) => c.pillar === "market");
    const techC = rec.correlates.filter((c) => c.pillar === "technology");
    if (mktC.length) {
      h += `<div class="mug-corr"><div class="mugc-explain"><b>Why this gap matters now:</b> there ${
        mktC.length === 1 ? "is <b>1 live tender</b>" : `are <b>${mktC.length} live tenders</b>`
      } in ${esc(m.cat)} that KSSL can bid on right now. This spec gap directly affects how KSSL scores on ${
        mktC.length === 1 ? "it" : "them"
      }. Click a tender to see its full requirements and KSSL's fit.</div>`;
      h += '<div class="mugc-chiprow">';
      mktC.forEach((c) => {
        const lbl = (c.label || "").replace(/^(KSSL|Kalyani Strategic Systems) · /, "");
        h += `<span class="mugc-chip market clickable" role="button" tabindex="0" data-tender="${esc(lbl).replace(/"/g, "&quot;")}" title="Open this tender in the Market pillar">${esc(lbl.slice(0, 40))} ↗</span>`;
      });
      h += "</div>";
      if (techC.length)
        h += '<div class="mugc-tech-note">Also a technology-frontier gap in this category — KSSL trails the state of the art here too.</div>';
      h += "</div>";
    } else if (techC.length) {
      h += '<div class="mug-corr"><div class="mugc-explain"><b>Why this gap matters:</b> this is also where the technology frontier is moving past KSSL. It compounds the competitive gap — KSSL is behind on both current specs and the direction the technology is heading.</div></div>';
    }
  }
  h += `<div class="mug-src">Derived · matchup.edge=${edge}${exp > 0 ? " · exposure from live tenders" : ""} · descriptive</div>`;
  h += "</div>";
  return h;
}
