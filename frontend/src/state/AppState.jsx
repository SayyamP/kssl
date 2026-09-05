import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { PILLARS, PILLAR_LABEL, RAIL, isOverview, parseRoute, resolveRoute } from "../lib/route.js";

const AppStateContext = createContext(null);

/* The rail, the pillars and the route resolver live in lib/route.js (pure, tested
   under node); re-exported here so every existing import keeps working. */
export { PILLARS, PILLAR_LABEL, RAIL, isOverview };

const ROUTE_KEY = "kssl_parallax_route";

/* The hash first, then the saved route, then the default -- and every one of them
   resolved to a page. The hash used to be taken as written once its pillar was
   known, so a link carrying a view no case in Layout handles (#v=nonsense, or a view
   renamed in a later build) booted into a permanently blank pane and was then SAVED,
   so the blank pane came back on every later visit. */
const readSavedRoute = () => {
  try {
    const saved = localStorage.getItem(ROUTE_KEY);
    return saved ? JSON.parse(saved) : null;
  } catch (e) {
    return null;
  }
};

const getInitialAppState = () => {
  let hash = "";
  try {
    hash = window.location.hash;
  } catch (e) {}
  return resolveRoute(hash, readSavedRoute());
};

export function AppStateProvider({ children }) {
  const initial = getInitialAppState();
  const [pillar, setPillarState] = useState(initial.pillar);
  const [view, setViewState] = useState(initial.view);

  /* Sync route state to localStorage and window.location.hash */
  useEffect(() => {
    try {
      localStorage.setItem(ROUTE_KEY, JSON.stringify({ pillar, view }));
      const newHash = `#p=${encodeURIComponent(pillar)}&v=${encodeURIComponent(view)}`;
      if (window.location.hash !== newHash) {
        window.history.replaceState(null, "", newHash);
      }
    } catch (e) {}
  }, [pillar, view]);

  /* The hash is a live input, not a boot-time one. It was read once at start-up and
     never again, so editing it in the address bar -- the one thing a URL invites --
     changed nothing on screen. replaceState above does not fire this, so the app's
     own writes do not loop back; only a hand edit, or a link opened in this tab, does. */
  useEffect(() => {
    const onHash = () => {
      const next = parseRoute(window.location.hash);
      if (!next) return;
      const r = resolveRoute(window.location.hash, null);
      setPillarState(r.pillar);
      setViewState(r.view);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

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

  /* Global search query state used by the top bar to filter the currently open page's rows live */
  const [searchQuery, setSearchQuery] = useState("");

  /* What the open view is showing, published by the view itself for the header's
     Copy Summary / Export JSON / Print Report. See lib/report.js for the shape. Null
     when the view has not published one; the header then says so rather than reaching
     for another view's data. Withdrawn by the publishing view's own unmount (see
     useHeaderReport) -- NOT by an effect here on `view`: a parent's effects run after
     its children's, so a clear-on-navigate up here would fire after the new page had
     already published and wipe it. */
  const [headerReport, setHeaderReport] = useState(null);

  /* Cleared on navigation. The box filters the page in view, so carrying a query across
     a page change silently filtered the next page's rows -- a reader who searched
     "drone" on Overview then opened Products found a near-empty sidebar and nothing
     saying why. */
  useEffect(() => {
    setSearchQuery("");
  }, [view]);

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
      searchQuery,
      setSearchQuery,
      headerReport,
      setHeaderReport,
    }),
    [pillar, view, setPillar, chatCtx, scoped, setScope, jumpTo, pending, takePending, searchQuery, headerReport],
  );

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState() {
  const value = useContext(AppStateContext);
  if (!value) throw new Error("useAppState must be used within AppStateProvider");
  return value;
}

/* A view publishes its report with this. `report` must be memoised by the caller --
   a fresh object every render would republish every render. Unmounting withdraws it. */
export function useHeaderReport(report) {
  const { setHeaderReport } = useAppState();
  useEffect(() => {
    setHeaderReport(report || null);
    return () => setHeaderReport(null);
  }, [report, setHeaderReport]);
}
