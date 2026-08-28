/* ===================================================================
   PATENT DATA SEAM — the single integration point for a live patent backend.

   TODAY: reads the filings already indexed in the dataset (dataset.js adapts
   PATENTS.byArea / byAssignee into byCompetitor / byTechnology on load).
   LATER: set PATENT_BACKEND_READY and replace ONLY the body of searchPatents()
   with a call to the endpoint. Return the documented shape and the entire patents
   UI works unchanged — no other edits.

   CONTRACT
   --------
   searchPatents(dataset, { competitor?, technology?, query?, page? })
     -> Promise<{
          status: 'ok' | 'empty' | 'awaiting_backend' | 'error',
          results: [{ id, title, assignee,
                      status,        // 'granted' | 'filed' | 'pending'
                      filed, granted,
                      jurisdiction,  // 'IN' | 'US' | 'EP' ...
                      ipc: [], abstract,
                      url }],        // REAL patent link (Google Patents / Espacenet)
          total, source
        }>
   =================================================================== */
import { attr, escAll, srcChips } from "./html.js";

export const PATENT_BACKEND_READY = false;

export async function searchPatents(d, params) {
  // ---- dataset-backed (today) ----
  if (!PATENT_BACKEND_READY) {
    let results = [];
    const PATENTS = d.PATENTS;
    if (PATENTS) {
      const byC = PATENTS.byCompetitor || {};
      const byT = PATENTS.byTechnology || {};
      if (params.competitor && byC[params.competitor]) {
        results = (byC[params.competitor].records || []).map(normSample);
      } else if (params.technology && byT[params.technology]) {
        results = (byT[params.technology].records || []).map(normSample);
      }
    }
    // records come from the loaded dataset, not a live API — so report 'ok' when
    // there are any and 'empty' when the research pass has landed none.
    return {
      status: results.length ? "ok" : "empty",
      results,
      total: results.length,
      source: "dataset",
    };
  }
  // ---- LIVE (replace this body when the endpoint lands) ----
  try {
    return { status: "awaiting_backend", results: [], total: 0, source: "unwired" };
  } catch (e) {
    return { status: "error", results: [], total: 0, source: "error", error: String(e) };
  }
}

function normSample(r) {
  return {
    id: r.id,
    title: r.title,
    assignee: r.assignee || "",
    status: r.status || "filed",
    filed: r.filed || "",
    granted: r.granted || "",
    jurisdiction: r.jurisdiction || "",
    ipc: r.ipc || [],
    abstract: r.abstract || "",
    techArea: r.techArea || "",
    koel_relevance: r.koel_relevance || "",
    srcs: r.srcs || [],
    url:
      (r.srcs && r.srcs[0] && r.srcs[0].url) ||
      r.url ||
      `https://patents.google.com/?q=${encodeURIComponent(r.title || r.id || "")}`,
    /* 4 records have no filing link and fall back to a Google Patents SEARCH.
       Labelling that "View patent" presents a query as a citation, so the flag
       lets the link say what it actually is. */
    urlIsSearch: !((r.srcs && r.srcs[0] && r.srcs[0].url) || r.url),
  };
}

export function patLoadingHtml(label) {
  return `<div class="pat-loading"><span class="pat-spin"></span><span>Searching patents${label ? ` · ${label}` : ""}…</span></div>`;
}

export function patStateHtml(state, label) {
  if (state === "awaiting_backend") {
    return `<div class="pat-state"><div class="ps-ic">◷</div><div class="ps-t">Live patent search not yet connected</div><div class="ps-s">The patent backend is being wired in. Once connected, selecting ${label || "an item"} will auto-fetch real filings and grants, each with a direct link to the patent.</div></div>`;
  }
  if (state === "empty") {
    return `<div class="pat-state"><div class="ps-ic">⊡</div><div class="ps-t">No patents found</div><div class="ps-s">The search returned no filings for ${label || "this selection"}.</div></div>`;
  }
  if (state === "error") {
    return '<div class="pat-state err"><div class="ps-ic">⚠</div><div class="ps-t">Search failed</div><div class="ps-s">The patent service did not respond. Check the backend connection and retry.</div></div>';
  }
  return "";
}

