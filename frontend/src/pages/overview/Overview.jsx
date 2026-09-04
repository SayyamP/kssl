import { useEffect, useMemo, useState } from "react";
import SignalCard from "../../components/signalCard/SignalCard";
import DetailPanel from "../../components/detailPanel/DetailPanel";
import ErrorBoundary from "../../components/ErrorBoundary";
import FeedFilters from "../../components/subHead/FeedFilters";
import { useAppState, useHeaderReport, PILLAR_LABEL } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildFeed, paginateFeed, signalDate, tilePredicate, SEQ_LABEL, TILE_LABELS } from "../../lib/overview";

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
  const [page, setPage] = useState(1);

  // the shell's third column collapses when nothing is selected, so Layout has to know
  useEffect(() => {
    onSelectionChange?.(!!selected);
  }, [selected, onSelectionChange]);

  const cfg = data.overviewConfig[pillarKey] || data.overviewConfig.competitive;
  // `data` is a dependency because the sort now reads the same date the card prints,
  // which lives in data.details, not on the card
  const feed = useMemo(() => buildFeed(cfg, seqMode, data), [cfg, seqMode, data]);

  // a pillar change or a re-sequence drops the selection, same as the original's
  // "collapsed until a signal is clicked" reset
  useEffect(() => {
    setSelected(null);
  }, [pillarKey, seqMode]);

  /* Anything that changes WHAT the feed contains sends the reader back to page 1.
     The search boxes are in this list because they were not in the pre-port version --
     they did not exist yet -- and a query that shrinks 453 signals to 3 would otherwise
     leave the reader on page 7 of a 1-page feed, looking at nothing. */
  useEffect(() => {
    setPage(1);
  }, [pillarKey, seqMode, dirFilter, tile, feedSearchQuery, searchQuery]);

  /* Memoised on the tile NAME, not rebuilt per render: an identity that changed every
     render made the auto-select effect below re-fire forever. */
  const tilePred = useMemo(() => (tile ? tilePredicate(tile) : null), [tile]);

  /* Split so the filter counts can reuse this predicate verbatim rather than
     paraphrasing it. A count computed from a paraphrase is the exact bug this page was
     fixed for: a two-word query, or a hit that lives only in the detail text, made the
     badges read 0 while matching cards were plainly on screen -- and since an empty
     filter is disabled, every button including "All" went dead beneath a full feed. */
  const visibleExceptDir = (card) => {
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

  const visible = (card) =>
    (!dirFilter || dirFilter === "all" || card.dir === dirFilter) && visibleExceptDir(card);

  /* Picking a signal moves both chat contexts: the scoped ask box answers about this
     signal, and the floating assistant's context line names it. */
  const select = (id) => {
    const detail = data.details[id];
    if (!detail || id === selected) return;
    setSelected(id);
    /* The context line names the pillar and heading the reader is actually on. It
       said "Competitive / Overview" on all three pillars, so a technology signal was
       announced under a page it is not listed on (FE 18). */
    setScope("signal", { type: "signal", data: detail }, {
      pillar: PILLAR_LABEL[pillarKey] || "Competitive",
      view: cfg.title || "Overview",
      selection: detail.title,
    });
  };

  // Opened from global search targeting a specific signal card.
  useEffect(() => {
    const pend = takePending("overview");
    if (pend && pend.cardId && data.details && data.details[pend.cardId]) {
      /* A hit is usually not on the page in view -- 453 signals is ten pages -- so turn
         to the page holding it BEFORE selecting, or the reader gets a detail panel
         beside a feed that does not list what it describes. */
      const at = pageView.pageOf(pend.cardId);
      if (at && at !== pageView.page) goPage(at);
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

  /* paginateFeed takes the `keep` predicate, so the pager runs over the search-filtered
     set rather than fighting it -- the two cannot disagree about what is on screen. */
  const pageView = useMemo(
    () => paginateFeed(feed.groups, visible, page),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [feed, dirFilter, tilePred, feedSearchQuery, searchQuery, page],
  );
  const shownCount = pageView.shown;
  const firstVisibleId = pageView.firstId;

  /* What the header's Copy / Export / Print act on: the signals on THIS page of the
     feed, under the sequence and filter in force. Every field is the card's own. */
  const report = useMemo(() => {
    const cards = pageView.groups.flatMap((g) => g.cards);
    const filterLabel = tile
      ? TILE_LABELS[tile] || tile
      : dirFilter && dirFilter !== "all"
        ? ((filters || []).find((f) => f.f === dirFilter) || {}).l || dirFilter
        : "all signals";
    return {
      title: cfg.title || "Signals",
      subtitle: `${SEQ_LABEL[seqMode] || seqMode} · ${filterLabel} · page ${pageView.page} of ${pageView.pageCount}`,
      sections: [
        {
          h: `Signals ${pageView.from}-${pageView.to} of ${pageView.shown}`,
          rows: cards.map((c) => [`${c.company ? `${c.company} — ` : ""}${c.title || ""}`, c.sowhat || ""]),
        },
      ],
      payload: {
        pillar: pillarKey,
        sequence: seqMode,
        filter: filterLabel,
        page: pageView.page,
        pageCount: pageView.pageCount,
        shown: pageView.shown,
        total: feed.total,
        signals: cards.map((c) => ({
          id: c.id,
          title: c.title || null,
          company: c.company || null,
          direction: c.dir || null,
          date: signalDate(c, data) || null,
          sowhat: c.sowhat || null,
          url: c.url || null,
        })),
      },
    };
  }, [pageView, cfg, seqMode, tile, dirFilter, filters, pillarKey, feed.total, data]);
  useHeaderReport(report);

  const goPage = (n) => {
    setPage(n);
    const el = document.getElementById("feed");
    if (el) el.scrollTop = 0;
  };

  /* first, last, and a window around the current page -- 453 signals is ten pages, and a
     corpus that grows to eighty must not put eighty buttons on screen */
  const pageNumbers = (cur, count) => {
    if (count <= 7) return Array.from({ length: count }, (_, i) => i + 1);
    const out = [1];
    const from = Math.max(2, cur - 1);
    const to = Math.min(count - 1, cur + 1);
    if (from > 2) out.push("…");
    for (let n = from; n <= to; n += 1) out.push(n);
    if (to < count - 1) out.push("…");
    out.push(count);
    return out;
  };

  /* How many cards each direction filter would show, before it is applied. Counted over
     the tile/search-filtered set so the number matches what clicking it produces. */
  const filterCounts = useMemo(() => {
    const inScope = (cfg.cards || []).filter(visibleExceptDir);
    const out = {};
    (filters || []).forEach((f) => {
      out[f.f] = f.f === "all" ? inScope.length : inScope.filter((c) => c.dir === f.f).length;
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cfg, filters, tilePred, feedSearchQuery, searchQuery, data.details]);

  const isFiltered = dirFilter && dirFilter !== "all";
  const activeFilterObj = (filters || []).find((f) => f.f === dirFilter);

  /* paginateFeed already applied `visible` and re-grouped the slice, so this keeps the
     ported shape ({...g, visibleCards}) while showing one page rather than all 453. */
  const groupsWithCards = pageView.groups.map((g) => ({ ...g, visibleCards: g.cards }));

  let topHeaderTitle = "";
  let topHeaderSub = "";

  if (isFiltered && activeFilterObj) {
    topHeaderTitle = activeFilterObj.l || "Filtered Signals";
    /* No group strapline here. The filtered feed is flat, and the first group's
       sub-heading ("what's live now") described a grouping the rows on screen no
       longer follow -- a heading that names a structure the page is not showing. */
    topHeaderSub = "";
  } else if (groupsWithCards.length > 0) {
    /* The feed title, NOT the first group's name. This banner is sticky, so naming
       group 0 pinned "Live Opportunities" to the top of the window and left it there
       for all 138 cards below it -- of which three were in that group. The group split
       is by INDEX (`cards.slice(idx, idx + g.n)`), not by content, so the label was
       never a property of what the reader was looking at. Each group now carries its
       own inline header instead; see the `gi > 0` guard removed below. */
    topHeaderTitle = cfg.title || "Signals";
    topHeaderSub = "";
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
          counts={filterCounts}
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
                  when={signalDate(c, data)}
                  selected={selected === c.id}
                />
              ))}
            </div>
          ) : (
            groupsWithCards.map((g) => (
              <div className="feed-grp" key={g.h}>
                {/* Every group carries its own header, the first included. It used to be
                    suppressed on gi === 0 because the sticky banner was showing that
                    group's name -- and kept showing it for the whole scroll. */}
                <div className="feed-grp-h">
                  <span className="eyebrow">
                    {g.h} <span className="sub">{g.s}</span>
                  </span>
                </div>
                {g.visibleCards.map((c) => (
                  <SignalCard
                    card={c}
                    dirWord={cfg.dirWord[c.dir] || c.dir}
                    fresh={c.id === firstVisibleId}
                    key={c.id}
                    onSelect={select}
                    when={signalDate(c, data)}
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
              ) : null}
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
