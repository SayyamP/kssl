import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import ScopeChat from "../../components/scopeChat/ScopeChat";
import { useAppState, useHeaderReport } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { gapCorrelateStrip } from "../../lib/gapModel";
import { srcChips } from "../../lib/html";
import { formatLabel } from "../../lib/profile";
import { facetOptions } from "../../lib/countryFacet";
import { NOT_ON_RECORD, resolveTenderRow, tenderFactRows } from "../../lib/tenderRow";

const fitClass = (p) => {
  const n = parseInt(p, 10);
  return n >= 75 ? "high" : n >= 50 ? "mid" : "low";
};

const has = (v) => v != null && String(v).trim() !== "";

/* The source record's own reference (the part after the 'ted_/ca_/gem_/uk_/sam_'
   prefix on the id) — the number a buyer's portal actually indexes the notice by. */
const noticeRef = (t) => {
  if (!t || !t.id) return null;
  const s = String(t.id);
  const u = s.indexOf("_");
  return u > -1 ? s.slice(u + 1) : s;
};

/* The facts of a notice: the FIXED eight (src/lib/tenderRow.js) -- each a stored value
   or the explicit unresolved state -- then the notice reference the portal indexes it
   by. Rows are [label, text, resolved]. Nothing is dropped for being empty: a field the
   notice does not publish is a fact about the notice, and it used to vanish here (and
   an empty status used to be printed as "Open", which nobody recorded). */
const factRows = (t) => {
  if (!t) return [];
  const rows = tenderFactRows(t);
  const ref = noticeRef(t);
  rows.push(["Notice ref.", has(ref) ? ref : NOT_ON_RECORD, has(ref)]);
  return rows;
};

/* A meta line is only the parts the record carries — a null `value` used to leave
   its separator behind, so every card read "… ·  · …". A part is a string, or
   [text, className] where the original markup styled that span. */
const metaLine = (parts) =>
  parts
    .map((p) => (Array.isArray(p) ? p : [p, null]))
    .filter(([txt]) => has(txt))
    .map(([txt, cls], n) => (
      <Fragment key={`${n}-${txt}`}>
        {n ? <span className="sep">·</span> : null}
        <span className={cls || undefined}>{txt}</span>
      </Fragment>
    ));

const dlClass = (d, statusClass) => {
  if (statusClass) return statusClass;
  const n = Number(d);
  if (isNaN(n) || n <= 0) return "settled";
  return n <= 7 ? "urgent" : n <= 14 ? "soon" : "normal";
};

/* The button used to promise a portal and open nothing. Every tender carries its
   source URL, so open that. urlKind says what it lands on: 'notice' = this tender's
   own page, 'portal' = the listing it was found in, 'award' = an already-decided
   contract. Label it honestly rather than promising a notice we do not have. */
const tpUrl = (t) => (t && t.url) || (t && t.srcs && t.srcs.length ? t.srcs[0].url : null);
const ctaLabel = (t) =>
  t.urlKind === "award"
    ? "Read the award announcement"
    : t.urlKind === "portal"
      ? "Open the tender portal"
      : tpUrl(t)
        ? "Open the tender notice"
        : "Pursue this tender";
const ctaNote = (t) => {
  const u = tpUrl(t);
  if (!u) return "no source URL on this record";
  return (
    ({
      notice: "opens this tender on ",
      portal: "no per-tender page on record — opens the listing on ",
      award: "this contract is settled — opens the announcement on ",
    }[t.urlKind] || "opens ") + u.replace(/^https?:\/\/(www\.)?/, "").split("/")[0]
  );
};

