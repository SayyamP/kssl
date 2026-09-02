import { useEffect, useMemo, useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { bucketTenders } from "../../lib/overview";
import {
  CATEGORY_COLOR,
  catOf,
  categoryRank,
  closingWindows,
  countriesOf,
  demandSplit,
  hostOf,
  initCategoryPalette,
  portalRows,
  sliceLabel,
  windowOf,
} from "../../lib/marketOverview";

/* ===== Market Overview =====
   Ported from the sibling JSW EV deployment (its own source, not its bundle) so the two
   read as one product. Same five-section tab strip, same country filter beneath it, same
   two charts in the active-tenders section only, same evidence table underneath.

   What is NOT the same is the demand split. JSW cuts its corpus into Product /
   Product + MRO / MRO-only, which is a statement about what a bus tender contracts for
   and has no defence equivalent — nothing in these 89 rows says whether a shell contract
   includes servicing. The honest cut on this corpus is the one the rows carry: `cat`.
   So sections 03-05 are the LIFECYCLE cuts this corpus does have (awarded, closed) and
   the pie navigates by category instead.

   Every number is counted from the tenders `useData()` serves. Where the corpus holds
   nothing — no tender on record publishes a value, none carries a bid verdict — the
   measure is absent or reads "—", never 0 and never a column of dashes. */

const fmt = (n) => new Intl.NumberFormat("en-IN").format(n);
const TABLE_PAGE = 25;
const NO_DATE = "No date published";

const SECTIONS = [
  { id: "active", label: "Number of active tenders" },
  { id: "category", label: "By category" },
  { id: "awarded", label: "Awarded" },
  { id: "closed", label: "Closed" },
];

const SECTION_KEY = "kssl_market_section";
const savedSection = () => {
  try {
    const s = localStorage.getItem(SECTION_KEY);
    return SECTIONS.some((x) => x.id === s) ? s : "active";
  } catch (e) {
    return "active";
  }
};

/* ---- Pie: share of the whole ----
   Stroked arcs on one circle rather than wedge paths: one <circle> per slice, no arc
   maths, and the 2px gap between neighbours falls out of the dash gap instead of needing
   a border. A pie is honest about "roughly half vs a third" and genuinely poor at ranking
   two slices a point apart — which is why the count and share are printed in the legend
   beside every slice. The numbers carry the close comparisons, not the arcs. */
function PieChart({ rows, total, colorOf, onPick, examples }) {
  const R = 56;
  const C = 2 * Math.PI * R;
  const GAP = rows.length > 1 ? 2.5 : 0;
  let offset = 0;

  return (
    <div className="ovp">
      <svg
        aria-label={`share of open tenders by category: ${rows.map((r) => `${r.key} ${r.n}`).join(", ")}`}
        className="ovp-svg"
        role="img"
        viewBox="0 0 150 150"
      >
        {rows.map((r) => {
          const frac = total ? r.n / total : 0;
          const len = Math.max(0, frac * C - GAP);
          const el = (
            <circle
              className={onPick ? "pick" : undefined}
              cx="75"
              cy="75"
              fill="none"
              key={r.key}
              onClick={onPick ? () => onPick(r.key) : undefined}
              r={R}
              stroke={colorOf(r.key)}
              strokeDasharray={`${len} ${C - len}`}
              strokeDashoffset={-offset}
              strokeWidth="30"
              /* start at 12 o'clock and run clockwise, the direction a reader expects */
              transform="rotate(-90 75 75)"
            >
              <title>{`${r.key}: ${fmt(r.n)} (${Math.round(frac * 100)}%)`}</title>
            </circle>
          );
          offset += frac * C;
          return el;
        })}
      </svg>
      {/* The legend rows are the real hit target — a 30px arc is fiddly to land on, and
          only the legend can be reached by keyboard. Both do the same thing. */}
      <div className="ovp-legend">
        {rows.map((r) => {
          const Row = onPick ? "button" : "div";
          return (
            <Row
              className={`ovp-key${onPick ? " pick" : ""}`}
              key={r.key}
              onClick={onPick ? () => onPick(r.key) : undefined}
              title={examples ? examples(r.key) : undefined}
              type={onPick ? "button" : undefined}
            >
              <span className="ovp-dot" style={{ background: colorOf(r.key) }} />
              <span className="ovp-lab">{r.key}</span>
              <span className="ovp-val">
                {fmt(r.n)}
                <em>{total ? ` ${Math.round((r.n / total) * 100)}%` : ""}</em>
              </span>
              {onPick ? <span className="ovp-go">→</span> : null}
            </Row>
          );
        })}
      </div>
    </div>
  );
}

/* ---- Columns: a distribution across an ordered scale ----
   One hue, because this is one series: the x-axis already carries the order, so colouring
   each column differently would spend the only free channel restating it. Value above,
   category beneath — nothing needs hover to be read.

   The last bucket is not a point on the runway scale, it is the ABSENCE of one, and on
   this corpus it is a quarter of the open set. Drawn in the series colour at the
   right-hand end it would read as "the longest runway" — the exact opposite. Neutral
   grey marks it off-scale and the label says so in words. */
const WINDOW_COLORS = {
  "1–7 days": "#ef4444",
  "8–14 days": "#fbbf24",
  "15–30 days": "#10b981",
  "30+ days": "#3b82f6",
  "No date published": "#64748b",
};

function ColumnChart({ rows, total, examples }) {
  const max = rows.reduce((m, r) => Math.max(m, r.n), 0) || 1;
  return (
    <div className="ovb">
      {rows.map((r) => (
        <div
          className={`ovb-col${r.key === NO_DATE ? " nodate" : ""}`}
          key={r.key}
          title={examples ? examples(r.key) : undefined}
        >
          <span className="ovb-n">{fmt(r.n)}</span>
          <span className="ovb-track">
            {/* min 2px so a bucket of 1 is a mark, not an invisible zero */}
            <i style={{ height: `max(2px, ${(r.n / max) * 100}%)`, background: WINDOW_COLORS[r.key] || "var(--fav-badge)" }} />
          </span>
          <span className="ovb-lab">{r.key}</span>
          <span className="ovb-pct">{total ? `${Math.round((r.n / total) * 100)}%` : ""}</span>
        </div>
      ))}
    </div>
  );
}

/* A chart card: heading, note, and whatever chart the question deserves. */
function Chart({ title, note, empty, show, children }) {
  return (
    <section aria-label={title} className="ovc">
      <div className="ovc-h">
        <span className="eyebrow">{title}</span>
        {note ? <span className="ovc-note">{note}</span> : null}
      </div>
      {show ? children : <div className="ovc-empty">{empty || "nothing on record in this corpus"}</div>}
    </section>
  );
}

export default function MarketOverview() {
  const { data } = useData();
  const { setScope } = useAppState();
  const [section, setSectionRaw] = useState(savedSection);
  const [rows, setRows] = useState(TABLE_PAGE);
  const [country, setCountry] = useState("all");
  const [cat, setCat] = useState(null);

  const setSection = (id) => {
    setSectionRaw(id);
    setRows(TABLE_PAGE);
    try {
      localStorage.setItem(SECTION_KEY, id);
    } catch (e) {}
  };

  const tenders = data.tenders || [];
  const { open, awarded, closed } = useMemo(() => bucketTenders(tenders), [tenders]);

  /* The report is about live demand — awarded and closed rows have their own sections,
     and counting them into the charts would inflate every number on the page. */
  const scope = section === "awarded" ? awarded : section === "closed" ? closed : open;
  const list = useMemo(() => {
    let out = country === "all" ? scope : scope.filter((t) => t.country === country);
    /* A pie slice can be the folded "Other", which is not any row's own category —
       match on the SLICE a row belongs to, so clicking Other returns its members. */
    if (cat) out = out.filter((t) => catOf(t) === cat || sliceLabel(catOf(t)) === cat);
    return out.slice().sort((a, b) => (a.dl || 0) - (b.dl || 0));
  }, [scope, country, cat]);
  const n = list.length;

  const countries = useMemo(() => countriesOf(tenders), [tenders]);
  /* Palette first, from the whole corpus — every later colour lookup reads the map this
     builds, so it must run before demandSplit and before the filter renders its dots. */
  const cats = useMemo(() => {
    initCategoryPalette(tenders);
    return categoryRank(tenders);
  }, [tenders]);
  const portals = useMemo(() => portalRows(tenders), [tenders]);
  /* The charts describe the OPEN set narrowed by country — never by the category the pie
     itself sets, or picking a slice would redraw the pie as a single full circle. */
  const chartBase = useMemo(
    () => (country === "all" ? open : open.filter((t) => t.country === country)),
    [open, country],
  );
  const demandRows = useMemo(
    () => demandSplit(chartBase).map((s) => ({ key: s.label, n: s.count })),
    [chartBase],
  );
  const closingRows = useMemo(
    () => closingWindows(chartBase).map((w) => ({ key: w.label, n: w.count })),
    [chartBase],
  );

  /* Up to three real titles behind a mark — the tooltip enhances, it never holds a
     number the row is missing. */
  const examplesFor = (pick) => (key) => {
    const hits = chartBase.filter((t) => pick(t) === key);
    return (
      hits.slice(0, 3).map((t) => `• ${t.title}`).join("\n") +
      (hits.length > 3 ? `\n…and ${hits.length - 3} more` : "")
    );
  };

  useEffect(() => {
    setScope("market", { tenders: n, section, country, cat }, {
      pillar: "Market",
      view: "Market Intelligence",
      selection: cat || (country === "all" ? null : country),
    });
  }, [n, section, country, cat, setScope]);

  const page = (src) => src.slice(0, rows);
  const more = (src) =>
    src.length > rows ? (
      <button className="ovt-more" onClick={() => setRows((r) => r + TABLE_PAGE * 2)} type="button">
        Show {Math.min(TABLE_PAGE * 2, src.length - rows)} more of {fmt(src.length - rows)}
      </button>
    ) : null;

  const none = (txt) => <span className="ovt-none">{txt}</span>;

  const titleCell = (t) => (
    <td className="ovt-t">
      {t.url ? (
        <a href={t.url} rel="noopener noreferrer" target="_blank" title={t.title}>
          {t.title}
        </a>
      ) : (
        <span title={t.title}>{t.title}</span>
      )}
      <span className="ovt-buyer">{[t.issuer, t.country].filter(Boolean).join(" · ")}</span>
    </td>
  );

  const sourceCell = (t) =>
    t.url ? (
      <td>
        <a href={t.url} rel="noopener noreferrer" target="_blank" title={t.url}>
          {hostOf(t.url)} ↗
        </a>
      </td>
    ) : (
      <td>{none("no URL on record")}</td>
    );

  const tenderTable = (src, emptyNote) =>
    src.length ? (
      <>
        <div className="ovt-scroll">
          <table>
            <thead>
              <tr>
                <th>Tender</th>
                <th>Where</th>
                <th>Category</th>
                <th>Closes</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {page(src).map((t) => (
                <tr key={t.id}>
                  {titleCell(t)}
                  <td>{t.country || none("—")}</td>
                  <td>{t.cat || none("—")}</td>
                  {/* the column is headed "Closes" -- it must hold a date, not a countdown */}
                  <td className="num">{t.closingDate || "—"}</td>
                  {sourceCell(t)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {more(src)}
      </>
    ) : (
      <div className="ovc-empty">{emptyNote}</div>
    );

  const countOf = (s) =>
    s.id === "sites"
      ? portals.length
      : s.id === "awarded"
        ? awarded.length
        : s.id === "closed"
          ? closed.length
          : s.id === "category"
            ? demandSplit(open).length
            : open.length;

  return (
    <div className="ov-report">
      {/* The five sections are the page's navigation, so they sit FIRST — above the
          filter, where navigation goes. The filter only narrows whichever section you
          have already chosen. Sticky, so the cut you are reading is still named once you
          have scrolled into a long list of rows. */}
      <div className="ovtabs" role="tablist">
        {SECTIONS.map((s, i) => (
          <button
            aria-selected={section === s.id}
            className={`ovtab${section === s.id ? " on" : ""}`}
            key={s.id}
            onClick={() => setSection(s.id)}
            role="tab"
            type="button"
          >
            <span className="ovtab-ix">{String(i + 1).padStart(2, "0")}</span>
            <span className="ovtab-nm">{s.label}</span>
            {/* how many rows this tab is about to show — the one thing its label cannot say */}
            <span className="ovtab-ct">{countOf(s)}</span>
          </button>
        ))}
      </div>

      {/* Country and category, UNDER the tabs: both narrow the section above them, so
          they read in that order.

          The category control carries the chart's own colour — a swatch on the control
          and a dot on every option — because that colour is what the pie above uses to
          say the same thing. Two encodings of one category that don't match is worse
          than one. The swatch is a SECOND encoding of a choice the text already states,
          never the only one: the option is readable with the dot ignored entirely. */}
      <div className="tp-fbar">
        <span className="eyebrow">Filter</span>
        <select
          aria-label="Filter by country"
          onChange={(e) => setCountry(e.target.value)}
          value={country}
        >
          <option value="all">Country · All ({countries.length})</option>
          {countries.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <span className="ovf-cat">
          <span
            aria-hidden="true"
            className="ovf-sw"
            style={{ background: cat ? CATEGORY_COLOR(sliceLabel(cat)) : "transparent" }}
          />
          <select
            aria-label="Filter by category"
            onChange={(e) => setCat(e.target.value === "all" ? null : e.target.value)}
            value={cat || "all"}
          >
            <option value="all">Category · All ({cats.length})</option>
            {cats.map((c) => (
              <option key={c.label} style={{ color: CATEGORY_COLOR(sliceLabel(c.label)) }} value={c.label}>
                {c.label} ({c.count})
              </option>
            ))}
          </select>
        </span>
        {cat ? (
          <button className="ovt-link" onClick={() => setCat(null)} type="button">
            clear {cat} ✕
          </button>
        ) : null}
        <span className="sortnote">
          {fmt(n)} row{n === 1 ? "" : "s"}
          {country === "all" ? "" : ` in ${country}`}
          {cat ? ` · ${cat}` : ""}
        </span>
      </div>

      {/* The two charts, in the active-tenders section ONLY. They summarise the live
          corpus, so they belong beside the count of it and nowhere else — a table of
          awarded contracts under a closing-window chart invites you to read the chart as
          describing the table, which it never did. The pie doubles as navigation. */}
      {section === "active" ? (
        <div className="ovc-grid">
          <Chart
            empty="nothing on record states a category"
            note="click a slice to filter the rows below · the split this corpus records, by procurement category"
            show={demandRows.length > 0}
            title="Demand split"
          >
            <PieChart
              colorOf={(k) => CATEGORY_COLOR(k)}
              examples={examplesFor((t) => sliceLabel(catOf(t)))}
              onPick={(k) => setCat((c) => (c === k ? null : k))}
              rows={demandRows}
              total={chartBase.length}
            />
          </Chart>
          <Chart
            empty="nothing open on record"
            note="how much runway is left · open tenders only, so a settled award is never counted as undated pipeline"
            show={closingRows.length > 0}
            title="Closing window"
          >
            <ColumnChart
              examples={examplesFor(windowOf)}
              rows={closingRows}
              total={chartBase.length}
            />
          </Chart>
        </div>
      ) : null}

      <section className="ovt">
        {section === "category" ? (
          <>
            <div className="ovc-h">
              <span className="eyebrow">By category</span>
              <span className="ovc-note">
                every open tender counted exactly once · click a row to read it in the table
              </span>
            </div>
            <div className="ovt-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th className="num">Open</th>
                    <th className="num">Share</th>
                    <th>Markets</th>
                  </tr>
                </thead>
                <tbody>
                  {demandSplit(open).map((s) => (
                    <tr key={s.label}>
                      <td className="ovt-t">
                        <button
                          onClick={() => {
                            setCat(s.label);
                            setSection("active");
                          }}
                          type="button"
                        >
                          {s.label}
                        </button>
                      </td>
                      <td className="num">{fmt(s.count)}</td>
                      <td className="num">{s.pct}%</td>
                      <td>
                        {Array.from(
                          new Set(
                            open
                              .filter((t) => catOf(t) === s.label || sliceLabel(catOf(t)) === s.label)
                              .map((t) => t.country),
                          ),
                        )
                          .filter(Boolean)
                          .join(" · ") || none("—")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <>
            <div className="ovc-h">
              <span className="eyebrow">{SECTIONS.find((s) => s.id === section).label}</span>
              <span className="ovc-note">
                {fmt(n)} row{n === 1 ? "" : "s"} · sorted by deadline · each row links to its source
                {section === "active" ? " · no tender on record publishes a value" : ""}
              </span>
            </div>
            {tenderTable(
              list,
              `no ${section === "active" ? "open" : section} tender on record for this filter`,
            )}
          </>
        )}
      </section>
    </div>
  );
}
