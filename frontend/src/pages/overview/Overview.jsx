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
  const { setScope, takePending, searchQuery } = useAppState();
  const [selected, setSelected] = useState(null);
  const [feedSearchQuery, setFeedSearchQuery] = useState("");

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
    const activeQ = (feedSearchQuery || searchQuery || "").trim().toLowerCase();
    if (activeQ) {
      const qTokens = activeQ.split(/\s+/).filter(Boolean);
      const detail = (data.details && data.details[card.id]) || {};
      const fullText = `${card.title || ""} ${card.company || ""} ${card.tags || ""} ${card.sowhat || ""} ${card.ago || ""} ${detail.facts || ""} ${detail.what || ""} ${detail.why || ""}`.toLowerCase();
      if (!qTokens.every((tok) => fullText.includes(tok))) return false;
    }
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

  const isFiltered = dirFilter && dirFilter !== "all";
  const activeFilterObj = (filters || []).find((f) => f.f === dirFilter);

  const groupsWithCards = feed.groups
    .map((g) => ({
      ...g,
      visibleCards: g.cards.filter(visible),
    }))
    .filter((g) => g.visibleCards.length > 0);

  let topHeaderTitle = "";
  let topHeaderSub = "";

  if (isFiltered && activeFilterObj) {
    topHeaderTitle = activeFilterObj.l || "Filtered Signals";
    const matchingGroup = groupsWithCards[0] || (cfg.groups || [])[0];
    topHeaderSub = matchingGroup?.s || "";
  } else if (groupsWithCards.length > 0) {
    topHeaderTitle = groupsWithCards[0].h;
    topHeaderSub = groupsWithCards[0].s;
  } else {
    const fallback = (cfg.groups || [])[0] || { h: cfg.title || "Signals", s: "" };
    topHeaderTitle = fallback.h;
    topHeaderSub = fallback.s;
  }

  return (
    <div className="ov-wrap">
      {/* FIXED TOP HEADER LINE: Fixed header bar with controls */}
      <div className="feed-grp-h ov-fixed-header">
        <span className="eyebrow">
          {topHeaderTitle} <span className="sub">{topHeaderSub}</span>
        </span>
        <FeedFilters
          active={tile ? null : dirFilter}
          filters={filters}
          onFilter={onFilter}
          onSeq={onSeq}
          seqMode={seqMode}
          searchQuery={feedSearchQuery}
          onSearch={setFeedSearchQuery}
        />
      </div>

      <div className={`ov-body${selected ? " has-sel" : ""}`}>
        <div className="feed v-overview" id="feed">
          {isFiltered ? (
            <div className="feed-grp">
              {groupsWithCards.flatMap((g) => g.visibleCards).map((c) => (
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
          ) : (
            groupsWithCards.map((g, gi) => (
              <div className="feed-grp" key={g.h}>
                {gi > 0 ? (
                  <div className="feed-grp-h">
                    <span className="eyebrow">
                      {g.h} <span className="sub">{g.s}</span>
                    </span>
                  </div>
                ) : null}
                {g.visibleCards.map((c) => (
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
            ))
          )}
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
