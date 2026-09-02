import { useEffect, useMemo, useState } from "react";
import SignalCard from "../../components/signalCard/SignalCard";
import DetailPanel from "../../components/detailPanel/DetailPanel";
import ErrorBoundary from "../../components/ErrorBoundary";
import FeedFilters from "../../components/subHead/FeedFilters";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildFeed, paginateFeed, tilePredicate, FEED_PAGE_SIZE } from "../../lib/overview";

/* Page numbers with an ellipsis: first, last, and a window around the current page.
   Nine pages fit; a corpus that grows to eighty must not put eighty buttons on screen. */
function pageNumbers(cur, count) {
  if (count <= 7) return Array.from({ length: count }, (_, i) => i + 1);
  const out = [1];
  const from = Math.max(2, cur - 1);
  const to = Math.min(count - 1, cur + 1);
  if (from > 2) out.push("…");
  for (let n = from; n <= to; n += 1) out.push(n);
  if (to < count - 1) out.push("…");
  out.push(count);
  return out;
}

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
  const [page, setPage] = useState(1);

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

  /* Any change to what the feed contains sends the reader back to page 1 -- staying on
     page 7 of a filter that now has two pages would show an empty list. */
  useEffect(() => {
    setPage(1);
  }, [pillarKey, seqMode, dirFilter, tile]);

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
      /* A global-search hit is usually not on the page in view -- 429 signals is nine
         pages -- so turn to the one holding it before selecting, or the reader gets a
         detail panel beside a feed that does not list what it describes. */
      const at = pageView.pageOf(pend.cardId);
      if (at && at !== page) goPage(at);
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

  /* One page of the filtered feed. `feed.groups` now covers every served card, so the
     page maths runs over the whole corpus and the reader walks it 50 at a time. */
  const pageView = useMemo(
    () => paginateFeed(feed.groups, visible, page),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [feed, dirFilter, tilePred, page],
  );
  const shownCount = pageView.shown;
  const firstVisibleId = pageView.firstId;

  /* The feed scrolls independently of the window, so a page turn has to rewind it --
     otherwise page 2 opens halfway down. */
  const goPage = (n) => {
    setPage(n);
    const el = document.getElementById("feed");
    if (el) el.scrollTop = 0;
  };
  /* An empty feed still has a header, and the hardcoded fallback below printed the COMPETITIVE
     heading over the technology pillar -- a wrong label on an empty panel reads as a wrong panel.
     The pillar's own group def carries the right words even when it has no cards to slice. */
  const topGroup =
    pageView.groups[0] ||
    feed.groups[0] ||
    (cfg.groups || [])[0] || { h: cfg.title || "Signals", s: "" };

  return (
    <div className="ov-wrap">
      {/* FIXED TOP HEADER LINE: Fixed header bar with controls */}
      <div className="feed-grp-h ov-fixed-header">
        <span className="eyebrow">
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
          {pageView.groups.map((g, gi) => {
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
            <div className="pager">
              <div className="pager-range">
                showing {pageView.from}–{pageView.to} of {shownCount}
                {shownCount !== feed.total ? ` filtered · ${feed.total} total` : " signals"}
              </div>
              {pageView.pageCount > 1 ? (
                <div className="pager-ctl">
                  <button
                    className="pgbtn"
                    disabled={pageView.page <= 1}
                    onClick={() => goPage(pageView.page - 1)}
                    type="button"
                  >
                    ‹ Prev
                  </button>
                  {pageNumbers(pageView.page, pageView.pageCount).map((n, i) =>
                    n === "…" ? (
                      <span className="pgap" key={`gap${i}`}>
                        …
                      </span>
                    ) : (
                      <button
                        className={`pgbtn num${n === pageView.page ? " on" : ""}`}
                        key={n}
                        onClick={() => goPage(n)}
                        type="button"
                      >
                        {n}
                      </button>
                    ),
                  )}
                  <button
                    className="pgbtn"
                    disabled={pageView.page >= pageView.pageCount}
                    onClick={() => goPage(pageView.page + 1)}
                    type="button"
                  >
                    Next ›
                  </button>
                </div>
              ) : (
                <div className="pager-range">— end of active signals —</div>
              )}
            </div>
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
