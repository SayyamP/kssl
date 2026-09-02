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
export default function FeedFilters({ filters, active, onFilter, seqMode, onSeq, searchQuery, onSearch, counts }) {
  return (
    <div className="filters" style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "nowrap", whiteSpace: "nowrap" }}>
      <div className="feed-search-box" style={{ display: "flex", alignItems: "center", background: "var(--d-bg-1)", border: "1px solid var(--d-line-2)", borderRadius: "4px", padding: "2px 6px", flexShrink: 0 }}>
        <span style={{ fontSize: "11px", color: "var(--d-txt-4)", marginRight: "4px" }}>⌕</span>
        <input
          type="text"
          placeholder="Filter cards..."
          value={searchQuery || ""}
          onChange={(e) => onSearch?.(e.target.value)}
          style={{ background: "transparent", border: "none", outline: "none", color: "var(--d-txt)", fontSize: "11px", fontFamily: "var(--mono)", width: "105px" }}
        />
        {searchQuery ? (
          <button
            onClick={() => onSearch?.("")}
            style={{ background: "none", border: "none", color: "var(--d-txt-4)", cursor: "pointer", fontSize: "12px", padding: "0 2px" }}
          >
            ×
          </button>
        ) : null}
      </div>

      <span className="dir-filters" style={{ display: "inline-flex", alignItems: "center", gap: "4px", flexWrap: "nowrap", whiteSpace: "nowrap", flexShrink: 0 }}>
        {(filters || []).map((f) => {
          const n = counts ? counts[f.f] : undefined;
          const empty = n === 0;
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
      <span className="seq-sep" style={{ flexShrink: 0 }} />
      <span className="seq-label">Sequence</span>
      <select className="seq-select" onChange={(e) => onSeq(e.target.value)} value={seqMode}>
        {SEQ_OPTIONS.map(([v, label]) => (
          <option key={v} value={v}>
            {label}
          </option>
        ))}
      </select>
    </div>
  );
}
