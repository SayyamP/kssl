import { SEQ_OPTIONS } from "../../lib/overview";

/* The direction buttons + sequence select.

   These sit in the FIRST FEED GROUP HEADER, not the subhead — the original parked the
   node in the subhead only long enough to survive an innerHTML wipe, then moved it into
   `.feed-grp-h` on every rebuild, which is where it is actually seen. Rendering it here
   puts it in its real home and drops the two DOM relocations that existed to get it
   there. It only exists on the overview, because that is the only view with a feed. */
export default function FeedFilters({ filters, active, onFilter, seqMode, onSeq, searchQuery, onSearch }) {
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
        {(filters || []).map((f) => (
          <button
            className={`fbtn${active === f.f ? " on" : ""}`}
            key={f.f}
            onClick={() => onFilter(f.f)}
            type="button"
          >
            {f.c ? <span className="sw" style={{ background: f.c }} /> : null}
            {f.l}
          </button>
        ))}
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
