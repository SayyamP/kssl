import { useEffect, useMemo, useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildProfile, rosterOf, formatSectorName } from "../../lib/profile";
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

/* The graph below was built for corporate structure -- a parent, its sister companies
 * and its subsidiaries -- and upstream fed it an if-chain of hand-typed strings for
 * about six firms ("BDL Kanchanbagh Guided Missile Complex" and the like). None of that
 * came from the corpus, so 95f781c replaced it with null and the graph went dark.
 *
 * Nothing in the serving schema holds ownership: there is no parent, sister or
 * subsidiary column anywhere, and no writer that could fill one. What the schema DOES
 * hold is competitors.partners -- 582 ties over 178 companies, each with a type and a
 * source URL. So the graph draws the relationships we can actually prove, and the
 * heading says "Partner Network" rather than claiming an ownership tree we do not have.
 *
 * Ordered so the strongest ties are the ones that survive the cap: equity first (a joint
 * venture says more about a company than a supply contract), then transfers of
 * technology, then everything else; a sourced tie always outranks an unsourced one of
 * the same class. Capped at 8 because one company carries 55 ties and a row of 55 nodes
 * is not a graph. */
const TIE_RANK = [
  [/joint venture|acquisition|stake|jv\b/i, 0],
  [/technology|tot\b|transfer|manufactur/i, 1],
  [/mou|strategic/i, 2],
];

const tieRank = (t) => {
  const hit = TIE_RANK.find(([rx]) => rx.test(t || ""));
  return hit ? hit[1] : 3;
};

export const partnerTree = (p, cap = 8) => {
  const ties = (p && p.partners) || [];
  if (!ties.length) return null;

  const seen = new Set();
  const nodes = ties
    .filter((t) => {
      const name = (t.label || "").trim();
      // A tie with no counterparty name cannot be a node, and the same partner listed
      // twice under two deals must not become two circles.
      if (!name || seen.has(name.toLowerCase())) return false;
      seen.add(name.toLowerCase());
      return true;
    })
    .map((t) => ({
      name: (t.label || "").trim(),
      type: (t.ptype || t.kind || "").trim(),
      sourced: Boolean(t.src),
    }))
    .sort(
      (a, b) =>
        tieRank(a.type) - tieRank(b.type) ||
        Number(b.sourced) - Number(a.sourced) ||
        a.name.localeCompare(b.name),
    )
    .slice(0, cap);

  if (!nodes.length) return null;
  return {
    current: p.name || "Company",
    sisters: nodes.map((n) => (n.type ? n.name + " · " + n.type : n.name)),
    subsidiaries: [],
    shown: nodes.length,
    total: seen.size,
  };
};

/* Ownership, when the corpus states any. serving.competitor_structure holds parent and
 * subsidiary edges mined by enrich_serving.step_structure, each carrying the article it
 * was read from -- so the graph above can finally be what it was built to be. When a
 * company has no stated ownership it falls back to the partner network, which is real
 * too and says so in the heading. The two are never mixed: a partner drawn under a
 * "Corporate Structure" heading is the hand-typed hierarchy this page already removed
 * once, arriving by a different route. */
const REL_WORD = { parent: "Parent", subsidiary: "Subsidiary", sister: "Sister",
                   division: "Division" };
const REL_RANK = { parent: 0, division: 1, subsidiary: 2, sister: 3 };

export const ownershipTree = (p, edges, cap = 8) => {
  const rows = (edges || []).filter((e) => e && e.entity_name);
  if (!rows.length) return null;
  const seen = new Set();
  const nodes = rows
    .filter((e) => {
      const k = `${e.relationship_type}:${(e.entity_name || "").toLowerCase()}`;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    })
    .sort(
      (a, b) =>
        (REL_RANK[a.relationship_type] ?? 9) - (REL_RANK[b.relationship_type] ?? 9) ||
        a.entity_name.localeCompare(b.entity_name),
    );
  const shown = nodes.slice(0, cap);
  return {
    current: p.name || "Company",
    kind: "ownership",
    sisters: shown.map((e) => {
      const word = REL_WORD[e.relationship_type] || e.relationship_type;
      // The percentage is printed only when a source stated one; step_structure drops
      // any figure its quote does not carry, so a number here was always in an article.
      const pct = e.ownership_pct ? ` ${e.ownership_pct}%` : "";
      return `${e.entity_name} · ${word}${pct}`;
    }),
    subsidiaries: [],
    shown: shown.length,
    total: nodes.length,
  };
};

