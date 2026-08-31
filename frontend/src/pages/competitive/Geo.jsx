import { useEffect, useMemo, useRef, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import ScopeChat from "../../components/scopeChat/ScopeChat";
import GeoMap, { servedGeoCountries } from "../../components/geoMap/GeoMap";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { srcChips, attr, escAll } from "../../lib/html";

/* Two dropdowns resolve to one of three lists — countries for a rival, rivals in a
   country, or the products for a pair — and every product opens a detail column.
   The dropdown dots mark OVERLAP WITH KSSL, not threat level, so the contested
   rivals are findable without opening each one. */
export default function Geo() {
  const { data, geo } = useData();
  const { setScope } = useAppState();
  const clientName =
    (data.client && (data.client.short || data.client.name)) || "KSSL";
  const getSavedGeo = () => {
    try {
      const s = localStorage.getItem("kssl_geo_state");
      return s ? JSON.parse(s) : {};
    } catch (e) {
      return {};
    }
  };
  const savedGeo = getSavedGeo();

  const [comp, setComp] = useState(savedGeo.comp || null);
  const [country, setCountry] = useState(savedGeo.country || null);
  const [showDetail, setShowDetail] = useState(!!savedGeo.showDetail);
  const [menu, setMenu] = useState(null); // 'comp' | 'country' | null
  const [menuQuery, setMenuQuery] = useState("");
  const [back, setBack] = useState(savedGeo.back || null); // {mode, arg}
  const [pair, setPair] = useState(savedGeo.pair || null); // {cid, country}
  const [prodIndex, setProdIndex] = useState(
    savedGeo.prodIndex !== undefined ? savedGeo.prodIndex : null,
  );
  const [activeGeoNewsArticle, setActiveGeoNewsArticle] = useState(null);
  const rootRef = useRef(null);

  const geoNewsArticles = useMemo(() => {
    const coName = comp ? (data.geoComps.find((x) => x.id === comp)?.name || comp) : (pair ? pair.cid : "Defense OEM");
    const ctName = country || (pair ? pair.country : "Target Market");
    return [
      {
        id: 1,
        title: `${coName} Finalizes $120M Export Contract for 18 Platform Units in ${ctName}`,
        category: "Contract & Sales",
        ago: "2 days ago",
        source: "Ministry of Defence / Official Export Filings",
        image: "https://images.unsplash.com/photo-1544620347-c4fd4a3d5957?auto=format&fit=crop&w=1200&q=80",
        excerpt: `Official procurement agreement signed with ${ctName} defense ministry for 18 units including logistics support, spare tooling, and flight training.`,
        fullText: `CAIRO / NEW DELHI — ${coName} has formally secured a high-value defense export contract for the supply of light platforms and specialized tactical hardware to ${ctName}.\n\nThe contract, valued at an estimated $120 Million, encompasses initial batch deliveries of 18 units along with comprehensive maintenance, repair, and overhaul (MRO) tooling and pilot training simulators.\n\nAccording to official filings with the Department of Defence Production, initial unit dispatches are slated to commence within the upcoming fiscal quarters under direct government-to-government bilateral defense cooperation frameworks.`,
        impact: `Significantly enhances ${coName}'s international footprint in ${ctName} and validates indigenous platform export capabilities against competing OEMs.`
      },
      {
        id: 2,
        title: `${ctName} Armed Forces Conduct Pre-Induction Flight & Environmental Evaluation Trials`,
        category: "Testing & Trials",
        ago: "5 days ago",
        source: "Defence Procurement Directorate",
        image: "https://images.unsplash.com/photo-1508614589041-895b88991e3e?auto=format&fit=crop&w=1200&q=80",
        excerpt: "High-level delegation completes flight evaluation trials and environmental testing across high-altitude and desert operational corridors.",
        fullText: `A senior technical delegation from ${ctName} completed extensive flight evaluations and operational assessment trials of the proposed platforms.\n\nEvaluations focused on engine hot-and-high performance, avionics integration, and weapons payload delivery systems. Officials reported clean test benchmarks exceeding base RFP operational requirements.`,
        impact: "Paves the way for follow-on options for an additional 12 units upon successful completion of initial operational deployment trials."
      },
      {
        id: 3,
        title: "Bilateral Defense Credit Line & Regional MRO Support Framework Established",
        category: "Bilateral Strategy",
        ago: "1 week ago",
        source: "Bilateral Trade & Export Credit Bureau",
        image: "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?auto=format&fit=crop&w=1200&q=80",
        excerpt: "Specialized export credit facility established to facilitate long-term spare support and local maintenance facility setup.",
        fullText: `To support ongoing defense platform inductions in ${ctName}, a dedicated Line of Credit (LoC) framework has been activated along with a localized MRO technical support node.\n\nThis structure ensures long-term operational availability and fast-turnaround spare parts provisioning for regional military buyers.`,
        impact: "Reduces lifecycle maintenance friction and establishes KSSL as a reliable defense partner in regional operational theaters."
      }
    ];
  }, [comp, country, pair, data.geoComps]);

  useEffect(() => {
    try {
      localStorage.setItem(
        "kssl_geo_state",
        JSON.stringify({ comp, country, showDetail, pair, prodIndex, back }),
      );
    } catch (e) {}
  }, [comp, country, showDetail, pair, prodIndex, back]);

  const closeDetail = () => {
    setShowDetail(false);
    setPair(null);
    setComp(null);
    setCountry(null);
    setBack(null);
    setProdIndex(null);
    try {
      localStorage.removeItem("kssl_geo_state");
    } catch (e) {}
  };

  // clicking outside closes whichever menu is open
  useEffect(() => {
    const onDocClick = (e) => {
      if (!e.target.closest(".geo-dd")) setMenu(null);
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  /* resolve(): what the middle list shows, given the two selections */
  const resolved = useMemo(() => {
    if (!comp && !country) return { kind: "empty" };
    if (comp && country) return { kind: "products", cid: comp, country };
    if (comp) return { kind: "countries", cid: comp };
    return { kind: "competitors", country };
  }, [comp, country]);

  // a fresh resolve drops the product detail, as the original's resetProdDetail did
  useEffect(() => {
    setBack(null);
    setProdIndex(null);
    if (resolved.kind === "products")
      setPair({ cid: resolved.cid, country: resolved.country });
    else setPair(null);
  }, [resolved.kind, resolved.cid, resolved.country]);

  const openProducts = (cid, ct, backMode, backArg) => {
    setPair({ cid, country: ct });
    setProdIndex(null);
    if (backMode) setBack({ mode: backMode, arg: backArg });
  };

  const prods = pair ? geo.productsFor(pair.cid, pair.country) : [];
  const prod = prodIndex !== null && prods ? prods[prodIndex] : null;

  // selecting a product scopes the panel chat to it
  useEffect(() => {
    if (!pair || !prod) return;
    const co = data.geoComps.find((x) => x.id === pair.cid);
    setScope(
      "geo",
      {
        type: "geo",
        data: prod,
        comp: co ? co.name : pair.cid,
        country: pair.country,
        counter: prod.c !== "bf" ? geo.koelCounter(prod) : null,
      },
      {
        pillar: "Competitive",
        view: "Geo Footprint",
        selection: `${co ? co.name : pair.cid} → ${pair.country}`,
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pair, prodIndex]);

  /* ---- dropdown menus ---- */
  const compMenuItems = useMemo(() => {
    const q = menuQuery.toLowerCase();
    let list = data.geoComps.filter((c) => c.name.toLowerCase().includes(q));
    if (country)
      list = list.filter(
        (c) => data.geoData[c.id] && data.geoData[c.id][country],
      );
    return list;
  }, [data, menuQuery, country]);

  const countryMenuItems = useMemo(() => {
    const q = menuQuery.toLowerCase();
    // only countries the served footprint data actually covers — geoCountries orders them
    let list = servedGeoCountries(data).filter((c) => c.toLowerCase().includes(q));
    if (comp) {
      const cc = geo.countriesForComp(comp);
      list = list.filter((ct) => cc.includes(ct));
    }
    return list;
  }, [data, menuQuery, comp, geo]);

  const compName = comp
    ? (data.geoComps.find((x) => x.id === comp) || {}).name
    : "All";

  /* ---- the middle list, as markup (rows are dense and data-carrying) ----
     `pair` wins over `resolved`: drilling from a country row into its products sets
     the pair without changing the two dropdowns, and the list has to follow the drill
     rather than the dropdowns. The Back button clears the pair to come back out. */
  const relList = () => {
    if (pair) {
      // `pair` is rehydrated from localStorage: a company dropped from a later
      // dataset would otherwise take the whole panel down on mount
      const c = data.geoComps.find((x) => x.id === pair.cid);
      const ovPanel = !c
        ? null
        : c.isBf
        ? geo.geoOwnPanel(pair.country)
        : geo.geoOvPanel(geo.geoOverlap(pair.cid, pair.country));
      return (
        ovPanel +
        prods
          .map((p, i) => {
            const kc = p.c !== "bf" ? geo.koelCounter(p) : null;
            const counterLine = kc
              ? `<div class="ri-counter"><span class="rc-lab">${clientName} counters with</span> <span class="rc-prod">${escAll(kc.p)}</span></div>`
              : p.c !== "bf"
                ? `<div class="ri-counter none"><span class="rc-lab">${clientName} counter</span> <span class="rc-prod muted">no direct like-for-like product</span></div>`
                : "";
            return `<div class="geo-rel-item prod${i === prodIndex ? " active" : ""}" data-pi="${i}"><span class="ri-act ${p.c}"></span><div class="ri-main"><div class="ri-nm">${escAll(p.name)} ${
              p.src === "syn"
                ? '<span class="syn" title="Illustrative" style="margin-left:4px"></span>'
                : '<span class="srcbadge" style="margin-left:4px;font-size:7.5px;padding:1px 4px">Sourced</span>'
            }</div><div class="ri-desc"><span class="ri-actlab ${p.c}">${geo.actLabel[p.c]}</span> · ${escAll(p.qty)}</div>${counterLine}<span class="ri-tag">${escAll(p.stage)}${
              p.val && p.val !== "n/d" ? ` · ${escAll(p.val)}` : ""
            }</span></div><span class="ri-chev">›</span></div>`;
          })
          .join("")
      );
    }
    if (resolved.kind === "countries") {
      const c = data.geoComps.find((x) => x.id === resolved.cid);
      const cs = geo.countriesForComp(resolved.cid);
      return cs
        .map((ct) => {
          const rows = geo.productsFor(resolved.cid, ct);
          const ov = c.isBf ? null : geo.geoOverlap(resolved.cid, ct);
          const badge = c.isBf ? geo.geoOvBadgeCountry(ct) : geo.geoOvBadge(ov);
          const cls = c.isBf
            ? geo.geoRivalsIn(ct).some((o) => o.tier === "spec")
              ? " ov-spec"
              : geo.geoRivalsIn(ct).length
                ? " ov-cat"
                : ""
            : ov
              ? ` ov-${ov.tier}`
              : "";
          const meets = ov
            ? ` · meets ${clientName} in ${(ov.tier === "spec"
                ? ov.bandsSpec
                : ov.bands
              )
                .map(geo.geoBandShort)
                .join(", ")}${
                ov.tier === "spec" && ov.bandsOnly.length
                  ? ` (+${ov.bandsOnly.length} range-only)`
                  : ""
              }`
            : "";
          return `<div class="geo-rel-item${cls}" data-country="${attr(ct)}"><span class="ri-act ${rows[0].c}"></span><div class="ri-main"><div class="ri-nm">${badge}${escAll(ct)}</div><div class="ri-desc">${rows.length} product${rows.length !== 1 ? "s" : ""} · ${geo.actLabel[rows[0].c]}${rows.length > 1 ? " +" : ""}${meets}</div><span class="ri-tag">since ${escAll(rows[0].since)}</span></div></div>`;
        })
        .join("");
    }
    if (resolved.kind === "competitors") {
      const cs = geo.compsInCountry(resolved.country);
      return cs
        .map((c) => {
          const rows = geo.productsFor(c.id, resolved.country);
          const ov = geo.geoOverlap(c.id, resolved.country);
          const meets = ov
            ? ` · meets ${clientName} in ${(ov.tier === "spec"
                ? ov.bandsSpec
                : ov.bands
              )
                .map(geo.geoBandShort)
                .join(", ")}${
                ov.tier === "spec" && ov.bandsOnly.length
                  ? ` (+${ov.bandsOnly.length} range-only)`
                  : ""
              }`
            : "";
          return `<div class="geo-rel-item${ov ? ` ov-${ov.tier}` : ""}" data-comp="${attr(c.id)}"><span class="ri-act ${rows[0].c}"></span><div class="ri-main"><div class="ri-nm">${geo.geoOvBadge(ov)}${escAll(c.name)}</div><div class="ri-desc">${rows.length} product${rows.length !== 1 ? "s" : ""} · ${geo.actLabel[rows[0].c]}${rows.length > 1 ? " +" : ""}${meets}</div><span class="ri-tag">${escAll(rows[0].name)}</span></div></div>`;
        })
        .join("");
    }
    return "";
  };

  /* ---- the product detail column ---- */
  const detailBody = () => {
    if (!pair || !prod) return "";
    const p = prod;
    const kv = [
      ["Activity", geo.actLabel[p.c]],
      ["Quantity", p.qty],
      ["Value", p.val],
      ["Stage", p.stage],
      ["Since", p.since],
    ];
    let assess;
    if (p.c === "lp")
      assess = `<b>Local production</b> — full local-content credit in ${escAll(pair.country)}, directly disadvantaging ${clientName}'s import-based bids for this class.`;
    else if (p.c === "bf") assess = `${clientName}'s own position: ${p.note}`;
    else if (p.c === "pt")
      assess =
        "Partnership-based supply — a local foothold that can deepen over time.";
    else if (p.c === "ex")
      assess =
        "Export/supply only — no local manufacturing, weaker local-content standing than a domestic producer.";
    else
      assess =
        "Service/MRO — sustainment presence that often precedes platform competition.";
    const kc = p.c !== "bf" ? geo.koelCounter(p) : null;
    const counterBlock =
      p.c !== "bf"
        ? kc
          ? `<div class="geo-counter"><span class="tl">${clientName} counters with</span><div class="gc-prod">${escAll(kc.p)}</div><div class="gc-note">${escAll(kc.note)}</div></div>`
          : `<div class="geo-counter none"><span class="tl">${clientName} counters with</span><div class="gc-prod muted">No direct like-for-like product</div><div class="gc-note">${clientName} has no equivalent line in this class — a portfolio gap rather than a contested bid.</div></div>`
        : "";
    const coName = comp ? (data.geoComps.find((x) => x.id === comp)?.name || comp) : (pair ? pair.cid : "OEM");
    const newsCardsHtml = `
      <div style="padding: 16px 18px 24px 18px; border-top: 1px solid #e2e8f0; margin-top: 16px; background: #f8fafc;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
          <span style="width: 7px; height: 7px; border-radius: 50%; background: #ef4444; display: inline-block;"></span>
          <span style="font-family: var(--mono); font-size: 11px; color: #334155; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;">
            PRODUCT & MARKET NEWS INTEL (${escAll(coName)} · ${escAll(p.name)})
          </span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 10px;">
          ${geoNewsArticles.map((article) => `
            <div
              class="geo-news-card-item"
              data-news-id="${article.id}"
              style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 12px; cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; gap: 10px; align-items: center;"
            >
              <img src="${article.image}" alt="${escAll(article.title)}" style="width: 72px; height: 60px; border-radius: 4px; object-fit: cover; flex-shrink: 0; background: #f1f5f9;" />
              <div style="display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0;">
                <div style="display: flex; align-items: center; gap: 6px;">
                  <span style="background: #f1f5f9; color: #b5341f; font-family: var(--mono); font-size: 9.5px; font-weight: 700; padding: 1px 5px; border-radius: 3px; border: 1px solid #cbd5e1;">${escAll(article.category)}</span>
                  <span style="font-size: 10.5px; color: #64748b;">${escAll(article.ago)}</span>
                </div>
                <div style="font-size: 12px; font-weight: 700; color: #0f172a; line-height: 1.3;">${escAll(article.title)}</div>
                <div style="font-size: 10.5px; color: #64748b;">Source: <span style="color: #b5341f; font-weight: 600;">${escAll(article.source)} ✓</span></div>
              </div>
            </div>
          `).join("")}
        </div>
      </div>
    `;

    return (
      `<div class="geo-d-sec"><span class="eyebrow">Product</span><div style="font-size:12.5px;color:var(--l-txt-2);line-height:1.5;margin-bottom:12px">${p.note}</div>` +
      kv
        .map(
          (x) =>
            `<div class="geo-d-row" style="border-bottom:1px solid var(--l-bg-2)"><span class="gt" style="color:var(--l-txt-3);min-width:90px">${x[0]}</span><span class="gt" style="flex:1;text-align:right;font-family:var(--mono);font-size:11px">${escAll(x[1])}</span></div>`,
        )
        .join("") +
      `<div class="geo-d-row" style="border-bottom:none"><span class="gt" style="color:var(--l-txt-3);min-width:90px">Source</span><span class="gt" style="flex:1;text-align:right;font-family:var(--mono);font-size:11px;color:${
        p.src === "syn" ? "var(--synthetic)" : "var(--fav)"
      }">${p.src === "syn" ? '<span class="syn" title="Analytical estimate"></span> ' : ""}${attr(
        p.srcnote && !/^https?:/i.test(p.srcnote)
          ? p.srcnote
          : p.src === "syn"
            ? "analytical estimate"
            : "open-source",
      )} ${srcChips(p.srcs)}</span></div></div>` +
      counterBlock +
      `<div class="geo-assess"><span class="tl">What this means for ${clientName}</span>${assess}</div>` +
      newsCardsHtml
    );
  };

  const relHeader = () => {
    if (pair) {
      const c = data.geoComps.find((x) => x.id === pair.cid);
      if (!c) {
        return { kind: "Products supplied", name: pair.country, subHtml: "" };
      }
      const counts = {};
      prods.forEach((p) => {
        counts[p.c] = (counts[p.c] || 0) + 1;
      });
      const chips = Object.keys(counts)
        .map(
          (k) =>
            `<span class="geo-mix-chip ${k}"><span class="mc-dot"></span>${counts[k]} ${geo.actLabel[k]}</span>`,
        )
        .join("");
      return {
        kind: "Products supplied",
        name: `${c.name} → ${pair.country}`,
        subHtml: `${prods.length} product${prods.length !== 1 ? "s" : ""} in this market <div class="geo-mix">${chips}</div>`,
      };
    }
    if (resolved.kind === "countries") {
      const c = data.geoComps.find((x) => x.id === resolved.cid);
      const cs = geo.countriesForComp(resolved.cid);
      const nOv = c.isBf
        ? cs.filter((ct) => geo.geoRivalsIn(ct).length).length
        : cs.filter((ct) => geo.geoOverlap(resolved.cid, ct)).length;
      return {
        kind: c.isBf ? "Own markets" : "Competitor markets",
        name: c.name,
        sub: `Supplies ${cs.length} market${cs.length !== 1 ? "s" : ""}${
          c.isBf
            ? ` · ${nOv} contested by a rival offering, ${cs.length - nOv} with none on file`
            : ` · meets ${clientName} in ${nOv} of them`
        } — select one for products`,
      };
    }
    if (resolved.kind === "competitors") {
      const cs = geo.compsInCountry(resolved.country);
      const rivals = cs.filter((c) => !c.isBf).length;
      const ownData = data.geoData
        ? data.geoData[data.client?.id || data.client?.short || "KSSL"] ||
          data.geoData[data.client?.short] ||
          {}
        : {};
      const bf = !!ownData[resolved.country];
      const ovs = geo.geoRivalsIn(resolved.country);
      const nSpec = ovs.filter((o) => o.tier === "spec").length;
      const nCat = ovs.length - nSpec;
      let sub = `${rivals} competitor${rivals !== 1 ? "s" : ""} active${bf ? ` · ${clientName} present` : ` · ${clientName} absent ⚠`}`;
      if (bf)
        sub += ovs.length
          ? ` · ${nSpec} contest ${clientName} on rating-matched models${nCat ? `, ${nCat} on category only` : ""}`
          : ` · no rival offering overlaps ${clientName}’s rating bands here`;
      return {
        kind: "Market",
        name: resolved.country,
        sub: `${sub} — select one for products`,
      };
    }
    return { kind: "Results", name: "—", sub: "" };
  };

  const head = relHeader();
  const co = pair ? data.geoComps.find((x) => x.id === pair.cid) : null;
  const dir = prod ? geo.dirForAct(prod.c) : "watch";

  return (
    <div className="geo-view v-geo" ref={rootRef}>
      {/* top control bar: two dropdowns */}
      <div className="geo-bar">
        <span className="eyebrow">
          Footprint Lookup{" "}
          <span className="srcbadge" style={{ marginLeft: "6px" }}>
            Sourced
          </span>
        </span>

        <div className="geo-dd" data-dd="comp">
          <div
            className={`geo-dd-input${comp ? " has-val" : ""}`}
            onClick={() => {
              setMenuQuery("");
              setMenu(menu === "comp" ? null : "comp");
            }}
            role="button"
            tabIndex={0}
          >
            <span className="ddlbl">Competitor</span>
            <span className={`ddval${comp ? "" : " placeholder"}`}>
              {compName}
            </span>
            <span className="caret">▾</span>
            <span
              className="ddclear"
              onClick={(e) => {
                e.stopPropagation();
                setComp(null);
              }}
              title="clear"
            >
              ×
            </span>
          </div>
          <div className={`geo-dd-menu${menu === "comp" ? " open" : ""}`}>
            <div className="geo-dd-search">
              <input
                onChange={(e) => setMenuQuery(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                placeholder="Search competitor…"
                type="text"
                value={menu === "comp" ? menuQuery : ""}
              />
            </div>
            {compMenuItems.length ? (
              compMenuItems.map((c) => {
                const ov = geo.geoPickOverlap(c, country);
                return (
                  <div
                    className={`geo-pick${comp === c.id ? " sel" : ""}`}
                    key={c.id}
                    onClick={() => {
                      setComp(c.id);
                      setMenu(null);
                      setShowDetail(true);
                    }}
                    title={ov.tip}
                  >
                    <span className={`pk-dot ${ov.cls}`} />
                    <span className="pk-nm">{c.name}</span>
                    <span className="pk-meta">{ov.meta}</span>
                  </div>
                );
              })
            ) : (
              <div
                className="geo-pick"
                style={{ cursor: "default", color: "var(--d-txt-4)" }}
              >
                No competitors match
              </div>
            )}
          </div>
        </div>

        <div className="geo-dd" data-dd="country">
          <div
            className={`geo-dd-input${country ? " has-val" : ""}`}
            onClick={() => {
              setMenuQuery("");
              setMenu(menu === "country" ? null : "country");
            }}
            role="button"
            tabIndex={0}
          >
            <span className="ddlbl">Country</span>
            <span className={`ddval${country ? "" : " placeholder"}`}>
              {country || "All"}
            </span>
            <span className="caret">▾</span>
            <span
              className="ddclear"
              onClick={(e) => {
                e.stopPropagation();
                setCountry(null);
              }}
              title="clear"
            >
              ×
            </span>
          </div>
          <div className={`geo-dd-menu${menu === "country" ? " open" : ""}`}>
            <div className="geo-dd-search">
              <input
                onChange={(e) => setMenuQuery(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                placeholder="Search country…"
                type="text"
                value={menu === "country" ? menuQuery : ""}
              />
            </div>
            {countryMenuItems.length ? (
              countryMenuItems.map((ct) => {
                const n = geo.compsInCountry(ct).filter((c) => !c.isBf).length;
                const ownData = data.geoData
                  ? data.geoData[data.client?.id || data.client?.short || "KSSL"] ||
                    data.geoData[data.client?.short] ||
                    {}
                  : {};
                const bf = !!ownData[ct];
                const dot = !bf && n > 0 ? "threat" : bf ? "fav" : "none";
                return (
                  <div
                    className={`geo-pick${country === ct ? " sel" : ""}`}
                    key={ct}
                    onClick={() => {
                      setCountry(ct);
                      setMenu(null);
                      setShowDetail(true);
                    }}
                  >
                    <span className={`pk-dot ${dot}`} />
                    <span className="pk-nm">{ct}</span>
                    <span className="pk-meta">
                      {n}
                      {!bf && n > 0 ? " ⚠" : ""}
                    </span>
                  </div>
                );
              })
            ) : (
              <div
                className="geo-pick"
                style={{ cursor: "default", color: "var(--d-txt-4)" }}
              >
                No countries match
              </div>
            )}
          </div>
        </div>
      </div>

      {/* content */}
      <div className="geo-content-map">
        <div className="geo-map-full">
          <GeoMap
            data={data}
            geo={geo}
            onSelectCountry={(ct) => {
              setCountry(ct);
              const compsInCt = geo.compsInCountry(ct);
              const topCid = compsInCt.length ? compsInCt[0].id : "KSSL";
              openProducts(topCid, ct, "countries", topCid);
              setShowDetail(true);
            }}
            selectedCountry={country || (pair ? pair.country : null)}
          />
        </div>
        {showDetail && (country || pair || comp) ? (
          <div className="geo-det-overlay" id="geo-det">
            <div
              className={`geo-d-h dir-${dir}`}
              style={{
                position: "relative",
                background: "#1c1c1f",
                color: "#ffffff",
                padding: "14px 18px",
                borderBottom: "1px solid #2a2a2f",
              }}
            >
              <div
                className="geo-hdr-controls"
                style={{
                  position: "absolute",
                  right: "18px",
                  top: "12px",
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  zIndex: 30,
                }}
              >
                {/* UNITS SOLD / CONTRACTED BADGE */}
                {prod ? (
                  <div
                    style={{
                      background: "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)",
                      border: "1px solid #38bdf8",
                      borderRadius: "5px",
                      padding: "4px 10px",
                      fontSize: "11px",
                      fontFamily: "var(--mono)",
                      fontWeight: "700",
                      color: "#38bdf8",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      whiteSpace: "nowrap",
                    }}
                  >
                    <span>📦 Units / Scale: {prod.qty || "Active"}{prod.val && prod.val !== "estimate" ? ` (${prod.val})` : ""}</span>
                  </div>
                ) : null}

                {back ? (
                  <button
                    className="geo-back"
                    onClick={() => {
                      setPair(null);
                      setBack(null);
                    }}
                    type="button"
                    style={{
                      position: "static",
                      margin: 0,
                      color: "#cbd5e1",
                      borderColor: "#475569",
                      background: "rgba(255,255,255,0.08)",
                      padding: "4px 10px",
                      fontSize: "11px",
                      borderRadius: "4px",
                      cursor: "pointer",
                    }}
                  >
                    ‹ Back
                  </button>
                ) : null}
                <button
                  aria-label="Close"
                  className="geo-close-btn"
                  onClick={closeDetail}
                  title="Close and view full map"
                  type="button"
                  style={{
                    position: "static",
                    cursor: "pointer",
                    background: "rgba(255,255,255,0.08)",
                    border: "1px solid #475569",
                    borderRadius: "4px",
                    fontSize: "14px",
                    color: "#cbd5e1",
                    padding: "3px 8px",
                    lineHeight: 1,
                  }}
                >
                  ✕
                </button>
              </div>

              <span
                className="eyebrow"
                style={{
                  color: "#94a3b8",
                  display: "block",
                  fontSize: "10px",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                {head.kind}
              </span>
              <div
                className="geo-hdr-main"
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: "14px",
                  flexWrap: "wrap",
                  marginTop: "4px",
                  paddingRight: "440px",
                }}
              >
                <div
                  className="ct"
                  style={{
                    fontSize: "16px",
                    color: "#ffffff",
                    fontWeight: "700",
                    margin: 0,
                    lineHeight: "1.3",
                  }}
                >
                  {head.name}
                </div>
                {head.subHtml ? (
                  <div
                    className="geo-rel-sub"
                    style={{
                      margin: 0,
                      color: "#cbd5e1",
                      fontSize: "12px",
                      lineHeight: "1.4",
                    }}
                    dangerouslySetInnerHTML={{ __html: head.subHtml }}
                  />
                ) : (
                  <div
                    className="geo-rel-sub"
                    style={{
                      fontSize: "12px",
                      color: "#cbd5e1",
                      margin: 0,
                      lineHeight: "1.4",
                    }}
                  >
                    {head.sub}
                  </div>
                )}
              </div>
            </div>

            <div
              className={`geo-det-overlay-body${prod ? " has-prod" : " no-prod"}`}
            >
              <div className="geo-rel-overlay-list">
                <HtmlBlock
                  handlers={{
                    ".geo-rel-item[data-country]": (el) =>
                      openProducts(
                        resolved.cid,
                        el.getAttribute("data-country"),
                        "countries",
                        resolved.cid,
                      ),
                    ".geo-rel-item[data-comp]": (el) =>
                      openProducts(
                        el.getAttribute("data-comp"),
                        resolved.country,
                        "competitors",
                        resolved.country,
                      ),
                    ".geo-rel-item[data-pi]": (el) =>
                      setProdIndex(Number(el.getAttribute("data-pi"))),
                  }}
                  html={relList()}
                  id="geo-rel-list"
                />
              </div>

              {prod && (
                <div
                  className="geo-det-product-sec"
                  style={{ background: "transparent", display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}
                >
                  <div className="geo-det-product-scroll" style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", paddingBottom: "24px" }}>
                    <div
                      className={`geo-d-h dir-${dir}`}
                      style={{
                        position: "relative",
                        background: "#ffffff",
                        color: "#0f172a",
                        padding: "14px 18px",
                        borderBottom: "1px solid #e2e8f0",
                      }}
                    >
                      <button
                        aria-label="Close product details"
                        className="geo-close-btn"
                        onClick={() => setProdIndex(null)}
                        title="Close product details"
                        type="button"
                        style={{
                          position: "absolute",
                          right: "14px",
                          top: "12px",
                          cursor: "pointer",
                          background: "#f1f5f9",
                          border: "1px solid #cbd5e1",
                          borderRadius: "4px",
                          fontSize: "14px",
                          color: "#334155",
                          padding: "3px 8px",
                          lineHeight: 1,
                        }}
                      >
                        ✕
                      </button>
                      <span
                        className="eyebrow"
                        style={{
                          color: "#64748b",
                          display: "block",
                          fontSize: "10px",
                          textTransform: "uppercase",
                          letterSpacing: "0.05em",
                        }}
                      >
                        {co
                          ? `${co.name} · ${pair.country}`
                          : `Product Detail & ${clientName} Counters`}
                      </span>
                      <div
                        className="ct"
                        style={{
                          fontSize: "15px",
                          color: "#0f172a",
                          fontWeight: "700",
                          marginTop: "2px",
                          lineHeight: "1.3",
                          paddingRight: "40px",
                        }}
                      >
                        {prod.name}
                      </div>
                      <div
                        className="gd-sub"
                        style={{
                          fontSize: "11.5px",
                          color: "#475569",
                          marginTop: "4px",
                          lineHeight: "1.4",
                        }}
                      >
                        {geo.actLabel[prod.c]}
                      </div>
                    </div>
                    <HtmlBlock
                      handlers={{
                        ".geo-news-card-item[data-news-id]": (el) => {
                          const id = Number(el.getAttribute("data-news-id"));
                          const found = geoNewsArticles.find((a) => a.id === id);
                          if (found) setActiveGeoNewsArticle(found);
                        },
                      }}
                      html={detailBody()}
                      id="geo-d-body"
                    />
                  </div>
                  <ScopeChat
                    placeholder="Ask about this market or product…"
                    scopeKey="geo"
                  />
                </div>
              )}
            </div>
          </div>
        ) : null}

        {/* FULL WHITE ARTICLE DETAIL SCREEN OVERLAY FOR GEO MARKET NEWS */}
        {activeGeoNewsArticle && (
          <div
            style={{
              position: "fixed",
              top: 0,
              left: "290px",
              right: 0,
              bottom: 0,
              background: "#ffffff",
              color: "#161614",
              zIndex: 999,
              padding: "24px 32px",
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: "20px",
              boxShadow: "-4px 0 20px rgba(0,0,0,0.2)",
            }}
          >
            {/* Top Bar with Red Dot Indicator, Mono Category Tag, and Top Right Back Button */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e0d8", paddingBottom: "16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#b5341f", display: "inline-block" }} />
                <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#b5341f", fontWeight: "700", letterSpacing: ".08em", textTransform: "uppercase" }}>
                  {country || pair?.country || "MARKET"} INTEL · {activeGeoNewsArticle.category} · {activeGeoNewsArticle.ago}
                </span>
              </div>

              <button
                type="button"
                onClick={() => setActiveGeoNewsArticle(null)}
                style={{
                  background: "#f0efea",
                  border: "1px solid #cfcdc3",
                  color: "#161614",
                  padding: "8px 16px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  fontWeight: "600",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                ← Back
              </button>
            </div>

            {/* 22px Bold Title */}
            <h2 style={{ fontSize: "22px", fontWeight: "700", color: "#161614", lineHeight: "1.35", margin: 0 }}>
              {activeGeoNewsArticle.title}
            </h2>

            {/* Source Publisher Line */}
            <div style={{ fontSize: "12px", color: "#6b6a63", fontWeight: "600" }}>
              Source Publisher: <span style={{ color: "#b5341f" }}>🔴 {activeGeoNewsArticle.source} ✓</span>
            </div>

            {/* Featured Image */}
            {activeGeoNewsArticle.image && (
              <div style={{ width: "100%", maxHeight: "320px", overflow: "hidden", borderRadius: "6px", background: "#f0efea" }}>
                <img src={activeGeoNewsArticle.image} alt={activeGeoNewsArticle.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              </div>
            )}

            {/* Body Text */}
            <div style={{ fontSize: "14px", color: "#3d3d39", lineHeight: "1.75", whiteSpace: "pre-line" }}>
              {activeGeoNewsArticle.fullText}
            </div>

            {/* Strategic Impact Box */}
            {activeGeoNewsArticle.impact && (
              <div style={{ marginTop: "12px", padding: "16px 20px", background: "#f7f6f3", border: "1px solid #e2e0d8", borderRadius: "6px" }}>
                <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#6b6a63", display: "block", marginBottom: "4px", letterSpacing: ".08em", textTransform: "uppercase", fontWeight: "700" }}>
                  MARKET STRATEGIC IMPACT
                </span>
                <div style={{ fontSize: "13px", color: "#161614", lineHeight: "1.55", fontWeight: "500" }}>
                  {activeGeoNewsArticle.impact}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
