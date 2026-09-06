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

/* `meta` is PATENTS._meta, which dataset.js measures over the whole corpus (see
   grantStatusKnown / relevDiscriminates there). Two of this card's three badges are
   only findings when the corpus carries the field:

     - the status badge. 'filed' is also the normaliser's fall-through, so on a corpus
       where no row has a grant date every card wore a blue "FILED" that reads as a
       registry answer. Where nothing was captured the badge says so instead.
     - the relevance badge. Every harvested row is relev='CORE'; a grade every record
       shares grades nothing, so it renders only where the corpus uses more than one.

   Both come back automatically once the harvester lands the real values. */
export function patRecCard(r, showAssignee, meta) {
  const esc = (s) => (s || "").replace(/</g, "&lt;");
  const m = meta || {};
  const st = r.status || "filed";
  /* PER-RECORD, NOT PER-CORPUS. `grantStatusKnown` says the corpus as a whole carries
     grant status; it cannot say this record does. A mixed corpus is the normal end
     state of a harvest that reads the registry per record and gives up on some, so a
     row whose own status is 'unknown' must say so even while its neighbours show real
     grants. */
  const unknown = st === "unknown" || !m.grantStatusKnown;
  const badge = unknown
    ? '<span class="pat-badge unknown" title="No grant or publication status was captured for this record. It is not being reported as ungranted -- it is unknown.">status not captured</span>'
    : `<span class="pat-badge ${st}">${st}</span>`;
  /* `filed` is the application date and is NULL where the registry was not read;
     `published` is the publication date and is always known. Printing "Filed —" for a
     record we do have a publication date for states the wrong absence. */
  const dateLine = unknown
    ? r.published
      ? `Published ${r.published}`
      : `Filed ${r.filed || r.published || "—"}`
    : st === "granted"
      ? `Filed ${r.filed || "—"} · Granted ${r.granted || "—"}`
      : `Filed ${r.filed || "—"}${st === "pending" ? " · Pending" : ""}`;
  const ipc = (r.ipc || []).map((c) => `<span>${esc(c)}</span>`).join("");
  const relev =
    m.relevDiscriminates && r.koel_relevance
      ? `<span class="pat-relev ${r.koel_relevance}">${r.koel_relevance}</span>`
      : "";
  const assignee = showAssignee && r.assignee ? `<b>${esc(r.assignee)}</b> · ` : "";
  return (
    `<div class="pat-rec" data-cat="${attr(r.techArea || "")}">` +
    `<div class="pat-rec-h"><div class="pat-rec-t">${esc(r.title)}</div>${relev}${badge}</div>` +
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

/* Arithmetic only, and correct on its own terms -- but note what it CANNOT say: every
   record whose status was never captured normalises to 'filed', so on a corpus with no
   grant data this returns granted 0 / pending 0 / filed N without anything having been
   looked up. Callers must gate the three-tile presentation on _meta.grantStatusKnown;
   a bare 0 under "Granted" is a registry claim this function never made. */
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
  const meta = (d.PATENTS && d.PATENTS._meta) || {};
  const pd = d.PATENTS ? (d.PATENTS.byCompetitor || {})[cid] : null;
  const s = (pd && pd.stats) || deriveStats(recs);
  const name = (d.competitors[cid] || {}).name || cid;
  /* GRANTED 0 / PENDING 0 IS NOT A PORTFOLIO READ. With no grant status in the corpus
     these two tiles counted the absence of a field and printed it as a measurement --
     a rival with granted patents would have shown "Granted 0" just the same. The
     count that IS backed (how many filings are on record) keeps its tile; the two
     that are not read "—" and the line underneath says why. Restores itself to the
     three-way split the moment any row carries a grant date or status. */
  let h;
  if (meta.grantStatusKnown) {
    h =
      '<div class="pat-stats">' +
      `<div class="pat-stat granted"><div class="pv">${s.granted || 0}</div><div class="pl">Granted</div></div>` +
      `<div class="pat-stat filed"><div class="pv">${s.filed || 0}</div><div class="pl">Filed</div></div>` +
      `<div class="pat-stat pending"><div class="pv">${s.pending || 0}</div><div class="pl">Pending</div></div>` +
      "</div>";
  } else {
    const total = (s.granted || 0) + (s.filed || 0) + (s.pending || 0);
    h =
      '<div class="pat-stats">' +
      `<div class="pat-stat filed"><div class="pv">${total}</div><div class="pl">Filings on record</div></div>` +
      '<div class="pat-stat unknown"><div class="pv">—</div><div class="pl">Granted</div></div>' +
      '<div class="pat-stat unknown"><div class="pv">—</div><div class="pl">Pending</div></div>' +
      "</div>" +
      '<div class="pat-nograde">Grant status was not captured for this corpus — no record carries a grant date, ' +
      "so granted and pending cannot be counted and are not being reported as zero.</div>";
  }
  if (res.status === "awaiting_backend") h += patStateHtml("awaiting_backend", name);
  else if (res.status === "error") h += patStateHtml("error", name);
  else if (!recs.length) h += patStateHtml("empty", name);
  if (recs.length) {
    h += `<div class="ws-sec-l" style="margin-top:6px">▸ ${recs.length} filing${recs.length !== 1 ? "s" : ""}</div>`;
    h += recs.map((r) => patRecCard(r, false, meta)).join("");
  }
  h += patApiNote(d);
  return h;
}

/* The by-field canvas: crowding, who holds filings, KSSL's position, then filings. */
export function patTechBody(d, area, res) {
  const td = (d.PATENTS && d.PATENTS.byTechnology) ? d.PATENTS.byTechnology[area] : null;
  const esc = escAll;
  const meta = (d.PATENTS && d.PATENTS._meta) || {};
  if (!td) {
    /* The white-space promise came out of this copy: nothing upstream computes
       sparsely-patented areas (dataset.js sets whitespace to null and says so), and
       a page must not promise a section it has no source for. */
    return (
      `<div class="pat-empty"><div class="pe-ic">⊡</div><div class="pe-t">No filings recorded in this field</div><div class="pe-s">No patents are indexed for <b>${esc(area)}</b> yet. Once the patent research pass lands, this view shows filing volume, the crowding trend and who leads the field.</div></div>` +
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
          : /* "recorded", not "holds": this corpus is a harvest of RIVAL filings, so
               the absence of a KSSL row means none was indexed here, which is not the
               same finding as KSSL owning nothing in the field. The enforceability
               clause is conditional and stays that way -- with no grant status
               captured it simply does not appear, rather than reading "0 enforceable". */
            "<b>No KSSL filing is recorded in this field.</b> " +
            `${rivals.length} rival${rivals.length !== 1 ? "s have" : " has"} staked it` +
            (grantedRivals.length
              ? `, ${grantedRivals.length} with a granted patent already enforceable`
              : "") +
            "."
      }</div></div>`;
    /* THE CAPTION NAMES THE KEYS THAT ACTUALLY SORT. dataset.js orders holders by
       granted, then threat, then recency, then name -- but two of those are NULL on
       every harvested row, so the caption described a ranking that was really just
       recency-then-name. It now lists only the keys the corpus supplies, and says
       which ones are missing rather than implying they were weighed. */
    const anyThreat = L.some((l) => l.threat);
    const sortKeys = [
      meta.grantStatusKnown ? "granted patents" : null,
      anyThreat ? "assessed threat" : null,
      "most recent filing",
      "name",
    ].filter(Boolean);
    const notRanked = [
      meta.grantStatusKnown ? null : "grant status",
      anyThreat ? null : "threat assessment",
    ].filter(Boolean);
    h +=
      '<div class="ws-sec-l">▸ Who holds filings here <span class="ws-sec-note">ranked by ' +
      `${sortKeys.join(", then ")}` +
      (notRanked.length
        ? ` · ${notRanked.join(" and ")} not captured for this corpus, so ${notRanked.length === 1 ? "it does" : "they do"} not rank anything`
        : "") +
      "</span></div>";
    h += '<div class="ws-holders">';
    L.forEach((l) => {
      const geo = (l.countries || []).join(" · ");
      h +=
        /* th-* is the row accent. An unassessed holder gets no threat class at all --
           it used to fall back to th-low, which paints "assessed and harmless". */
        `<div class="ws-holder${l.isClient ? " client" : ""}${l.threat ? ` th-${esc(l.threat)}` : ""}">` +
        `<div class="wh-l"><span class="wh-name">${esc(l.name)}${l.isClient ? ' <i class="wh-you">KSSL</i>' : ""}</span>` +
        `<span class="wh-meta">${l.filings || 0} filing${l.filings !== 1 ? "s" : ""}` +
        `${geo ? ` · ${esc(geo)}` : ""}${l.latest ? ` · latest ${l.latest}` : ""}</span></div>` +
        '<div class="wh-r">' +
        /* The grant chips are claims about a registry. "N published" titled "Published,
           not yet granted" asserted NON-grant for every record in a corpus that never
           checked -- 1,157 of them -- so with no grant status captured neither chip is
           drawn and one neutral marker says why. */
        (meta.grantStatusKnown
          ? (l.granted
              ? `<span class="wh-chip granted" title="Granted — enforceable now">${l.granted} granted</span>`
              : "") +
            (l.pending
              ? `<span class="wh-chip pending" title="Published, not yet granted">${l.pending} published</span>`
              : "")
          : '<span class="wh-chip unknown" title="No grant or publication status was captured for this corpus — these filings are not being reported as ungranted">grant status not captured</span>') +
        // a threat chip only where a threat was assessed; absence is not "low"
        (l.isClient || !l.threat
          ? ""
          : `<span class="wh-chip th ${esc(l.threat)}" title="Assessed threat to KSSL">${esc(l.threat)}</span>`) +
        "</div></div>";
    });
    h += "</div>";
  }
  /* Sparsely-patented areas: rendered when a white-space pass has produced them,
     stated as not computed when it has not. `whitespace` is null (never []) precisely
     so those two cases can be told apart -- an empty list would read as "we looked and
     the field is fully staked", which is the opposite of the truth. */
  if (td.whitespace && td.whitespace.length) {
    h += '<div class="ws-sec-l open">▸ Sparsely-patented areas</div><div class="ws-gaps">';
    td.whitespace.forEach((w) => {
      h +=
        `<div class="ws-gap"><div class="ws-gap-h"><span class="ws-gap-name">${esc(w.area)}</span><span class="ws-gap-n">${w.filings || 0} filings</span></div>` +
        `<div class="ws-gap-note">${esc(w.note)}</div></div>`;
    });
    h += "</div>";
  } else if (td.whitespace == null) {
    h +=
      '<div class="ws-sec-l open">▸ Sparsely-patented areas <span class="ws-sec-note">not computed — ' +
      "no white-space pass runs over this corpus, so no area is being claimed as open</span></div>";
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
  if (recs.length) h += recs.map((r) => patRecCard(r, true, meta)).join("");
  h += patApiNote(d);
  return h;
}

/* The fields the "By technology field" lens lists. The filings are indexed in
   PATENTS.byTechnology under the areas the harvest assigned; PATENTS.techAreas is the
   ui_config vocabulary, which on the reference dataset shares no name with them --
   the lens listed nine configured fields all reading 0 while 21 filings sat under the
   other lens. Indexed fields first, most-filed first; the configured areas only when
   nothing is indexed (each then carries its own empty state); the tracked technology
   categories only when nothing is configured either. */
export function patentAreas(P, techCats) {
  const byTech = (P && P.byTechnology) || {};
  const indexed = Object.keys(byTech)
    .filter((k) => ((byTech[k] && byTech[k].records) || []).length > 0)
    .sort((a, b) => byTech[b].records.length - byTech[a].records.length || a.localeCompare(b));
  if (indexed.length) return indexed;
  const configured = (P && Array.isArray(P.techAreas) ? P.techAreas : []).filter(Boolean);
  if (configured.length) return configured;
  return (Array.isArray(techCats) ? techCats : []).map((c) => c && c.name).filter(Boolean);
}
