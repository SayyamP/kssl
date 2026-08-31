import { useEffect, useMemo, useState } from "react";
import ErrorBoundary from "../ErrorBoundary";
import TopBar from "../topBar/TopBar";
import Sidebar from "../sidebar/Sidebar";
import SubHead from "../subHead/SubHead";
import MetricsStrip from "../metricsStrip/MetricsStrip";
import MalloryChat from "../malloryChat/MalloryChat";
import Overview from "../../pages/overview/Overview";
import Positioning from "../../pages/competitive/Positioning";
import GapAnalysis from "../../pages/competitive/GapAnalysis";
import Partnerships from "../../pages/competitive/Partnerships";
import Geo from "../../pages/competitive/Geo";
import Patents from "../../pages/competitive/Patents";
import Tenders from "../../pages/market/Tenders";
import MarketOverview from "../../pages/market/MarketOverview";
import Profile from "../../pages/competitive/Profile";
import Products from "../../pages/competitive/Products";
import Innovation from "../../pages/technology/Innovation";
import { useAppState, isOverview } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { metricsFor, tilePredicate, TILE_LABELS, bucketTenders } from "../../lib/overview";
import { marketMetrics } from "../../lib/marketOverview";

const PILLAR_OF_VIEW = {
  overview: "competitive",
  "m-overview": "market",
  "t-overview": "technology",
};