const getCorporateStructureMap = (p, edges) =>
  ownershipTree(p, edges) || partnerTree(p);

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
            {structMap.kind === "ownership" ? "Corporate Structure" : "Partner Network"} ·{" "}
            {structMap.current}
            {structMap.total > structMap.shown
              ? " · " + structMap.shown + " of " + structMap.total + " ties"
              : ""}
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

      {/* Interactive SVG Canvas - One-to-Many Connector Tree Graph */}
      <div
        style={{
          width: "100%",
          height: "460px",
          overflow: "hidden",
          background: "#0d1117",
          borderRadius: "8px",
          border: "1px solid #1e293b",
          position: "relative",
        }}
      >
        {(() => {
          const sisterList = Array.from(
            new Set([...(structMap.sisters || []), ...(structMap.subsidiaries || [])])
          );
          const n = sisterList.length;

          const canvasWidth = 900;
          const canvasHeight = 460;

          // Top Card (Actual Company) - Dynamic Width based on Company Name Length
          const companyName = structMap.current || "Company";
          const cardW = Math.max(340, Math.min(680, companyName.length * 9.5 + 110));
          const cardH = 85;
          const cardX = (canvasWidth - cardW) / 2;
          const cardY = 40;

          const rootBottomX = canvasWidth / 2;
          const rootBottomY = cardY + cardH;

          // Connector Junction
          const junctionY = 200;
          const leafY = 295;

          // Sister Company Column Positions (X coordinates)
          const leftMargin = 100;
          const rightMargin = 800;
          const stepX = n > 1 ? (rightMargin - leftMargin) / (n - 1) : canvasWidth / 2;

          const minX = n > 1 ? leftMargin : canvasWidth / 2;
          const maxX = n > 1 ? rightMargin : canvasWidth / 2;

          return (
            <svg
              viewBox="0 0 900 460"
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
              <rect width="900" height="460" fill="url(#grid)" />

              {/* ============ CONNECTOR LINES SYSTEM ============ */}
              {/* 1. Main Vertical Line down from Root Card */}
              <line
                x1={rootBottomX}
                y1={rootBottomY}
                x2={rootBottomX}
                y2={junctionY}
                stroke="#e8483a"
                strokeWidth="2.5"
              />

              {/* 2. Red Dot at Root Card bottom edge */}
              <circle cx={rootBottomX} cy={rootBottomY} r="5" fill="#e8483a" />

              {/* 3. Red Dot at Horizontal Junction Center */}
              <circle cx={rootBottomX} cy={junctionY} r="5" fill="#e8483a" />

              {/* 4. Horizontal Dashed Connector Bar */}
              {n > 0 && (
                <line
                  x1={minX}
                  y1={junctionY}
                  x2={maxX}
                  y2={junctionY}
                  stroke="#64748b"
                  strokeWidth="1.8"
                  strokeDasharray="4,4"
                />
              )}

              {/* 5. Vertical Lines to Sister Nodes */}
              {sisterList.map((item, i) => {
                const sisterX = n === 1 ? canvasWidth / 2 : leftMargin + i * stepX;
                const isHovered = hoveredNode === item;

                return (
                  <g key={`connector-${i}`}>
                    {/* Junction Dot on Horizontal Bar */}
                    <circle
                      cx={sisterX}
                      cy={junctionY}
                      r="3.5"
                      fill={isHovered ? "#38bdf8" : "#64748b"}
                    />
                    {/* Vertical Drop Line */}
                    <line
                      x1={sisterX}
                      y1={junctionY}
                      x2={sisterX}
                      y2={leafY}
                      stroke={isHovered ? "#38bdf8" : "#64748b"}
                      strokeWidth={isHovered ? 2.2 : 1.6}
                      strokeDasharray="4,4"
                      style={{ transition: "stroke 0.2s" }}
                    />
                  </g>
                );
              })}

              {/* ============ SISTER COMPANY NODES (BOTTOM ROW) ============ */}
              {sisterList.map((item, i) => {
                const sisterX = n === 1 ? canvasWidth / 2 : leftMargin + i * stepX;
                const label = typeof item === "string" ? item : item.name || "";
                const isHovered = hoveredNode === item;

                // Stagger label Y position for odd index nodes when there are 4+ nodes to prevent text overlap
                const isStaggered = n > 4 && i % 2 !== 0;
                const labelY1 = isStaggered ? leafY + 60 : leafY + 34;
                const labelY2 = isStaggered ? leafY + 74 : leafY + 48;

                const words = label.split(" ");
                let line1 = label;
                let line2 = "";
                if (label.length > 18 && words.length > 1) {
                  const mid = Math.ceil(words.length / 2);
                  line1 = words.slice(0, mid).join(" ");
                  line2 = words.slice(mid).join(" ");
                }

                return (
                  <g
                    key={`sister-node-${i}`}
                    onMouseEnter={() => setHoveredNode(item)}
                    onMouseLeave={() => setHoveredNode(null)}
                    style={{ cursor: "pointer" }}
                  >
                    {/* Connector line extensions for staggered labels */}
                    {isStaggered && (
                      <line
                        x1={sisterX}
                        y1={leafY + 18}
                        x2={sisterX}
                        y2={labelY1 - 12}
                        stroke={isHovered ? "#38bdf8" : "#334155"}
                        strokeWidth="1"
                        strokeDasharray="2,2"
                      />
                    )}

                    {/* Blue Ring Circle */}
                    <circle
                      cx={sisterX}
                      cy={leafY}
                      r={isHovered ? 20 : 16}
                      fill="#0d1117"
                      stroke={isHovered ? "#38bdf8" : "#0284c7"}
                      strokeWidth={isHovered ? 3.5 : 2.5}
                      style={{ transition: "all 0.2s" }}
                    />
                    <circle
                      cx={sisterX}
                      cy={leafY}
                      r={7}
                      fill={isHovered ? "#38bdf8" : "transparent"}
                      style={{ transition: "fill 0.2s" }}
                    />

                    {/* Sister Company Name Below Circle */}
                    <text
                      x={sisterX}
                      y={labelY1}
                      textAnchor="middle"
                      style={{
                        fill: isHovered ? "#ffffff" : "#e2e8f0",
                        fontFamily: "var(--mono)",
                        fontSize: n > 5 ? "10.5px" : "11.5px",
                        fontWeight: isHovered ? "700" : "600",
                        transition: "fill 0.2s",
                      }}
                    >
                      {line1}
                    </text>
                    {line2 && (
                      <text
                        x={sisterX}
                        y={labelY2}
                        textAnchor="middle"
                        style={{
                          fill: isHovered ? "#38bdf8" : "#94a3b8",
                          fontFamily: "var(--mono)",
                          fontSize: n > 5 ? "9.5px" : "10.5px",
                          fontWeight: "500",
                          transition: "fill 0.2s",
                        }}
                      >
                        {line2}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* ============ ROOT NODE CARD (ACTUAL COMPANY) ============ */}
              <g style={{ cursor: "pointer" }}>
                {/* Main Card Border & Background */}
                <rect
                  x={cardX}
                  y={cardY}
                  width={cardW}
                  height={cardH}
                  rx="12"
                  fill="#161b22"
                  stroke="#e8483a"
                  strokeWidth="1.8"
                />

                {/* Building Icon Container */}
                <circle cx={cardX + 38} cy={cardY + cardH / 2} r="20" fill="rgba(232, 72, 58, 0.12)" />
                <text
                  x={cardX + 38}
                  y={cardY + cardH / 2 + 6}
                  textAnchor="middle"
                  style={{ fontSize: "18px", userSelect: "none" }}
                >
                  🏢
                </text>

                {/* Company Title */}
                <text
                  x={cardX + 70}
                  y={cardY + 38}
                  style={{
                    fill: "#ffffff",
                    fontFamily: "var(--mono)",
                    fontSize: "14px",
                    fontWeight: "800",
                    letterSpacing: ".01em",
                  }}
                >
                  {companyName}
                </text>

                {/* Subtitle Badge */}
                <text
                  x={cardX + 70}
                  y={cardY + 58}
                  style={{
                    fill: "#e8483a",
                    fontFamily: "var(--mono)",
                    fontSize: "11px",
                    fontWeight: "700",
                    letterSpacing: ".04em",
                  }}
                >
                  Actual Company
                </text>
              </g>
            </svg>
          );
        })()}
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
  const { setScope, takePending, searchQuery } = useAppState();
  const [query, setQuery] = useState("");
  const roster = useMemo(() => rosterOf(data), [data]);
  const [cid, setCid] = useState(() => (roster[0] ? roster[0].cid : ""));

  /* Opened from global search targeting one company. Without this the page took the
     jump but never read the payload, so picking "RENK" in the search box landed on
     roster[0] -- the search looked broken because it navigated to the wrong rival. */
  useEffect(() => {
    const pend = takePending("profile");
    if (pend && pend.cid && data.competitors && data.competitors[pend.cid]) {
      setCid(pend.cid);
    }
  }, [takePending, data.competitors]);

  // News category filter pill & active open article state for White Detail Window
  const [newsFilter, setNewsFilter] = useState("All");
  const [activeArticle, setActiveArticle] = useState(null);

  useEffect(() => {
    const pend = takePending("profile");
    if (pend && pend.cid) {
      setCid(pend.cid);
    }
  }, [takePending]);

  const list = useMemo(() => {
    const q = (query || searchQuery || "").trim().toLowerCase();
    if (!q) return roster;
    const tokens = q.split(/\s+/).filter(Boolean);
    return roster.filter((r) => {
      const fullText = `${r.name || ""} ${r.sector || ""} ${r.hq || ""} ${r.cid || ""}`.toLowerCase();
      return tokens.every((tok) => fullText.includes(tok));
    });
  }, [roster, query, searchQuery]);

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

  /* Executive leadership.
   *
   * This block used to carry a hand-typed board for about six named firms --
   * "Shri Shailesh Vagerwal, Chairman & Managing Director" at Bharat Dynamics,
   * "Sukaran Singh" at TASL, "Gautam Adani" at Adani Defence -- returned before
   * the real branch could run. Named people in named roles at real companies is
   * the most damaging kind of invented content on this dashboard, and it was the
   * one I missed on the first pass: the strings survived into the deployed
   * bundle, which is where I found them.
   *
   * competitors.leadership is the column for this. It is 0% filled today, so the
   * section renders empty until enrichment writes it -- which is the correct
   * state, not a regression.
   */
  const leadershipList = useMemo(() => {
    if (!p || !p.leadership || !p.leadership.length) return [];
    return p.leadership.map((r) => ({
      name: r.value,
      role: r.detail || "Key Executive / Officer",
      source: r.url,
    }));
  }, [p]);

  /* Facilities. Same fault: a hand-typed plant list for Bharat Dynamics
     (Kanchanbagh, Bhanur, Visakhapatnam, and an "Armenia (Deployed) / Philippines
     (Negotiation)" export pipeline) shadowed the harvested branch. Now: the
     facilities column if it has rows, else the country presence rows, else
     nothing. */
  const facilitiesList = useMemo(() => {
    if (!p) return [];
    if (p.facilities && p.facilities.length > 0) {
      return p.facilities.map((f) => ({
        name: f.value,
        type: f.detail || "Manufacturing & Operating Facility",
        url: f.url,
      }));
    }
    if (p.presence && p.presence.length > 0) {
      return p.presence.slice(0, 4).map((pr) => ({
        name: pr.name || `${pr.country} Operations`,
        type: `Operating Location (${pr.country})`,
        stage: pr.stage,
      }));
    }
    return [];
  }, [p]);

  const displayName = p ? cleanCompanyName(p.name) : "";
  const companyMeta = p ? getCompanyDetailsMeta(p) : null;
  const structMap = p
    ? getCorporateStructureMap(p, (data.competitorStructure || {})[cid])
    : null;
  // Absent for a company no dated document names -- the tile then does not render
  // at all, rather than showing a confident zero.
  const metrics = (data.competitorMetrics || {})[cid] || null;
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
            <Sec title="Company Details" note="Corporate metadata & operational focus">
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
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{formatSectorName(companyMeta.sector)}</span>
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

              {/* PARTNER NETWORK GRAPH -- real sourced ties, see partnerTree above */}
              {structMap && (
                <div style={{ marginTop: "24px", marginBottom: "24px" }}>
                  <CorporateHierarchySvgMap structMap={structMap} />
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

                      {/* Three widgets stood here and all three were literals.

                          MARKET IMPACT printed a share price of 1,428.50 INR and
                          "-42.35 (-2.88%) Today" for EVERY company on the roster --
                          including the private ones and the state arsenals that have no
                          listed equity at all -- beside a sparkline drawn from a fixed
                          path. This system has no market-data feed of any kind, so it
                          stays gone: serving.competitor_metrics deliberately has no
                          share_price column for a future version of this to read.

                          SET NEWS ALERTS was a button with no onClick, and stays gone
                          too -- there is no alerting behind it.

                          MENTIONS is BACK, and different. It printed a 24-hour count and
                          a percentage against yesterday, both literals in the JSX. What
                          is below is counted by enrich_serving.step_metrics over the
                          documents this pipeline actually crawled and dated. Two things
                          keep it honest: it says CORPUS MENTIONS, because that is what it
                          counts and not what the world is saying, and it takes its window
                          from the record rather than naming one here -- the corpus is
                          day-granular, so there is no 24-hour figure to print. */}
                      {metrics ? (
                        <div className="ln-widget">
                          <div className="ln-widget-h">
                            <span className="eyebrow">
                              Corpus mentions · {metrics.window_days}d to{" "}
                              {metrics.window_end || "\u2014"}
                            </span>
                          </div>
                          <div style={{ display: "flex", alignItems: "baseline", gap: "10px" }}>
                            <span style={{ fontSize: "26px", fontWeight: 700,
                                           fontVariantNumeric: "tabular-nums" }}>
                              {metrics.mentions_window}
                            </span>
                            {typeof metrics.mentions_change_pct === "number" ? (
                              <span
                                style={{
                                  fontSize: "12px",
                                  fontVariantNumeric: "tabular-nums",
                                  color: metrics.mentions_change_pct >= 0
                                    ? "var(--d-up, #34d399)"
                                    : "var(--d-down, #f87171)",
                                }}
                              >
                                {metrics.mentions_change_pct >= 0 ? "+" : ""}
                                {metrics.mentions_change_pct}% share of corpus
                              </span>
                            ) : (
                              /* The previous window held nothing, so there is no
                                 baseline to compare against. Saying so beats printing
                                 a percentage computed from zero. */
                              <span style={{ fontSize: "12px", color: "var(--d-txt-2)" }}>
                                no documents in the previous {metrics.window_days}d
                              </span>
                            )}
                          </div>
                          {/* The denominators are printed, not hidden. The percentage
                              above compares SHARE of the corpus rather than raw counts,
                              because the crawler's weekly volume moves independently of
                              the news: measured 2026-09-04, it put 847 documents in one
                              window against 423 in the previous, which on raw counts
                              made every company on the roster look like it was surging.
                              A reader can only check that if the base is on screen. */}
                          <div style={{ fontSize: "11px", color: "var(--d-txt-2)",
                                        marginTop: "4px" }}>
                            of {metrics.corpus_window} corpus documents naming {p.name};
                            previously {metrics.mentions_previous} of{" "}
                            {metrics.corpus_previous}
                          </div>
                        </div>
                      ) : null}
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
