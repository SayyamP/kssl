import { SEQ_OPTIONS } from "../../lib/overview";

/* The direction buttons + sequence select.

   These sit in the FIRST FEED GROUP HEADER, not the subhead — the original parked the
   node in the subhead only long enough to survive an innerHTML wipe, then moved it into
   `.feed-grp-h` on every rebuild, which is where it is actually seen. Rendering it here
   puts it in its real home and drops the two DOM relocations that existed to get it
   there. It only exists on the overview, because that is the only view with a feed. */
export default function FeedFilters({ filters, active, onFilter, seqMode, onSeq }) {
  return (
    <div className="filters">
      <span className="dir-filters">
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
      <span className="seq-sep" />
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
