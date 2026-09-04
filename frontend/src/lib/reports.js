/* The two CEO briefings: one for a Positioning matchup, one for an Innovation theme.
   Both are descriptive — they restate what the platform already holds and add the
   cross-pillar exposure, and neither prescribes a move. */
import { computeSpecEdge, edgeVerdict } from "./edge.js";
import { escAll, srcChips, attr, stripTags } from "./html.js";
import { formatDate } from "../utils/formatDate.js";

export function positioningReportHtml(m, tenders, today = formatDate()) {
  const edge = m.edge == null ? null : m.edge;
  if (edge == null) {
    return (
      '<div class="tech-report"><div class="tr-head"><div class="tr-title">Positioning Briefing · CEO</div>' +
      `<div class="tr-sub">${escAll(m.comp || "")} vs ${escAll(m.bf || "KSSL")}</div>` +
      `<div class="tr-meta">CONFIDENTIAL · KSSL · Prepared ${today} · Category: ${escAll(m.cat || "")}</div></div>` +
      '<div class="tr-verdict parity"><b>KSSL spec undisclosed — no measured edge.</b></div>' +
      `<div class="tr-sec"><div class="tr-sec-h">Assessment</div><div class="tr-body">${escAll(m.comp || "")} is a real, sourced competitor mapped to KSSL's ${escAll((m.bf || "counterpart").replace(/^KSSL · /, ""))} by role and spec class. KSSL has not publicly disclosed specifications for this counterpart, so no spec-level edge or verdict is computed. The comparison holds at the role and capability-class level.</div></div>` +
      (m.advBf && m.advBf.length
        ? `<div class="tr-sec"><div class="tr-sec-h">KSSL Advantages To Press</div><div class="tr-body">${m.advBf.map((a) => `• ${stripTags(a)}`).join("<br>")}</div></div>`
        : "") +
      (m.advComp && m.advComp.length
        ? `<div class="tr-sec"><div class="tr-sec-h">Competitor Strengths To Counter</div><div class="tr-body">${m.advComp.map((a) => `• ${stripTags(a)}`).join("<br>")}</div></div>`
        : "") +
      '<div class="tr-foot">Descriptive · sourced · no fabricated specs</div></div>'
    );
  }
  const v = edgeVerdict(edge);
  const edgeWord = v.phrase.toUpperCase();
  /* Spec leads come from the same decided votes that produced the edge index —
     computeSpecEdge already excludes pairing axes, null-direction rows and
     sub-deadband deltas, so "leads" here can never contradict the gauge. */
  const ce = computeSpecEdge(m);
  const specByLabel = {};
  (m.specs || []).forEach((s) => {
    specByLabel[s.l] = s;
  });
  const leads = { comp: [], bf: [], even: [] };
  ce.dims.forEach((d) => {
    const s = specByLabel[d.l] || {};
    if (d.a > 0) leads.bf.push(`${d.l} (${s.kv != null ? s.kv : "—"})`);
    else if (d.a < 0) leads.comp.push(`${d.l} (${s.cv != null ? s.cv : "—"})`);
    else leads.even.push(d.l);
  });
  // cross-pillar tenders in this category
  let relT = [];
  try {
    relT = tenders.filter((t) => t.cat === m.cat).slice(0, 4);
  } catch (e) {
    /* no tender pipeline -> no market exposure section */
  }
  // the det rows label this "Provenance"; "Source" matched 0 of 507 matchups
  const srcRow = (m.det || []).find((d) => d[0] === "Provenance" || d[0] === "Source");
  return (
    '<div class="tech-report">' +
    `<div class="trep-head"><div><div class="trep-eyebrow">Positioning Briefing · CEO</div><div class="trep-title">${escAll(m.comp)} vs ${escAll(m.bf)}</div></div><div class="trep-class">CONFIDENTIAL · KSSL</div></div>` +
    `<div class="trep-meta">Prepared ${today} · Category: ${escAll(m.cat)} · Competitor: ${escAll(m.compBy)}</div>` +
    `<div class="trep-verdict ${v.cls}">${edgeWord} · edge index ${edge}/100</div>` +
    `<div class="trep-sec"><div class="trep-h">1 · Bottom line</div><p>${m.verdict.replace(/<b>\[Analysis\]<\/b>\s*/, "")}</p></div>` +
    '<div class="trep-sec"><div class="trep-h">2 · Where each side leads (spec gap)</div>' +
    `<p><b>${escAll((m.compBy || m.comp || "Competitor").split(" ")[0])} leads:</b> ${leads.comp.length ? escAll(leads.comp.join("; ")) : "—"}</p>` +
    `<p style="margin-top:6px"><b>KSSL leads:</b> ${leads.bf.length ? escAll(leads.bf.join("; ")) : "—"}</p>` +
    (leads.even.length
      ? `<p style="margin-top:6px"><b>Comparable:</b> ${escAll(leads.even.join("; "))}</p>`
      : "") +
    "</div>" +
    `<div class="trep-sec"><div class="trep-h">3 · KSSL advantages to press</div><p>${(m.advBf || []).map((a) => `• ${stripTags(a)}`).join("<br>")}</p></div>` +
    `<div class="trep-sec"><div class="trep-h">4 · Competitor strengths to counter</div><p>${(m.advComp || []).map((a) => `• ${stripTags(a)}`).join("<br>")}</p></div>` +
    (relT.length
      ? `<div class="trep-sec"><div class="trep-h">5 · Where this matchup is live (market exposure)</div><p>Open tenders in ${escAll(m.cat)} where this competition plays out:</p>` +
        relT
          .map(
            (t) =>
              `<div class="trep-tender"><b>${escAll(t.title)}</b> — ${escAll(t.country)}, ${escAll(t.value)} · KSSL match: ${
                t.matches && t.matches[0]
                  ? `${escAll(t.matches[0].n)} (${escAll(t.matches[0].pct)})`
                  : "—"
              } · lean: <span class="trep-lean ${t.lean}">${t.lean}</span></div>`,
          )
          .join("") +
        "</div>"
      : "") +
    `<div class="trep-sources">Competitor specs: ${srcRow ? escAll(srcRow[1]) : "on file"}. KSSL specs sourced where marked; comparative analysis is KSSL-platform assessment. Figures marked with an orange dot are analytical estimates, not sourced.</div>` +
    '<div class="trep-foot"><button class="trep-print" data-print="1">⎙ Print / save as PDF</button></div>' +
    "</div>"
  );
}

