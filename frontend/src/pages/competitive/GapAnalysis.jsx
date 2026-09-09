import { useEffect, useMemo, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import {
  gapCategories,
  gapRivals,
  gapCategoryBody,
  gapCategorySub,
  gesc,
} from "../../lib/gapAnalysis";

/* Where KSSL trails rivals, band by band. Same list+canvas shape as Positioning,
   Patents and Geo: a selectable list on the left, the read on the right.
   Clicking a rival row opens that rival's worst comparison back in Positioning. */
export default function GapAnalysis() {
  const { data } = useData();
  const { jumpTo } = useAppState();
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState(null);
  const clientName = (data.client && (data.client.short || data.client.name)) || "KSSL";

  const cats = useMemo(() => gapCategories(data.matchups), [data.matchups]);

  /* How many pairings this category HOLDS, comparable or not. The measured count on
     its own read as the whole category. */
  const held = useMemo(() => {
    if (!cat) return 0;
    const all = data.matchups || {};
    return Object.keys(all).filter((id) => all[id] && all[id].cat === cat).length;
  }, [data.matchups, cat]);

  useEffect(() => {
    if (!cats.length) {
      if (cat) setCat(null);
      return;
    }
    if (!cat || !cats.some((c) => c.cat === cat)) setCat(cats[0].cat);
  }, [cats, cat]);

  const rivals = useMemo(
    () => (cat ? gapRivals(data.matchups, cat, clientName) : []),
    [data.matchups, cat, clientName],
  );

  const shown = cats.filter(
    (c) => !query.trim() || c.cat.toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <div className="pat-view v-gap-competitive">
      <div className="pat-pane" data-glens="cat">
        <div className="mu-list">
          <div className="mu-list-h">
            <span className="eyebrow">
              Categories <span className="srcbadge" style={{ marginLeft: "6px" }}>Derived</span>
            </span>
            <div className="sub">Product categories, worst exposure first</div>
            <div className="mu-search">
              <span className="si">⌕</span>
              <input
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search category…"
                type="text"
                value={query}
              />
            </div>
          </div>
          <div id="gap-cat-list">
            {shown.length ? (
              shown.map((c) => {
                const k = c.behind ? (c.behind >= c.rivals / 2 ? "behind" : "level") : "ahead";
                return (
                  <div
                    className={`pat-li${cat === c.cat ? " active" : ""}`}
                    key={c.cat}
                    onClick={() => setCat(c.cat)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setCat(c.cat);
                      }
                    }}
                  >
                    <span className="pli-n">
                      {c.cat}
                      <i className="gcl-sub">
                        {c.rivals} rivals · {c.n} comparisons
                      </i>
                    </span>
                    <span className={`gcl-lead ${k}`}>
                      {c.balance > 0 ? "+" : ""}
                      {c.balance}
                    </span>
                  </div>
                );
              })
            ) : (
              <div className="pat-li-none">No scored comparisons yet.</div>
            )}
          </div>
        </div>
        <div className="pat-canvas">
          <div className="pat-head">
            <span className="eyebrow">{cat ? `${cat} · competitive edge` : "Category"}</span>
            <span className="pat-sub">{gapCategorySub(rivals, held)}</span>
          </div>
          <HtmlBlock
            handlers={{
              /* Listed BEFORE the rival row: HtmlBlock returns on the first selector
                 that `closest` matches, and every comparison line sits inside the
                 same block as the rows. */
              ".ga-cmp[data-mu]": (el) => {
                const id = el.getAttribute("data-mu");
                if (id) jumpTo("competitive", "positioning", { matchupId: id });
              },
              ".ga-row[data-mu]": (el) => {
                const id = el.getAttribute("data-mu");
                if (id) jumpTo("competitive", "positioning", { matchupId: id });
              },
            }}
            html={cat ? gapCategoryBody(rivals, clientName, held) : ""}
            id="gap-cat-body"
          />
        </div>
      </div>
    </div>
  );
}
