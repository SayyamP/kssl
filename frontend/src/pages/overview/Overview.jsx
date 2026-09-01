import { useEffect, useMemo, useState } from "react";
import SignalCard from "../../components/signalCard/SignalCard";
import DetailPanel from "../../components/detailPanel/DetailPanel";
import ErrorBoundary from "../../components/ErrorBoundary";
import FeedFilters from "../../components/subHead/FeedFilters";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildFeed, tilePredicate } from "../../lib/overview";

/* The overview feed and its detail column. Shared by all three pillars — the pillar
   only decides which card set and which metric strip config is in play, which is
   exactly how the original's buildOverviewFeed(pillarKey) worked. */
export default function Overview({
  pillarKey,
  seqMode,
  dirFilter,
  tile,
  filters,
  onFilter,
  onSeq,
  onSelectionChange,
}) {
  const { data } = useData();
  const { setScope, takePending } = useAppState();
  const [selected, setSelected] = useState(null);

  // the shell's third column collapses when nothing is selected, so Layout has to know
  useEffect(() => {
    onSelectionChange?.(!!selected);
  }, [selected, onSelectionChange]);

  const cfg = data.overviewConfig[pillarKey] || data.overviewConfig.competitive;
  const feed = useMemo(() => buildFeed(cfg, seqMode), [cfg, seqMode]);

  // a pillar change or a re-sequence drops the selection, same as the original's
  // "collapsed until a signal is clicked" reset
  useEffect(() => {
    setSelected(null);
  }, [pillarKey, seqMode]);

  /* Memoised on the tile NAME, not rebuilt per render: an identity that changed every
     render made the auto-select effect below re-fire forever. */
  const tilePred = useMemo(() => (tile ? tilePredicate(tile) : null), [tile]);

  const visible = (card) => {
    if (dirFilter && dirFilter !== "all" && card.dir !== dirFilter) return false;
    if (tilePred && !tilePred(card)) return false;
    return true;
  };

  /* Picking a signal moves both chat contexts: the scoped ask box answers about this
     signal, and the floating assistant's context line names it. */
  const select = (id) => {
    const detail = data.details[id];
    if (!detail || id === selected) return;
    setSelected(id);
    setScope("signal", { type: "signal", data: detail }, {
      pillar: "Competitive",
      view: "Overview",
      selection: detail.title,
    });
  };

  // Opened from global search targeting a specific signal card.
  useEffect(() => {
    const pend = takePending("overview");
    if (pend && pend.cardId && data.details && data.details[pend.cardId]) {
      select(pend.cardId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takePending]);

  // the metric tiles open the first matching signal, as the tiles did before
  useEffect(() => {
    if (!tile) return;
    const first = (cfg.cards || []).find(visible);
    if (first) select(first.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tile]);

  const shownCount = (cfg.cards || []).filter(visible).length;
  const firstVisibleId = (cfg.cards || []).find(visible)?.id;
  /* An empty feed still has a header, and the hardcoded fallback below printed the COMPETITIVE
     heading over the technology pillar -- a wrong label on an empty panel reads as a wrong panel.
     The pillar's own group def carries the right words even when it has no cards to slice. */
  const topGroup =
    feed.groups[0] || (cfg.groups || [])[0] || { h: cfg.title || "Signals", s: "" };

  return (
    <div className="ov-wrap">
      {/* FIXED TOP HEADER LINE: Fixed header bar with controls. The title is a
          button that scrolls the feed back to the top — a returning anchor for a
          long, deep-scrolled list. */}
      <div className="feed-grp-h ov-fixed-header">
        <span
          className="eyebrow ov-top-link"
          role="button"
          tabIndex={0}
          title="Back to top of feed"
          onClick={() => {
            const el = document.getElementById("feed");
            if (el) el.scrollTo({ top: 0, behavior: "smooth" });
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              const el = document.getElementById("feed");
              if (el) el.scrollTo({ top: 0, behavior: "smooth" });
            }
          }}
        >
          {topGroup.h} <span className="sub">{topGroup.s}</span>
        </span>
        <FeedFilters
          active={tile ? null : dirFilter}
          filters={filters}
          onFilter={onFilter}
          onSeq={onSeq}
          seqMode={seqMode}
        />
      </div>

      <div className="ov-body">
        <div className="feed v-overview" id="feed">
          {feed.groups.map((g, gi) => {
            const cards = g.cards.filter(visible);
            if (!cards.length && gi !== 0) return null;
            return (
              <div className="feed-grp" key={g.h}>
                {gi > 0 && cards.length ? (
                  <div className="feed-grp-h">
                    <span className="eyebrow">
                      {g.h} <span className="sub">{g.s}</span>
                    </span>
                  </div>
                ) : null}
                {cards.map((c) => (
                  <SignalCard
                    card={c}
                    dirWord={cfg.dirWord[c.dir] || c.dir}
                    fresh={c.id === firstVisibleId}
                    key={c.id}
                    onSelect={select}
                    selected={selected === c.id}
                  />
                ))}
              </div>
            );
          })}
          {shownCount === 0 ? (
            <div className="empty-note">
              {/* an empty feed with no filter active is a served-nothing state,
                  not the filter's fault — say which one it is */}
              {tile || (dirFilter && dirFilter !== "all")
                ? "— no signals match this filter —"
                : "— no signals served yet —"}
            </div>
          ) : (
            <div className="empty-note">— end of active signals · {feed.total} total —</div>
          )}
        </div>

        {/* Its own boundary as well as the app's: one malformed signal must cost the reader that
            one signal, not the feed they were reading it from. */}
        {selected ? (
          <ErrorBoundary label="signal detail">
            <DetailPanel detail={data.details[selected]} onClose={() => setSelected(null)} />
          </ErrorBoundary>
        ) : null}
      </div>
    </div>
  );
}