export function patRecCard(r, showAssignee) {
  const esc = (s) => (s || "").replace(/</g, "&lt;");
  const st = r.status || "filed";
  const dateLine =
    st === "granted"
      ? `Filed ${r.filed || "—"} · Granted ${r.granted || "—"}`
      : `Filed ${r.filed || "—"}${r.status === "pending" ? " · Pending" : ""}`;
  const ipc = (r.ipc || []).map((c) => `<span>${esc(c)}</span>`).join("");
  const relev = r.koel_relevance
    ? `<span class="pat-relev ${r.koel_relevance}">${r.koel_relevance}</span>`
    : "";
  const assignee = showAssignee && r.assignee ? `<b>${esc(r.assignee)}</b> · ` : "";
  return (
    `<div class="pat-rec" data-cat="${attr(r.techArea || "")}">` +
    `<div class="pat-rec-h"><div class="pat-rec-t">${esc(r.title)}</div>${relev}<span class="pat-badge ${st}">${st}</span></div>` +
    `<div class="pat-rec-meta"><span>${assignee}${esc(r.id || "")}</span><span>${esc(r.jurisdiction || "")}</span><span>${dateLine}</span></div>` +
    (ipc ? `<div class="pat-ipc">${ipc}</div>` : "") +
    `<div class="pat-abs">${esc(r.abstract || "")}</div>` +
    (r.url
      ? `<a class="pat-view-link" href="${attr(r.url)}" target="_blank" rel="noopener noreferrer">${r.urlIsSearch ? "Search for this filing ↗" : "View patent ↗"}</a>`
      : "") +
    // any source beyond the primary patent page (deduped against it)
    srcChips((r.srcs || []).filter((s) => s && s.url && s.url !== r.url)) +
    "</div>"
  );
}

export function patApiNote(d) {
  const meta = (d.PATENTS && d.PATENTS._meta) || {};
  const pv = meta.providers || [
    "Google Patents",
    "EPO Espacenet",
    "WIPO Patentscope",
    "Indian Patent Office",
  ];
  const tot = meta.total || 0;
  return (
    `<div class="pat-api-note"><b>Data source:</b> patent records are loaded from the platform dataset, sourced from ${pv.join(", ")}. ` +
    (tot
      ? `${tot} filings currently indexed.`
      : "No filings indexed yet — the patent research pass has not landed for this client.") +
    "</div>"
  );
}

export function deriveStats(recs) {
  const s = { granted: 0, filed: 0, pending: 0 };
  (recs || []).forEach((r) => {
    if (r.status === "granted") s.granted++;
    else if (r.status === "pending") s.pending++;
    else s.filed++;
  });
  return s;
}

/* The by-rival canvas: portfolio stats then every filing. */
export function patCompBody(d, cid, res) {
  const recs = res.results || [];
  const pd = d.PATENTS ? (d.PATENTS.byCompetitor || {})[cid] : null;
  const s = (pd && pd.stats) || deriveStats(recs);
  const name = (d.competitors[cid] || {}).name || cid;
  let h =
    '<div class="pat-stats">' +
    `<div class="pat-stat granted"><div class="pv">${s.granted || 0}</div><div class="pl">Granted</div></div>` +
    `<div class="pat-stat filed"><div class="pv">${s.filed || 0}</div><div class="pl">Filed</div></div>` +
    `<div class="pat-stat pending"><div class="pv">${s.pending || 0}</div><div class="pl">Pending</div></div>` +
    "</div>";
  if (res.status === "awaiting_backend") h += patStateHtml("awaiting_backend", name);
  else if (res.status === "error") h += patStateHtml("error", name);
  else if (!recs.length) h += patStateHtml("empty", name);
  if (recs.length) {
    h += `<div class="ws-sec-l" style="margin-top:6px">▸ ${recs.length} filing${recs.length !== 1 ? "s" : ""}</div>`;
    h += recs.map((r) => patRecCard(r, false)).join("");
  }
  h += patApiNote(d);
  return h;
}

