import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_ROUTE, PILLARS, PILLAR_LABEL, RAIL, OVERVIEW_VIEW, parseRoute, routeHash } from "../lib/route";

const AppStateContext = createContext(null);

/* The route tables live in lib/route.js (pure, tested under node); re-exported here so
   the rail, the top bar and the pages keep importing them from the state module. */
export { PILLARS, PILLAR_LABEL, RAIL };

const OVERVIEW_VIEWS = new Set(Object.values(OVERVIEW_VIEW));
export const isOverview = (view) => OVERVIEW_VIEWS.has(view);

const ROUTE_STORE_KEY = "kssl_parallax_route";

/* The hash wins, then the saved route, then the default. Both go through parseRoute,
   so an unknown view -- from a stale link OR from a saved route written by an older
   build -- lands on its pillar's overview instead of a blank pane. */
const getInitialAppState = () => {
  let hash = "";
  try {
    const fromHash = parseRoute(window.location.hash);
    if (fromHash) return { pillar: fromHash.pillar, view: fromHash.view };
    const saved = localStorage.getItem(ROUTE_STORE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      const r = parsed && parseRoute(routeHash(parsed.pillar, parsed.view));
      if (r) return { pillar: r.pillar, view: r.view };
    }
  } catch (e) {}
  return { ...DEFAULT_ROUTE };
};

export function AppStateProvider({ children }) {
  const initial = getInitialAppState();
  const [pillar, setPillarState] = useState(initial.pillar);
  const [view, setViewState] = useState(initial.view);

  /* HISTORY. Every navigation the reader makes is a history entry, and Back / Forward
     (and a hash edited in the address bar) drive the state through popstate.

     Before this the router wrote every change with replaceState and listened to
     nothing: the session held ONE entry, so Back after Competitive -> Technology ->
     Innovation left the site, and a pasted hash in an open tab did nothing on screen.

     `fromHistory` marks a state change that CAME from popstate, so the sync effect
     below does not push a second entry for it. The first render replaces rather than
     pushes: the entry the reader arrived on is normalised (a repaired view, or a hash
     added to a bare URL), not duplicated. */
  const fromHistory = useRef(true);
  // the route in force, readable from the popstate listener without a stale closure
  const routeRef = useRef({ pillar, view });

  useEffect(() => {
    routeRef.current = { pillar, view };
    try {
      localStorage.setItem(ROUTE_STORE_KEY, JSON.stringify({ pillar, view }));
      const newHash = routeHash(pillar, view);
      if (window.location.hash !== newHash) {
        if (fromHistory.current) window.history.replaceState(null, "", newHash);
        else window.history.pushState(null, "", newHash);
      }
    } catch (e) {}
    fromHistory.current = false;
  }, [pillar, view]);

  useEffect(() => {
    const onPop = () => {
      const r = parseRoute(window.location.hash);
      /* a hash carrying no route (erased by hand, foreign) is left alone: the state
         in view is still the state in view */
      if (!r) return;
      /* the same route again (a hash edited to what it already was) changes no state,
         so the sync effect would not run to clear the flag -- and the reader's next
         click would replace an entry instead of pushing one */
      if (r.pillar === routeRef.current.pillar && r.view === routeRef.current.view) return;
      fromHistory.current = true;
      setPillarState(r.pillar);
      setViewState(r.view);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
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
