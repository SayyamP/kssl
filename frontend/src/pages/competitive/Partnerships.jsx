import { useEffect, useMemo, useRef, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import ScopeChat from "../../components/scopeChat/ScopeChat";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { formatSectorName, formatCompanyName } from "../../lib/profile";

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
  const getSavedPart = () => {
    try {
      const s = localStorage.getItem("kssl_part_state");
      return s ? JSON.parse(s) : {};
    } catch (e) { return {}; }
  };
  const savedPart = getSavedPart();
  /* A saved selection outlives the dataset that produced it: the stored id can be
     from an older export, or the client itself (which this list no longer shows).
     Restore it only if the row is still here, or the drawer renders an id with no
     competitor behind it and throws on the first field it reads. */
  const savedCid =
    savedPart.cid && data.competitors[savedPart.cid] && savedPart.cid !== (data.client?.id || "KSSL")
      ? savedPart.cid
      : null;

  const [cid, setCid] = useState(savedCid);
  const [query, setQuery] = useState("");
  const [hq, setHq] = useState("");
  const [tie, setTie] = useState(savedCid ? savedPart.tie || null : null); // a partner row id, or null for the competitor read
  const [mode, setMode] = useState(savedPart.mode || "syn"); // 'syn' | 'field'
  const [relCardIndex, setRelCardIndex] = useState(null);

  const svgRef = useRef(null);
  const drawerRef = useRef(null);

  useEffect(() => {
    setRelCardIndex(null);
  }, [cid, tie, mode]);

  useEffect(() => {
    if (drawerRef.current) {
      drawerRef.current.scrollTop = 0;
    }
  }, [cid, tie, mode, relCardIndex]);

  useEffect(() => {
    try {
      if (cid) localStorage.setItem("kssl_part_state", JSON.stringify({ cid, tie, mode }));
      else localStorage.removeItem("kssl_part_state");
    } catch (e) {}
  }, [cid, tie, mode]);

  const selCo = cid ? data.competitors[cid] : null;
  const c = selCo ? { ...selCo, id: cid } : null;

  const hqOptions = useMemo(() => {
    const set = new Set();
    data.compOrder.forEach((k) => {
      const co = data.competitors[k];
      if (co && co.hq) set.add(co.hq.trim());
    });
    return [...set].filter(Boolean).sort();
  }, [data]);

  const activeQ = (query || searchQuery || "").trim().toLowerCase();
  const tokens = activeQ.split(/\s+/).filter(Boolean);

  const list = data.compOrder
    .filter((k) => k !== (data.client?.id || "KSSL"))
    .filter((k) => {
      const co = data.competitors[k];
      if (!co) return false;
      const nsh = partners.pgSharedFor(co).length;
      const pNames = (co.partners || []).map((x) => x.name).join(" ");
      const search = `${(co.name || "").toLowerCase()} ${sectorText(co).toLowerCase()} ${(co.hq || "").toLowerCase()} ${pNames.toLowerCase()}${nsh ? " overlap" : ""}`;
      if (tokens.length > 0 && !tokens.every((tok) => search.includes(tok))) return false;
      if (hq && (co.hq || "").toLowerCase() !== hq) return false;
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
  };

  /* Highlighting is a class sweep over the rendered SVG rather than a re-render:
     the graph markup is a static string, and touching classes is cheaper and keeps
     the CSS transitions the original relied on. */
  const applyHighlight = (selectedNodeId, tracedNodeIds) => {
    const svg = svgRef.current;
    if (!svg) return;
    svg.querySelectorAll(".pg-node").forEach((n) => n.classList.remove("sel", "dim", "trace"));
    svg.querySelectorAll(".pg-edge").forEach((e) => e.classList.remove("hl", "dim", "trace"));
    if (selectedNodeId) {
      svg.querySelectorAll(".pg-node").forEach((n) => n.classList.add("dim"));
      svg.querySelectorAll(".pg-edge").forEach((e) => e.classList.add("dim"));
      const node = svg.querySelector(`.pg-node[data-id="${CSS.escape(selectedNodeId)}"]`);
      if (node) {
        node.classList.add("sel");
        node.classList.remove("dim");
      }
      const centre = svg.querySelector(".pg-node.center-root");
      if (centre) centre.classList.remove("dim");
      svg.querySelectorAll(`.pg-edge[data-b="${CSS.escape(selectedNodeId)}"]`).forEach((e) => {
        e.classList.add("hl");
        e.classList.remove("dim");
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
            className="mu-fsel"
            onChange={(e) => setHq(e.target.value)}
            style={{ width: "100%", marginTop: "8px" }}
            value={hq}
          >
            <option value="">All HQ Countries</option>
            {hqOptions.map((ct) => (
              <option key={ct} value={ct.toLowerCase()}>
                {ct}
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
                {sectorText(c) ? ` · ${sectorText(c)}` : ""} · click a node to read a tie
              </span>
            ) : null}
          </div>
        </div>
        <div className="pg-graph-wrap">
          {!c ? (
            <div className="pg-empty">
              <div className="pg-empty-ic">◆</div>
              <div className="pg-empty-t">Select a competitor</div>
              <div className="pg-empty-s">Choose from the list to map their alliance network</div>
            </div>
          ) : null}
          <svg
            id="pg-svg"
            preserveAspectRatio="xMidYMid meet"
            ref={svgRef}
            viewBox="0 0 900 500"
            dangerouslySetInnerHTML={{ __html: c ? partners.graphSvg(c) : "" }}
            onClick={(e) => {
              const g = e.target.closest(".pg-node");
              if (!g) return;
              if (g.classList.contains("comp") || g.classList.contains("center-root")) {
                setTie(null);
                setMode("syn");
              } else {
                // the node stands for a company; open its strongest row
                const nodeId = g.getAttribute("data-id");
                selectPartner(nodeId);
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
              <span className="nd" style={{ background: "#ffffff", boxShadow: "0 0 6px #ffffff" }} />
              {c ? c.name : "Current Company"} (White Node)
            </span>
            <span className="lg">
              <span className="nd" style={{ background: "#22c55e", boxShadow: "0 0 6px #22c55e" }} />
              Direct Partner (Green Node)
            </span>
            <span className="lg">
              <span className="nd" style={{ background: "#ef4444", boxShadow: "0 0 6px #ef4444" }} />
              Overlapping Partner (Red Node)
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
            {/* moved here from under the graph: the canvas states the relation, the side
                states what it means. Renders nothing when this rival shares no partner. */}
            <HtmlBlock
              className="pg-ov-side"
              html={c ? partners.overlapDefsHtml(c, cid, clientName) : ""}
              id="pg-ov-side"
            />
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
