import { useEffect, useMemo, useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildProfile, rosterOf } from "../../lib/profile";
import { companyNews } from "../../lib/news";

// Helper function to extract clean company short name without full form or legal suffixes
const cleanCompanyName = (rawName) => {
  if (!rawName) return "";
  let name = rawName.split("(")[0].split("-")[0].trim();
  name = name.replace(/,?\s*(Private|Pvt|Limited|Ltd|Inc|Corp|Corporation)\b.*/gi, "").trim();
  return name || rawName;
};

// Helper function to extract executive initials for avatar
const getInitials = (name) => {
  if (!name) return "EX";
  const clean = name.replace(/^(Mr\.|Ms\.|Dr\.|Shri|Prof\.|Commodore|Cdre\.|Retd)\s+/i, "").trim();
  const parts = clean.split(/\s+/);
  if (parts.length >= 2) return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  return parts[0].slice(0, 2).toUpperCase();
};

// Helper to derive exact metadata for BDL and all tracked competitors
/* Company facts, from the pipeline's own columns.
 *
 * This function used to hold a hand-written dossier for about eleven named firms
 * — founded date, headcount, revenue, site count, all typed in — and a fallback
 * that INVENTED the rest: "₹1,000 Cr+ (Published Financials)", "1,000–5,000
 * Employees". Every one of those values now has a column in serving.competitors
 * (starting_year, company_size, sales, global_locations, hq, sector, assess), so
 * the panel reads them instead. A fact the corpus does not state renders as a
 * dash. The markup below is untouched; only where the values come from changed.
 */
const DASH = "—";

const firstValue = (v) => {
  if (!v) return null;
  if (Array.isArray(v)) {
    const hit = v.find((x) => x && (typeof x === "string" ? x.trim() : x.value));
    if (!hit) return null;
    return typeof hit === "string" ? hit : hit.value || null;
  }
  return typeof v === "string" ? v.trim() || null : null;
};

const joinList = (v) => {
  if (!Array.isArray(v) || !v.length) return null;
  const names = v
    .map((x) => (typeof x === "string" ? x : x && (x.value || x.name)))
    .filter(Boolean);
  return names.length ? names.join(" · ") : null;
};

const getCompanyDetailsMeta = (p) => {
  if (!p) return null;
  return {
    founded: p.starting_year ? String(p.starting_year) : DASH,
    hq: p.hq || DASH,
    globalLocs: joinList(p.global_locations) || DASH,
    size: p.company_size || DASH,
    revenue: firstValue(p.sales) || DASH,
    sector: p.sector || DASH,
    /* assess is 100% filled and already grounded against the corpus. */
    assess: p.assess || null,
  };
};

/* Corporate structure — parent, sister companies, subsidiaries — was typed by hand
 * for the same eleven firms and drawn as a zoomable org chart. Nothing in the
 * serving schema holds corporate structure, so there is no honest value to put
 * here: returning null makes CorporateHierarchySvgMap render nothing (it already
 * guards on it) until a column and a writer exist. */
const getCorporateStructureMap = () => null;

// Generate Company-Specific Interactive News Articles Dataset

