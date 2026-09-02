import { useRef, useEffect } from "react";
import { useAppState, PILLARS, PILLAR_LABEL } from "../../state/AppState";

export default function TopBar() {
  const { pillar, setPillar, searchQuery, setSearchQuery } = useAppState();
  const searchRef = useRef(null);

  const goMainPage = () => {
    setPillar("competitive");
  };

  // Focus search input on Ctrl+K / Cmd+K shortcut
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        searchRef.current?.querySelector("input")?.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

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
            value={searchQuery || ""}
            onChange={(e) => setSearchQuery(e.target.value)}
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
      </div>

      <div className="topright">
        <div className="statusbox client">
          <span className="v">KSSL</span>
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