export default function Tenders({ mode = "tender" }) {
  const { data, gapModel } = useData();
  const { setScope, takePending, searchQuery } = useAppState();
  const clientName = (data.client && (data.client.short || data.client.name)) || "KSSL";
  const [productType, setProductType] = useState(null);
  const [country, setCountry] = useState(null);
  const [cat, setCat] = useState(null);
  const [menu, setMenu] = useState(null);
  const [menuQuery, setMenuQuery] = useState("");
  const [sel, setSel] = useState(null);
  const asmtRef = useRef(null);

  useEffect(() => {
    if (asmtRef.current) {
      asmtRef.current.scrollTop = 0;
    }
  }, [sel]);

  /* A tab CHANGE drops the selection -- a row from the open list is not on the awarded
     list. Guarded against the mount run: an effect with [mode] also fires once after
     the first render, and that run was clearing the `sel` restored from localStorage
     three lines up, so the selection this page saves on every change never survived a
     reload or a detour to the Market Report and back. */
  const lastMode = useRef(mode);
  useEffect(() => {
    if (lastMode.current === mode) return;
    lastMode.current = mode;
    setSel(null);
  }, [mode]);

  useEffect(() => {
    const onDocClick = (e) => {
      if (!e.target.closest(".tp-dd")) setMenu(null);
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  /* `scope` is the tab and the search box -- everything that is NOT one of the three
     dropdown facets. Each facet's option counts are then taken from scope with the OTHER
     two facets applied, so a badge can never describe a different set than the rows
     below it. They read "India 7" over a list of 2, because the counts ran over all 106
     tenders while the list showed only the 74 that are open; five of those seven had
     closed. Product Type had the same fault and is included here -- fixing two of three
     facets and leaving the third is how this bug survives a fix. */
  const isAirNaval = (t) =>
    /uav|drone|naval|marine|missile|air defence/i.test(`${t.cat} ${t.title}`);

  const scope = useMemo(
    () =>
      (data.tenders || [])
        .filter((t) => {
          const isAwarded = (t.status || "").toLowerCase() === "awarded" || t.urlKind === "award";
          const isClosed = !isAwarded && (t.isLive === false || (t.status || "").toLowerCase() === "closed" || (t.deadline || "").toLowerCase().includes("closed"));
          const isOpen = !isAwarded && !isClosed;

          if (mode === "awarded-tenders") return isAwarded;
          if (mode === "closed-tenders") return isClosed;
          return isOpen;
        })
        .filter((t) => {
          if (!searchQuery) return true;
          const tokens = searchQuery.trim().toLowerCase().split(/\s+/).filter(Boolean);
          const fullText = `${t.title || ""} ${t.issuer || ""} ${t.cat || ""} ${t.country || ""} ${t.desc || ""}`.toLowerCase();
          return tokens.every((tok) => fullText.includes(tok));
        }),
    [data.tenders, mode, searchQuery],
  );

  /* One place decides what each facet means, so the list and the counts cannot drift. */
  const facetOk = {
    country: (t, v) => !v || t.country === v,
    cat: (t, v) => !v || t.cat === v,
    productType: (t, v) =>
      !v || (v === "Air, Naval & Missiles" ? isAirNaval(t) : !isAirNaval(t)),
  };

  const applyFacets = (rows, except) =>
    rows.filter(
      (t) =>
        (except === "country" || facetOk.country(t, country)) &&
        (except === "cat" || facetOk.cat(t, cat)) &&
        (except === "productType" || facetOk.productType(t, productType)),
    );

  const list = useMemo(
    () =>
      applyFacets(scope, null).sort(
        (a, b) => (Number(a.dl) || 999) - (Number(b.dl) || 999),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scope, country, cat, productType],
  );

  const select = (id) => {
    const t = (data.tenders || []).find((x) => x.id === id);
    if (!t) return;
    setSel(id);
    setScope("tender", { type: "tender", data: t }, {
      pillar: "Market",
      view: "Tender Pipeline",
      selection: `${t.title} (${t.country})`,
    });
  };

  /* A correlate chip elsewhere can open a tender here by title. */
  useEffect(() => {
    const p = takePending("tender");
    if (p && p.tenderTitle) {
      const t =
        (data.tenders || []).find((x) => x.title === p.tenderTitle) ||
        (data.tenders || []).find(
          (x) => x.title.indexOf(p.tenderTitle) > -1 || p.tenderTitle.indexOf(x.title) > -1,
        );
      if (t) {
        select(t.id);
        setTimeout(() => asmtRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 130);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takePending]);

  const t = sel ? (data.tenders || []).find((x) => x.id === sel) : null;

  /* What the header's Copy / Export / Print act on: the open tender's facts and
     requirement rows as served, then every tender listed under the tab and facets in
     force. */
  const modeTitle =
    mode === "awarded-tenders" ? "Awarded Tenders" : mode === "closed-tenders" ? "Closed Tenders" : "Tender Pipeline";
  const report = useMemo(() => {
    /* the same eight parameters the card shows, labelled, unresolved ones included */
    const row = (x) => [
      x.title,
      resolveTenderRow(x).params.map((p) => `${p.label}: ${p.text}`).join(" · "),
    ];
    const sections = [];
    if (t) {
      sections.push({
        h: "Selected tender",
        rows: [["Title", t.title], ...factRows(t).map(([k, v]) => [k, v])],
      });
      if (has(t.reqNote)) sections.push({ h: "Requirement", rows: [t.reqNote] });
      if (Array.isArray(t.req) && t.req.length) sections.push({ h: "Requirements", rows: t.req });
      if (Array.isArray(t.matches) && t.matches.length) {
        sections.push({
          h: `${clientName} match`,
          rows: t.matches.map((m) => [m.n, [m.fit, m.pct].filter(has).join(" · ")]),
        });
      }
    }
    sections.push({ h: `${modeTitle} (${list.length})`, rows: list.map(row) });
    return {
      title: modeTitle,
      subtitle: [country, cat, productType].filter(Boolean).join(" · ") || "all tenders in this tab",
      sections,
      payload: {
        tab: mode,
        filters: { country: country || null, category: cat || null, productType: productType || null },
        selected: t || null,
        tenders: list,
      },
    };
  }, [t, list, mode, modeTitle, country, cat, productType, clientName]);
  useHeaderReport(report);

  const menuItems = (which) => {
    if (which === "productType") {
      const pool = applyFacets(scope, "productType");
      return [
        { v: "Land Systems", n: pool.filter((x) => !isAirNaval(x)).length },
        { v: "Air, Naval & Missiles", n: pool.filter(isAirNaval).length },
      ];
    }
    /* Option values come from the SERVED tenders only. The config vocabulary
       (tpAllCountries / tpAllCats) ORDERS them; it adds nothing. It used to be unioned
       in "for completeness", which put Armenia, Kenya, Morocco and eight more countries
       with no tender at all into the menu as unclickable zero rows -- eleven of the
       twenty-five options were padding -- and the acceptance test read that as the
       filter not matching the data. An option is a promise of rows; a zero is not
       information a menu should carry.
       Counted over `scope` with the OTHER facets applied -- the facet being counted is
       excluded, so picking one of its options gives exactly the number promised. */
    const cfgOrder = which === "country" ? data.tpAllCountries || [] : data.tpAllCats || [];
    const pool = applyFacets(scope, which);
    const q = menuQuery.trim().toLowerCase();
    return facetOptions(pool, (x) => (which === "country" ? x.country : x.cat), cfgOrder)
      .filter((o) => which !== "country" || !q || o.v.toLowerCase().includes(q));
  };

  const dd = (which, label, value, setValue) => {
    /* one array: the "All" row prints its length, the rows under it are its members */
    const items = menuItems(which);
    return (
    <div className="tp-dd" data-tpdd={which}>
      <div
        className={`tp-dd-input${value ? " has-val" : ""}`}
        onClick={() => {
          setMenuQuery("");
          setMenu(menu === which ? null : which);
        }}
        role="button"
        tabIndex={0}
      >
        <span className="ddlbl">{label}</span>
        <span className={`ddval${value ? "" : " placeholder"}`}>{value || "All"}</span>
        <span className="caret">▾</span>
        <span
          className="ddclear"
          onClick={(e) => {
            e.stopPropagation();
            setValue(null);
          }}
        >
          ×
        </span>
      </div>
      <div className={`tp-dd-menu${menu === which ? " open" : ""}`}>
        {which === "country" ? (
          <div className="tp-dd-search">
            <input
              autoComplete="off"
              onChange={(e) => setMenuQuery(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              placeholder="Search country…"
              type="text"
              value={menu === "country" ? menuQuery : ""}
            />
          </div>
        ) : null}
        <div
          className="tp-dd-pick tp-dd-all"
          onClick={() => {
            setValue(null);
            setMenu(null);
          }}
        >
          All {which === "country" ? "countries" : which === "productType" ? "product types" : "categories"} ({items.length})
        </div>
        {items.map(({ v, n }) => (
          <div
            className="tp-dd-pick"
            key={v}
            onClick={() => {
              setValue(v);
              setSel(null);
              setMenu(null);
            }}
          >
            {v}
            <span className="m">{n}</span>
          </div>
        ))}
      </div>
    </div>
    );
  };

  return (
    <div className={`tp-view v-tender ${t ? "has-sel" : "no-sel"}`}>
      <div className="tp-list">
        <div className="tp-fbar">
          <span className="eyebrow">Filter</span>
          {dd("productType", "Product Type", productType, setProductType)}
          {dd("country", "Country", country, setCountry)}
          {dd("cat", "Category", cat, setCat)}
          <span className="sortnote">sorted by deadline</span>
        </div>
        <div className="tp-sum">
          <b>{list.length}</b>{" "}
          {mode === "awarded-tenders"
            ? "awarded"
            : mode === "closed-tenders"
              ? "closed"
              : "open"}{" "}
          tender{list.length !== 1 ? "s" : ""}
          {productType || country || cat ? " (filtered)" : ""} · sorted by deadline
        </div>
        {/* Stated ONCE for the list, the way the Innovation view states its missing
            fields once for the domain. `matches` is empty on every served tender, so
            no card can carry a fit line; saying so here is the difference between a
            field that was assessed as poor and one that was never assessed at all. */}
        {list.length && !list.some((r) => (r.matches || []).length) ? (
          <div className="tp-sum tp-sum-note">
            No {clientName} fit assessment was served for these tenders — the requirement
            match is not part of this dataset, so no card carries a fit score.
          </div>
        ) : null}
        <div id="tp-cards">
          {list.length ? (
            list.map((row) => {
              /* THE BAR'S LENGTH HAS TO BE THE MEASUREMENT.
                 The width came from a three-value constant map -- high 85%, mid 55%,
                 low 25% -- so a source publishing 76% and one publishing 98% both drew
                 the same 85% bar, and the reader was looking at a lookup table rendered
                 as a measured quantity. A real percentage now sets its own width. A
                 TIER WORD is a grade, not a length, so it prints as the word with no
                 track behind it rather than being converted into a bar nobody measured.

                 And with no match row at all there is no verdict to fall back on:
                 'weak' used to be stamped on every tender out of nothing. On the served
                 corpus that is every row -- `matches` is empty on all of them -- so the
                 whole fit line is omitted per card (see fitAssessed below) and the list
                 header states once that no fit assessment was served. An empty labelled
                 shell on 136 cards is a surface pretending to have an opinion. */
              const m0 = (row.matches || [])[0];
              const pctNum = m0 && /%/.test(m0.pct || "")
                ? parseFloat(String(m0.pct).replace(/[^\d.]/g, ""))
                : NaN;
              const scored = !Number.isNaN(pctNum);
              const graded = !!(m0 && has(m0.fit));
              const assessed = scored || graded;
              const fc = scored ? fitClass(m0.pct) : graded ? m0.fit : null;
              const fw = scored ? `${Math.max(0, Math.min(100, pctNum))}%` : "0%";
              const fp = scored
                ? m0.pct
                : graded
                  ? { high: "strong", mid: "partial", low: "weak" }[fc] || fc
                  : "";
              return (
                <div
                  className={`tcard${sel === row.id ? " sel" : ""}`}
                  key={row.id}
                  onClick={() => select(row.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      select(row.id);
                    }
                  }}
                >
                  <div className="trow1">
                    <div className="ttl">{row.title}</div>
                    <span className={`ddl ${dlClass(row.dl, row.statusClass)}`}>{row.deadline}</span>
                  </div>
                  <div className="tpgrid">
                    {/* The SAME eight parameters on every card, in the same order, each a
                        stored value or the explicit "not on record" state. The chip above
                        is a countdown; the date it counts to is the Closing date cell. A
                        one-word title ("Ammunition") is read with its buyer, country,
                        category and portal around it, and a value the notice never
                        published is stated as absent rather than silently dropped. */}
                    {resolveTenderRow(row).params.map((p) => (
                      <div className="tpp" key={p.key}>
                        <span className="tpk">{p.label}</span>
                        <span className={`tpv${p.value == null ? " na" : ""}`}>{p.text}</span>
                      </div>
                    ))}
                  </div>
                  {/* No assessment -> no fit row. A labelled control reading "not
                      assessed" on every card is chrome for a feature that is not
                      there; the header says it once, for the whole list. */}
                  {assessed ? (
                    <div className="fitbar">
                      <span className="fitlab">{clientName} fit</span>
                      {scored ? (
                        <span className="fittrack">
                          <i className={fc} style={{ width: fw }} />
                        </span>
                      ) : null}
                      <span className={`fitpct${scored ? "" : " grade"}`}>{fp}</span>
                    </div>
                  ) : null}
                </div>
              );
            })
          ) : (
            <div className="tp-list-empty">
              {productType || country || cat
                ? "No tenders match this filter"
                : "No tenders served yet"}
            </div>
          )}
        </div>
      </div>

      <div className="tp-asmt" id="tp-asmt">
        {t ? (
          <div id="tp-asmt-body" style={{ display: "flex", flex: 1, flexDirection: "column", height: "100%", overflow: "hidden" }}>
            <div className="tp-asmt-scroll" ref={asmtRef} style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", paddingBottom: "24px" }}>
              <div className="tp-asmt-h">
                <div className="ctx-h-actions">
                  <button
                    aria-label="Close"
                    className="col-close"
                    onClick={() => setSel(null)}
                    title="Close"
                    type="button"
                  >
                    ✕
                  </button>
                </div>
                <span className="eyebrow">Tender Assessment</span>
                <div className="ct">{t.title}</div>
                <div className="sub" style={{ display: "flex", flexDirection: "column", gap: "4px", marginTop: "8px" }}>
                  <div>{metaLine([t.issuer, t.country, t.value])}</div>
                  <div>{metaLine([t.timing || t.deadline])}</div>
                </div>
              </div>

              <div className="tp-asmt-sec">
                <span className="eyebrow">Tender details</span>
                <div className="tp-facts">
                  {factRows(t).map(([k, v, resolved]) => (
                    <div className="kv" key={k}>
                      {/* the label wears the house capitalisation, the value never does */}
                      <span className="k">{formatLabel(k)}</span>
                      <span className={`v${resolved ? "" : " na"}`}>{v}</span>
                    </div>
                  ))}
                </div>
              </div>

              {has(t.reqNote) || (t.req || []).length ? (
                <div className="tp-asmt-sec">
                  <span className="eyebrow">What the tender requires</span>
                  {has(t.reqNote) ? (
                    <div className="req" dangerouslySetInnerHTML={{ __html: t.reqNote }} />
                  ) : null}
                  {(t.req || []).map((r, i) => (
                    <div className="kv" key={`${r[0]}-${i}`}>
                      <span className="k">{r[0]}</span>
                      <span className="v" dangerouslySetInnerHTML={{ __html: r[1] }} />
                    </div>
                  ))}
                  {(t.req || []).some((r) => /indigen|content|offset/i.test(`${r[0]} ${r[1]}`)) ? (
                    <div className="req-gloss">
                      “Indigenous content” = the DAP 2020 threshold a bid must clear for its
                      procurement category (50%+ for Buy Indian-IDDM). A bid that cannot declare the
                      threshold is technically non-compliant regardless of price.
                    </div>
                  ) : null}
                </div>
              ) : null}

              {(t.matches || []).length ? (
              <div className="tp-asmt-sec">
                <span className="eyebrow">Matched {clientName} products</span>
                {(t.matches || []).map((m, i) => (
                  <div className="tp-match" key={`${m.n}-${i}`}>
                    <div className="mh">
                      <span className="mn">{m.n}</span>
                      <span className={`fit ${m.fit}`}>{m.pct} fit</span>
                    </div>
                    {(m.lines || []).map((l, j) => (
                      <div className="mline" key={j}>
                        <span className={`mk ${l[0]}`}>{l[0] === "up" ? "▲" : "▼"}</span>
                        <span dangerouslySetInnerHTML={{ __html: l[1] }} />
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              ) : null}

              <div className="tp-asmt-sec">
                {has(t.leanTxt) ? (
                  <div className={`tp-lean${has(t.lean) ? ` ${t.lean}` : ""}`}>
                    <span className="tl">Bid assessment</span>
                    <span dangerouslySetInnerHTML={{ __html: t.leanTxt }} />
                  </div>
                ) : null}
                {srcChips(t.srcs && t.srcs.length ? t.srcs : t.url ? [{ label: "Source", url: t.url }] : null) ? (
                  <div style={{ marginTop: "10px" }}>
                    <span className="eyebrow">Source</span>
                    <div
                      dangerouslySetInnerHTML={{
                        __html: srcChips(
                          t.srcs && t.srcs.length ? t.srcs : t.url ? [{ label: "Source", url: t.url }] : null,
                        ),
                      }}
                      style={{ marginTop: "5px" }}
                    />
                  </div>
                ) : null}
              </div>

              <div className="tp-cta-wrap">
                <button
                  className="tp-pursue"
                  onClick={() => {
                    const u = tpUrl(t);
                    if (u) window.open(u, "_blank", "noopener,noreferrer");
                    else
                      window.alert(
                        `No source URL on record for:\n\n${t.title}\n${t.issuer} · ${t.country}`,
                      );
                  }}
                  type="button"
                >
                  {ctaLabel(t)} <span style={{ fontFamily: "var(--mono)" }}>→</span>
                </button>
                <div className="tp-cta-note">{ctaNote(t)}</div>
              </div>
            </div>

            <ScopeChat placeholder="Ask about this tender…" scopeKey="tender" />
          </div>
        ) : null}
      </div>
    </div>
  );
}