const MAT_LAB_REPORT = {
  lab: "Lab / research",
  dev: "In development",
  prod: "In production",
  fielded: "Fielded",
};

export function techReportHtml(iv, d, techCatId, today = formatDate()) {
  const matLab = MAT_LAB_REPORT[iv.mat] || iv.mat;
  const gapLab = {
    behind: "KSSL is BEHIND the leaders",
    parity: "KSSL is AT PARITY",
    ahead: "KSSL is AHEAD",
  }[iv.gap];
  const catName = (() => {
    const c = d.techCats.filter((x) => x.id === techCatId)[0];
    return c ? c.name : "";
  })();
  let relTenders = [];
  let relComps = [];
  try {
    relTenders = d.tenders.filter((t) => t.cat === catName).slice(0, 4);
  } catch (e) {
    /* no matching tenders -> section omitted */
  }
  try {
    relComps = [
      ...new Set(
        Object.values(d.matchups)
          .filter((m) =>
            m.cat.toLowerCase().includes((catName.split(" ")[0] || "").toLowerCase()),
          )
          .map((m) => m.comp),
      ),
    ].slice(0, 6);
  } catch (e) {
    /* no matching matchups -> landscape list omitted */
  }
  return (
    '<div class="tech-report">' +
    `<div class="trep-head"><div><div class="trep-eyebrow">Intelligence Briefing · CEO</div><div class="trep-title">${escAll(iv.t)}</div></div><div class="trep-class">CONFIDENTIAL · KSSL</div></div>` +
    `<div class="trep-meta">Prepared ${today} · Domain: ${escAll(catName)} · Maturity: ${escAll(matLab)} · Horizon: ${escAll(iv.horizon)}</div>` +
    `<div class="trep-verdict ${iv.gap}">${gapLab}</div>` +
    `<div class="trep-sec"><div class="trep-h">1 · Executive summary</div><p>${iv.body}</p></div>` +
    `<div class="trep-sec"><div class="trep-h">2 · What's new</div><p>${iv.whatsNew}</p></div>` +
    `<div class="trep-sec"><div class="trep-h">3 · Strategic implication for KSSL</div><p>${iv.impact.replace(/<b>\[Analysis\][^<]*<\/b>\s*/, "")}</p></div>` +
    `<div class="trep-sec"><div class="trep-h">4 · Competitive landscape</div><p>${iv.compNote}</p>` +
    (relComps.length
      ? `<p style="margin-top:8px"><b>Competitor products tracked in ${escAll(catName)}:</b><br>${relComps.map((c) => `• ${escAll(c)}`).join("<br>")}</p>`
      : "") +
    "</div>" +
    (relTenders.length
      ? "<div class=\"trep-sec\"><div class=\"trep-h\">5 · Live market exposure</div><p>Open tenders in this domain where the technology bears on KSSL's bid:</p>" +
        relTenders
          .map(
            (t) =>
              `<div class="trep-tender"><b>${escAll(t.title)}</b> — ${escAll(t.country)}, ${escAll(t.value)} · matched: ${
                t.matches && t.matches[0]
                  ? `${escAll(t.matches[0].n)} (${escAll(t.matches[0].pct)})`
                  : "—"
              } · lean: <span class="trep-lean ${t.lean}">${t.lean}</span></div>`,
          )
          .join("") +
        "</div>"
      : "") +
    `<div class="trep-sources">Sources: ${attr(iv.sources || "—")} ` +
    srcChips(
      iv.srcs && iv.srcs.length
        ? iv.srcs
        : iv.url
          ? [{ label: "Source", url: iv.url }]
          : null,
    ) +
    "<br>Competitive &amp; market figures drawn from the platform dataset (real where sourced, estimated where marked).</div>" +
    '<div class="trep-foot"><button class="trep-print" data-print="1">⎙ Print / save as PDF</button></div>' +
    "</div>"
  );
}