export default function Layout() {
  const { pillar, view, chatCtx, setChatCtx, jumpTo, railCollapsed } = useAppState();
  const { data, viewMeta } = useData();

  /* Overview state lives here because two pieces of chrome above the feed depend on
     it: the subhead's filter row and the shell's third column, which collapses when
     nothing is selected. */
  const [seqMode, setSeqMode] = useState("priority");
  const [dirFilter, setDirFilter] = useState("all");
  const [tile, setTile] = useState(null);
  const [hasSelection, setHasSelection] = useState(false);

  const overviewPillar = isOverview(view) ? PILLAR_OF_VIEW[view] || pillar : pillar;
  const cfg = data.overviewConfig[overviewPillar] || data.overviewConfig.competitive;

  // switching pillar resets the feed controls, as the original rebuild did
  useEffect(() => {
    setDirFilter("all");
    setTile(null);
    setHasSelection(false);
  }, [overviewPillar, view]);

  // the assistant's context line follows the view when nothing is selected in it
  useEffect(() => {
    const meta = viewMeta[view] || viewMeta.overview;
    setChatCtx((prev) => ({
      pillar: pillar.charAt(0).toUpperCase() + pillar.slice(1),
      view: meta.title,
      selection: prev.view === meta.title ? prev.selection : null,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, pillar]);

  /* The Market overview is a tender page, not a signal feed. It keeps the metric strip
     — with its OWN four measured tiles, not the served signal-feed labels — but none of
     the feed chrome: the count line, the direction filters and the tile-to-feed filter
     all describe cards it does not render. `onFeed` is what gates that chrome;
     `isOverview` still gates the strip and the collapsed third column. */
  const onMarketReport = view === "m-report" || view === "tender" || view === "awarded-tenders" || view === "closed-tenders";
  const onFeed = isOverview(view) && !onMarketReport;

  const metrics = useMemo(
    () =>
      onMarketReport
        ? marketMetrics(data.tenders)
        : metricsFor(cfg, overviewPillar, data),
    [cfg, overviewPillar, data, onMarketReport],
  );

  const meta = viewMeta[isOverview(view) ? "overview" : view] || viewMeta.overview;
  const onOverview = isOverview(view);
  /* The report is not an overview — it has no feed and no selectable card — but it does
     want the two things `isOverview` used to hand it while it lived in that slot: the
     metric strip above, and the shell's third column collapsed so it can use the width.
     Gating those on `isOverview` alone left it rendering into a two-column grid with a
     third column reserved for a drawer that never opens. */
  const wideNoDrawer = onOverview || onMarketReport;
  /* Each pillar's overview carries its own heading ("Market Intelligence"), which lives
     on the served config; viewMeta only has the competitive one. */
  const headTitle = onMarketReport
    ? "Market Report"
    : onOverview
      ? cfg.title || meta.title
      : meta.title;

  /* The count line reflects whichever filter is active — the original rewrote it in
     applyFilter(), with the tile label or the direction word. */
  const countLine = (() => {
    if (onMarketReport) {
      const { open, awarded, closed } = bucketTenders(data.tenders || []);
      return `${open.length} open · ${awarded.length} awarded · ${closed.length} closed · demand shape, spec and requirement`;
    }
    if (!onFeed) return meta.cnt;
    const total = (cfg.cards || []).length;
    const pred = tile ? tilePredicate(tile) : null;
    const shown = (cfg.cards || []).filter(
      (c) => (dirFilter === "all" || c.dir === dirFilter) && (!pred || pred(c)),
    ).length;
    if (tile) return `${shown} of ${total} signals · ${TILE_LABELS[tile] || ""}`;
    if (dirFilter !== "all") {
      const label = (cfg.filters || []).find((f) => f.f === dirFilter)?.l || dirFilter;
      return `${shown} of ${total} signals · ${label}`;
    }
    /* cfg.cnt's phrasing survives, its baked number does not: the count is the
       served card set's, so an empty dataset says 0 instead of a stale total. */
    return `${total} ${String(cfg.cnt || "signals").replace(/^\s*[\d,]+\s*/, "")}`;
  })();

  const body = () => {
    switch (view) {
      case "m-report":
        return <MarketOverview />;
      case "overview":
      case "m-overview":
      case "t-overview":
        return (
          <Overview
            dirFilter={dirFilter}
            filters={cfg.filters}
            onFilter={(f) => {
              setDirFilter(f);
              setTile(null);
            }}
            onSelectionChange={setHasSelection}
            onSeq={setSeqMode}
            pillarKey={overviewPillar}
            seqMode={seqMode}
            tile={tile}
          />
        );
      case "profile":
        return <Profile />;
      case "products":
        return <Products />;
      case "positioning":
        return <Positioning />;
      /* ARCHIVED — off the rail, still routed. getInitialAppState validates the pillar
         but never the view, so a saved route or a pasted link pointing here would
         otherwise fall through to `default: null` and render a blank pane forever. */
      case "gap-competitive":
        return <GapAnalysis />;
      case "partnerships":
        return <Partnerships />;
      case "geo":
        return <Geo />;
      case "patents-comp":
        return <Patents />;
      case "tender":
      /* Also archived: the Market overview carries Awarded and Closed as tabs now, but
         the routes stay for the same reason gap-competitive's does. */
      case "awarded-tenders":
      case "closed-tenders":
        return <Tenders mode={view} />;
      case "innovation":
        return <Innovation />;
      default:
        return null;
    }
  };

  return (
    <>
      <TopBar />
      <SubHead count={countLine} title={headTitle} />
      {wideNoDrawer ? (
        <MetricsStrip
          active={tile}
          /* The market tiles are a readout, not doors — the page below them has its own
             tabs and filter. Rendering them as buttons that do nothing is worse than
             rendering them as numbers. */
          inert={onMarketReport}
          metrics={metrics}
          /* The 'all' tiles are the reset door: they clear both the tile and the
             direction filter rather than filtering to everything. Redirect tile clicks if requested. */
          onPick={(m, act) => {
            const label = (m && m.l ? m.l : typeof m === "string" ? m : "").toLowerCase().trim();
            if (label.includes("audited rival skus") || label.includes("rival skus")) {
              jumpTo("competitive", "positioning");
              return;
            }
            if (label.includes("competitor brands") || label.includes("competitor brand") || label.includes("tracked competitors")) {
              jumpTo("competitive", "partnerships");
              return;
            }
            if (act === "all") {
              setTile(null);
              setDirFilter("all");
              return;
            }
            setTile(act);
          }}
        />
      ) : null}
      <div className={`shell${wideNoDrawer && !hasSelection ? " ov-nosel" : ""}${railCollapsed ? " rail-collapsed" : ""}`}>
        <Sidebar />
        {/* One boundary per view case (keyed so a crash in one view resets when the
            user navigates away) — a bad panel must never unmount the whole app. */}
        <ErrorBoundary key={view} label={view}>
          {body()}
        </ErrorBoundary>
      </div>
      <MalloryChat />
    </>
  );
}
