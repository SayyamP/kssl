import { useAppState, RAIL } from "../../state/AppState";
import { useData } from "../../state/DataProvider";

/* The left rail. One section per pillar in the original markup, shown and hidden;
   here only the active pillar's rail is rendered at all. Counts come from
   navCounts() — every one is computed from the loaded corpus, never hardcoded. */
export default function Sidebar() {
  const { pillar, view, setView } = useAppState();
  const { counts } = useData();
  const items = RAIL[pillar];

  const row = (item) => (
    <div
      className={`svc${view === item.view ? " active" : ""}${item.overview ? " nav-overview" : ""}`}
      key={item.view}
      onClick={() => setView(item.view)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setView(item.view);
        }
      }}
    >
      <span className="ix">
        {item.ix === "grid" ? (
          <i className="ti ti-layout-grid" style={{ fontSize: "13px" }} />
        ) : (
          item.ix
        )}
      </span>
      <span className="nm">{item.label}</span>
      <span className="tdot none" />
      <span className="ct">{counts[item.view] ?? "—"}</span>
    </div>
  );

  return (
    <div className="rail">
      <div className="rail-pillar" data-railpillar={pillar}>
        <div className="rail-sec svc-sec">{row(items[0])}</div>
        <div className="rail-sec svc-sec" style={{ borderTop: "none" }}>
          {items.slice(1).map(row)}
        </div>
      </div>
    </div>
  );
}