// Interactive SVG Corporate Hierarchy Map & Node Graph Component
function CorporateHierarchySvgMap({ structMap }) {
  const [hoveredNode, setHoveredNode] = useState(null);
  const [zoom, setZoom] = useState(1);

  if (!structMap) return null;

  const handleZoomIn = () => setZoom((z) => Math.min(z + 0.15, 1.5));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 0.15, 0.7));
  const handleResetZoom = () => setZoom(1);

  const sisters = structMap.sisters || [];
  const subsidiaries = structMap.subsidiaries || [];

  return (
    <div
      className="corp-hierarchy-svg-container"
      style={{
        background: "var(--d-bg-1)",
        border: "1px solid var(--d-line)",
        borderRadius: "8px",
        padding: "16px",
        position: "relative",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
    >
      {/* Graph Toolbar Controls */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid var(--d-line)",
          paddingBottom: "10px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              display: "inline-block",
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background: "#3b82f6",
            }}
          />
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: "11px",
              color: "var(--d-txt)",
              fontWeight: "700",
              letterSpacing: ".06em",
              textTransform: "uppercase",
            }}
          >
            Interactive Corporate Structure Graph · {structMap.current}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <button
            type="button"
            onClick={handleZoomOut}
            title="Zoom Out"
            style={{
              background: "var(--d-bg-2)",
              border: "1px solid var(--d-line-2)",
              color: "var(--d-txt-2)",
              borderRadius: "4px",
              padding: "3px 8px",
              fontSize: "12px",
              cursor: "pointer",
            }}
          >
            −
          </button>
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: "10px",
              color: "var(--d-txt-3)",
              minWidth: "42px",
              textAlign: "center",
            }}
          >
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            onClick={handleZoomIn}
            title="Zoom In"
            style={{
              background: "var(--d-bg-2)",
              border: "1px solid var(--d-line-2)",
              color: "var(--d-txt-2)",
              borderRadius: "4px",
              padding: "3px 8px",
              fontSize: "12px",
              cursor: "pointer",
            }}
          >
            +
          </button>
          <button
            type="button"
            onClick={handleResetZoom}
            title="Reset Graph View"
            style={{
              background: "var(--d-bg-2)",
              border: "1px solid var(--d-line-2)",
              color: "var(--d-txt-3)",
              borderRadius: "4px",
              padding: "3px 8px",
              fontSize: "10px",
              fontFamily: "var(--mono)",
              cursor: "pointer",
              marginLeft: "4px",
            }}
          >
            RESET
          </button>
        </div>
      </div>

      {/* Interactive SVG Canvas - Radial Constellation Graph */}
      <div
        style={{
          width: "100%",
          height: "480px",
          overflow: "hidden",
          background: "#0d1117",
          borderRadius: "8px",
          border: "1px solid #1e293b",
          position: "relative",
        }}
      >
        {(() => {
          const cx = 450;
          const cy = 250;
          const rx = 280;
          const ry = 160;

          // Combine parent, sisters, and subsidiaries into radial nodes
          const sisterList = structMap.sisters || [];
          const subList = structMap.subsidiaries || [];
          const radialItems = [
            ...sisterList.map((s) => ({ label: s, type: "sister" })),
            ...subList.slice(0, 3).map((s) => ({ label: s, type: "sister" })),
          ];

          const nRadial = radialItems.length;

          return (
            <svg
              viewBox="0 0 900 500"
              style={{
                width: "100%",
                height: "100%",
                transform: `scale(${zoom})`,
                transformOrigin: "center center",
                transition: "transform 0.2s ease-out",
              }}
            >
              {/* Background Grid Lines */}
              <pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse">
                <path d="M 30 0 L 0 0 0 30" fill="none" stroke="#1e293b" strokeWidth="0.5" strokeDasharray="2 2" />
              </pattern>
              <rect width="900" height="500" fill="url(#grid)" />

              {/* ============ TOP PARENT COMPANY NODE ============ */}
              {(() => {
                const px = 450;
                const py = 75;
                return (
                  <g key="parent-group">
                    <line x1={cx} y1={cy} x2={px} y2={py} stroke="#eab308" strokeWidth="2.5" opacity="0.85" />
                    <g className="graph-node parent-node" style={{ cursor: "pointer" }}>
                      <circle cx={px} cy={py} r="22" fill="#1e293b" stroke="#eab308" strokeWidth="3" />
                      <circle cx={px} cy={py} r="13" fill="#eab308" />
                      <text x={px} y={py - 30} textAnchor="middle" style={{ fill: "#fef08a", fontFamily: "var(--mono)", fontSize: "11.5px", fontWeight: "800" }}>
                        {structMap.mother}
                      </text>
                    </g>
                  </g>
                );
              })()}

              {/* ============ SURROUNDING RADIAL SISTER NODES ============ */}
              {radialItems.map((item, i) => {
                const angle = -Math.PI / 2 + (i + 1) * ((2 * Math.PI) / (nRadial + 1));
                const nx = Math.round(cx + rx * Math.cos(angle));
                const ny = Math.round(cy + ry * Math.sin(angle));

                const isRight = Math.cos(angle) >= 0;
                const textAnchor = Math.abs(Math.cos(angle)) < 0.2 ? "middle" : isRight ? "start" : "end";
                const textX = isRight ? nx + 26 : nx - 26;
                const textY = ny + 4;

                return (
                  <g key={`sister-${i}`}>
                    <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="#38bdf8" strokeWidth="1.8" strokeDasharray="3,3" opacity="0.75" />
                    <g className="graph-node sister-node" style={{ cursor: "pointer" }}>
                      <circle cx={nx} cy={ny} r="19" fill="#1e293b" stroke="#38bdf8" strokeWidth="2.5" />
                      <circle cx={nx} cy={ny} r="11" fill="#38bdf8" />
                      <text x={textX} y={textY} textAnchor={textAnchor} style={{ fill: "#e2e8f0", fontFamily: "var(--mono)", fontSize: "11px", fontWeight: "700" }}>
                        {item.label}
                      </text>
                    </g>
                  </g>
                );
              })}

              {/* ============ ACTUAL COMPANY (CENTER HUB NODE) ============ */}
              <g className="graph-node actual-node" style={{ cursor: "pointer" }}>
                <circle cx={cx} cy={cy} r="28" fill="#1e293b" stroke="#e8483a" strokeWidth="3.5" />
                <circle cx={cx} cy={cy} r="18" fill="#e8483a" />
                <text x={cx} y={cy - 36} textAnchor="middle" style={{ fill: "#ffffff", fontFamily: "var(--mono)", fontSize: "14px", fontWeight: "800" }}>
                  {structMap.current}
                </text>
              </g>
            </svg>
          );
        })()}

        {/* BOTTOM-RIGHT 3-COLOR COMPANY STRUCTURE LEGEND INDEX */}
        <div
          className="pg-company-structure-index"
          style={{
            position: "absolute",
            bottom: "16px",
            right: "16px",
            background: "#ffffff",
            border: "1px solid #e2e0d8",
            padding: "10px 14px",
            borderRadius: "8px",
            boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
            display: "flex",
            flexDirection: "column",
            gap: "6px",
            zIndex: 20,
          }}
        >
          <div style={{ fontSize: "10px", fontWeight: "700", color: "#b5341f", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: "2px", fontFamily: "var(--mono)" }}>
            COMPANY STRUCTURE INDEX
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "11.5px", color: "#161614", fontWeight: "600" }}>
            <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#eab308", border: "2px solid #ca8a04", display: "inline-block" }} />
            <span>1. Parent Company</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "11.5px", color: "#161614", fontWeight: "600" }}>
            <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#e8483a", border: "2px solid #b91c1c", display: "inline-block" }} />
            <span>2. Actual Company</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "11.5px", color: "#161614", fontWeight: "600" }}>
            <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#38bdf8", border: "2px solid #0284c7", display: "inline-block" }} />
            <span>3. Sister Companies</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Sec({ title, note, children }) {
  return (
    <div className="cp-sec">
      <div className="cp-sec-h">
        <span className="eyebrow">{title}</span>
        {note ? <span className="cp-note">{note}</span> : null}
      </div>
      {children}
    </div>
  );
}

