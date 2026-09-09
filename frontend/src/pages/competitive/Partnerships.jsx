import { useEffect, useMemo, useRef, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import ScopeChat from "../../components/scopeChat/ScopeChat";
import { useAppState, useHeaderReport } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { formatSectorName, formatCompanyName } from "../../lib/profile";
import { companyCountries, facetOptionsByName } from "../../lib/countryFacet";

/* `sector` is escaped at write time ("Defence &amp; Aerospace") and is formatted consistently here. */
const sectorText = (co) => formatSectorName(co && co.sector);

/* Competitor-centric relationship graph. Three panes: the rival list, the alliance
   network with the shared-partner read beneath it, and a drawer that switches between
   the competitor-level synthesis, a single tie, and the field-level read.

   The graph is raw SVG built by lib/partners — one node per partner COMPANY, each on
   its own angle, so no two lines coincide and no line runs through another node. */
export default function Partnerships() {
  const { data, partners } = useData();
  const { setScope, searchQuery } = useAppState();
  const clientName = (data.client && (data.client.short || data.client.name)) || "KSSL";
  const [cid, setCid] = useState(null);
  const [query, setQuery] = useState("");
  const [hq, setHq] = useState("");
  const [tie, setTie] = useState(null); // a partner row id, or null for the competitor read
  const [mode, setMode] = useState("syn"); // 'syn' | 'field'
  const [relCardIndex, setRelCardIndex] = useState(null);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [panCenter, setPanCenter] = useState(null);

  const svgRef = useRef(null);
  const drawerRef = useRef(null);

  const viewBoxStr = useMemo(() => {
    const baseW = 960;
    const baseH = 540;
    const w = baseW / zoomLevel;
    const h = baseH / zoomLevel;
    const cx = panCenter ? panCenter.x : baseW / 2;
    const cy = panCenter ? panCenter.y : baseH / 2;
    const x = Math.max(0, Math.min(baseW - w, cx - w / 2));
    const y = Math.max(0, Math.min(baseH - h, cy - h / 2));
    return `${x.toFixed(1)} ${y.toFixed(1)} ${w.toFixed(1)} ${h.toFixed(1)}`;
  }, [zoomLevel, panCenter]);

  useEffect(() => {
    setRelCardIndex(null);
  }, [cid, tie, mode]);

  useEffect(() => {
    if (drawerRef.current) {
      drawerRef.current.scrollTop = 0;
    }
  }, [cid, tie, mode, relCardIndex]);

  const selCo = cid ? data.competitors[cid] : null;
  const c = selCo ? { ...selCo, id: cid } : null;

  /* The rival ids this list draws from -- the same population the options describe. */
  const rivalIds = useMemo(
    () => data.compOrder.filter((k) => k !== (data.client?.id || "KSSL") && data.competitors[k]),
    [data],
  );
  /* This select was headed "All HQ Countries" and offered the raw hq strings --
     "Arlington, Virginia", "Falls Church, Virginia, USA" -- one option per spelling,
     none of them a country. Same expression as the Products and Competitor sidebars
     now, and the "All" label prints the list's own length. */
  const hqOptions = useMemo(
    () => facetOptionsByName(rivalIds, (k) => companyCountries(data, k)),
    [data, rivalIds],
  );
  /* What the header's Copy / Export / Print act on: the selected competitor's mapped
     partners, and the open tie in full. Memoised on selCo (the served record), not on
     `c`, which is re-spread every render. */
  const report = useMemo(() => {
    const rel = data.REL_LABEL || {};
    if (!selCo) {
      /* nothing selected: the roster the rail lists, each with its mapped-partner count */
      const clientId = (data.client && data.client.id) || "KSSL";
      const roster = (data.compOrder || [])
        .filter((k) => k !== clientId && data.competitors[k])
        .map((k) => {
          const co = data.competitors[k];
          const n = (co.partners || []).length;
          return { cid: k, name: co.name, partners: n, hq: co.hq || null };
        });
      return {
        title: "Partnerships",
        subtitle: `${roster.length} competitors · none selected`,
        sections: [
          {
            h: "Competitors and mapped partnerships",
            rows: roster.map((r) => [r.name, `${r.partners} partnership${r.partners === 1 ? "" : "s"}${r.hq ? ` · ${r.hq}` : ""}`]),
          },
        ],
        payload: { competitors: roster },
      };
    }
    const partners = selCo.partners || [];
    const tp = tie ? partners.find((x) => x.id === tie) : null;
    const nd = (v) => (v && v !== "n/d" ? String(v) : "—");
    return {
      title: selCo.name,
      subtitle: `${partners.length} mapped partnership${partners.length === 1 ? "" : "s"}${tp ? ` · ${tp.label}` : ""}`,
      sections: [
        tp
          ? {
              h: `Tie: ${selCo.name} and ${tp.label}`,
              rows: [
                ["Kind", nd(tp.kind)],
                // ptype FIRST. REL_LABEL is five legacy keys in serving.ui_config, so
                // the ten types the pipeline now writes fell through to `nd(tp.rel)`
                // and this report printed the raw key -- "manufacturing", "rnd".
                ["Relationship", nd(tp.ptype) !== "—" ? tp.ptype : (rel[tp.rel] || nd(tp.rel))],
                ["Status", tp.status === "ended"
                  ? `ended${tp.ended ? ` (${tp.ended})` : ""}`
                  : nd(tp.status)],
                ["Source confidence", nd(tp.confidence)],
                ["Country", nd(tp.country)],
                ["Date", nd(tp.date)],
                ["Deal", nd(tp.deal)],
                tp.note ? ["Note", tp.note] : null,
                tp.insight ? ["Insight", tp.insight] : null,
                tp.mean ? ["Meaning", tp.mean] : null,
              ].filter(Boolean),
            }
          : null,
        {
          h: "Mapped partners",
          rows: partners.map((x) => [
            x.label || x.name || x.id,
            [x.kind, x.ptype || rel[x.rel] || x.rel, x.country,
             x.status === "ended" ? "ENDED" : null].filter(Boolean).join(" · "),
          ]),
        },
        selCo.threat ? { h: "Threat read", rows: [selCo.threat] } : null,
        selCo.assess ? { h: "Assessment", rows: [selCo.assess] } : null,
      ].filter(Boolean),
      payload: {
        cid,
        name: selCo.name,
        partners,
        tie: tp || null,
        threat: selCo.threat || null,
        assessment: selCo.assess || null,
      },
    };
  }, [selCo, cid, tie, data]);
  useHeaderReport(report);

  const activeQ = (query || searchQuery || "").trim().toLowerCase();
  const tokens = activeQ.split(/\s+/).filter(Boolean);

  const list = data.compOrder
    .filter((k) => k !== (data.client?.id || "KSSL"))
    .filter((k) => {
      const co = data.competitors[k];
      if (!co) return false;
      const nsh = partners.pgSharedFor(co).length;
      const pNames = (co.partners || []).map((x) => x.name || x.label || "").join(" ");
      const search = `${(co.name || "").toLowerCase()} ${sectorText(co).toLowerCase()} ${(co.hq || "").toLowerCase()} ${pNames.toLowerCase()}${nsh ? " overlap" : ""}`;
      if (tokens.length > 0 && !tokens.every((tok) => search.includes(tok))) return false;
      if (hq && !companyCountries(data, k).includes(hq)) return false;
      return true;
    });


  const selectCompetitor = (nextCid) => {
    const co = data.competitors[nextCid];
    if (!co) return;
    setCid(nextCid);
    setTie(null);
    setScope("partner", { type: "partner", comp: { ...co, id: nextCid }, partner: null }, {
      pillar: "Competitive",
      view: "Partnerships",
      selection: co.name,
    });
  };

  const selectPartner = (pid) => {
    if (!c) return;
    const p = (c.partners || []).find((x) => x.id === pid);
    if (!p) return;
    setTie(pid);
    setScope("partner", { type: "partner", comp: c, partner: p }, {
      pillar: "Competitive",
      view: "Partnerships",
      selection: `${c.name} ↔ ${p.label}`,
    });

    // Auto-zoom to selected cluster
    const svg = svgRef.current;
    if (svg) {
      const nodeEl = svg.querySelector(`.pg-node[data-id="${CSS.escape(pid)}"]`);
      if (nodeEl) {
        const circle = nodeEl.querySelector("circle:not([fill*='url(#pg'])") || nodeEl.querySelector("circle");
        if (circle) {
          const nx = parseFloat(circle.getAttribute("cx") || "480");
          const ny = parseFloat(circle.getAttribute("cy") || "270");
          setPanCenter({ x: nx, y: ny });
          setZoomLevel(1.55);
        }
      }
    }
  };

  const deselectPartner = () => {
    setTie(null);
    setMode("syn");
    setPanCenter(null);
    setZoomLevel(1);
  };

  /* Highcharts network graph feature: clicking any bubble isolates that bubble and its
     connected network ties, while smoothly dimming all remaining unrelated bubbles.
     Clicking background or the selected bubble clears dimming back to full brightness. */
  const applyHighlight = (selectedNodeId, tracedNodeIds) => {
    const svg = svgRef.current;
    if (!svg) return;
    svg.querySelectorAll(".pg-node").forEach((n) => n.classList.remove("sel", "dim", "trace", "connected"));
    svg.querySelectorAll(".pg-edge").forEach((e) => e.classList.remove("hl", "dim", "trace"));

    if (selectedNodeId) {
      // Dim all nodes and edges by default
      svg.querySelectorAll(".pg-node").forEach((n) => n.classList.add("dim"));
      svg.querySelectorAll(".pg-edge").forEach((e) => e.classList.add("dim"));

      // 1. Keep selected node bright with glowing highlight
      const node = svg.querySelector(`.pg-node[data-id="${CSS.escape(selectedNodeId)}"]`);
      if (node) {
        node.classList.add("sel");
        node.classList.remove("dim");
      }

      // 2. Keep center root OEM node visible
      const centre = svg.querySelector(".pg-node.center-root");
      if (centre) centre.classList.remove("dim");

      // 3. Highlight connected edges and keep connected neighbor nodes bright
      svg.querySelectorAll(
        `.pg-edge[data-a="${CSS.escape(selectedNodeId)}"], .pg-edge[data-b="${CSS.escape(selectedNodeId)}"], .pg-edge[data-parent="${CSS.escape(selectedNodeId)}"]`
      ).forEach((e) => {
        e.classList.add("hl");
        e.classList.remove("dim");

        const a = e.getAttribute("data-a");
        const b = e.getAttribute("data-b");
        const otherId = a === selectedNodeId ? b : a;
        if (otherId) {
          const otherNode = svg.querySelector(`.pg-node[data-id="${CSS.escape(otherId)}"]`);
          if (otherNode) {
            otherNode.classList.remove("dim");
            otherNode.classList.add("connected");
          }
        }
      });

      // 4. Keep connected satellite nodes bright
      svg.querySelectorAll(`.pg-node[data-parent="${CSS.escape(selectedNodeId)}"]`).forEach((sat) => {
        sat.classList.remove("dim");
        sat.classList.add("connected");
      });
    }

    (tracedNodeIds || []).forEach((id) => {
      const node = svg.querySelector(`.pg-node[data-id="${CSS.escape(id)}"]`);
      if (node) node.classList.add("trace");
      svg.querySelectorAll(`.pg-edge[data-b="${CSS.escape(id)}"]`).forEach((e) =>
        e.classList.add("trace"),
      );
    });
  };

  useEffect(() => {
    if (!c) return;
    applyHighlight(tie ? partners.pgNodeIdFor(c, tie) : null, null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tie, cid]);

  const drawerBody = () => {
    if (!c) return "";
    if (tie) {
      return partners.tieHtml(c, cid, tie, clientName, relCardIndex);
    }
    return partners.allPartnersRosterHtml(c, cid, clientName);
  };

  const drawerHeadText = () => {
    if (tie) return "Relationship detail";
    return c ? `${c.name} · Mapped Partners` : "Mapped Partners";
  };

  const nNode = c ? partners.pgNodes(c).length : 0;
  const nRow = c && c.partners ? c.partners.length : 0;

  return (
    <div
      className={`pos-view v-partnerships ${c ? "has-sel" : "no-sel"}`}
      style={{
        position: "relative",
        gridTemplateColumns: c ? "290px 1fr 380px" : "460px 1fr 0px",
        transition: "grid-template-columns 0.28s cubic-bezier(0.22, 0.61, 0.36, 1)",
      }}
    >
      {/* LEFT: competitor list */}
      <div className="mu-list">
        <div className="mu-list-h">
          <span className="eyebrow">Competitors</span>
          <div className="sub">Select to analyse</div>
          <div className="mu-search">
            <span className="si">⌕</span>
            <input
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search competitor…"
              type="text"
              value={query}
            />
          </div>
          <select
            aria-label="Filter competitors by country"
            className="mu-fsel"
            onChange={(e) => setHq(e.target.value)}
            style={{ width: "100%", marginTop: "8px" }}
            value={hq}
          >
            <option value="">All countries ({hqOptions.length})</option>
            {hqOptions.map((o) => (
              <option key={o.v} value={o.v}>
                {o.v} ({o.n})
              </option>
            ))}
          </select>
               <div id="patc-list">
          {list.map((k) => {
            const co = data.competitors[k];
            const nPartners = (co.partners || []).length;
            return (
              <div
                className={`pat-li${cid === k ? " active" : ""}`}
                key={k}
                onClick={() => selectCompetitor(k)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    selectCompetitor(k);
                  }
                }}
              >
                <span className="pli-n" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span className={`wdot ${co.dir || "watch"}`} />
                  {co.name}
                </span>
                <span className="pli-c">{nPartners}</span>
              </div>
            );
          })}
          {/* The Competitor and Products sidebars say so when nothing matches; this
              one rendered an empty column, which reads as a list that failed to load. */}
          {!list.length ? (
            <div className="cp-empty">
              {activeQ ? <>no competitor matches “{activeQ}”</> : "no competitor matches this filter"}
            </div>
          ) : null}
        </div>        </div>
      </div>

      {/* CENTER: thesis line + interactive graph + shared-partner read */}
      <div className="pg-canvas">
        <div className="pg-instrument-head">
          <div className="pg-i-title">{c ? `${c.name} · alliance network` : "Alliance network"}</div>
          <div className="pg-i-thesis">
            {c ? (
              <span style={{ color: "var(--d-txt-3)" }}>
                {nNode} partner{nNode === 1 ? "" : "s"}
                {nRow !== nNode
                  ? ` · ${nRow} tracked relationships`
                  : ` · ${nRow} tracked relationship${nRow === 1 ? "" : "s"}`}
                {sectorText(c) ? ` · ${sectorText(c)}` : ""}
                {/* an invitation to click a node is only honest when there is one */}
                {nNode ? " · click a node to read a tie" : " · no partnership on record for this competitor"}
              </span>
            ) : null}
          </div>
        </div>
        <div className="pg-graph-wrap" style={{ position: "relative" }}>
          {!c ? (
            <div className="pg-empty">
              <div className="pg-empty-ic">◆</div>
              <div className="pg-empty-t">Select a competitor</div>
              <div className="pg-empty-s">Choose from the list to map their alliance network</div>
            </div>
          ) : (
            <div className="pg-canvas-toolbar">
              {/* A Network / Heatmap toggle stood here. `viewMode` was read by nothing
                  but the two buttons' own active class: "Heatmap" lit itself up and the
                  canvas stayed byte-for-byte the same, measured 2026-09-05. No heatmap
                  exists in this build; a control that promises one and delivers nothing
                  is worse than no control. If a heatmap is built, the toggle returns
                  with it. */}
              <div className="pg-zoom-box">
                <button
                  type="button"
                  className="pg-tb-btn"
                  onClick={() => setZoomLevel((z) => Math.min(1.6, Number((z + 0.15).toFixed(2))))}
                  title="Zoom In"
                >
                  +
                </button>
                <button
                  type="button"
                  className="pg-tb-btn"
                  onClick={() => setZoomLevel((z) => Math.max(0.7, Number((z - 0.15).toFixed(2))))}
                  title="Zoom Out"
                >
                  -
                </button>
                <button
                  type="button"
                  className="pg-tb-btn"
                  onClick={deselectPartner}
                  title="Reset View"
                >
                  ⟲
                </button>
              </div>
            </div>
          )}
          <svg
            id="pg-svg"
            preserveAspectRatio="xMidYMid meet"
            ref={svgRef}
            viewBox={viewBoxStr}
            dangerouslySetInnerHTML={{ __html: c ? partners.graphSvg(c) : "" }}
            onClick={(e) => {
              const g = e.target.closest(".pg-node");
              if (!g) {
                // Clicked on empty canvas -> clear dimming and auto-zoom back to normal view
                deselectPartner();
                return;
              }
              if (g.classList.contains("comp") || g.classList.contains("center-root")) {
                // Clicked central root OEM -> reset
                deselectPartner();
              } else {
                const nodeId = g.getAttribute("data-id") || g.getAttribute("data-parent");
                if (!nodeId) return;
                if (tie === nodeId) {
                  // Toggle off when clicking already selected bubble -> un-dim all & zoom out
                  deselectPartner();
                } else {
                  selectPartner(nodeId);
                }
              }
            }}
          />
        </div>
        {/* Shared-partner read, RELATIONSHIPS ONLY: who overlaps, on what terms, and who
            else they carry. What that overlap costs the client is interpretation, and it
            lives in the drawer on the right — see overlapDefsHtml. */}
        <HtmlBlock
          className="pg-overlap"
          handlers={{ ".pg-ov-tie": (el) => selectPartner(el.getAttribute("data-pid")) }}
          html={c ? partners.overlapHtml(c, cid, true, clientName) : ""}
          id="pg-overlap"
        />
        <div className="pg-graph-foot">
          <div className="pg-legend">
            <span className="lg">
              <span className="nd" style={{ background: "#0f6f7d" }} />
              {c ? c.name : "Current Company"} (Beacon Core)
            </span>
            <span className="lg">
              <span className="nd" style={{ background: "#ab7016" }} />
              Foreign OEM / International (Amber)
            </span>
            <span className="lg">
              <span className="nd" style={{ background: "#8340b8" }} />
              Defence Tech & Systems (Purple)
            </span>
            <span className="lg">
              <span className="nd" style={{ background: "#0a8f70" }} />
              Domestic & Strategic (Teal)
            </span>
            <span className="lg">
              <span className="nd" style={{ background: "#8c2f2f" }} />
              Overlapping Partner (Red)
            </span>
          </div>
        </div>
      </div>


      {/* RIGHT: reactive intelligence drawer */}
      <div className={`pg-drawer${cid ? " open" : ""}`} id="pg-drawer">
        <div style={{ display: "flex", flex: 1, flexDirection: "column", height: "100%", overflow: "hidden" }}>
          <div className="pg-drawer-scroll" ref={drawerRef} style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", paddingBottom: "24px" }}>
            <div style={{ position: "absolute", top: "12px", right: "14px", display: "flex", alignItems: "center", gap: "6px", zIndex: 30, paddingBottom: "10px" }}>
              {(tie || mode === "field") && (
                <button
                  type="button"
                  className="col-close"
                  onClick={() => {
                    setTie(null);
                    setMode("syn");
                  }}
                  title="Back"
                  style={{
                    position: "static",
                    width: "auto",
                    height: "26px",
                    padding: "0 10px",
                    fontSize: "11.5px",
                    fontWeight: "600",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                    marginBottom: "8px",
                  }}
                >
                  ‹ Back
                </button>
              )}
              <button
                aria-label="Close"
                className="col-close"
                onClick={() => setCid(null)}
                title="Close"
                type="button"
                style={{ position: "static", height: "26px", width: "26px", marginBottom: "8px" }}
              >
                ✕
              </button>
            </div>
            <div className="pg-drawer-head" style={{ paddingRight: "110px", paddingBottom: "16px" }} dangerouslySetInnerHTML={{ __html: drawerHeadText() }} />
            <HtmlBlock
              className="pg-drawer-body"
              handlers={{
                "[data-back]": () => {
                  setTie(null);
                  setMode("syn");
                },
                "[data-fieldread]": () => setMode("field"),
                "[data-relcard]": (el) => {
                  const ix = Number(el.getAttribute("data-relcard"));
                  setRelCardIndex(ix);
                },
                "[data-backrelcards]": () => {
                  setRelCardIndex(null);
                },
                ".pg-partner-roster-card[data-pid]": (el) => selectPartner(el.getAttribute("data-pid")),
                ".pg-ov-tie[data-pid]": (el) => selectPartner(el.getAttribute("data-pid")),
                ".sib-row[data-pid]": (el) => selectPartner(el.getAttribute("data-pid")),
                ".pg-rel[data-pid]": (el) => selectPartner(el.getAttribute("data-pid")),
                "[data-vulnclick]": (el) => {
                  const ix = Number(el.getAttribute("data-vulnclick"));
                  const body = el.nextElementSibling;
                  if (body) body.classList.toggle("open");
                  el.closest(".pg-drawer-body")
                    ?.querySelectorAll(".syn-vuln")
                    .forEach((v) => v.classList.remove("traceactive"));
                  el.closest(".syn-vuln")?.classList.add("traceactive");
                  applyHighlight(null, partners.traceNodeIds(c, cid, ix));
                },
              }}
              html={drawerBody()}
              id="pg-r-body"
            />
            {/* REMOVED ON REQUEST: the "What an overlapping <kind> partner costs KSSL"
                explainer that used to sit under the drawer. It was generic interpretation
                keyed off the overlap kind -- the same two paragraphs for every rival that
                shared a partner of that kind -- and it said nothing the drawer above does
                not already state about THIS rival. partners.overlapDefsHtml and OV_DEF are
                left intact, so restoring it is putting this element back. */}
          </div>
        </div>
      </div>

      {/* FULL-SCREEN OVERLAY COVERING GRAPH AND DRAWER WHEN A RELATIONSHIP CARD IS OPENED */}
      {relCardIndex !== null && tie && c && (
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: "290px",
            right: 0,
            zIndex: 200,
            background: "#ffffff",
            overflowY: "auto",
            padding: "24px",
          }}
        >
          <HtmlBlock
            handlers={{
              "[data-backrelcards]": () => setRelCardIndex(null),
            }}
            html={partners.tieHtml(c, cid, tie, clientName, relCardIndex)}
          />
        </div>
      )}
    </div>
  );
}
