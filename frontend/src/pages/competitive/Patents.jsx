import { useEffect, useMemo, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import { useData } from "../../state/DataProvider";
import {
  searchPatents,
  patCompBody,
  patTechBody,
  patLoadingHtml,
} from "../../lib/patents";

/* Both patent lenses live in the Competitive pillar. The field lens used to sit
   under Technology; it is the same patent set read a different way, and a rival
   fencing a field is competitive intelligence — so one view with a lens toggle. */
export default function Patents() {
  const { data } = useData();
  const clientName = (data.client && (data.client.short || data.client.name)) || "KSSL";
  const getSavedPat = () => {
    try {
      const s = localStorage.getItem("kssl_pat_state");
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

  const areas = useMemo(() => {
    // fall back to the tracked technology areas when no patent area has filings yet,
    // so the view lists real fields (each with its own empty state) instead of nothing
    const a = (data.PATENTS && data.PATENTS.techAreas) || [];
    return a.length ? a : data.techCats.map((c) => c.name);
  }, [data]);
  const [area, setArea] = useState(savedPat.area || areas[0]);
  const [techRes, setTechRes] = useState(null);

  useEffect(() => {
    try {
      localStorage.setItem("kssl_pat_state", JSON.stringify({ lens, cid, area, catFilter }));
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

  const compList = data.compOrder.filter(
    (k) =>
      !compQuery.trim() ||
      data.competitors[k].name.toLowerCase().includes(compQuery.trim().toLowerCase()),
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
            <span className="eyebrow">
              Competitors <span className="srcbadge" style={{ marginLeft: "6px" }}>Sourced</span>
            </span>
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
            <span className="eyebrow">
              Technology fields <span className="srcbadge" style={{ marginLeft: "6px" }}>Sourced</span>
            </span>
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
