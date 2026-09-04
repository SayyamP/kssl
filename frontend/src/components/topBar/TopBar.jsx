import { useRef, useEffect, useMemo, useState } from "react";
import { useAppState, PILLARS, PILLAR_LABEL } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { searchDataset, SEARCH_MIN_CHARS } from "../../lib/search";

/* The global search.

   FE 25: "does not work at all". After the UI port it was a live filter on whichever
   page was open, and nothing else: on a page with nothing to filter (Innovation, Geo,
   Patents, the Market report) typing changed nothing on screen, and no page ever said
   "no results". The filter stays -- Overview, Profile, Products, Positioning,
   Partnerships and Tenders still narrow to the query -- and the popover is back on top
   of it: every store in the served dataset is searched (lib/search.js, pure, tested
   under node), each hit opens the page that holds it, and a miss is stated. */
export default function TopBar() {
  const { pillar, setPillar, searchQuery, setSearchQuery, jumpTo } = useAppState();
  const { data } = useData();
  const [open, setOpen] = useState(false);
  const searchRef = useRef(null);

  const goMainPage = () => {
    setPillar("competitive");
  };

  // Focus search input on Ctrl+K / Cmd+K; Escape closes the result list
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        searchRef.current?.querySelector("input")?.focus();
        setOpen(true);
      }
      if (e.key === "Escape") setOpen(false);
    };
    const handleOutside = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleOutside);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleOutside);
    };
  }, []);

  const results = useMemo(() => searchDataset(data, searchQuery), [data, searchQuery]);

  /* What a miss was measured against. Every number is the served store's size, so
     "no results" names the corpus it searched rather than reading as a broken box. */
  const scope = useMemo(() => {
    const n = (o) => (Array.isArray(o) ? o.length : o ? Object.keys(o).length : 0);
    const innovations = Object.values(data.innovations || {}).reduce((t, rows) => t + (rows || []).length, 0);
    const parts = [
      [n(data.competitors), "competitor"],
      [n(data.matchups), "matched product"],
      [n(data.competitiveCards) + n(data.marketCards) + n(data.techCards), "signal"],
      [n(data.tenders), "tender"],
      [innovations, "innovation"],
    ].filter(([c]) => c > 0);
    return parts.map(([c, w]) => `${c} ${w}${c === 1 ? "" : "s"}`).join(", ");
  }, [data]);

  const pick = (hit) => {
    setOpen(false);
    setSearchQuery("");
    const t = hit.target;
    jumpTo(t.pillar, t.view, t.payload);
  };

  const firstHit = results.groups.length ? results.groups[0].hits[0] : null;
  const showPopover = open && searchQuery.trim().length >= SEARCH_MIN_CHARS;

  return (
    <div className="topbar">
      <div
        className="brand"
        onClick={goMainPage}
        role="button"
        tabIndex={0}
        style={{ cursor: "pointer" }}
        title="Go to main page"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            goMainPage();
          }
        }}
      >
        <span className="wordmark">
          137<span className="wm-prod">Parallax</span>
        </span>
      </div>

      <div className="topnav">
        {PILLARS.map((p) => (
          <div
            className={`pill${pillar === p ? " active" : ""}`}
            key={p}
            onClick={() => setPillar(p)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setPillar(p);
              }
            }}
          >
            <span className="dot" />
            {PILLAR_LABEL[p]}
          </div>
        ))}
      </div>

      <div className="topbar-search-wrap" ref={searchRef}>
        <div className="topbar-search-input-box">
          <span className="topbar-search-icon">⌕</span>
          <input
            aria-autocomplete="list"
            aria-expanded={showPopover}
            aria-label="Search intelligence"
            className="topbar-search-input"
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && firstHit) {
                e.preventDefault();
                pick(firstHit);
              }
            }}
            placeholder="Search intelligence (Ctrl+K)"
            type="text"
            value={searchQuery || ""}
          />
          {searchQuery && (
            <button
              aria-label="Clear search"
              className="topbar-search-clear"
              onClick={() => {
                setSearchQuery("");
                setOpen(false);
              }}
              type="button"
            >
              ✕
            </button>
          )}
        </div>

        {showPopover ? (
          <div className="topbar-search-popover" role="listbox">
            {results.total === 0 ? (
              <div className="topbar-search-empty">
                <div>No results for &ldquo;{results.query}&rdquo;</div>
                <div className="topbar-search-scope">Searched {scope || "an empty dataset"}.</div>
              </div>
            ) : (
              <>
                {results.groups.map((g) => (
                  <div className="topbar-search-section" key={g.key}>
                    <div className="topbar-search-section-title">
                      {g.label}
                      <span className="topbar-search-more">
                        {g.count > g.hits.length ? `showing ${g.hits.length} of ${g.count}` : g.count}
                      </span>
                    </div>
                    {g.hits.map((h) => (
                      <div
                        className="topbar-search-item"
                        key={h.key}
                        onClick={() => pick(h)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            pick(h);
                          }
                        }}
                        role="option"
                        tabIndex={0}
                      >
                        <span className={`topbar-search-item-badge ${g.key}`}>{g.label.split(" ")[0].toUpperCase()}</span>
                        <span className="topbar-search-item-title">{h.title}</span>
                        {h.meta ? <span className="topbar-search-item-meta">{h.meta}</span> : null}
                      </div>
                    ))}
                  </div>
                ))}
                <div className="topbar-search-foot">
                  {results.total} result{results.total === 1 ? "" : "s"} · Enter opens the first · the open page is filtered to this query where it has a list
                </div>
              </>
            )}
          </div>
        ) : null}
      </div>

      <div className="topright">
        <div className="statusbox client">
          <span className="v">{(data.client && (data.client.short || data.client.name)) || "KSSL"}</span>
        </div>
        <div className="statusbox">
          <span className="k">Feed</span>
          <span className="v">
            <span className="live" />
            Live
          </span>
        </div>
      </div>
    </div>
  );
}
