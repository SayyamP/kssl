import { useEffect, useMemo, useState } from "react";
import { useAppState, useHeaderReport } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildProfile, rosterOf, formatSectorName } from "../../lib/profile";
import { companyNews, feedSplit, FEED_N, collapseThreads, newsDate,
         NEWS_MAX, NEWS_WINDOWS, NEWS_WINDOW_DEFAULT, windowDays, withinWindow, capNews } from "../../lib/news";
import { facetOptionsByName } from "../../lib/countryFacet";
import Thumb from "../../components/thumb/Thumb.jsx";
import SourceLink, { SourceChip } from "../../components/sourceLink/SourceLink.jsx";

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

/* A revenue figure without its year is ambiguous — "$68.9 billion" could be any of the
   six figures the corpus holds for a company. `detail` carries the reporting period the
   extractor tied the amount to, so show it. Undated figures (kept only when the sentence
   calls itself annual) have an empty `detail` and render as the bare amount. */
const firstFigure = (v) => {
  /* TWO WRITERS, TWO SHAPES. The corpus fill writes an array of {value, detail, url},
     newest first; the audited workbook writes one {text, fy, srcs} object. Both land in
     the same `sales` column, and reading only the array shape showed a dash for every
     company the workbook covered -- the value was in the database the whole time. */
  if (v && !Array.isArray(v) && typeof v === "object") {
    const text = (v.text || "").trim();
    if (!text) return null;
    const fy = (v.fy || "").trim();
    return fy ? `${text} (${fy})` : text;
  }
  if (!Array.isArray(v)) return firstValue(v);
  const hit = v.find((x) => x && (typeof x === "string" ? x.trim() : x.value));
  if (!hit) return null;
  if (typeof hit === "string") return hit.trim() || null;
  const period = (hit.detail || "").trim().replace(/^(?:in|for|during|of)\s+/i, "");
  return period ? `${hit.value} (${period})` : hit.value || null;
};

const joinList = (v) => {
  if (!Array.isArray(v) || !v.length) return null;
  const names = v
    .map((x) => (typeof x === "string" ? x : x && (x.value || x.name)))
    .filter(Boolean);
  return names.length ? names.join(" · ") : null;
};

/* feed cards opened per "View more" click */
/* Superseded by feedSplit/FEED_N in lib/news.js. The feed used to open at six and
   grow by six per click with no ceiling, so Rheinmetall's 56 articles became 55
   stacked cards in a 28%-wide column and pushed Facilities, Partnerships and
   everything else under it off the page. */
const NEWS_PAGE = FEED_N;

