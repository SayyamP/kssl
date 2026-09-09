import { useEffect, useMemo, useState } from "react";
import { useAppState, useHeaderReport } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { bucketTenders } from "../../lib/overview";
import { formatDate } from "../../utils/formatDate";
import {
  CATEGORY_COLOR,
  catOf,
  closingWindows,
  demandSplit,
  hostOf,
  initCategoryPalette,
  portalRows,
  reportFacets,
  reportRows,
  sliceLabel,
  valueNote,
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
/* Darkened per the brief. NOT as dark as the alliance-graph nodes, and the difference
   is the point: there, every node is directly labelled and hue is decoration, so it can
   go as dark as it likes. Here the colour IS the encoding -- a bar's hue is its urgency
   band -- so darkening past a point destroys the reading. Taken to the graph's darkness
   the blue and the off-scale grey measured dE 8.2 apart, meaning nobody could tell
   "30+ days" from "No date published".

   The four SCALE colours pass every dataviz check on the dark surface (lightness band,
   chroma floor, normal-vision separation, contrast). The grey is excluded from that
   check on purpose: it is deliberately off-scale, as the note above says. */
const WINDOW_COLORS = {
  "1–7 days": "#c03a3a",
  "8–14 days": "#a87d16",
  "15–30 days": "#13906a",
  "30+ days": "#3670bd",
  "No date published": "#6b7480",
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
  const { setScope, takePending } = useAppState();
  const [section, setSectionRaw] = useState(savedSection);
  const [rows, setRows] = useState(TABLE_PAGE);
  const [country, setCountry] = useState("all");
  const [cat, setCat] = useState(null);

  const setSection = (id) => {
    setSectionRaw(id);
    setRows(TABLE_PAGE);
    /* the options are the new section's rows; a country or category picked in another
       section may not exist in this one, and a filter matching nothing must not be
       silently kept. Both are reset -- the country alone was, and a category carried
       across tabs was still filtering the awarded list. */
    setCountry("all");
    setCat(null);
    try {
      localStorage.setItem(SECTION_KEY, id);
    } catch (e) {}
  };

  /* A metric tile on the Market overview ("Already concluded", "Markets tracked")
     opens the report on the section that holds what it counted. */
  useEffect(() => {
    const p = takePending("m-report");
    if (p && p.section && SECTIONS.some((s) => s.id === p.section)) setSection(p.section);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takePending]);

  const tenders = data.tenders || [];
  /* Palette first, from the whole corpus — every later colour lookup reads the map this
     builds, so it must run before the facets, demandSplit and the filter's dots. */
  useMemo(() => initCategoryPalette(tenders), [tenders]);
  const { open, awarded, closed } = useMemo(() => bucketTenders(tenders), [tenders]);

  /* The report is about live demand — awarded and closed rows have their own sections,
     and counting them into the charts would inflate every number on the page. */
  const scope = section === "awarded" ? awarded : section === "closed" ? closed : open;
  /* A pie slice can be the folded "Other", which is not any row's own category --
     reportRows matches on the SLICE a row belongs to, so clicking Other returns its
     members. */
  const list = useMemo(() => reportRows(scope, { country, cat }), [scope, country, cat]);
  const n = list.length;

  /* Both filters over `scope` -- the rows this section lists -- each counted with the
     OTHER filter applied, so an option lists exactly what it advertises. The country
     select was already built this way; the category select was ranked over all 136
     tenders whatever the tab and read "Ammunition (48)" over an awarded list of 11. */
  const facets = useMemo(() => reportFacets(scope, { country, cat }), [scope, country, cat]);
  const countries = facets.countries;
  const cats = useMemo(() => facets.cats.map((c) => ({ label: c.v, count: c.n })), [facets]);
  /* What the header's Copy / Export / Print act on: the pipeline split and the rows
     the report is currently listing, under the section and filters in force. */
  const report = useMemo(() => {
    const bucket = section === "awarded" ? "Awarded" : section === "closed" ? "Closed" : "Open";
    return {
      title: "Market Report",
      subtitle: `${bucket.toLowerCase()} tenders${country === "all" ? "" : ` · ${country}`}${cat ? ` · ${cat}` : ""}`,
      sections: [
        {
          h: "Pipeline",
          rows: [
            ["Open", String(open.length)],
            ["Awarded", String(awarded.length)],
            ["Closed", String(closed.length)],
          ],
        },
        {
          h: `${bucket} tenders listed (${n})`,
          rows: list.map((x) => [x.title, [x.country, x.cat, x.value, x.deadline].filter(Boolean).join(" · ")]),
        },
      ],
      payload: {
        section,
        country,
        category: cat || null,
        counts: { open: open.length, awarded: awarded.length, closed: closed.length },
        tenders: list,
      },
    };
  }, [section, country, cat, open, awarded, closed, list, n]);
  useHeaderReport(report);

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
    /* "Market Report" is the rail label and the heading; the context line said
       "Market Intelligence", a page that exists nowhere in the navigation (FE 18). */
    setScope("market", { tenders: n, section, country, cat }, {
      pillar: "Market",
      view: "Market Report",
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
                  <td className="num">{t.closingDate ? formatDate(t.closingDate) : "—"}</td>
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
      {/* The same control shape as the Tender Pipeline's filter bar (tender.css
          .tp-dd-input): a mono label, the value in white, a clear cross inside the
          control once something is picked. The report had its own -- rounded native
          selects, a separate green "clear" chip -- so the two tabs of one pillar
          filtered in two designs. The <select> is kept because it is the correct
          control for keyboard and screen readers; only its chrome is shared. */}
      <div className="tp-fbar">
        <span className="eyebrow">Filter</span>
        <label className="ovf-sel">
          <span className="ddlbl">Country</span>
          <select
            aria-label="Filter by country"
            onChange={(e) => setCountry(e.target.value)}
            value={country}
          >
            <option value="all">All ({countries.length})</option>
            {countries.map((c) => (
              <option key={c.v} value={c.v}>
                {c.v} ({c.n})
              </option>
            ))}
          </select>
          {country !== "all" ? (
            <button
              aria-label="Clear country"
              className="ddclear"
              onClick={(e) => {
                e.preventDefault();
                setCountry("all");
              }}
              type="button"
            >
              ×
            </button>
          ) : null}
        </label>
        <label className="ovf-sel">
          {cat ? (
            <span
              aria-hidden="true"
              className="ovf-sw"
              style={{ background: CATEGORY_COLOR(sliceLabel(cat)) }}
            />
          ) : null}
          <span className="ddlbl">Category</span>
          <select
            aria-label="Filter by category"
            onChange={(e) => setCat(e.target.value === "all" ? null : e.target.value)}
            value={cat || "all"}
          >
            <option value="all">All ({cats.length})</option>
            {cats.map((c) => (
              <option key={c.label} style={{ color: CATEGORY_COLOR(sliceLabel(c.label)) }} value={c.label}>
                {c.label} ({c.count})
              </option>
            ))}
          </select>
          {cat ? (
            <button
              aria-label="Clear category"
              className="ddclear"
              onClick={(e) => {
                e.preventDefault();
                setCat(null);
              }}
              type="button"
            >
              ×
            </button>
          ) : null}
        </label>
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
                            /* section first: setSection clears the category, so the
                               pick has to land after it */
                            setSection("active");
                            setCat(s.label);
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
                {/* measured over the rows listed -- this was a hard-coded "no tender on
                    record publishes a value" on a corpus where 14 do */}
                {section === "active" && n ? ` · ${valueNote(list)}` : ""}
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
