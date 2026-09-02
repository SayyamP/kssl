import { useState, useRef, useEffect, useMemo } from "react";
import { useAppState, PILLARS, PILLAR_LABEL } from "../../state/AppState";
import { useData } from "../../state/DataProvider";

export default function TopBar() {
  const { pillar, setPillar, jumpTo } = useAppState();
  const { data } = useData();
  const [searchQuery, setSearchQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const searchRef = useRef(null);

  const goMainPage = () => {
    setPillar("competitive");
  };

  // Close search popup on click outside or Escape
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (e) => {
      if (e.key === "Escape") setIsOpen(false);
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        searchRef.current?.querySelector("input")?.focus();
        setIsOpen(true);
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const results = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q || q.length < 2) return null;

    const comps = [];
    if (data.competitors) {
      Object.entries(data.competitors).forEach(([cid, c]) => {
        if (c.name?.toLowerCase().includes(q) || c.sector?.toLowerCase().includes(q) || c.hq?.toLowerCase().includes(q)) {
          comps.push({ cid, name: c.name, sector: c.sector || "Defense" });
        }
      });
    }

    const tenders = [];
    if (data.tenders) {
      data.tenders.forEach((t) => {
        if (t.title?.toLowerCase().includes(q) || t.issuer?.toLowerCase().includes(q) || t.cat?.toLowerCase().includes(q)) {
          tenders.push({ id: t.id, title: t.title, cat: t.cat, issuer: t.issuer });
        }
      });
    }

    /* Each card is carried with the pillar whose feed actually lists it. Every hit used
       to open the COMPETITIVE overview, so picking a technology or market signal landed
       on a feed that does not contain it. */
    const signals = [];
    [
      ["competitive", "overview", data.competitiveCards],
      ["market", "m-overview", data.marketCards],
      ["technology", "t-overview", data.techCards],
    ].forEach(([pillarKey, viewKey, cards]) => {
      (cards || []).forEach((card) => {
        const hay = `${card.title || ""} ${card.company || ""} ${card.tags || ""}`.toLowerCase();
        if (hay.includes(q)) {
          signals.push({
            id: card.id,
            title: card.title,
            company: card.company,
            pillar: pillarKey,
            view: viewKey,
          });
        }
      });
    });

    /* "drone" matches 264 signals. Showing four with no hint that there are 260 more
       reads as a search that only knows about four things. */
    return {
      comps: comps.slice(0, 5),
      tenders: tenders.slice(0, 5),
      signals: signals.slice(0, 8),
      counts: { comps: comps.length, tenders: tenders.length, signals: signals.length },
      total: comps.length + tenders.length + signals.length,
    };
  }, [searchQuery, data]);

  const handlePickResult = (type, item) => {
    setIsOpen(false);
    setSearchQuery("");
    if (type === "comp") {
      jumpTo("competitive", "profile", { cid: item.cid });
    } else if (type === "tender") {
      jumpTo("market", "tender", { tenderTitle: item.title });
    } else if (type === "signal") {
      jumpTo(item.pillar || "competitive", item.view || "overview", { cardId: item.id });
    }
  };

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
            type="text"
            className="topbar-search-input"
            placeholder="Search intelligence (⌘K)..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setIsOpen(true);
            }}
            onFocus={() => setIsOpen(true)}
          />
          {searchQuery && (
            <button
              className="topbar-search-clear"
              onClick={() => setSearchQuery("")}
            >
              ✕
            </button>
          )}
        </div>

        {isOpen && results && (
          <div className="topbar-search-popover">
            {results.total === 0 ? (
              <div className="topbar-search-empty">No intelligence matching "{searchQuery}"</div>
            ) : (
              <>
                {results.comps.length > 0 && (
                  <div className="topbar-search-section">
                    <div className="topbar-search-section-title">Competitors<span className="topbar-search-more">{results.counts.comps > results.comps.length ? `showing ${results.comps.length} of ${results.counts.comps}` : results.counts.comps}</span></div>
                    {results.comps.map((c) => (
                      <div
                        key={c.cid}
                        className="topbar-search-item"
                        onClick={() => handlePickResult("comp", c)}
                      >
                        <span className="topbar-search-item-badge comp">COMP</span>
                        <span className="topbar-search-item-title">{c.name}</span>
                        <span className="topbar-search-item-meta">{c.sector}</span>
                      </div>
                    ))}
                  </div>
                )}

                {results.tenders.length > 0 && (
                  <div className="topbar-search-section">
                    <div className="topbar-search-section-title">Tenders<span className="topbar-search-more">{results.counts.tenders > results.tenders.length ? `showing ${results.tenders.length} of ${results.counts.tenders}` : results.counts.tenders}</span></div>
                    {results.tenders.map((t) => (
                      <div
                        key={t.id}
                        className="topbar-search-item"
                        onClick={() => handlePickResult("tender", t)}
                      >
                        <span className="topbar-search-item-badge tender">TENDER</span>
                        <span className="topbar-search-item-title">{t.title}</span>
                        <span className="topbar-search-item-meta">{t.issuer || t.cat}</span>
                      </div>
                    ))}
                  </div>
                )}

                {results.signals.length > 0 && (
                  <div className="topbar-search-section">
                    <div className="topbar-search-section-title">Signals & Intel<span className="topbar-search-more">{results.counts.signals > results.signals.length ? `showing ${results.signals.length} of ${results.counts.signals}` : results.counts.signals}</span></div>
                    {results.signals.map((s) => (
                      <div
                        key={s.id}
                        className="topbar-search-item"
                        onClick={() => handlePickResult("signal", s)}
                      >
                        <span className="topbar-search-item-badge signal">SIGNAL</span>
                        <span className="topbar-search-item-title">{s.title}</span>
                        {s.company && <span className="topbar-search-item-meta">{s.company}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <div className="topright">
        <div className="statusbox client">
          <span className="v">{data.client?.name || "the client"}</span>
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

