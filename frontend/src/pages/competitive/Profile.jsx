import { useEffect, useMemo, useState } from "react";
import { useAppState, useHeaderReport } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildProfile, rosterOf, formatSectorName } from "../../lib/profile";
import { companyNews } from "../../lib/news";
import { facetOptionsByName } from "../../lib/countryFacet";
import Thumb from "../../components/thumb/Thumb.jsx";
import SourceLink from "../../components/sourceLink/SourceLink.jsx";

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

/* feed cards opened per "View more" click */
const NEWS_PAGE = 6;

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

const PROFILE_KEY = "kssl_profile_cid";

export default function Profile() {
  const { data } = useData();
  const { setScope, takePending, searchQuery } = useAppState();
  const [query, setQuery] = useState("");
  const [country, setCountry] = useState("all");
  const roster = useMemo(() => rosterOf(data), [data]);
  /* Finding T 3: no country-level filter on the competitor list. Options are the
     countries the roster rows carry (rosterOf stamps each row through the shared
     companyCountries), counted, and the "All" label prints the list's own length. */
  const countryOptions = useMemo(
    () => facetOptionsByName(roster, (r) => r.countries || []),
    [roster],
  );
  /* The selected competitor is remembered, as Positioning, Partnerships, Geo, Patents
     and the Tender Pipeline remember theirs: this page reset to roster[0] on every
     reload and every detour to another rail row, alone among the sidebars. A saved id
     that the served roster no longer carries falls back to the first row. */
  const [cid, setCidState] = useState(() => {
    try {
      const saved = localStorage.getItem(PROFILE_KEY);
      if (saved && roster.some((r) => r.cid === saved)) return saved;
    } catch (e) {}
    return roster[0] ? roster[0].cid : "";
  });
  const setCid = (next) => {
    setCidState(next);
    try {
      if (next) localStorage.setItem(PROFILE_KEY, next);
      else localStorage.removeItem(PROFILE_KEY);
    } catch (e) {}
  };

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
  /* How many feed cards are open. "View More News" had no handler and the stack
     already listed every article, so the button could not have done anything; the
     stack now opens NEWS_PAGE at a time and the button says how many remain. */
  const [newsShown, setNewsShown] = useState(NEWS_PAGE);

  useEffect(() => {
    const pend = takePending("profile");
    if (pend && pend.cid) {
      setCid(pend.cid);
    }
  }, [takePending]);

  const list = useMemo(() => {
    const q = (query || searchQuery || "").trim().toLowerCase();
    const tokens = q.split(/\s+/).filter(Boolean);
    return roster.filter((r) => {
      if (country !== "all" && !(r.countries || []).includes(country)) return false;
      if (!tokens.length) return true;
      const fullText = `${r.name || ""} ${r.sector || ""} ${r.hq || ""} ${r.cid || ""}`.toLowerCase();
      return tokens.every((tok) => fullText.includes(tok));
    });
  }, [roster, query, searchQuery, country]);

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
    setNewsShown(NEWS_PAGE);
  }, [cid]);
  useEffect(() => {
    setNewsShown(NEWS_PAGE);
  }, [newsFilter]);

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
  /* Memoised because the header report below depends on it: a fresh object each
     render would republish the report each render, and each publish re-renders. */
  const companyMeta = useMemo(() => (p ? getCompanyDetailsMeta(p) : null), [p]);
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

  /* What the header's Copy / Export / Print act on: this company's profile as shown --
     details, leadership, and every sourced article. Nothing is added to the record. */
  const report = useMemo(() => {
    if (!p) return null;
    const details = companyMeta
      ? [
          ["Starting year", companyMeta.founded],
          ["Headquarters", companyMeta.hq],
          ["Global locations", companyMeta.globalLocs],
          ["Company size", companyMeta.size],
          ["Annual revenue / sales", companyMeta.revenue],
          ["Industry / sector", formatSectorName(companyMeta.sector)],
        ]
      : [];
    return {
      title: displayName,
      subtitle: "Competitor profile",
      sections: [
        { h: "Company details", rows: details },
        companyMeta && companyMeta.assess
          ? { h: "Strategic positioning & operations", rows: [companyMeta.assess] }
          : null,
        {
          h: "Leadership",
          rows: leadershipList.length
            ? leadershipList.map((l) => [l.name, l.role])
            : ["No executive officers published on public record."],
        },
        {
          h: `Company news (${companyArticles.length})`,
          rows: companyArticles.map((a) => [a.title, [a.source, a.ago, a.category].filter(Boolean).join(" · ")]),
        },
      ].filter(Boolean),
      payload: {
        cid: p.cid,
        name: displayName,
        details: companyMeta
          ? {
              startingYear: companyMeta.founded,
              hq: companyMeta.hq,
              globalLocations: companyMeta.globalLocs,
              companySize: companyMeta.size,
              revenue: companyMeta.revenue,
              sector: companyMeta.sector,
              assessment: companyMeta.assess || null,
            }
          : null,
        leadership: leadershipList.map((l) => ({ name: l.name, role: l.role, source: l.source || null })),
        news: companyArticles.map((a) => ({
          title: a.title,
          source: a.source || null,
          date: a.date || null,
          category: a.category || null,
          url: a.url || null,
        })),
      },
    };
  }, [p, displayName, companyMeta, leadershipList, companyArticles]);
  useHeaderReport(report);

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
          <select
            aria-label="Filter competitors by country"
            className="mu-fsel"
            onChange={(e) => setCountry(e.target.value)}
            style={{ width: "100%", marginTop: "8px" }}
            value={country}
          >
            <option value="all">All countries ({countryOptions.length})</option>
            {countryOptions.map((o) => (
              <option key={o.v} value={o.v}>
                {o.v} ({o.n})
              </option>
            ))}
          </select>
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
          {!list.length ? (
            <div className="cp-empty">
              {query.trim() ? <>no competitor matches “{query}”</> : "no competitor matches this filter"}
            </div>
          ) : null}
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
              <SourceLink url={activeArticle.url} source={activeArticle.source} color="#b5341f" />
            </div>

            {/* Banner Image */}
            {activeArticle.image && (
              <div style={{ width: "100%", maxHeight: "340px", overflow: "hidden", borderRadius: "6px", background: "#f0efea" }}>
                <Thumb src={activeArticle.image} alt={activeArticle.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
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
            {/* "Real-time news feed & live market intelligence" promised something nothing
                delivers: these are corpus articles, dated when they were published
                (Products already says so). And with none on file the section rendered
                its heading over nothing at all -- on the live dataset that is every
                competitor, since competitorNews is served empty -- which reads as a feed
                that failed to load rather than a corpus that holds no article. */}
            <Sec title="Company News" note={`Sourced articles naming ${displayName}`}>
              {!topStory ? (
                <div className="cp-thin" style={{ fontSize: "12px", padding: "8px 0" }}>
                  No sourced article in the corpus names {displayName}.
                </div>
              ) : null}
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
                          <Thumb src={topStory.image} alt="Top Story" className="ln-story-img" />
                          <span className="ln-top-badge">TOP STORY</span>
                        </div>
                        <div className="ln-story-content">
                          <div className="ln-story-meta">{topStory.category} · {topStory.ago}</div>
                          <h3 className="ln-story-title">{topStory.title}</h3>
                          <p className="ln-story-desc">{topStory.excerpt}</p>
                          <div className="ln-story-foot">
                            <span style={{ fontSize: "11px", color: "var(--d-txt-2)", fontWeight: "600" }}>
                              <span className="src-dot"></span>{topStory.source}
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
                      {feedArticles.slice(0, newsShown).map((item, idx) => (
                        <div
                          key={item.id || idx}
                          className="ln-feed-card"
                          onClick={() => setActiveArticle(item)}
                          style={{ cursor: "pointer" }}
                          role="button"
                          tabIndex={0}
                        >
                          <Thumb src={item.image} alt="News Thumb" className="ln-feed-thumb" />
                          <div className="ln-feed-info">
                            <div className="ln-feed-meta">{item.category} · {item.ago}</div>
                            <div className="ln-feed-title">{item.title}</div>
                            <span style={{ fontSize: "11px", color: "var(--d-txt-3)", marginTop: "auto" }}>
                              {item.source} ✓
                            </span>
                          </div>
                        </div>
                      ))}
                      {feedArticles.length > newsShown ? (
                        <button
                          type="button"
                          onClick={() => setNewsShown((n) => n + NEWS_PAGE)}
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
                          View {Math.min(NEWS_PAGE, feedArticles.length - newsShown)} more of {feedArticles.length}
                        </button>
                      ) : null}
                    </div>

                    {/* COLUMN 3: ANALYTICS & MARKET WIDGETS */}
                    <div className="ln-widget-col">
                      {/* Trending Now */}
                      <div className="ln-widget">
                        <div className="ln-widget-h">
                          TRENDING NOW
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