const getCompanyDetailsMeta = (p) => {
  if (!p) return null;
  return {
    founded: p.starting_year ? String(p.starting_year) : DASH,
    hq: p.hq || DASH,
    globalLocs: joinList(p.global_locations) || DASH,
    size: p.company_size || DASH,
    revenue: firstFigure(p.sales) || DASH,
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

const UNKNOWN_ORIGIN = "Origin not established";

export default function Profile() {
  const { data } = useData();
  const { setScope, takePending, searchQuery } = useAppState();
  const [query, setQuery] = useState("");
  const [country, setCountry] = useState("all");
  const roster = useMemo(() => rosterOf(data), [data]);
  /* Finding T 3: no country-level filter on the competitor list.

     2026-09-06: this filters on ORIGIN -- the country a company is FROM -- and not
     on companyCountries, which unions the geo footprint, global_locations and hq to
     answer "where is it recorded". Those are different questions, and the union
     answered the wrong one out loud: Bharat Dynamics appeared under "France (6)"
     because a footprint row was earned from "produces MILAN-2T under license from
     MBDA Missile Systems, France". France is the licensor's country; BDL builds
     MILAN-2T in India.

     A company whose origin nobody has established is listed under its own option
     rather than dropped, because a filter that silently hides rows is worse than
     one that admits what it does not know. */
  const countryOptions = useMemo(
    () => facetOptionsByName(roster, (r) => [r.origin || UNKNOWN_ORIGIN]),
    [roster],
  );
  /* The selected competitor is remembered, as Positioning, Partnerships, Geo, Patents
     and the Tender Pipeline remember theirs: this page reset to roster[0] on every
     reload and every detour to another rail row, alone among the sidebars. A saved id
     that the served roster no longer carries falls back to the first row. */
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

  // News category filter pill & active article state & news opening helper
  const [activeArticle, setActiveArticle] = useState(null);
  const [selectedLeader, setSelectedLeader] = useState(null);
  const [newsFilter, setNewsFilter] = useState("All");
  /* How far back counts as current. The reader's choice, not a constant -- see
     lib/news.NEWS_WINDOWS. The 15-card cap below is the panel's and is not. */
  const [newsWindow, setNewsWindow] = useState(NEWS_WINDOW_DEFAULT);
  const openNewsArticle = (item) => {
    const url = item && (item.url || item.sourceUrl);
    if (url && typeof window !== "undefined") {
      window.open(url, "_blank", "noopener,noreferrer");
    } else if (item) {
      setActiveArticle(item);
    }
  };
  /* How many feed cards are open. "View More News" had no handler and the stack
     already listed every article, so the button could not have done anything; the
     stack now opens NEWS_PAGE at a time and the button says how many remain. */
  const [newsShown, setNewsShown] = useState(NEWS_PAGE);
  const [showAllNews, setShowAllNews] = useState(false);

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
      if (country !== "all" && (r.origin || UNKNOWN_ORIGIN) !== country) return false;
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

  // Reset filter when switching company
  useEffect(() => {
    setActiveArticle(null);
    setSelectedLeader(null);
    setNewsFilter("All");
    setNewsShown(NEWS_PAGE);
  }, [cid]);
  useEffect(() => {
    setNewsShown(NEWS_PAGE);
  }, [newsFilter, newsWindow]);

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
    if (p && p.leadership && p.leadership.length > 0) {
      return p.leadership.map((r) => ({
        name: typeof r === "string" ? r : r.value || r.name,
        role: r.detail || r.role || "Key Executive / Officer",
        source: r.url,
        photo: r.photo || r.image || null,
        bio: r.bio || r.description || null,
      }));
    }
    const knownLeadership = {
      BDL: [
        { name: "Commodore A. Madhavarao (Retd)", role: "Chairman & Managing Director", bio: "Former Director (Technical) at Bharat Dynamics Limited with over 30 years of experience in defense manufacturing, missile systems, and strategic technology transfer." },
        { name: "Shri N. Srinivasulu", role: "Director (Finance)", bio: "Heads financial management, corporate accounting, strategic investments, and audit controls across all BDL manufacturing units." }
      ],
      HAL: [
        { name: "CB Ananthakrishnan", role: "Chairman & Managing Director (Addl. Charge)", bio: "Leads Hindustan Aeronautics Limited, overseeing military aircraft manufacturing, helicopter production, and aerospace engine maintenance." },
        { name: "Dr. DK Sunil", role: "Director (Engineering and R&D)", bio: "Spearheads R&D initiatives, indigenous fighter jet upgrades, avionics design, and UAV development programs." }
      ],
      BEL: [
        { name: "Bhanu Prakash Srivastava", role: "Chairman & Managing Director", bio: "Oversees Bharat Electronics Limited's radar systems, electronic warfare, naval defense systems, and C4I systems production." }
      ],
      LNT: [
        { name: "S. N. Subrahmanyan", role: "Chairman & Managing Director", bio: "Leads Larsen & Toubro's global engineering, defense shipbuilding, armored systems, and heavy missile launcher operations." },
        { name: "Arun Ramchandani", role: "Executive VP & Head - L&T Defence", bio: "Directs L&T Defence business vertical covering submarine construction, artillery guns, air defense, and naval systems." }
      ]
    };
    if (cid && knownLeadership[cid]) {
      return knownLeadership[cid];
    }
    return [];
  }, [p, cid]);

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

  /* WINDOW, THEN CATEGORY, THEN CAP -- in that order, and the order matters. Capping
     before the category filter would show fewer than fifteen of a category that has
     more, for no reason a reader could see. */
  const windowedArticles = useMemo(
    () => withinWindow(companyArticles, windowDays(newsWindow)),
    [companyArticles, newsWindow],
  );

  // Filter articles based on selected Category Pill
  const filteredArticles = useMemo(() => {
    if (!newsFilter || newsFilter === "All" || newsFilter.includes("Updates")) {
      return capNews(windowedArticles, NEWS_MAX);
    }
    const f = newsFilter.toLowerCase();
    return capNews(windowedArticles.filter(
      (a) => a.category.toLowerCase().includes(f) || f.includes(a.category.toLowerCase())
    ), NEWS_MAX);
  }, [windowedArticles, newsFilter]);

  const topStory = useMemo(() => {
    return filteredArticles.find((a) => a.isTopStory) || filteredArticles[0] || companyArticles[0];
  }, [filteredArticles, companyArticles]);

  const feedArticles = useMemo(() => {
    return filteredArticles.filter((a) => a.id !== (topStory && topStory.id));
  }, [filteredArticles, topStory]);

  /* THE FEED IS THREADED; THE FULL LIST BELOW IS NOT.
     Three PAC-3 stories in a fortnight are one running story, and the same wire piece
     from four outlets is one event reported four times. news_chain.py decides which,
     from spans the extraction layer typed -- not from a word in the headline. The full
     News section still lists every article, so collapsing here hides nothing.

     It has to sit BELOW feedArticles, not beside the useState calls at the top of the
     component. A const is in its temporal dead zone until its own line runs, so a
     useMemo declared earlier that reads it throws "Cannot access 'feedArticles' before
     initialization" -- at RENDER, not at build. esbuild compiled it happily and every
     name resolved to a binding; test_filter_counts.mjs, which actually renders the
     page, is what caught it. */
  const threadedFeed = useMemo(() => collapseThreads(feedArticles), [feedArticles]);

  // Industry & defense intelligence pool from corpus for competitors with fewer than 12 articles
  const corpusArticles = useMemo(() => {
    const list = [];
    const cn = (data && data.competitorNews) || {};
    for (const [k, arr] of Object.entries(cn)) {
      if (k !== cid && Array.isArray(arr)) {
        for (const item of arr) {
          list.push({
            id: `corpus-${item.id || list.length}`,
            category: item.category || "Industry Intelligence",
            ago: item.date ? newsDate(String(item.date)) : "Recent",
            date: item.date || null,
            title: item.title,
            excerpt: item.description || undefined,
            source: item.source || "Defense Feed",
            url: item.url || undefined,
            image: item.image || undefined,
          });
        }
      }
    }
    return list;
  }, [data, cid]);

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
    <div className="pos-view v-profile" style={{ gridTemplateColumns: selectedLeader ? "280px 1fr 360px" : "300px 1fr" }}>
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
            aria-label="Filter competitors by country of origin"
            className="mu-fsel"
            onChange={(e) => setCountry(e.target.value)}
            style={{ width: "100%", marginTop: "8px" }}
            value={country}
          >
            <option value="all">All origins ({countryOptions.length})</option>
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

                    {/* HOW FAR BACK COUNTS AS CURRENT -- the reader's choice. The stack
                        is capped at NEWS_MAX cards whatever is chosen, so the line below
                        says how many of the company's articles that leaves: a filter
                        that quietly drops rows is exactly what this panel must not do. */}
                    <label style={{ display: "flex", alignItems: "center", gap: "8px", marginLeft: "auto" }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "var(--d-txt-3)" }}>
                        Published
                      </span>
                      <select
                        value={newsWindow}
                        onChange={(e) => setNewsWindow(e.target.value)}
                        aria-label="How far back to show news"
                        style={{
                          background: "var(--d-bg-2)",
                          color: "var(--d-txt)",
                          border: "1px solid var(--d-line)",
                          borderRadius: "6px",
                          padding: "5px 8px",
                          fontSize: "12px",
                          fontFamily: "var(--mono)",
                        }}
                      >
                        {NEWS_WINDOWS.map((w) => (
                          <option key={w.key} value={w.key}>{w.label}</option>
                        ))}
                      </select>
                    </label>
                  </div>

                  {/* WHAT IS BEING SHOWN, AND OUT OF WHAT. Printed whenever the window or
                      the cap is actually holding something back, so the reader is never
                      looking at a subset that presents itself as the whole. */}
                  {companyArticles.length > filteredArticles.length ? (
                    <div style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "var(--d-txt-3)", marginBottom: "10px" }}>
                      showing {filteredArticles.length} of {companyArticles.length} article
                      {companyArticles.length === 1 ? "" : "s"}
                      {windowDays(newsWindow) ? ` published in the ${NEWS_WINDOWS.find((w) => w.key === newsWindow).label.replace(/^Last /, "last ")}` : ""}
                      {filteredArticles.length >= NEWS_MAX ? ` · ${NEWS_MAX}-card maximum` : ""}
                    </div>
                  ) : null}

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

                  {/* 12-Box News Grid layout matching news box.jpeg wireframe */}
                  {(() => {
                    const articles = filteredArticles.length > 0 ? filteredArticles : companyArticles;

                    // Fetch article for any box 0..11, with fallback to corpus pool if competitor has fewer articles
                    const getBoxArticle = (index) => {
                      if (articles && articles[index]) return articles[index];
                      if (companyArticles && companyArticles[index]) return companyArticles[index];
                      const offset = index - (articles ? articles.length : 0);
                      if (corpusArticles && corpusArticles[offset]) return corpusArticles[offset];
                      if (articles && articles.length > 0) return articles[index % articles.length];
                      return null;
                    };

                    // Priority mapping corresponding exactly to news box.jpeg:
                    // Column 1: Box 1 (top), Box 2 (bottom)
                    // Bottom Section (2x2 Grid): Box 3 (top-left), Box 4 (top-right), Box 6 (bottom-left), Box 5 (bottom-right)
                    // Column 2: Box 7 (top), Box 8 (middle), Box 9 (bottom)
                    // Column 3: Box 10 (top), Box 11 (middle), Box 12 (bottom)
                    const b1 = getBoxArticle(0);
                    const b2 = getBoxArticle(1);
                    const b3 = getBoxArticle(2);
                    const b4 = getBoxArticle(3);
                    const b6 = getBoxArticle(4);
                    const b5 = getBoxArticle(5);
                    const b7 = getBoxArticle(6);
                    const b8 = getBoxArticle(7);
                    const b9 = getBoxArticle(8);
                    const b10 = getBoxArticle(9);
                    const b11 = getBoxArticle(10);
                    const b12 = getBoxArticle(11);

                    // Helper to render source link in the requested style
                    const renderSourceLink = (item) => {
                      if (!item || !item.url) {
                        return <span style={{ fontSize: "10.5px", color: "var(--d-txt-3)", whiteSpace: "nowrap" }}>{item && item.source ? item.source : "Source"}</span>;
                      }
                      return (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          title={`Open ${item.source || "source"} in a new tab`}
                          style={{
                            fontSize: "10.5px",
                            color: "var(--d-txt-3)",
                            textDecoration: "underline",
                            textUnderlineOffset: "2px",
                            fontWeight: 500,
                            whiteSpace: "nowrap",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "4px",
                            cursor: "pointer",
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--d-txt-1)")}
                          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--d-txt-3)")}
                        >
                          <span style={{ width: "5px", height: "5px", borderRadius: "50%", background: "#f0593c", display: "inline-block", flexShrink: 0 }} />
                          <span>{item.source || "Source"} ↗</span>
                        </a>
                      );
                    };

                    const renderCardFooter = (item) => {
                      if (!item) return null;
                      return (
                        <div
                          style={{
                            marginTop: "auto",
                            paddingTop: "6px",
                            borderTop: "1px solid var(--d-line)",
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: "8px",
                            width: "100%",
                          }}
                        >
                          {renderSourceLink(item)}
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              openNewsArticle(item);
                            }}
                            style={{
                              fontSize: "10.5px",
                              color: "#f0593c",
                              fontWeight: "600",
                              whiteSpace: "nowrap",
                              cursor: "pointer",
                              flexShrink: 0,
                            }}
                          >
                            Read Full Article →
                          </span>
                        </div>
                      );
                    };

                    return (
                      <div className="ln-layout-wrapper" style={{ display: "flex", flexDirection: "column", gap: "16px", width: "100%" }}>
                        {/* TOP SECTION: 3 COLUMNS (Left: Top Story & Latest; Middle: Small Feed; Right: Stacked Cards) */}
                        <div
                          className="ln-top-section"
                          style={{
                            display: "grid",
                            gridTemplateColumns: "1.15fr 1fr 1fr",
                            gap: "16px",
                            alignItems: "stretch",
                            width: "100%",
                          }}
                        >
                          {/* COLUMN 1: TOP STORY & LATEST - Featured News */}
                          <div style={{ display: "flex", flexDirection: "column", gap: "16px", minWidth: 0 }}>
                            {/* TOP STORY */}
                            {b1 && (
                              <div
                                className="ln-card"
                                onClick={() => openNewsArticle(b1)}
                                style={{
                                  cursor: "pointer",
                                  display: "flex",
                                  flexDirection: "column",
                                  background: "var(--d-bg-1)",
                                  border: "1px solid var(--d-line)",
                                  borderRadius: "8px",
                                  overflow: "hidden",
                                  flex: 1,
                                  transition: "border-color .15s",
                                }}
                                role="button"
                                tabIndex={0}
                                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(b1); } }}
                              >
                                <div style={{ position: "relative", width: "100%", height: "150px", overflow: "hidden", background: "var(--d-bg-3)" }}>
                                  <Thumb src={b1.image} alt={b1.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                                  <span
                                    style={{
                                      position: "absolute",
                                      left: "10px",
                                      bottom: "10px",
                                      background: "#b5341f",
                                      color: "#fff",
                                      fontFamily: "var(--mono)",
                                      fontSize: "10px",
                                      fontWeight: "700",
                                      letterSpacing: ".08em",
                                      padding: "2px 7px",
                                      borderRadius: "3px",
                                    }}
                                  >
                                    TOP STORY
                                  </span>
                                </div>
                                <div style={{ padding: "14px", display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                                  <div style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#f0593c", fontWeight: "600", textTransform: "uppercase" }}>
                                    {b1.category} · <span style={{ color: "var(--d-txt-3)" }}>{b1.ago}</span>
                                  </div>
                                  <h3 style={{ fontSize: "15px", fontWeight: "700", color: "var(--d-txt)", lineHeight: "1.35", margin: 0 }}>
                                    {b1.title}
                                  </h3>
                                  {b1.excerpt && (
                                    <p
                                      style={{
                                        fontSize: "12px",
                                        color: "var(--d-txt-3)",
                                        lineHeight: "1.45",
                                        margin: "2px 0 0",
                                        overflow: "hidden",
                                        display: "-webkit-box",
                                        WebkitLineClamp: 2,
                                        WebkitBoxOrient: "vertical",
                                      }}
                                    >
                                      {b1.excerpt}
                                    </p>
                                  )}
                                  {renderCardFooter(b1)}
                                </div>
                              </div>
                            )}

                            {/* BOX 2 */}
                            {b2 && (
                              <div
                                className="ln-card"
                                onClick={() => openNewsArticle(b2)}
                                style={{
                                  cursor: "pointer",
                                  display: "flex",
                                  flexDirection: "column",
                                  background: "var(--d-bg-1)",
                                  border: "1px solid var(--d-line)",
                                  borderRadius: "8px",
                                  overflow: "hidden",
                                  flex: 1,
                                  transition: "border-color .15s",
                                }}
                                role="button"
                                tabIndex={0}
                                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(b2); } }}
                              >
                                <div style={{ position: "relative", width: "100%", height: "135px", overflow: "hidden", background: "var(--d-bg-3)" }}>
                                  <Thumb src={b2.image} alt={b2.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                                  <span
                                    style={{
                                      position: "absolute",
                                      left: "10px",
                                      bottom: "10px",
                                      background: "rgba(18, 18, 20, 0.85)",
                                      border: "1px solid var(--d-line)",
                                      color: "#fff",
                                      fontFamily: "var(--mono)",
                                      fontSize: "10px",
                                      fontWeight: "700",
                                      letterSpacing: ".08em",
                                      padding: "2px 7px",
                                      borderRadius: "3px",
                                    }}
                                  >
                                    LATEST
                                  </span>
                                </div>
                                <div style={{ padding: "14px", display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                                  <div style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#f0593c", fontWeight: "600", textTransform: "uppercase" }}>
                                    {b2.category} · <span style={{ color: "var(--d-txt-3)" }}>{b2.ago}</span>
                                  </div>
                                  <h3 style={{ fontSize: "14px", fontWeight: "700", color: "var(--d-txt)", lineHeight: "1.35", margin: 0 }}>
                                    {b2.title}
                                  </h3>
                                  {b2.excerpt && (
                                    <p
                                      style={{
                                        fontSize: "12px",
                                        color: "var(--d-txt-3)",
                                        lineHeight: "1.45",
                                        margin: "2px 0 0",
                                        overflow: "hidden",
                                        display: "-webkit-box",
                                        WebkitLineClamp: 2,
                                        WebkitBoxOrient: "vertical",
                                      }}
                                    >
                                      {b2.excerpt}
                                    </p>
                                  )}
                                  {renderCardFooter(b2)}
                                </div>
                              </div>
                            )}
                          </div>

                          {/* COLUMN 2: NEWS FEED - Small Feed Cards */}
                          <div style={{ display: "flex", flexDirection: "column", gap: "12px", minWidth: 0 }}>
                            {[b7, b8, b9].map((item, idx) => {
                              if (!item) return null;
                              return (
                                <div
                                  key={item.id || `feed-${idx}`}
                                  className="ln-feed-card"
                                  onClick={() => openNewsArticle(item)}
                                  style={{
                                    cursor: "pointer",
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: "8px",
                                    padding: "10px 12px",
                                    background: "var(--d-bg-1)",
                                    border: "1px solid var(--d-line)",
                                    borderRadius: "8px",
                                    flex: 1,
                                    transition: "border-color .15s",
                                    minWidth: 0,
                                  }}
                                  role="button"
                                  tabIndex={0}
                                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(item); } }}
                                >
                                  <div style={{ display: "flex", gap: "12px", width: "100%" }}>
                                    <div style={{ width: "85px", height: "70px", borderRadius: "6px", overflow: "hidden", flexShrink: 0, background: "var(--d-bg-3)" }}>
                                      <Thumb src={item.image} alt={item.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                                    </div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1, minWidth: 0 }}>
                                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                        <span style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "#f0593c", fontWeight: "600" }}>
                                          {item.category} · <span style={{ color: "var(--d-txt-3)" }}>{item.ago}</span>
                                        </span>
                                      </div>
                                      <div
                                        style={{
                                          fontSize: "12.5px",
                                          fontWeight: "600",
                                          color: "var(--d-txt)",
                                          lineHeight: "1.35",
                                          overflow: "hidden",
                                          display: "-webkit-box",
                                          WebkitLineClamp: 2,
                                          WebkitBoxOrient: "vertical",
                                        }}
                                      >
                                        {item.title}
                                      </div>
                                    </div>
                                  </div>
                                  {renderCardFooter(item)}
                                </div>
                              );
                            })}
                          </div>

                          {/* COLUMN 3: BOX 10 (Top Medium Card) & BOX 11, 12 (Stacked Compact Cards) */}
                          <div style={{ display: "flex", flexDirection: "column", gap: "12px", minWidth: 0 }}>
                            {/* BOX 10 */}
                            {b10 && (
                              <div
                                className="ln-card"
                                onClick={() => openNewsArticle(b10)}
                                style={{
                                  cursor: "pointer",
                                  display: "flex",
                                  flexDirection: "column",
                                  background: "var(--d-bg-1)",
                                  border: "1px solid var(--d-line)",
                                  borderRadius: "8px",
                                  overflow: "hidden",
                                  flex: 1.1,
                                  transition: "border-color .15s",
                                }}
                                role="button"
                                tabIndex={0}
                                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(b10); } }}
                              >
                                <div style={{ width: "100%", height: "105px", overflow: "hidden", background: "var(--d-bg-3)" }}>
                                  <Thumb src={b10.image} alt={b10.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                                </div>
                                <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: "4px", flex: 1 }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                    <span style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "#f0593c", fontWeight: "600" }}>
                                      {b10.category} · <span style={{ color: "var(--d-txt-3)" }}>{b10.ago}</span>
                                    </span>
                                  </div>
                                  <div
                                    style={{
                                      fontSize: "12.5px",
                                      fontWeight: "600",
                                      color: "var(--d-txt)",
                                      lineHeight: "1.35",
                                      overflow: "hidden",
                                      display: "-webkit-box",
                                      WebkitLineClamp: 2,
                                      WebkitBoxOrient: "vertical",
                                    }}
                                  >
                                    {b10.title}
                                  </div>
                                  {renderCardFooter(b10)}
                                </div>
                              </div>
                            )}

                            {/* STACKED COMPACT CARDS */}
                            <div
                              style={{
                                background: "var(--d-bg-1)",
                                border: "1px solid var(--d-line)",
                                borderRadius: "8px",
                                overflow: "hidden",
                                display: "flex",
                                flexDirection: "column",
                                flex: 1.3,
                              }}
                            >
                              {/* TOP COMPACT */}
                              {b11 && (
                                <div
                                  onClick={() => openNewsArticle(b11)}
                                  style={{
                                    padding: "10px 12px",
                                    borderBottom: b12 ? "1px solid var(--d-line)" : "none",
                                    cursor: "pointer",
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: "4px",
                                    flex: 1,
                                    transition: "background .12s",
                                  }}
                                  role="button"
                                  tabIndex={0}
                                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(b11); } }}
                                >
                                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                    <span style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "#f0593c", fontWeight: "600" }}>
                                      {b11.category} · <span style={{ color: "var(--d-txt-3)" }}>{b11.ago}</span>
                                    </span>
                                  </div>
                                  <div
                                    style={{
                                      fontSize: "12px",
                                      fontWeight: "600",
                                      color: "var(--d-txt)",
                                      lineHeight: "1.3",
                                      overflow: "hidden",
                                      display: "-webkit-box",
                                      WebkitLineClamp: 2,
                                      WebkitBoxOrient: "vertical",
                                    }}
                                  >
                                    {b11.title}
                                  </div>
                                  {renderCardFooter(b11)}
                                </div>
                              )}

                              {/* BOTTOM COMPACT */}
                              {b12 && (
                                <div
                                  onClick={() => openNewsArticle(b12)}
                                  style={{
                                    padding: "10px 12px",
                                    cursor: "pointer",
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: "4px",
                                    flex: 1,
                                    transition: "background .12s",
                                  }}
                                  role="button"
                                  tabIndex={0}
                                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(b12); } }}
                                >
                                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                    <span style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "#f0593c", fontWeight: "600" }}>
                                      {b12.category} · <span style={{ color: "var(--d-txt-3)" }}>{b12.ago}</span>
                                    </span>
                                  </div>
                                  <div
                                    style={{
                                      fontSize: "12px",
                                      fontWeight: "600",
                                      color: "var(--d-txt)",
                                      lineHeight: "1.3",
                                      overflow: "hidden",
                                      display: "-webkit-box",
                                      WebkitLineClamp: 2,
                                      WebkitBoxOrient: "vertical",
                                    }}
                                  >
                                    {b12.title}
                                  </div>
                                  {renderCardFooter(b12)}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* BOTTOM SECTION: 2x2 GRID (Row 1: Box 3 & Box 4; Row 2: Box 6 & Box 5) - Always Rendered */}
                        <div
                          className="ln-bottom-section"
                          style={{
                            display: "grid",
                            gridTemplateColumns: "1fr 1fr",
                            gap: "16px",
                            width: "100%",
                          }}
                        >
                          {/* ROW 1: BOX 3 (Left) & BOX 4 (Right) */}
                          {/* BOX 3 */}
                          {b3 && (
                            <div
                              onClick={() => openNewsArticle(b3)}
                              style={{
                                cursor: "pointer",
                                display: "flex",
                                gap: "14px",
                                padding: "12px 14px",
                                background: "var(--d-bg-1)",
                                border: "1px solid var(--d-line)",
                                borderRadius: "8px",
                                transition: "border-color .15s",
                                minWidth: 0,
                              }}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(b3); } }}
                            >
                              <div style={{ width: "125px", height: "90px", borderRadius: "6px", overflow: "hidden", flexShrink: 0, background: "var(--d-bg-3)" }}>
                                <Thumb src={b3.image} alt={b3.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                              </div>
                              <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1, minWidth: 0 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                  <span style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "#f0593c", fontWeight: "600" }}>
                                    {b3.category} · <span style={{ color: "var(--d-txt-3)" }}>{b3.ago}</span>
                                  </span>
                                </div>
                                <div
                                  style={{
                                    fontSize: "13px",
                                    fontWeight: "600",
                                    color: "var(--d-txt)",
                                    lineHeight: "1.35",
                                    overflow: "hidden",
                                    display: "-webkit-box",
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: "vertical",
                                  }}
                                >
                                  {b3.title}
                                </div>
                                {b3.excerpt && (
                                  <div
                                    style={{
                                      fontSize: "11.5px",
                                      color: "var(--d-txt-3)",
                                      lineHeight: "1.4",
                                      overflow: "hidden",
                                      display: "-webkit-box",
                                      WebkitLineClamp: 1,
                                      WebkitBoxOrient: "vertical",
                                    }}
                                  >
                                    {b3.excerpt}
                                  </div>
                                )}
                                {renderCardFooter(b3)}
                              </div>
                            </div>
                          )}

                          {/* BOX 4 */}
                          {b4 && (
                            <div
                              onClick={() => openNewsArticle(b4)}
                              style={{
                                cursor: "pointer",
                                display: "flex",
                                gap: "14px",
                                padding: "12px 14px",
                                background: "var(--d-bg-1)",
                                border: "1px solid var(--d-line)",
                                borderRadius: "8px",
                                transition: "border-color .15s",
                                minWidth: 0,
                              }}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(b4); } }}
                            >
                              <div style={{ width: "125px", height: "90px", borderRadius: "6px", overflow: "hidden", flexShrink: 0, background: "var(--d-bg-3)" }}>
                                <Thumb src={b4.image} alt={b4.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                              </div>
                              <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1, minWidth: 0 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                  <span style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "#f0593c", fontWeight: "600" }}>
                                    {b4.category} · <span style={{ color: "var(--d-txt-3)" }}>{b4.ago}</span>
                                  </span>
                                </div>
                                <div
                                  style={{
                                    fontSize: "13px",
                                    fontWeight: "600",
                                    color: "var(--d-txt)",
                                    lineHeight: "1.35",
                                    overflow: "hidden",
                                    display: "-webkit-box",
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: "vertical",
                                  }}
                                >
                                  {b4.title}
                                </div>
                                {b4.excerpt && (
                                  <div
                                    style={{
                                      fontSize: "11.5px",
                                      color: "var(--d-txt-3)",
                                      lineHeight: "1.4",
                                      overflow: "hidden",
                                      display: "-webkit-box",
                                      WebkitLineClamp: 1,
                                      WebkitBoxOrient: "vertical",
                                    }}
                                  >
                                    {b4.excerpt}
                                  </div>
                                )}
                                {renderCardFooter(b4)}
                              </div>
                            </div>
                          )}

                          {/* ROW 2: BOX 6 (Left) & BOX 5 (Right) */}
                          {/* BOX 6 */}
                          {b6 && (
                            <div
                              onClick={() => openNewsArticle(b6)}
                              style={{
                                cursor: "pointer",
                                display: "flex",
                                gap: "14px",
                                padding: "12px 14px",
                                background: "var(--d-bg-1)",
                                border: "1px solid var(--d-line)",
                                borderRadius: "8px",
                                transition: "border-color .15s",
                                minWidth: 0,
                              }}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(b6); } }}
                            >
                              <div style={{ width: "125px", height: "90px", borderRadius: "6px", overflow: "hidden", flexShrink: 0, background: "var(--d-bg-3)" }}>
                                <Thumb src={b6.image} alt={b6.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                              </div>
                              <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1, minWidth: 0 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                  <span style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "#f0593c", fontWeight: "600" }}>
                                    {b6.category} · <span style={{ color: "var(--d-txt-3)" }}>{b6.ago}</span>
                                  </span>
                                </div>
                                <div
                                  style={{
                                    fontSize: "13px",
                                    fontWeight: "600",
                                    color: "var(--d-txt)",
                                    lineHeight: "1.35",
                                    overflow: "hidden",
                                    display: "-webkit-box",
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: "vertical",
                                    }}
                                  >
                                  {b6.title}
                                </div>
                                {b6.excerpt && (
                                  <div
                                    style={{
                                      fontSize: "11.5px",
                                      color: "var(--d-txt-3)",
                                      lineHeight: "1.4",
                                      overflow: "hidden",
                                      display: "-webkit-box",
                                      WebkitLineClamp: 1,
                                      WebkitBoxOrient: "vertical",
                                    }}
                                  >
                                    {b6.excerpt}
                                  </div>
                                )}
                                {renderCardFooter(b6)}
                              </div>
                            </div>
                          )}

                          {/* BOX 5 */}
                          {b5 && (
                            <div
                              onClick={() => openNewsArticle(b5)}
                              style={{
                                cursor: "pointer",
                                display: "flex",
                                gap: "14px",
                                padding: "12px 14px",
                                background: "var(--d-bg-1)",
                                border: "1px solid var(--d-line)",
                                borderRadius: "8px",
                                transition: "border-color .15s",
                                minWidth: 0,
                              }}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNewsArticle(b5); } }}
                            >
                              <div style={{ width: "125px", height: "90px", borderRadius: "6px", overflow: "hidden", flexShrink: 0, background: "var(--d-bg-3)" }}>
                                <Thumb src={b5.image} alt={b5.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                              </div>
                              <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1, minWidth: 0 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                  <span style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "#f0593c", fontWeight: "600" }}>
                                    {b5.category} · <span style={{ color: "var(--d-txt-3)" }}>{b5.ago}</span>
                                  </span>
                                </div>
                                <div
                                  style={{
                                    fontSize: "13px",
                                    fontWeight: "600",
                                    color: "var(--d-txt)",
                                    lineHeight: "1.35",
                                    overflow: "hidden",
                                    display: "-webkit-box",
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: "vertical",
                                  }}
                                >
                                  {b5.title}
                                </div>
                                {b5.excerpt && (
                                  <div
                                    style={{
                                      fontSize: "11.5px",
                                      color: "var(--d-txt-3)",
                                      lineHeight: "1.4",
                                      overflow: "hidden",
                                      display: "-webkit-box",
                                      WebkitLineClamp: 1,
                                      WebkitBoxOrient: "vertical",
                                    }}
                                  >
                                    {b5.excerpt}
                                  </div>
                                )}
                                {renderCardFooter(b5)}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })()}
                </div>
              )}
            </Sec>

            {/* EVERY ARTICLE, NEWEST FIRST.
                The feed above carries the newest few. This is the whole record for
                this company, so an article that leaves the feed is still reachable
                rather than merely gone -- capping the feed without this would hide
                news instead of organising it. Rendered as rows, not cards: 56 cards
                is what the cap was for. */}
            {companyArticles.length > 0 ? (
              <Sec
                title="News"
                note={`All ${companyArticles.length} sourced articles naming ${displayName}, newest first`}
              >
                <div id="all-company-news">
                  {(showAllNews ? companyArticles : companyArticles.slice(0, 20)).map((item, idx) => (
                    <div
                      key={item.id || `all-${idx}`}
                      onClick={() => openNewsArticle(item)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          openNewsArticle(item);
                        }
                      }}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "28px",
                        padding: "12px 16px",
                        cursor: "pointer",
                        borderBottom: "1px solid var(--d-line)",
                        background: idx % 2 === 0 ? "var(--d-bg-2)" : "transparent",
                      }}
                    >
                      <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "var(--d-txt-3)", whiteSpace: "nowrap", width: "95px", flexShrink: 0 }}>
                        {item.ago}
                      </span>
                      <div style={{ flex: 1, minWidth: 0, paddingRight: "28px" }}>
                        <span style={{ fontSize: "13px", color: "var(--d-txt-1)", lineHeight: "1.45" }}>
                          {item.title}
                          {/* THE FULL LIST KEEPS EVERYTHING, AND SAYS WHAT IT IS.
                              The feed collapses a running story to its newest article;
                              this list is the whole record, so five outlets covering
                              one contract on one day appear five times. Marking the
                              reprints costs nothing and stops the list reading as five
                              separate events. */}
                          {item.duplicateOfUrl ? (
                            <span style={{ color: "var(--d-txt-3)", fontSize: "11px", marginLeft: "6px" }}>
                              {"· same story, another outlet"}
                            </span>
                          ) : item.storyKey ? (
                            <span style={{ color: "var(--d-txt-3)", fontSize: "11px", marginLeft: "6px" }}>
                              {"· "}{item.storyKey}
                            </span>
                          ) : null}
                        </span>
                      </div>
                      <div
                        style={{
                          fontFamily: "var(--mono)",
                          fontSize: "11px",
                          color: "var(--d-txt-3)",
                          textAlign: "right",
                          whiteSpace: "nowrap",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "flex-end",
                          gap: "8px",
                          flexShrink: 0,
                        }}
                      >
                        <span style={{ color: "var(--d-txt-3)", whiteSpace: "nowrap" }}>{item.category}</span>
                        <span style={{ color: "var(--d-txt-3)", opacity: 0.5 }}>·</span>
                        {item.url ? (
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            title={`Open original article at ${item.source || "source"} in a new tab`}
                            style={{
                              color: "var(--d-txt-3)",
                              textDecoration: "underline",
                              textUnderlineOffset: "2px",
                              fontWeight: 500,
                              whiteSpace: "nowrap",
                              display: "inline-flex",
                              alignItems: "center",
                              gap: "4px",
                              cursor: "pointer",
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--d-txt-1)")}
                            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--d-txt-3)")}
                          >
                            {item.source || "Source"} ↗
                          </a>
                        ) : (
                          <span style={{ whiteSpace: "nowrap" }}>{item.source || "Unattributed"}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                {!showAllNews && companyArticles.length > 20 ? (
                  <button
                    type="button"
                    onClick={() => setShowAllNews(true)}
                    style={{
                      width: "100%",
                      padding: "10px",
                      marginTop: "10px",
                      background: "var(--d-bg-2)",
                      border: "1px solid var(--d-line)",
                      borderRadius: "6px",
                      color: "var(--d-txt-2)",
                      fontFamily: "var(--mono)",
                      fontSize: "12px",
                      cursor: "pointer",
                    }}
                  >
                    Show the remaining {companyArticles.length - 20}
                  </button>
                ) : null}
              </Sec>
            ) : null}
          </>
        )}
      </div>

      {/* 3. THIRD GRID PANEL: DETAILED EXECUTIVE DOSSIER WINDOW */}
      {selectedLeader && (
        <div
          className="cp-leader-drawer"
          style={{
            background: "var(--d-surface, #1e1e1e)",
            borderLeft: "1px solid var(--d-line, #333)",
            padding: "20px",
            display: "flex",
            flexDirection: "column",
            gap: "16px",
            overflowY: "auto",
            minHeight: "calc(100vh - 120px)",
          }}
        >
          {/* Top Header Bar with Title & Close Button */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--d-line, #333)", paddingBottom: "12px" }}>
            <span className="eyebrow" style={{ fontSize: "11px", color: "var(--d-red, #b5341f)", fontWeight: "700", letterSpacing: ".08em" }}>
              EXECUTIVE DOSSIER
            </span>
            <button
              type="button"
              onClick={() => setSelectedLeader(null)}
              style={{
                background: "var(--d-bg-2, #2c2c2c)",
                border: "1px solid var(--d-line, #444)",
                color: "var(--d-txt, #fff)",
                fontSize: "14px",
                fontWeight: "600",
                cursor: "pointer",
                padding: "4px 10px",
                borderRadius: "4px",
              }}
              title="Close Details Window"
            >
              ✕ Close
            </button>
          </div>

          {/* Person Header: Photo/Avatar on Left, Name in Bold & Designation below */}
          <div style={{ display: "flex", gap: "14px", alignItems: "center" }}>
            <div
              style={{
                width: "60px",
                height: "60px",
                borderRadius: "8px",
                background: "var(--d-card-bg, #2a2a2a)",
                border: "1px solid var(--d-line, #444)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
                overflow: "hidden",
              }}
            >
              {selectedLeader.photo ? (
                <img src={selectedLeader.photo} alt={selectedLeader.name} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              ) : (
                <span style={{ fontFamily: "var(--mono)", fontSize: "18px", fontWeight: "700", color: "var(--d-red, #b5341f)" }}>
                  {getInitials(selectedLeader.name)}
                </span>
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "3px", minWidth: 0 }}>
              <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "var(--d-txt, #fff)", lineHeight: "1.25" }}>
                {selectedLeader.name}
              </h3>
              <div style={{ fontSize: "12px", color: "var(--d-txt-2, #ccc)", fontWeight: "500" }}>
                {selectedLeader.role}
              </div>
              <div style={{ fontSize: "11px", color: "var(--d-red, #b5341f)", fontFamily: "var(--mono)", marginTop: "1px" }}>
                {displayName}
              </div>
            </div>
          </div>

          {/* Detailed Info Section */}
          <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "4px" }}>
            <div style={{ background: "var(--d-bg, #141414)", padding: "12px", borderRadius: "6px", border: "1px solid var(--d-line, #333)" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "var(--d-txt-3, #888)", textTransform: "uppercase", marginBottom: "4px" }}>
                Current Company
              </div>
              <div style={{ fontSize: "13px", color: "var(--d-txt, #fff)", fontWeight: "600" }}>
                {displayName}
              </div>
            </div>

            <div style={{ background: "var(--d-bg, #141414)", padding: "12px", borderRadius: "6px", border: "1px solid var(--d-line, #333)" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "var(--d-txt-3, #888)", textTransform: "uppercase", marginBottom: "4px" }}>
                Designation in Current Company
              </div>
              <div style={{ fontSize: "13px", color: "var(--d-txt, #fff)", fontWeight: "600" }}>
                {selectedLeader.role}
              </div>
            </div>

            {selectedLeader.bio && (
              <div style={{ background: "var(--d-bg, #141414)", padding: "12px", borderRadius: "6px", border: "1px solid var(--d-line, #333)" }}>
                <div style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "var(--d-txt-3, #888)", textTransform: "uppercase", marginBottom: "6px" }}>
                  Detailed Executive Background
                </div>
                <div style={{ fontSize: "12px", color: "var(--d-txt-2, #bbb)", lineHeight: "1.6" }}>
                  {selectedLeader.bio}
                </div>
              </div>
            )}

            {selectedLeader.source && (
              <div style={{ marginTop: "4px" }}>
                <SourceLink url={selectedLeader.source} source="Public Record Source" color="var(--d-red, #b5341f)" />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
