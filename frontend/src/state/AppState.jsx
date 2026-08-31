import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

const AppStateContext = createContext(null);

/* Which rail item each pillar opens on, and the pillar each rail belongs to. */
export const PILLARS = ["competitive", "market", "technology"];
export const PILLAR_LABEL = {
  competitive: "Competitive",
  market: "Market",
  technology: "Technology",
};
export const RAIL = {
  /* `gap-competitive` is ARCHIVED, not deleted: it is off the rail but Layout still
     routes it, so a saved route or a pasted #v=gap-competitive link still resolves.
     Same for `awarded-tenders` / `closed-tenders`, which the Market overview now
     carries as tabs. getInitialAppState validates the PILLAR but never the view, so a
     removed case would boot a returning user into a permanently blank pane. */
  competitive: [
    { view: "overview", label: "Overview", ix: "grid", overview: true },
    { view: "profile", label: "Competitor", ix: "01" },
    { view: "products", label: "Products", ix: "02" },
    { view: "positioning", label: "Positioning", ix: "03" },
    { view: "partnerships", label: "Partnerships", ix: "04" },
    { view: "geo", label: "Geo Footprint", ix: "05" },
    { view: "patents-comp", label: "Patents", ix: "06" },
  ],
  market: [
    /* Overview is the SIGNAL FEED again, as the other two pillars' overviews are — the
       tender report that briefly occupied this slot is its own tab below. An overview
       that reads differently from every other pillar's overview is not an overview. */
    { view: "m-overview", label: "Overview", ix: "grid", overview: true },
    { view: "m-report", label: "Market Report", ix: "01" },
    { view: "tender", label: "Tender Pipeline", ix: "02" },
  ],
  technology: [
    { view: "t-overview", label: "Overview", ix: "grid", overview: true },
    { view: "innovation", label: "Innovation Pipeline", ix: "01" },
  ],
};

const OVERVIEW_VIEWS = new Set(["overview", "m-overview", "t-overview"]);
export const isOverview = (view) => OVERVIEW_VIEWS.has(view);

const getInitialAppState = () => {
  try {
    const hash = window.location.hash;
    if (hash && hash.includes("p=")) {
      const params = new URLSearchParams(hash.replace(/^#/, ""));
      const p = params.get("p");
      const v = params.get("v");
      if (p && v && PILLARS.includes(p)) return { pillar: p, view: v };
    }
    const saved = localStorage.getItem("kssl_parallax_route");
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed.pillar && parsed.view && PILLARS.includes(parsed.pillar)) return parsed;
    }
  } catch (e) {}
  return { pillar: "competitive", view: "overview" };
};

export function AppStateProvider({ children }) {
  const initial = getInitialAppState();
  const [pillar, setPillarState] = useState(initial.pillar);
  const [view, setViewState] = useState(initial.view);

  /* Sync route state to localStorage and window.location.hash */
  useEffect(() => {
    try {
      localStorage.setItem("kssl_parallax_route", JSON.stringify({ pillar, view }));
      const newHash = `#p=${encodeURIComponent(pillar)}&v=${encodeURIComponent(view)}`;
      if (window.location.hash !== newHash) {
        window.history.replaceState(null, "", newHash);
      }
    } catch (e) {}
  }, [pillar, view]);

  /* The floating assistant's context line, and the per-panel scoped chat context.
     One place, so every panel updates the same two things when its selection moves —
     the original scattered this across `window.malloryCtx` and `window.scopedCtx`. */
  const [chatCtx, setChatCtx] = useState({
    pillar: PILLAR_LABEL[pillar] || "Competitive",
    view: view,
    selection: null,
  });
  const [scoped, setScopedState] = useState({});
  // bumped whenever a scope changes, so each ScopeChat can clear its own log
  const scopeEpoch = useRef({});

  const setPillar = useCallback((next) => {
    setPillarState(next);
    setViewState(RAIL[next][0].view);
  }, []);

  const setView = useCallback((next) => {
    setViewState(next);
  }, []);

  /* A panel calls this when its selection changes: it moves the assistant's context
     line and replaces that panel's scoped answer context in one go. */
  const setScope = useCallback((key, ctxObject, chatLabel) => {
    scopeEpoch.current[key] = (scopeEpoch.current[key] || 0) + 1;
    setScopedState((prev) => ({ ...prev, [key]: ctxObject }));
    if (chatLabel) setChatCtx(chatLabel);
  }, []);

  /* Cross-pillar jumps: Gap Analysis opens a matchup in Positioning, a correlate
     chip opens a tender in Market. The target page reads `pending` on mount. */
  const [pending, setPending] = useState(null);
  const jumpTo = useCallback((nextPillar, nextView, payload) => {
    setPillarState(nextPillar);
    setViewState(nextView);
    setPending(payload ? { view: nextView, ...payload } : null);
  }, []);
  const takePending = useCallback(
    (forView) => {
      if (pending && pending.view === forView) {
        setPending(null);
        return pending;
      }
      return null;
    },
    [pending],
  );

  /* Collapse the whole left rail — set when a company/product is opened so the
     detail panel gets full width; a toggle in the rail brings it back. */
  const [railCollapsed, setRailCollapsed] = useState(false);

  const value = useMemo(
    () => ({
      pillar,
      view,
      setPillar,
      setView,
      chatCtx,
      setChatCtx,
      scoped,
      setScope,
      scopeEpoch: scopeEpoch.current,
      jumpTo,
      pending,
      takePending,
      railCollapsed,
      setRailCollapsed,
    }),
    [pillar, view, setPillar, chatCtx, scoped, setScope, jumpTo, pending, takePending, railCollapsed],
  );

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState() {
  const value = useContext(AppStateContext);
  if (!value) throw new Error("useAppState must be used within AppStateProvider");
  return value;
}
