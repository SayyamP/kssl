import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import ScopeChat from "../../components/scopeChat/ScopeChat";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { gapCorrelateStrip } from "../../lib/gapModel";
import { srcChips } from "../../lib/html";

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
const sourceName = (t) =>
  (t && t.srcs && t.srcs[0] && t.srcs[0].label) ||
  (t && t.url ? t.url.replace(/^https?:\/\/(www\.)?/, "").split("/")[0] : null);

/* The facts a procurement notice actually carries — everything the reader needs to
   act, drawn only from the record. Empty fields are dropped, never shown blank. */
const factRows = (t) => {
  if (!t) return [];
  const statusTxt = has(t.status)
    ? t.status.charAt(0).toUpperCase() + t.status.slice(1)
    : t.urlKind === "award"
      ? "Awarded"
      : "Open";
  return [
    ["Category", t.cat],
    ["Buyer", t.issuer],
    ["Country", t.country],
    ["Estimated value", t.value],
    ["Quantity", t.qty],
    ["Closing date", t.closingDate || "not published"],
    ["Status", statusTxt],
    ["Notice ref.", noticeRef(t)],
    ["Source", sourceName(t)],
  ].filter(([, v]) => has(v));
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
  const getSavedTender = () => {
    try {
      const s = localStorage.getItem("kssl_tender_state");
      return s ? JSON.parse(s) : {};
    } catch (e) { return {}; }
  };
  const savedTender = getSavedTender();

  const [productType, setProductType] = useState(savedTender.productType || null);
  const [country, setCountry] = useState(savedTender.country || null);
  const [cat, setCat] = useState(savedTender.cat || null);
  const [menu, setMenu] = useState(null);
  const [menuQuery, setMenuQuery] = useState("");
  const [sel, setSel] = useState(savedTender.sel !== undefined ? savedTender.sel : null);
  const asmtRef = useRef(null);

  useEffect(() => {
    if (asmtRef.current) {
      asmtRef.current.scrollTop = 0;
    }
  }, [sel]);

  useEffect(() => {
    try {
      localStorage.setItem("kssl_tender_state", JSON.stringify({ productType, country, cat, sel }));
    } catch (e) {}
  }, [productType, country, cat, sel]);

  useEffect(() => {
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

  const menuItems = (which) => {
    if (which === "productType") {
      const pool = applyFacets(scope, "productType");
      return [
        { v: "Land Systems", n: pool.filter((x) => !isAirNaval(x)).length },
        { v: "Air, Naval & Missiles", n: pool.filter(isAirNaval).length },
      ];
    }
    /* Option values come from the SERVED tenders — the config lists only order
       values that exist; a country no tender mentions is not offered as a filter. */
    const cfgOrder = which === "country" ? data.tpAllCountries || [] : data.tpAllCats || [];
    /* Counted over `scope` with the OTHER facets applied -- the facet being counted is
       excluded, so picking one of its options gives exactly the number promised. */
    const pool = applyFacets(scope, which);
    /* The configured vocabulary is included even where it has no rows. Building the
       options from served rows alone silently dropped "Armoured Vehicle MRO" -- a
       configured category with 0 tenders -- so the interface advertised 7 categories
       and offered 6, which is exactly what the report counted. A configured facet with
       nothing behind it is information: it says the vocabulary covers a segment this
       corpus has not reached. It is shown with its 0 and cannot be clicked. */
    const items = [
      ...new Set([
        ...pool.map((x) => (which === "country" ? x.country : x.cat)).filter(Boolean),
        ...cfgOrder,
      ]),
    ];
    const counts = {};
    items.forEach((v) => {
      counts[v] = pool.filter((x) => (which === "country" ? x.country : x.cat) === v).length;
    });
    // most tenders first, then the config's ordering, then alphabetically
    const cfgIx = (v) => {
      const i = cfgOrder.indexOf(v);
      return i < 0 ? cfgOrder.length : i;
    };
    const sorted = [...items].sort(
      (a, b) => counts[b] - counts[a] || cfgIx(a) - cfgIx(b) || a.localeCompare(b),
    );
    const q = menuQuery.trim().toLowerCase();
    return sorted
      .filter((v) => which !== "country" || !q || v.toLowerCase().includes(q))
      .map((v) => ({ v, n: counts[v] }));
  };

  const dd = (which, label, value, setValue) => (
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
          All {which === "country" ? "countries" : which === "productType" ? "product types" : "categories"}
        </div>
        {menuItems(which).map(({ v, n }) => (
          <div
            className={`tp-dd-pick${n === 0 ? " zero" : ""}`}
            key={v}
            onClick={() => {
              // a configured facet with no rows is shown for completeness, not to pick
              if (!n) return;
              setValue(v);
              setSel(null);
              setMenu(null);
            }}
          >
            {v}
            {n === 0 ? <span className="m none">—</span> : <span className="m">{n}</span>}
          </div>
        ))}
      </div>
    </div>
  );

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
        <div id="tp-cards">
          {list.length ? (
            list.map((row) => {
              /* pct is '—' when the source discloses no scored fit; fall back to the tier.
                 With NO match row at all there is no verdict to fall back to: 'weak' was
                 being stamped on every tender from nothing, which reads as an assessment
                 nobody made. Say "not assessed" and draw no bar. */
              const m0 = (row.matches || [])[0];
              const assessed = !!m0 && (has(m0.pct) || has(m0.fit));
              const fc = assessed
                ? /%/.test(m0.pct || "")
                  ? fitClass(m0.pct)
                  : m0.fit || "low"
                : null;
              const fw = { high: "85%", mid: "55%", low: "25%" }[fc] || "0%";
              const fp = assessed
                ? /%/.test(m0.pct || "")
                  ? m0.pct
                  : { high: "strong", mid: "partial", low: "weak" }[fc] || "—"
                : "not assessed";
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
                  <div className="meta">
                    {metaLine([row.issuer, row.country, row.cat, [row.value, "val"], row.qty])}
                  </div>
                  <div className="fitbar">
                    <span className="fitlab">{clientName} fit</span>
                    <span className={`fittrack${assessed ? "" : " na"}`}>
                      {assessed ? <i className={fc} style={{ width: fw }} /> : null}
                    </span>
                    <span className={`fitpct${assessed ? "" : " na"}`}>{fp}</span>
                  </div>
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
                  {factRows(t).map(([k, v]) => (
                    <div className="kv" key={k}>
                      <span className="k">{k}</span>
                      <span className="v">{v}</span>
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