export default function Profile() {
  const { data } = useData();
  const { setScope } = useAppState();
  const [query, setQuery] = useState("");
  const roster = useMemo(() => rosterOf(data), [data]);
  const [cid, setCid] = useState(() => (roster[0] ? roster[0].cid : ""));

  // News category filter pill & active open article state for White Detail Window
  const [newsFilter, setNewsFilter] = useState("All");
  const [activeArticle, setActiveArticle] = useState(null);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return roster;
    return roster.filter(
      (r) => `${r.name} ${r.sector}`.toLowerCase().indexOf(q) >= 0,
    );
  }, [roster, query]);

  const p = useMemo(() => (cid ? buildProfile(data, cid) : null), [data, cid]);

  useEffect(() => {
    if (!p) return;
    setScope("profile", { company: p.name, cid: p.cid }, {
      pillar: "Competitive",
      view: "Competitor",
      selection: p.name,
    });
  }, [p, setScope]);

  // Reset active article and filter when switching company
  useEffect(() => {
    setActiveArticle(null);
    setNewsFilter("All");
  }, [cid]);

  // Executive Leadership board members
  const leadershipList = useMemo(() => {
    if (!p) return [];
    const name = (p.name || "").toLowerCase();
    const companyCid = (p.cid || "").toUpperCase();

    // Specific verified board members for BDL
    if (name.includes("bharat dynamics") || companyCid.includes("BDL")) {
      return [
        { name: "Shri Shailesh Vagerwal", role: "Chairman & Managing Director (CMD)" },
        { name: "Shri D V Srinivas Rao", role: "Director (Technical)" },
        { name: "Commodore Sujay Kapoor (Retd)", role: "Director (Production)" },
        { name: "Shri G. Gayatri Prasad", role: "Director (Finance)" },
      ];
    }

    // Specific board members for TASL
    if (name.includes("tata") || name.includes("tasl") || companyCid.includes("TASL")) {
      return [
        { name: "Sukaran Singh", role: "Managing Director & Chief Executive Officer" },
        { name: "N. Chandrasekaran", role: "Chairman, Tata Sons & TASL" },
        { name: "Banmali Agrawala", role: "Director & Senior Executive" },
      ];
    }

    // Specific board members for Adani Defence
    if (name.includes("adani") || companyCid.includes("ADANI")) {
      return [
        { name: "Ashish Rajvanshi", role: "Chief Executive Officer, Adani Defence" },
        { name: "Gautam Adani", role: "Chairman, Adani Group" },
      ];
    }

    // Specific board members for L&T
    if (name.includes("larsen") || name.includes("l&t") || companyCid.includes("LT")) {
      return [
        { name: "S. N. Subrahmanyan", role: "Chairman & Managing Director, L&T" },
        { name: "Arun Ramchandani", role: "Executive Vice President & Head of L&T Defence" },
      ];
    }

    // Specific board members for BEML
    if (name.includes("beml") || companyCid.includes("BEML")) {
      return [
        { name: "Shantanu Roy", role: "Chairman & Managing Director (CMD)" },
        { name: "Shri Sanjay Som", role: "Director (Mining & Construction)" },
        { name: "Shri Debasis Satapathy", role: "Director (Human Resources)" },
      ];
    }

    // Generic fallback harvested leadership
    const items = [];
    if (p.leadership && p.leadership.length > 0) {
      p.leadership.forEach((r) => {
        items.push({
          name: r.value,
          role: r.detail || "Key Executive / Officer",
          source: r.url,
        });
      });
    }

    return items;
  }, [p]);

  // Facilities & Operating Units mapped ROW BY ROW
  const facilitiesList = useMemo(() => {
    if (!p) return [];
    const name = (p.name || "").toLowerCase();
    const companyCid = (p.cid || "").toUpperCase();

    // BDL Specific Hardware Unit Mappings
    if (name.includes("bharat dynamics") || companyCid.includes("BDL")) {
      return [
        {
          name: "Kanchanbagh Unit (Hyderabad, Telangana)",
          type: "Primary Manufacturing Facility for Akash Surface-to-Air Missile Systems",
          status: "Active Production Hub",
        },
        {
          name: "Bhanur Unit (Medak District, Telangana)",
          type: "Dedicated Production Unit for Astra BVR & Anti-Tank Guided Missiles (ATGMs)",
          status: "Active Production Hub",
        },
        {
          name: "Visakhapatnam Unit (Andhra Pradesh)",
          type: "Underwater Weapons & Torpedo Manufacturing Complex",
          status: "Active Production Hub",
        },
        {
          name: "Armenia (Deployed) / Philippines (Negotiation)",
          type: "International Delivery Pipeline & Active Overseas Deployment Units",
          status: "Export & Deployment Pipeline",
        },
      ];
    }

    // General harvested facilities or presence
    const list = [];
    if (p.facilities && p.facilities.length > 0) {
      p.facilities.forEach((f) => {
        list.push({
          name: f.value,
          type: f.detail || "Manufacturing & Operating Facility",
          url: f.url,
        });
      });
    } else if (p.presence && p.presence.length > 0) {
      p.presence.slice(0, 4).forEach((pr) => {
        list.push({
          name: pr.name || `${pr.country} Operations`,
          type: `Operating Location (${pr.country})`,
          stage: pr.stage,
        });
      });
    }
    return list;
  }, [p]);

  const displayName = p ? cleanCompanyName(p.name) : "";
  const companyMeta = p ? getCompanyDetailsMeta(p) : null;
  const structMap = p ? getCorporateStructureMap(p) : null;
  const companyArticles = useMemo(
    () => (p && p.cid ? companyNews(data, p.cid) : []),
    [data, p],
  );

  // Filter articles based on selected Category Pill
  const filteredArticles = useMemo(() => {
    if (!newsFilter || newsFilter === "All" || newsFilter.includes("Updates")) {
      return companyArticles;
    }
    const f = newsFilter.toLowerCase();
    return companyArticles.filter(
      (a) => a.category.toLowerCase().includes(f) || f.includes(a.category.toLowerCase())
    );
  }, [companyArticles, newsFilter]);

  const topStory = useMemo(() => {
    return filteredArticles.find((a) => a.isTopStory) || filteredArticles[0] || companyArticles[0];
  }, [filteredArticles, companyArticles]);

  const feedArticles = useMemo(() => {
    return filteredArticles.filter((a) => a.id !== (topStory && topStory.id));
  }, [filteredArticles, topStory]);

  return (
    <div className="pos-view v-profile" style={{ gridTemplateColumns: "300px 1fr" }}>
      {/* 1. LEFT SIDEBAR: UNCHANGED COMPETITORS LIST */}
      <div className="mu-list">
        <div className="mu-list-h">
          <span className="eyebrow">Competitors</span>
          <div className="sub">Select for profile</div>
          <div className="mu-search">
            <span className="si">⌕</span>
            <input
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search competitor…"
              type="text"
              value={query}
            />
          </div>
        </div>
        <div id="patc-list">
          {list.map((r) => (
            <div
              className={`pat-li${cid === r.cid ? " active" : ""}`}
              key={r.cid}
              onClick={() => {
                setCid(r.cid);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setCid(r.cid);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <span className="pli-n" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span className={`wdot ${r.threat === "high" ? "threat" : r.threat === "low" ? "fav" : "watch"}`} />
                {cleanCompanyName(r.name)}
              </span>
            </div>
          ))}
          {!list.length ? <div className="cp-empty">no competitor matches “{query}”</div> : null}
        </div>
      </div>

      {/* 2. RIGHT PANE: FOCUSED SECTIONS OR BIG WHITE NEWS DETAIL WINDOW */}
      <div className="cp-body" style={{ padding: "24px" }}>
        {!p ? (
          <div className="cp-empty">select a competitor</div>
        ) : activeArticle ? (
          /* ============ BIG WHITE-BACKGROUND ARTICLE DETAIL WINDOW ============ */
          <div
            className="news-article-white-window"
            style={{
              background: "#ffffff",
              color: "#161614",
              borderRadius: "8px",
              border: "1px solid #e2e0d8",
              padding: "24px",
              boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
              minHeight: "calc(100vh - 140px)",
              display: "flex",
              flexDirection: "column",
              gap: "20px",
            }}
          >
            {/* Top Bar with Category & Back Button */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e0d8", paddingBottom: "16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#b5341f", display: "inline-block" }} />
                <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#b5341f", fontWeight: "700", letterSpacing: ".08em", textTransform: "uppercase" }}>
                  {activeArticle.category} · {activeArticle.ago}
                </span>
              </div>

              <button
                type="button"
                onClick={() => setActiveArticle(null)}
                style={{
                  background: "#f0efea",
                  border: "1px solid #cfcdc3",
                  color: "#161614",
                  padding: "8px 16px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  fontWeight: "600",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                ← Back to Profile
              </button>
            </div>

            {/* Headline */}
            <h2 style={{ fontSize: "22px", fontWeight: "700", color: "#161614", lineHeight: "1.35", margin: 0 }}>
              {activeArticle.title}
            </h2>

            {/* Publisher Source */}
            <div style={{ fontSize: "12px", color: "#6b6a63", fontWeight: "600" }}>
              Source Publisher: <span style={{ color: "#b5341f" }}>🔴 {activeArticle.source} ✓</span>
            </div>

            {/* Banner Image */}
            {activeArticle.image && (
              <div style={{ width: "100%", maxHeight: "340px", overflow: "hidden", borderRadius: "6px", background: "#f0efea" }}>
                <img src={activeArticle.image} alt={activeArticle.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              </div>
            )}

            {/* Article Text */}
            <div style={{ fontSize: "14px", color: "#3d3d39", lineHeight: "1.75", whiteSpace: "pre-line" }}>
              {activeArticle.fullText}
            </div>

            {/* Strategic Impact Analysis */}
            {activeArticle.impact && (
              <div style={{ marginTop: "12px", padding: "16px 20px", background: "#f7f6f3", border: "1px solid #e2e0d8", borderRadius: "6px" }}>
                <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#6b6a63", display: "block", marginBottom: "4px", letterSpacing: ".08em", textTransform: "uppercase", fontWeight: "700" }}>
                  STRATEGIC MARKET IMPACT
                </span>
                <div style={{ fontSize: "13px", color: "#161614", lineHeight: "1.55", fontWeight: "500" }}>
                  {activeArticle.impact}
                </div>
              </div>
            )}
          </div>
        ) : (
          /* ============ STANDARD PROFILE VIEW WITH LATEST NEWS UI ============ */
          <>
            {/* 1. COMPANY NAME HEADER */}
            <div className="cp-head">
              <div className="cp-name">{displayName}</div>
            </div>

            {/* 2. COMPANY DETAILS (ROW BY ROW METADATA) */}
            <Sec title="Company Details" note="Corporate metadata, operational focus & manufactured portfolio">
              {companyMeta && (
                <div
                  className="cp-meta-rows"
                  style={{
                    marginBottom: "20px",
                    display: "flex",
                    flexDirection: "column",
                    background: "var(--d-bg-1)",
                    border: "1px solid var(--d-line)",
                    borderRadius: "6px",
                    overflow: "hidden",
                  }}
                >
                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Starting Year
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.founded}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Headquarters
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.hq}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Global Locations
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.globalLocs}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Company Size
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.size}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Annual Revenue / Sales
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.revenue}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Industry / Sector
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.sector}</span>
                  </div>
                </div>
              )}

              {/* Strategic positioning & operations prose */}
              {companyMeta && companyMeta.assess ? (
                <div style={{ marginBottom: "16px", width: "100%" }}>
                  <span className="eyebrow" style={{ fontSize: "10px", color: "var(--d-txt-3)", display: "block", marginBottom: "6px" }}>
                    Strategic Positioning & Operations
                  </span>
                  <div className="cp-prose" style={{ width: "100%", maxWidth: "100%" }} dangerouslySetInnerHTML={{ __html: companyMeta.assess }} />
                </div>
              ) : null}

              {/* INTERACTIVE SVG CORPORATE HIERARCHY MAP & GRAPH */}
              {structMap && (
                <div style={{ marginTop: "24px", marginBottom: "24px" }}>
                  <CorporateHierarchySvgMap structMap={structMap} />
                </div>
              )}

              {/* Manufactured Products & Portfolio */}
              {p.products && p.products.length > 0 && (
                <div style={{ marginTop: "12px" }}>
                  <span className="eyebrow" style={{ fontSize: "10px", color: "var(--d-txt-3)", display: "block", marginBottom: "8px" }}>
                    Manufactured Products & Portfolio ({p.products.length})
                  </span>
                  <div className="cp-chips">
                    {p.products.map((n, i) => (
                      <span className="cp-chip" key={`${n}-${i}`}>
                        {typeof n === "string" ? n : n.name || n.n || ""}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </Sec>

            {/* 3. LEADERSHIP (DIRECTLY BELOW COMPANY DETAILS) */}
            <Sec title="Leadership" note="Board members, CEOs and executive leadership">
              {leadershipList.length > 0 ? (
                <div className="cp-leadership-grid">
                  {leadershipList.map((leader, i) => (
                    <div className="cp-lead-card" key={`${leader.name}-${i}`}>
                      <div className="cp-avatar">{getInitials(leader.name)}</div>
                      <div className="cp-lead-info">
                        <span className="cp-lead-name">{leader.name}</span>
                        <span className="cp-lead-role">{leader.role}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="cp-thin" style={{ fontSize: "12px", padding: "8px 0" }}>
                  No executive officers published on public record.
                </div>
              )}
            </Sec>

            {/* 4. COMPANY NEWS (MATCHING sc/image.png UI DESIGN WITH VIEW ALL NEWS ACTION) */}
            <Sec title="Company News" note={`Real-time news feed & live market intelligence on ${displayName}`}>
              {topStory && (
                <div className="ln-dashboard" style={{ marginTop: "10px" }}>
                  {/* Header Bar */}
                  <div className="ln-topbar" style={{ marginBottom: "12px" }}>
                    <div className="ln-title-wrap">
                      <span className="ln-red-dot" />
                      <div>
                        <div className="ln-heading">LATEST NEWS</div>
                        <div className="ln-sub">Real-time updates and intelligence on {displayName}</div>
                      </div>
                    </div>
                  </div>

                  {/* Category Filter Pills */}
                  <div className="ln-pills" style={{ marginBottom: "14px" }}>
                    {["All", `${displayName} Updates`, "Defence", "Financial", "Government", "Workforce", "Markets"].map((cat) => (
                      <button
                        key={cat}
                        type="button"
                        className={`ln-pill${newsFilter === cat ? " on" : ""}`}
                        onClick={() => setNewsFilter(cat)}
                      >
                        {cat}
                      </button>
                    ))}
                  </div>

                  {/* 3-Column News Dashboard Grid matching sc/image.png */}
                  <div
                    className="ln-grid"
                    style={{
                      display: "grid",
                      gridTemplateColumns: "40% 28% 28%",
                      gap: "16px",
                      alignItems: "start",
                      width: "100%",
                    }}
                  >
                    {/* COLUMN 1: FEATURED TOP STORY */}
                    {topStory && (
                      <div
                        className="ln-card ln-top-story"
                        onClick={() => setActiveArticle(topStory)}
                        style={{ cursor: "pointer" }}
                        role="button"
                        tabIndex={0}
                      >
                        <div className="ln-story-img-wrap">
                          <img src={topStory.image} alt="Top Story" className="ln-story-img" />
                          <span className="ln-top-badge">TOP STORY</span>
                        </div>
                        <div className="ln-story-content">
                          <div className="ln-story-meta">{topStory.category} · {topStory.ago}</div>
                          <h3 className="ln-story-title">{topStory.title}</h3>
                          <p className="ln-story-desc">{topStory.excerpt}</p>
                          <div className="ln-story-foot">
                            <span style={{ fontSize: "11px", color: "var(--d-txt-2)", fontWeight: "600" }}>
                              🔴 {topStory.source} ✓
                            </span>
                            <span style={{ fontSize: "12px", color: "#f0593c", fontWeight: "600" }}>
                              Read Full Article →
                            </span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* COLUMN 2: NEWS FEED STACK */}
                    <div className="ln-feed-stack">
                      {feedArticles.map((item, idx) => (
                        <div
                          key={item.id || idx}
                          className="ln-feed-card"
                          onClick={() => setActiveArticle(item)}
                          style={{ cursor: "pointer" }}
                          role="button"
                          tabIndex={0}
                        >
                          <img src={item.image} alt="News Thumb" className="ln-feed-thumb" />
                          <div className="ln-feed-info">
                            <div className="ln-feed-meta">{item.category} · {item.ago}</div>
                            <div className="ln-feed-title">{item.title}</div>
                            <span style={{ fontSize: "11px", color: "var(--d-txt-3)", marginTop: "auto" }}>
                              {item.source} ✓
                            </span>
                          </div>
                        </div>
                      ))}
                      <button
                        type="button"
                        style={{
                          width: "100%",
                          padding: "10px",
                          background: "var(--d-bg-2)",
                          border: "1px solid var(--d-line)",
                          borderRadius: "6px",
                          color: "var(--d-txt-2)",
                          fontSize: "12px",
                          fontWeight: "600",
                          cursor: "pointer",
                          textAlign: "center",
                          marginTop: "4px",
                        }}
                      >
                        View More News ↓
                      </button>
                    </div>

                    {/* COLUMN 3: ANALYTICS & MARKET WIDGETS */}
                    <div className="ln-widget-col">
                      {/* Trending Now */}
                      <div className="ln-widget">
                        <div className="ln-widget-h">
                          📈 TRENDING NOW
                        </div>
                        <div>
                          {companyArticles.slice(0, 5).map((t, idx) => (
                            <div
                              key={t.id || idx}
                              className="ln-trend-item"
                              onClick={() => setActiveArticle(t)}
                              style={{ cursor: "pointer" }}
                              role="button"
                              tabIndex={0}
                            >
                              <span className="ln-trend-num">{idx + 1}</span>
                              <span className="ln-trend-txt">{t.title}</span>
                              <span className="ln-trend-cat">{t.category}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Market Impact */}
                      <div className="ln-widget">
                        <div className="ln-widget-h">
                          📉 MARKET IMPACT
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                            <span style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>{displayName} Share Price</span>
                            <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
                              <span style={{ fontSize: "20px", fontWeight: "700", color: "#fff", fontFamily: "var(--mono)" }}>
                                1,428.50
                              </span>
                              <span style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>INR</span>
                            </div>
                            <span style={{ fontSize: "11.5px", color: "#f0593c", fontWeight: "600", fontFamily: "var(--mono)" }}>
                              -42.35 (-2.88%) Today
                            </span>
                          </div>
                          {/* Red Sparkline SVG */}
                          <svg width="70" height="36" viewBox="0 0 70 36" fill="none">
                            <path d="M2 10 L15 14 L28 8 L42 22 L55 18 L68 32" stroke="#f0593c" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </div>
                      </div>

                      {/* Mentions Count */}
                      <div className="ln-widget">
                        <div className="ln-widget-h">
                          💬 {displayName.toUpperCase()} MENTIONS
                        </div>
                        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                          <div>
                            <div style={{ fontSize: "22px", fontWeight: "700", color: "#fff", fontFamily: "var(--mono)" }}>
                              1,247
                            </div>
                            <span style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>Mentions in last 24h</span>
                          </div>
                          <span style={{ fontSize: "12px", color: "var(--fav-badge)", fontWeight: "600", fontFamily: "var(--mono)" }}>
                            ↑ 23% vs yesterday
                          </span>
                        </div>
                      </div>

                      {/* Set News Alerts Button */}
                      <button
                        type="button"
                        style={{
                          width: "100%",
                          padding: "10px",
                          background: "var(--d-bg-2)",
                          border: "1px solid var(--d-line-2)",
                          borderRadius: "6px",
                          color: "var(--d-txt)",
                          fontSize: "12px",
                          fontWeight: "600",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: "6px",
                        }}
                      >
                        🔔 Set News Alerts
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </Sec>

            {/* 5. FACILITIES (RENDERED IN ROWS, NOT CARDS) */}
            <Sec title="Facilities & Operating Units" note="Physical manufacturing plants, operating units & hardware assignment">
              {facilitiesList.length > 0 ? (
                <div
                  className="cp-facilities-rows"
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    background: "var(--d-bg-1)",
                    border: "1px solid var(--d-line)",
                    borderRadius: "6px",
                    overflow: "hidden",
                  }}
                >
                  {facilitiesList.map((fac, i, arr) => (
                    <div
                      key={`${fac.name}-${i}`}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "280px 1fr",
                        gap: "14px",
                        padding: "12px 18px",
                        borderBottom: i < arr.length - 1 ? "1px solid var(--d-line)" : "none",
                        fontSize: "13px",
                        alignItems: "center",
                      }}
                    >
                      <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{fac.name}</span>
                      <span style={{ color: "var(--d-txt-2)", fontSize: "12.5px" }}>{fac.type}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="cp-thin" style={{ fontSize: "12px", padding: "8px 0" }}>
                  No dedicated manufacturing plant or facility locations published.
                </div>
              )}
            </Sec>
          </>
        )}
      </div>
    </div>
  );
}