/* The by-field canvas: crowding, who holds filings, KSSL's position, then filings. */
export function patTechBody(d, area, res) {
  const td = (d.PATENTS && d.PATENTS.byTechnology) ? d.PATENTS.byTechnology[area] : null;
  const esc = escAll;
  if (!td) {
    return (
      `<div class="pat-empty"><div class="pe-ic">⊡</div><div class="pe-t">No filings recorded in this field</div><div class="pe-s">No patents are indexed for <b>${esc(area)}</b> yet. Once the patent research pass lands, this view shows filing volume, the crowding trend, who leads the field, and the white space KSSL can still claim.</div></div>` +
      patApiNote(d)
    );
  }
  const s = td.stats || {};
  const crowdMap = {
    open: ["#3b8d5c", "Open field"],
    emerging: ["#c08a2b", "Emerging"],
    crowded: ["#c0654a", "Crowded"],
    locked: ["#9c2b2b", "Locked up"],
  };
  const cm = crowdMap[td.crowding] || crowdMap.emerging;
  let h = "";
  h +=
    `<div class="ws-crowd"><div><span class="ws-crowd-l">Field crowding</span><span class="ws-crowd-v" style="color:${cm[0]}">${cm[1]}</span></div>` +
    '<div class="pat-stats" style="margin:0">' +
    `<div class="pat-stat filed"><div class="pv">${s.totalFilings || 0}</div><div class="pl">Filings</div></div>` +
    `<div class="pat-stat"><div class="pv">${s.activeAssignees || 0}</div><div class="pl">Assignees</div></div>` +
    "</div></div>";
  if (td.summary) h += `<div class="ws-summary">${esc(td.summary)}</div>`;
  if (td.leaders && td.leaders.length) {
    /* Was a row of share bars. Every assignee here holds exactly one filing in almost
       every field, so those bars were all the same length by construction — they
       encoded nothing. This shows what does differ between holders. */
    const L = td.leaders;
    const koelHere = L.filter((l) => l.isClient);
    const rivals = L.filter((l) => !l.isClient);
    const grantedRivals = rivals.filter((l) => l.granted > 0);
    const koelFilings = koelHere.reduce((t, l) => t + l.filings, 0);
    h +=
      `<div class="ws-koelbar ${koelHere.length ? "in" : "out"}">` +
      `<span class="wk-ic">${koelHere.length ? "●" : "○"}</span>` +
      `<div class="wk-txt">${
        koelHere.length
          ? `<b>KSSL holds ${koelFilings} filing${koelFilings !== 1 ? "s" : ""} in this field.</b> ` +
            `It is contested by ${rivals.length} other holder${rivals.length !== 1 ? "s" : ""}.`
          : "<b>KSSL holds no filings in this field.</b> " +
            `${rivals.length} rival${rivals.length !== 1 ? "s have" : " has"} staked it` +
            (grantedRivals.length
              ? `, ${grantedRivals.length} with a granted patent already enforceable`
              : "") +
            "."
      }</div></div>`;
    h +=
      '<div class="ws-sec-l">▸ Who holds filings here <span class="ws-sec-note">ranked by granted patents, then assessed threat, then recency</span></div>';
    h += '<div class="ws-holders">';
    L.forEach((l) => {
      const geo = (l.countries || []).join(" · ");
      h +=
        `<div class="ws-holder${l.isClient ? " client" : ""} th-${esc(l.threat || "low")}">` +
        `<div class="wh-l"><span class="wh-name">${esc(l.name)}${l.isClient ? ' <i class="wh-you">KSSL</i>' : ""}</span>` +
        `<span class="wh-meta">${l.filings || 0} filing${l.filings !== 1 ? "s" : ""}` +
        `${geo ? ` · ${esc(geo)}` : ""}${l.latest ? ` · latest ${l.latest}` : ""}</span></div>` +
        '<div class="wh-r">' +
        (l.granted
          ? `<span class="wh-chip granted" title="Granted — enforceable now">${l.granted} granted</span>`
          : "") +
        (l.pending
          ? `<span class="wh-chip pending" title="Published, not yet granted">${l.pending} published</span>`
          : "") +
        (l.isClient
          ? ""
          : `<span class="wh-chip th ${esc(l.threat || "low")}" title="Assessed threat to KSSL">${esc(l.threat || "low")}</span>`) +
        "</div></div>";
    });
    h += "</div>";
  }
  if (td.whitespace && td.whitespace.length) {
    h += '<div class="ws-sec-l open">▸ Sparsely-patented areas</div><div class="ws-gaps">';
    td.whitespace.forEach((w) => {
      h +=
        `<div class="ws-gap"><div class="ws-gap-h"><span class="ws-gap-name">${esc(w.area)}</span><span class="ws-gap-n">${w.filings || 0} filings</span></div>` +
        `<div class="ws-gap-note">${esc(w.note)}</div></div>`;
    });
    h += "</div>";
  }
  if (td.koel) {
    h +=
      '<div class="ws-koel"><span class="ws-koel-l">KSSL position</span>' +
      `<div class="ws-koel-pos">${esc(td.koel.position || "—")}</div>` +
      "</div>";
  }
  // ---- filings via the seam ----
  h += '<div class="ws-sec-l" style="margin-top:18px">▸ Filings in this field</div>';
  const recs = res.results || [];
  if (res.status === "awaiting_backend") h += patStateHtml("awaiting_backend", area);
  else if (res.status === "error") h += patStateHtml("error", area);
  else if (!recs.length) h += patStateHtml("empty", area);
  if (recs.length) h += recs.map((r) => patRecCard(r, true)).join("");
  h += patApiNote(d);
  return h;
}
