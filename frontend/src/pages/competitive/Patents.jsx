import { useEffect, useMemo, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import { useData } from "../../state/DataProvider";
import { useAppState, useHeaderReport } from "../../state/AppState";
import {
  searchPatents,
  patCompBody,
  patTechBody,
  patLoadingHtml,
  patentAreas,
} from "../../lib/patents";

/* Both patent lenses live in the Competitive pillar. The field lens used to sit
   under Technology; it is the same patent set read a different way, and a rival
   fencing a field is competitive intelligence — so one view with a lens toggle. */
export default function Patents() {
  const { data } = useData();
  const { setScope, takePending } = useAppState();
  const clientName = (data.client && (data.client.short || data.client.name)) || "KSSL";
  const getSavedPat = () => {
    try {
      return s ? JSON.parse(s) : {};
    } catch (e) { return {}; }
  };
  const savedPat = getSavedPat();

  const [lens, setLens] = useState(savedPat.lens || "rival");
  const [compQuery, setCompQuery] = useState("");
  const [techQuery, setTechQuery] = useState("");
  const [cid, setCid] = useState(savedPat.cid || data.compOrder[0]);
  const [catFilter, setCatFilter] = useState(savedPat.catFilter || "");
  const [compRes, setCompRes] = useState(null);

  useEffect(() => {
    const pend = takePending("patents-comp");
    if (pend && pend.cid) {
      setCid(pend.cid);
    }
  }, [takePending]);

  /* The fields the filings are INDEXED under, most-filed first (lib/patents.js). This
     listed PATENTS.techAreas -- the ui_config vocabulary -- which on the reference
     dataset shares no name with the harvest's areas, so the lens showed nine fields
     all reading 0 while 21 filings sat under the rival lens. The configured areas,
     then the tracked categories, remain the fallbacks when nothing is indexed. */
  const areas = useMemo(() => patentAreas(data.PATENTS, data.techCats), [data]);
  const [area, setArea] = useState(savedPat.area || areas[0] || null);
  const [techRes, setTechRes] = useState(null);

  useEffect(() => {
    try {
    } catch (e) {}
  }, [lens, cid, area, catFilter]);

  /* Selection triggers the search, through the same seam a live backend would use. */
  useEffect(() => {
    let live = true;
    setCompRes(null);
    searchPatents(data, { competitor: cid }).then((r) => {
      if (live) setCompRes(r);
    });
    return () => {
      live = false;
    };
  }, [data, cid]);

  useEffect(() => {
    let live = true;
    setTechRes(null);
    searchPatents(data, { technology: area }).then((r) => {
      if (live) setTechRes(r);
    });
    return () => {
      live = false;
    };
  }, [data, area]);

  // the category filter belongs to the selected competitor's filings
  const compRecs = compRes ? compRes.results || [] : [];
  const cats = useMemo(
    () => [...new Set(compRecs.map((r) => r.techArea).filter(Boolean))].sort(),
    [compRecs],
  );
  useEffect(() => {
    setCatFilter("");
  }, [cid]);

  /* What the header's Copy / Export / Print act on: the filings the open lens lists,
     under the category filter in force, with the search status stated -- an empty
     list says whether it is empty or still loading. */
  const report = useMemo(() => {
    const recRow = (r) => [
      r.title || r.id || "untitled",
      [r.assignee, r.status, r.granted || r.filed, r.jurisdiction].filter(Boolean).join(" · "),
    ];
    const res = lens === "rival" ? compRes : techRes;
    const recs = res ? res.results || [] : [];
    const shown = lens === "rival" && catFilter ? recs.filter((r) => r.techArea === catFilter) : recs;
    const subject = lens === "rival" ? (data.competitors[cid] || {}).name || cid : area || "";
    const status = res ? res.status : "loading";
    return {
      title: `Patents · ${subject}`,
      subtitle: `${shown.length} filing${shown.length === 1 ? "" : "s"}${catFilter ? ` · ${catFilter}` : ""} · ${status}`,
      sections: [
        {
          h: lens === "rival" ? `Filings by ${subject}` : `Filings in ${subject}`,
          rows: shown.length ? shown.map(recRow) : [`No filings on record (${status}).`],
        },
      ],
      payload: {
        lens,
        competitor: lens === "rival" ? cid : null,
        technology: lens === "rival" ? null : area,
        filter: catFilter || null,
        status,
        filings: shown,
      },
    };
  }, [lens, cid, area, catFilter, compRes, techRes, data.competitors]);
  useHeaderReport(report);

  const compList = data.compOrder.filter(
    (k) =>
      data.competitors[k] &&
      (!compQuery.trim() ||
        data.competitors[k].name.toLowerCase().includes(compQuery.trim().toLowerCase())),
  );
  const areaList = areas.filter(
    (a) => !techQuery.trim() || a.toLowerCase().includes(techQuery.trim().toLowerCase()),
  );

  /* Filtering hides rows rather than re-searching — the filings are already in hand,
     and the section count above them follows the filter. */
  const applyCatFilter = (node) => {
    if (!node) return;
    let shown = 0;
    node.querySelectorAll(".pat-rec").forEach((rec) => {
      const match = !catFilter || rec.dataset.cat === catFilter;
      rec.style.display = match ? "" : "none";
      if (match) shown++;
    });
    const secl = node.querySelector(".ws-sec-l");
    if (secl)
      secl.textContent = `▸ ${shown} filing${shown !== 1 ? "s" : ""}${catFilter ? ` · ${catFilter}` : ""}`;
  };

  /* Zero filings are indexed, so both lenses are scaffolding around nothing: the rival
     rail lists 178 competitors each reading 0, and the field rail lists technology areas
     that come from ui_config and match no row. A reader has to click a competitor to
     discover the emptiness, which is why this page reads as broken rather than empty.
     Say it once, at the top, before drawing either lens.

     serving.patent does hold 26 rows, and they stay withheld on purpose: 22 of the 26
     carry estimated numbers ("IN-2024-EST01 (est, grant verified)") rather than published
     ones. They are origin='reference', which serving_live does not serve. Showing an
     invented patent number is worse than showing none. */
  const pat = data.PATENTS || {};
  const noFilings =
    !Object.keys(pat.byAssignee || {}).length && !Object.keys(pat.byArea || {}).length;

  if (noFilings)
    return (
      <div className="pat-view v-patents-comp">
        <div className="pat-state" style={{ padding: "48px 32px" }}>
          <div className="ps-ic">⊟</div>
          <div className="ps-t">No patent filings are indexed</div>
          <div className="ps-s">
            The patent harvest has not landed any filings for this client, so there is
            nothing to compare. This is a pipeline step that has not run — not a
            failure of this page.
            <br />
            <br />
            26 records do exist from an earlier pass and are deliberately withheld: 22 of
            them carry estimated rather than published patent numbers. Nothing is shown
            here in preference to something unverified.
            <br />
            <br />
            Once the harvest runs, rival portfolios and technology-field crowding appear
            in this view.
          </div>
        </div>
      </div>
    );

  return (
    <div className="pat-view v-patents-comp">
      <div className="pat-lens">
        <span className="pat-lens-lab">Lens</span>
        <button
          className={`pat-lens-b${lens === "rival" ? " active" : ""}`}
          onClick={() => setLens("rival")}
          type="button"
        >
          By rival
        </button>
        <button
          className={`pat-lens-b${lens === "field" ? " active" : ""}`}
          onClick={() => setLens("field")}
          type="button"
        >
          By technology field
        </button>
        <span className="pat-lens-note">
          {lens === "rival"
            ? "Which rivals hold filings, and in what"
            : `Which fields are fenced, and where ${clientName} still has room to file`}
        </span>
      </div>

      <div className="pat-pane" data-lens="rival" style={{ display: lens === "rival" ? "" : "none" }}>
        {!data.compOrder.length ? (
          /* Honest empty state: an empty compOrder means the pipeline has served no
             competitors, not that a lookup should be attempted and crash. */
          <div className="pat-state" style={{ padding: "24px" }}>
            <div className="ps-ic">⊡</div>
            <div className="ps-t">No competitors indexed yet</div>
            <div className="ps-s">
              The served dataset carries no competitor records, so there are no patent
              portfolios to show. Once the pipeline serves competitors, they appear here.
            </div>
          </div>
        ) : (
        <>
        <div className="mu-list">
          <div className="mu-list-h">
            <span className="eyebrow">Competitors</span>
            <div className="sub">Select to view patent portfolio</div>
            <div className="mu-search">
              <span className="si">⌕</span>
              <input
                onChange={(e) => setCompQuery(e.target.value)}
                placeholder="Search competitor…"
                type="text"
                value={compQuery}
              />
            </div>
          </div>
          <div id="patc-list">
            {compList.length ? (
              compList.map((k) => {
                const pd = ((data.PATENTS || {}).byCompetitor || {})[k];
                return (
                  <div
                    className={`pat-li${cid === k ? " active" : ""}`}
                    key={k}
                    onClick={() => setCid(k)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setCid(k);
                      }
                    }}
                  >
                    <span className="pli-n">{data.competitors[k].name}</span>
                    <span className="pli-c">{pd ? pd.records.length : 0}</span>
                  </div>
                );
              })
            ) : (
              <div className="pat-li-none">No match for “{compQuery.trim()}”</div>
            )}
          </div>
        </div>
        <div className="pat-canvas">
          <div className="pat-head">
            <span className="eyebrow">{`${(data.competitors[cid] || {}).name || cid} · patent portfolio`}</span>
            <span className="pat-sub">Patents filed and granted to this competitor</span>
            {cats.length > 1 ? (
              <select
                className="mu-fsel patc-cat-filter"
                onChange={(e) => setCatFilter(e.target.value)}
                style={{ marginTop: "8px", maxWidth: "280px" }}
                value={catFilter}
              >
                <option value="">
                  All product categories{compRecs.length ? ` (${compRecs.length})` : ""}
                </option>
                {cats.map((c) => (
                  <option key={c} value={c}>
                    {c} ({compRecs.filter((r) => r.techArea === c).length})
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          <HtmlBlock
            html={
              compRes
                ? patCompBody(data, cid, compRes)
                : patLoadingHtml(((data.competitors[cid] || {}).name) || cid || "")
            }
            id="patc-body"
            onMount={applyCatFilter}
          />
        </div>
        </>
        )}
      </div>

      <div className="pat-pane" data-lens="field" style={{ display: lens === "field" ? "" : "none" }}>
        <div className="mu-list">
          <div className="mu-list-h">
            <span className="eyebrow">Technology fields</span>
            <div className="sub">Select to see who is fencing it</div>
            <div className="mu-search">
              <span className="si">⌕</span>
              <input
                onChange={(e) => setTechQuery(e.target.value)}
                placeholder="Search field…"
                type="text"
                value={techQuery}
              />
            </div>
          </div>
          <div id="patt-list">
            {areaList.length ? (
              areaList.map((a) => {
                const td = ((data.PATENTS || {}).byTechnology || {})[a];
                return (
                  <div
                    className={`pat-li${area === a ? " active" : ""}`}
                    key={a}
                    onClick={() => setArea(a)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setArea(a);
                      }
                    }}
                  >
                    <span className="pli-n">{a}</span>
                    <span className="pli-c">{td ? td.records.length : 0}</span>
                  </div>
                );
              })
            ) : (
              <div className="pat-li-none">No match for “{techQuery.trim()}”</div>
            )}
          </div>
        </div>
        <div className="pat-canvas">
          <div className="pat-head">
            <span className="eyebrow">{`${area} · field analysis`}</span>
            <span className="pat-sub">
              Who is fencing this field with patents, and where {clientName} still has room to file
            </span>
          </div>
          <HtmlBlock
            html={techRes ? patTechBody(data, area, techRes) : patLoadingHtml(area)}
            id="patt-body"
          />
        </div>
      </div>
    </div>
  );
}
