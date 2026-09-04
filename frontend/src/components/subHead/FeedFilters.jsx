import { SEQ_OPTIONS } from "../../lib/overview";

/* The direction buttons + sequence select.

   These sit in the FIRST FEED GROUP HEADER, not the subhead — the original parked the
   node in the subhead only long enough to survive an innerHTML wipe, then moved it into
   `.feed-grp-h` on every rebuild, which is where it is actually seen. Rendering it here
   puts it in its real home and drops the two DOM relocations that existed to get it
   there. It only exists on the overview, because that is the only view with a feed. */
/* `counts` maps a filter key to how many cards it would show.

   Every market card and every technology card carries dir='watch' -- the promoter never
   assigns another value -- so on those pillars "All" and "Emerging Demand" select the
   same 138 (or 254) cards in the same order, and "Opportunities" and "Live Bids" select
   nothing at all. That is what the report meant by All and Emerging being identical.

   A facet that selects everything is not a facet, and one that selects nothing is a
   dead end. Both are still shown -- hiding them would misrepresent the taxonomy the
   client configured -- but each carries its count, and an empty one cannot be clicked. */
/* Styled from chrome.css (.filters, .feed-search-box, .dir-filters), not inline. The
   inline styles this carried forced `flex-wrap: nowrap` on both rows, and an inline
   style outranks every class rule -- so the wrap the stylesheet asked for could never
   happen, and below about 1280px on the market pillar (four pills) the row ran off the
   right edge of a header whose scrollbar is hidden. The Sequence control was simply
   gone at 1024px. */
export default function FeedFilters({ filters, active, onFilter, seqMode, onSeq, searchQuery, onSearch, counts }) {
  return (
    <div className="filters">
      <div className="feed-search-box">
        <span className="feed-search-icon">⌕</span>
        <input
          type="text"
          placeholder="Filter cards..."
          value={searchQuery || ""}
          onChange={(e) => onSearch?.(e.target.value)}
        />
        {searchQuery ? (
          <button className="feed-search-clear" onClick={() => onSearch?.("")} type="button">
            ×
          </button>
        ) : null}
      </div>

      <span className="dir-filters">
        {(filters || []).map((f) => {
          const n = counts ? counts[f.f] : undefined;
          /* "All" is the reset door and is never disabled. If a search matches nothing
             every count is 0, and disabling all four would leave the reader with no
             control to click their way out of -- only the search box's little cross. */
          const empty = n === 0 && f.f !== "all";
          return (
            <button
              className={`fbtn${active === f.f ? " on" : ""}${empty ? " empty" : ""}`}
              disabled={empty}
              key={f.f}
              onClick={() => onFilter(f.f)}
              title={empty ? `No signals carry ${f.l}` : undefined}
              type="button"
            >
              {f.c ? <span className="sw" style={{ background: f.c }} /> : null}
              {f.l}
              {n === undefined ? null : <span className="fcount"> {n}</span>}
            </button>
          );
        })}
      </span>
      {/* one flex item, so the label and its select wrap together -- a row break between
          them left "SEQUENCE" stranded at the end of one line and the select alone on
          the next */}
      <span className="seq-ctl">
        <span className="seq-sep" />
        <span className="seq-label">Sequence</span>
        <select className="seq-select" onChange={(e) => onSeq(e.target.value)} value={seqMode}>
          {SEQ_OPTIONS.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </span>
    </div>
  );
}
