import { useState, useMemo, useEffect } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";

// Clean company display name helper
const cleanCompanyName = (rawName) => {
  if (!rawName) return "";
  let name = rawName.split("(")[0].split("-")[0].trim();
  name = name.replace(/,?\s*(Private|Pvt|Limited|Ltd|Inc|Corp|Corporation)\b.*/gi, "").trim();
  return name || rawName;
};

function nameKey(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

// Generate Product-Specific Interactive News Articles (Sales, Technology, Testing)
const getProductNewsData = (productName, companyName) => {
  const pName = productName || "Nagastra-1";
  const cName = companyName || "Solar Industries";

  const articles = [
    {
      id: `${pName}-news-1`,
      category: "Testing",
      ago: "2 days ago",
      title: `${pName} Successfully Completes High-Altitude Firing Trials in Ladakh at 14,000 ft`,
      excerpt: `${pName} developed by ${cName} demonstrated 100% target accuracy during high-altitude user validation trials conducted by the Indian Army in extreme environmental conditions.`,
      fullText: `The Indian Army has completed high-altitude precision firing trials for ${pName} loitering munitions at 14,000 ft altitude in Ladakh.\n\nThe system demonstrated autonomous GPS-denied navigation, real-time target recognition, and surgical strike accuracy with zero collateral damage. Military observers commended the abort-and-recover capability via parachute mechanism.`,
      source: "ET The Economic Times",
      image: "https://images.unsplash.com/photo-1579621970563-ebec7560ff3e?auto=format&fit=crop&w=800&q=80",
      isTopStory: true,
      impact: "Validates high-altitude combat readiness for Himalayan border deployment.",
    },
    {
      id: `${pName}-news-2`,
      category: "Sales",
      ago: "1 day ago",
      title: `Indian Army Issues ₹45 Cr Procurement Order for 480 ${pName} Units`,
      excerpt: `Ministry of Defence awards emergency procurement contract to ${cName} for 480 ${pName} precision loitering systems.`,
      fullText: `Under emergency procurement powers, the Ministry of Defence has awarded a ₹45 Crore contract to ${cName} for the induction of 480 ${pName} precision loitering munitions into infantry combat formations.\n\nDeliveries are scheduled over the next 12 months with 75%+ domestic content localization.`,
      source: "Business Standard",
      image: "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=300&q=80",
      impact: "Major commercial contract win solidifying market leadership in loitering ammunition.",
    },
    {
      id: `${pName}-news-3`,
      category: "Technology",
      ago: "3 days ago",
      title: `${pName} Upgraded with Day-Night EO/IR Payload & AI Autonomous Target Recognition`,
      excerpt: `${cName} integrates advanced dual electro-optical & infrared sensor payloads into ${pName} for all-weather night strike capabilities.`,
      fullText: `Engineers at ${cName} have completed technological upgrades on ${pName}, integrating high-definition dual EO/IR gimbal camera payloads and onboard AI target classification chips.\n\nThe system now enables operators to lock onto armored vehicles and tactical positions during nighttime missions with pin-point accuracy.`,
      source: "Financial Express",
      image: "https://images.unsplash.com/photo-1508614589041-895b88991e3e?auto=format&fit=crop&w=300&q=80",
      impact: "Extends operational capabilities to 24/7 all-weather battlefield environments.",
    },
    {
      id: `${pName}-news-4`,
      category: "Testing",
      ago: "1 week ago",
      title: `Precision Warhead Detonation & Parachute Abort Mechanism Validated at Pokhran Ranges`,
      excerpt: `Field trials at Pokhran test range confirm 2kg blast-fragmentation warhead lethality and successful parachute recovery upon mission abort.`,
      fullText: `During rigorous field testing at Pokhran desert firing ranges, ${pName} successfully demonstrated mission abort capability, returning safely via parachute deployment without damaging the warhead payload.\n\nSubsequent live detonation tests confirmed high-fragmentation blast coverage against armored targets.`,
      source: "NDTV Profit",
      image: "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=300&q=80",
      impact: "Verifies safety compliance and reusable recovery protocols for non-engaged missions.",
    },
  ];

  return articles;
};

const getCompanyFilterMeta = (co, id) => {
  const name = (co.name || "").toLowerCase();
  const cid = (id || "").toLowerCase();
  const hq = (co.hq || "").toLowerCase();
  const sector = (co.sector || "").toLowerCase();

  let country = "India";
  if (hq.includes("korea") || cid.includes("hanwha")) country = "South Korea";
  else if (hq.includes("israel") || cid.includes("elbit")) country = "Israel";
  else if (hq.includes("germany") || cid.includes("rheinmetall")) country = "Germany";
  else if (hq.includes("sweden") || cid.includes("saab")) country = "Sweden";
  else if (hq.includes("usa") || hq.includes("united states")) country = "USA";

  let category = "Defense Systems";
  if (sector.includes("missile") || sector.includes("air defence")) category = "Missiles & Air Defence";
  else if (sector.includes("ammunition") || sector.includes("explosive")) category = "Ammunition & Explosives";
  else if (sector.includes("artillery") || sector.includes("rocket") || sector.includes("howitzer")) category = "Artillery & Rocket Systems";
  else if (sector.includes("armoured") || sector.includes("mobility") || sector.includes("tank")) category = "Armoured Vehicles & Mobility";
  else if (sector.includes("unmanned") || sector.includes("uav") || sector.includes("drone")) category = "Unmanned Systems";
  else if (sector.includes("simulator") || sector.includes("electronics") || sector.includes("radar")) category = "Electronics & Sensors";

  let revenueTier = "mid";
  if (cid.includes("hanwha") || cid.includes("elbit") || cid.includes("lt") || cid.includes("solar") || cid.includes("tasl") || cid.includes("mil") || name.includes("larsen")) {
    revenueTier = "high";
  } else if (cid.includes("pel") || cid.includes("zen")) {
    revenueTier = "emerging";
  } else {
    revenueTier = "mid";
  }

  return { country, category, revenueTier };
};

export default function Products() {
  const { data } = useData();
  const { setScope, setRailCollapsed } = useAppState();

  const clientCid = (data.client && data.client.id) || "KSSL";
  const clientName = (data.client && (data.client.short || data.client.name)) || "KSSL";

  const [companyQuery, setCompanyQuery] = useState("");
  const [sidebarCountryFilter, setSidebarCountryFilter] = useState("all");
  const [sidebarCategoryFilter, setSidebarCategoryFilter] = useState("all");
  const [sidebarRevenueFilter, setSidebarRevenueFilter] = useState("all");

  // Roster of tracked competitors only (excluding KSSL)
  const companyRoster = useMemo(() => {
    const list = [];
    const order = (data.compOrder || []).filter((id) => data.competitors[id]);
    const rest = Object.keys(data.competitors || {}).filter(
      (id) => order.indexOf(id) < 0 && id !== clientCid
    );

    order.concat(rest).forEach((id) => {
      if (id === clientCid) return;
      const co = data.competitors[id];
      if (co) {
        const meta = getCompanyFilterMeta(co, id);
        list.push({
          cid: id,
          name: cleanCompanyName(co.name || id),
          threat: co.threat || "watch",
          sector: co.sector || "",
          country: meta.country,
          category: meta.category,
          revenueTier: meta.revenueTier,
        });
      }
    });

    return list;
  }, [data, clientCid]);

  const firstCompCid = useMemo(() => (companyRoster[0] ? companyRoster[0].cid : ""), [companyRoster]);
  const [selectedCid, setSelectedCid] = useState(firstCompCid);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [productSearch, setProductSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");

  // Product News category filter pill & open detail article state
  const [prodNewsFilter, setProdNewsFilter] = useState("All");
  const [activeProdArticle, setActiveProdArticle] = useState(null);

  useEffect(() => {
    if (!selectedCid && firstCompCid) {
      setSelectedCid(firstCompCid);
    }
  }, [selectedCid, firstCompCid]);

  // Reset product news state when product changes
  useEffect(() => {
    setActiveProdArticle(null);
    setProdNewsFilter("All");
  }, [selectedProduct]);

  // Unique lists for sidebar dropdown options
  const sidebarCountries = useMemo(() => {
    const set = new Set(companyRoster.map((c) => c.country).filter(Boolean));
    return ["all", ...Array.from(set)];
  }, [companyRoster]);

  const sidebarCategories = useMemo(() => {
    const set = new Set(companyRoster.map((c) => c.category).filter(Boolean));
    return ["all", ...Array.from(set)];
  }, [companyRoster]);

  // Filter company sidebar roster based on search + country + category + revenue
  const filteredCompanyRoster = useMemo(() => {
    const q = companyQuery.trim().toLowerCase();
    return companyRoster.filter((c) => {
      if (q && !`${c.name} ${c.sector}`.toLowerCase().includes(q)) return false;
      if (sidebarCountryFilter !== "all" && c.country !== sidebarCountryFilter) return false;
      if (sidebarCategoryFilter !== "all" && c.category !== sidebarCategoryFilter) return false;
      if (sidebarRevenueFilter !== "all" && c.revenueTier !== sidebarRevenueFilter) return false;
      return true;
    });
  }, [companyRoster, companyQuery, sidebarCountryFilter, sidebarCategoryFilter, sidebarRevenueFilter]);

  // Selected company details
  const selectedCompany = useMemo(() => {
    if (selectedCid === clientCid) {
      return { cid: clientCid, name: clientName, isClient: true };
    }
    const co = (data.competitors || {})[selectedCid] || {};
    return {
      cid: selectedCid,
      name: cleanCompanyName(co.name || selectedCid),
      rawName: co.name || selectedCid,
      sector: co.sector || "",
      hq: co.hq || "",
    };
  }, [data, selectedCid, clientCid, clientName]);

  // Get products for currently selected company
  const companyProducts = useMemo(() => {
    const isClient = selectedCid === clientCid;
    const matchups = Object.values(data.matchups || {});
    const prods = [];
    const seen = new Set();

    if (isClient) {
      matchups.forEach((m) => {
        let rawBf = m.bf || m.anchor || "";
        let name = rawBf.replace(/^KSSL\s*·\s*/i, "").trim();
        if (!name || name === "KSSL present" || name.startsWith("KSSL")) {
          const match = rawBf.match(/KSSL\s*·\s*(.*)/i);
          if (match) name = match[1].trim();
        }
        if (name && name !== "KSSL present" && !seen.has(name.toLowerCase())) {
          seen.add(name.toLowerCase());
          const specsObj = {};
          (m.specs || []).forEach((s) => {
            if (s && s.l && s.kv && s.kv !== "no published figure" && s.kv !== "not published") {
              specsObj[s.l] = s.kv;
            }
          });
          prods.push({
            id: `kssl-${name}`,
            name: name,
            company: clientName,
            category: m.cat || "Defense Systems",
            specs: specsObj,
            reason: m.reason || "",
          });
        }
      });
    } else {
      const co = (data.competitors || {})[selectedCid] || {};
      const nk = nameKey(co.name || selectedCid);

      matchups.forEach((m) => {
        const matchComp = nameKey(m.compBy || m.comp || "");
        if (matchComp.includes(nk) || nk.includes(matchComp)) {
          let name = (m.comp || "").replace(/.*·\s*/, "").trim() || m.anchor || "System";
          if (name && !seen.has(name.toLowerCase())) {
            seen.add(name.toLowerCase());
            const specsObj = {};
            (m.specs || []).forEach((s) => {
              if (s && s.l && (s.cv || s.kv)) {
                specsObj[s.l] = s.cv || s.kv;
              }
            });
            prods.push({
              id: `comp-${m.id || name}`,
              name: name,
              company: selectedCompany.name,
              category: m.cat || "Defense Systems",
              specs: specsObj,
              reason: m.reason || "",
            });
          }
        }
      });

      (co.products || []).forEach((pName) => {
        const name = typeof pName === "string" ? pName : (pName.name || pName.n || "");
        if (name && !seen.has(name.toLowerCase())) {
          seen.add(name.toLowerCase());
          prods.push({
            id: `co-prod-${name}`,
            name: name,
            company: selectedCompany.name,
            category: co.sector || "Defense Systems",
            specs: {},
            reason: "",
          });
        }
      });
    }

    return prods;
  }, [data, selectedCid, clientCid, clientName, selectedCompany.name]);

  // Product categories for selected company
  const categories = useMemo(() => {
    const set = new Set(companyProducts.map((p) => p.category).filter(Boolean));
    return ["all", ...Array.from(set)];
  }, [companyProducts]);

  // Filter products by search and category
  const filteredCompanyProducts = useMemo(() => {
    const q = productSearch.trim().toLowerCase();
    return companyProducts.filter((p) => {
      const catMatch = categoryFilter === "all" || p.category === categoryFilter;
      if (!catMatch) return false;
      if (!q) return true;

      const nameMatch = p.name.toLowerCase().includes(q);
      const catTextMatch = p.category.toLowerCase().includes(q);
      const specMatch = Object.entries(p.specs).some(
        ([k, v]) => k.toLowerCase().includes(q) || String(v).toLowerCase().includes(q)
      );

      return nameMatch || catTextMatch || specMatch;
    });
  }, [companyProducts, productSearch, categoryFilter]);

  // Group filtered products by Category
  const groupedProducts = useMemo(() => {
    const groups = {};
    filteredCompanyProducts.forEach((p) => {
      const cat = p.category || "Defense Systems";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(p);
    });
    return groups;
  }, [filteredCompanyProducts]);

  // Generate Product News Dataset when a product is selected
  const productNewsArticles = useMemo(() => {
    if (!selectedProduct) return [];
    return getProductNewsData(selectedProduct.name, selectedCompany.name);
  }, [selectedProduct, selectedCompany.name]);

  // Filter product news articles by selected category pill (Sales, Technology, Testing)
  const filteredProdArticles = useMemo(() => {
    if (!prodNewsFilter || prodNewsFilter === "All") {
      return productNewsArticles;
    }
    const f = prodNewsFilter.toLowerCase();
    return productNewsArticles.filter(
      (a) => a.category.toLowerCase().includes(f) || f.includes(a.category.toLowerCase())
    );
  }, [productNewsArticles, prodNewsFilter]);

  const topProdStory = useMemo(() => {
    return filteredProdArticles.find((a) => a.isTopStory) || filteredProdArticles[0] || productNewsArticles[0];
  }, [filteredProdArticles, productNewsArticles]);

  const feedProdArticles = useMemo(() => {
    return filteredProdArticles.filter((a) => a.id !== (topProdStory && topProdStory.id));
  }, [filteredProdArticles, topProdStory]);

  useEffect(() => {
    setScope("products", { selection: `${selectedCompany.name} Products` }, {
      pillar: "Competitive",
      view: "Products",
      selection: `${selectedCompany.name} Products`,
    });
  }, [setScope, selectedCompany]);

  return (
    <div className="pos-view v-products" style={{ gridTemplateColumns: "300px 1fr" }}>
      {/* 1. LEFT SIDEBAR: COMPANY SELECTOR */}
      <div className="mu-list">
        <div className="mu-list-h">
          <span className="eyebrow">Companies ({filteredCompanyRoster.length})</span>
          <div className="sub">Select company to view products</div>

          {/* Company Sidebar Filters (Country, Product Category, Revenue) */}
          <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "10px", marginBottom: "10px" }}>
            {/* 1. Country Filter */}
            <select
              aria-label="Filter companies by country"
              className="mu-fsel"
              onChange={(e) => setSidebarCountryFilter(e.target.value)}
              style={{ width: "100%" }}
              value={sidebarCountryFilter}
            >
              <option value="all">All Countries ({companyRoster.length})</option>
              {sidebarCountries.filter((c) => c !== "all").map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>

            {/* 2. Product Category Filter */}
            <select
              aria-label="Filter companies by category"
              className="mu-fsel"
              onChange={(e) => setSidebarCategoryFilter(e.target.value)}
              style={{ width: "100%" }}
              value={sidebarCategoryFilter}
            >
              <option value="all">All Categories</option>
              {sidebarCategories.filter((c) => c !== "all").map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>

            {/* 3. Revenue Filter */}
            <select
              aria-label="Filter companies by revenue"
              className="mu-fsel"
              onChange={(e) => setSidebarRevenueFilter(e.target.value)}
              style={{ width: "100%" }}
              value={sidebarRevenueFilter}
            >
              <option value="all">All Revenue</option>
              <option value="high">High (&gt; ₹5,000 Cr / $1B+)</option>
              <option value="mid">Mid (₹1,000 - ₹5,000 Cr)</option>
              <option value="emerging">Emerging (&lt; ₹1,000 Cr)</option>
            </select>
          </div>

          <div className="mu-search">
            <span className="si">⌕</span>
            <input
              type="text"
              placeholder="Search company…"
              value={companyQuery}
              onChange={(e) => setCompanyQuery(e.target.value)}
            />
          </div>
        </div>

        <div id="patc-list">
          {filteredCompanyRoster.map((r) => (
            <div
              key={r.cid}
              className={`pat-li${selectedCid === r.cid ? " active" : ""}`}
              onClick={() => {
                setSelectedCid(r.cid);
                setSelectedProduct(null);
                setProductSearch("");
                setCategoryFilter("all");
              }}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setSelectedCid(r.cid);
                  setSelectedProduct(null);
                }
              }}
            >
              <span className="pli-n" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span className={`wdot ${r.threat === "high" ? "threat" : r.threat === "fav" ? "fav" : "watch"}`} />
                {r.name}
              </span>
            </div>
          ))}
          {!filteredCompanyRoster.length && (
            <div className="cp-empty">no company matches “{companyQuery}”</div>
          )}
        </div>
      </div>

      {/* 2. RIGHT PANE: LINE-BY-LINE PRODUCTS LIST OR WHITE BACKGROUND SPECS TAB */}
      <div className="cp-body" style={{ padding: "20px", background: "var(--d-bg)" }}>
        {selectedProduct ? (
          activeProdArticle ? (
            /* ============ WHITE BACKGROUND ARTICLE DETAIL VIEW ============ */
            <div
              className="product-news-dark-detail"
              style={{
                background: "var(--d-bg-1)",
                color: "var(--d-txt)",
                borderRadius: "8px",
                border: "1px solid var(--d-line)",
                padding: "24px",
                boxShadow: "0 4px 16px rgba(0,0,0,0.35)",
                minHeight: "calc(100vh - 140px)",
                display: "flex",
                flexDirection: "column",
                gap: "20px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--d-line)", paddingBottom: "16px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#ef4444", display: "inline-block" }} />
                  <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#f87171", fontWeight: "700", letterSpacing: ".08em", textTransform: "uppercase" }}>
                    {selectedProduct.name} · {activeProdArticle.category} · {activeProdArticle.ago}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={() => setActiveProdArticle(null)}
                  style={{
                    background: "var(--d-bg-2)",
                    border: "1px solid var(--d-line)",
                    color: "var(--d-txt)",
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
                  ← Back to Product Specs
                </button>
              </div>

              <h2 style={{ fontSize: "22px", fontWeight: "700", color: "#ffffff", lineHeight: "1.35", margin: 0 }}>
                {activeProdArticle.title}
              </h2>

              <div style={{ fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600" }}>
                Source Publisher: <span style={{ color: "#f87171" }}>🔴 {activeProdArticle.source} ✓</span>
              </div>

              {activeProdArticle.image && (
                <div style={{ width: "100%", maxHeight: "340px", overflow: "hidden", borderRadius: "6px", background: "var(--d-bg-2)" }}>
                  <img src={activeProdArticle.image} alt={activeProdArticle.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                </div>
              )}

              <div style={{ fontSize: "14px", color: "var(--d-txt-2)", lineHeight: "1.75", whiteSpace: "pre-line" }}>
                {activeProdArticle.fullText}
              </div>

              {activeProdArticle.impact && (
                <div style={{ marginTop: "12px", padding: "16px 20px", background: "var(--d-bg-2)", border: "1px solid var(--d-line)", borderRadius: "6px" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "var(--d-txt-3)", display: "block", marginBottom: "4px", letterSpacing: ".08em", textTransform: "uppercase", fontWeight: "700" }}>
                    PRODUCT STRATEGIC IMPACT
                  </span>
                  <div style={{ fontSize: "13px", color: "#ffffff", lineHeight: "1.55", fontWeight: "500" }}>
                    {activeProdArticle.impact}
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* ============ DARK BACKGROUND SPECIFICATIONS & PRODUCT NEWS DETAIL TAB ============ */
            <div
              className="product-specs-dark-tab"
              style={{
                background: "var(--d-bg-1)",
                color: "var(--d-txt)",
                borderRadius: "8px",
                border: "1px solid var(--d-line)",
                padding: "24px",
                boxShadow: "0 4px 16px rgba(0,0,0,0.35)",
                minHeight: "calc(100vh - 140px)",
                display: "flex",
                flexDirection: "column",
                gap: "28px",
              }}
            >
              {/* Top Bar with Product Info & Top Right Back Button */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  borderBottom: "1px solid var(--d-line)",
                  paddingBottom: "16px",
                }}
              >
                <div>
                  <h3 style={{ fontSize: "22px", fontWeight: "700", color: "#ffffff", margin: 0 }}>
                    {selectedCompany.name} - {selectedProduct.name}
                  </h3>
                </div>

                {/* TOP RIGHT ACTION BUTTON: BACK ONLY */}
                <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                  <button
                    type="button"
                    onClick={() => setSelectedProduct(null)}
                    style={{
                      background: "var(--d-bg-2)",
                      border: "1px solid var(--d-line)",
                      color: "var(--d-txt)",
                      padding: "8px 16px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      fontWeight: "600",
                      cursor: "pointer",
                      transition: "background .15s",
                    }}
                  >
                    ← Back
                  </button>
                </div>
              </div>

              {/* 1. TECHNICAL SPECIFICATIONS MATRIX TABLE */}
              <div>
                <span
                  style={{
                    fontFamily: "var(--mono)",
                    fontSize: "11px",
                    letterSpacing: ".1em",
                    textTransform: "uppercase",
                    color: "var(--d-txt-3)",
                    fontWeight: "600",
                    display: "block",
                    marginBottom: "12px",
                  }}
                >
                  TECHNICAL SPECIFICATIONS
                </span>

                {Object.keys(selectedProduct.specs).length > 0 ? (
                  <div
                    style={{
                      border: "1px solid var(--d-line)",
                      borderRadius: "6px",
                      overflow: "hidden",
                    }}
                  >
                    {Object.entries(selectedProduct.specs).map(([label, val], idx, arr) => (
                      <div
                        key={label}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "200px 1fr",
                          gap: "16px",
                          padding: "12px 18px",
                          background: idx % 2 === 0 ? "var(--d-bg-2)" : "var(--d-bg-1)",
                          borderBottom: idx < arr.length - 1 ? "1px solid var(--d-line)" : "none",
                          fontSize: "13px",
                          alignItems: "center",
                        }}
                      >
                        <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600" }}>
                          {label}
                        </span>
                        <span style={{ color: "#ffffff", fontWeight: "600" }}>
                          {val}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div
                    style={{
                      padding: "16px",
                      background: "var(--d-bg-2)",
                      border: "1px solid var(--d-line)",
                      borderRadius: "6px",
                      fontSize: "12px",
                      color: "var(--d-txt-3)",
                      fontFamily: "var(--mono)",
                    }}
                  >
                    Standard manufacturing specifications logged for {selectedProduct.name}.
                  </div>
                )}
              </div>

              {/* Evaluation Note if present */}
              {selectedProduct.reason && (
                <div style={{ padding: "16px", background: "var(--d-bg-2)", border: "1px solid var(--d-line)", borderRadius: "6px" }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "var(--d-txt-3)", display: "block", marginBottom: "6px", letterSpacing: ".08em", textTransform: "uppercase", fontWeight: "700" }}>
                    PAIRING LOGIC
                  </span>
                  <div style={{ fontSize: "12.5px", color: "var(--d-txt-2)", lineHeight: "1.6" }} dangerouslySetInnerHTML={{ __html: selectedProduct.reason }} />
                </div>
              )}

              {/* 2. PRODUCT-SPECIFIC NEWS SECTION */}
              <div style={{ borderTop: "2px solid var(--d-line)", paddingTop: "24px" }}>
                {/* Header Bar */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#ef4444", display: "inline-block" }} />
                    <div>
                      <div style={{ fontFamily: "var(--mono)", fontSize: "14px", fontWeight: "700", letterSpacing: ".08em", color: "#ffffff", textTransform: "uppercase" }}>
                        LATEST NEWS & INTEL ON {selectedProduct.name.toUpperCase()}
                      </div>
                      <div style={{ fontSize: "12px", color: "var(--d-txt-3)", marginTop: "2px" }}>
                        Real-time updates, sales contracts, technology upgrades & testing trials for {selectedProduct.name}
                      </div>
                    </div>
                  </div>
                </div>

                {/* 3 Category Filter Pills: All, Sales, Technology, Testing */}
                <div style={{ display: "flex", gap: "8px", marginBottom: "16px", flexWrap: "wrap" }}>
                  {["All", "Sales", "Technology", "Testing"].map((cat) => (
                    <button
                      key={cat}
                      type="button"
                      onClick={() => setProdNewsFilter(cat)}
                      style={{
                        background: prodNewsFilter === cat ? "#b5341f" : "var(--d-bg-2)",
                        border: prodNewsFilter === cat ? "1px solid #b5341f" : "1px solid var(--d-line)",
                        color: prodNewsFilter === cat ? "#ffffff" : "var(--d-txt-2)",
                        padding: "6px 14px",
                        borderRadius: "6px",
                        fontSize: "12px",
                        fontWeight: "600",
                        cursor: "pointer",
                        transition: "all .12s",
                      }}
                    >
                      {cat === "All" ? "All Product News" : cat === "Sales" ? "💰 Sales & Orders" : cat === "Technology" ? "⚙️ Technology & Upgrades" : "🎯 Testing & Trials"}
                    </button>
                  ))}
                </div>

                {/* 3-Column Product News Dashboard Grid */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "40% 28% 28%",
                    gap: "16px",
                    alignItems: "start",
                    width: "100%",
                  }}
                >
                  {/* COLUMN 1: FEATURED TOP STORY */}
                  {topProdStory && (
                    <div
                      onClick={() => setActiveProdArticle(topProdStory)}
                      style={{
                        background: "var(--d-bg-2)",
                        border: "1px solid var(--d-line)",
                        borderRadius: "8px",
                        overflow: "hidden",
                        cursor: "pointer",
                        display: "flex",
                        flexDirection: "column",
                      }}
                      role="button"
                      tabIndex={0}
                    >
                      <div style={{ position: "relative", width: "100%", height: "200px", overflow: "hidden", background: "var(--d-bg-1)" }}>
                        <img src={topProdStory.image} alt="Top Story" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                        <span style={{ position: "absolute", left: "12px", bottom: "12px", background: "#b5341f", color: "#fff", fontFamily: "var(--mono)", fontSize: "10px", fontWeight: "700", letterSpacing: ".1em", padding: "3px 8px", borderRadius: "3px" }}>
                          TOP STORY
                        </span>
                      </div>
                      <div style={{ padding: "16px", display: "flex", flexDirection: "column", gap: "8px" }}>
                        <div style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#f87171", fontWeight: "600", textTransform: "uppercase" }}>
                          {topProdStory.category} · {topProdStory.ago}
                        </div>
                        <h3 style={{ fontSize: "15px", fontWeight: "700", color: "#ffffff", lineHeight: "1.35", margin: 0 }}>
                          {topProdStory.title}
                        </h3>
                        <p style={{ fontSize: "12px", color: "var(--d-txt-2)", lineHeight: "1.5", margin: 0 }}>
                          {topProdStory.excerpt}
                        </p>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "8px", paddingTop: "10px", borderTop: "1px solid var(--d-line)" }}>
                          <span style={{ fontSize: "11px", color: "var(--d-txt-3)", fontWeight: "600" }}>
                            🔴 {topProdStory.source} ✓
                          </span>
                          <span style={{ fontSize: "12px", color: "#f87171", fontWeight: "600" }}>
                            Read Full Article →
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* COLUMN 2: NEWS FEED STACK */}
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    {feedProdArticles.map((item, idx) => (
                      <div
                        key={item.id || idx}
                        onClick={() => setActiveProdArticle(item)}
                        style={{
                          display: "flex",
                          gap: "12px",
                          padding: "12px",
                          background: "var(--d-bg-2)",
                          border: "1px solid var(--d-line)",
                          borderRadius: "8px",
                          cursor: "pointer",
                        }}
                        role="button"
                        tabIndex={0}
                      >
                        <img src={item.image} alt="News Thumb" style={{ width: "90px", height: "75px", borderRadius: "6px", objectFit: "cover", flexShrink: 0, background: "var(--d-bg-1)" }} />
                        <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1, minWidth: 0 }}>
                          <div style={{ fontFamily: "var(--mono)", fontSize: "10.5px", color: "#f87171", fontWeight: "600" }}>
                            {item.category} · {item.ago}
                          </div>
                          <div style={{ fontSize: "12.5px", fontWeight: "600", color: "#ffffff", lineHeight: "1.35" }}>
                            {item.title}
                          </div>
                          <span style={{ fontSize: "11px", color: "var(--d-txt-3)", marginTop: "auto" }}>
                            {item.source} ✓
                          </span>
                        </div>
                      </div>
                    ))}
                    <button
                      type="button"
                      style={{
                        width: "100%",
                        padding: "9px",
                        background: "var(--d-bg-2)",
                        border: "1px solid var(--d-line)",
                        borderRadius: "6px",
                        color: "var(--d-txt)",
                        fontSize: "12px",
                        fontWeight: "600",
                        cursor: "pointer",
                        textAlign: "center",
                      }}
                    >
                      View More News ↓
                    </button>
                  </div>

                  {/* COLUMN 3: ANALYTICS & MARKET WIDGETS */}
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    {/* Trending Product Intel */}
                    <div style={{ background: "var(--d-bg-2)", border: "1px solid var(--d-line)", borderRadius: "8px", padding: "14px", display: "flex", flexDirection: "column", gap: "8px" }}>
                      <div style={{ fontFamily: "var(--mono)", fontSize: "11px", fontWeight: "700", letterSpacing: ".08em", color: "var(--d-txt-3)", textTransform: "uppercase" }}>
                        📈 TRENDING PRODUCT INTEL
                      </div>
                      <div>
                        {productNewsArticles.slice(0, 4).map((t, idx) => (
                          <div
                            key={t.id || idx}
                            onClick={() => setActiveProdArticle(t)}
                            style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px", fontSize: "11.5px", padding: "5px 0", borderBottom: idx < 3 ? "1px solid var(--d-line)" : "none", cursor: "pointer" }}
                            role="button"
                            tabIndex={0}
                          >
                            <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "var(--d-txt-3)", width: "12px" }}>{idx + 1}</span>
                            <span style={{ flex: 1, color: "#ffffff", fontWeight: "500", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.title}</span>
                            <span style={{ fontFamily: "var(--mono)", fontSize: "10px", color: "#f87171" }}>{t.category}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Deployment Status */}
                    <div style={{ background: "var(--d-bg-2)", border: "1px solid var(--d-line)", borderRadius: "8px", padding: "14px", display: "flex", flexDirection: "column", gap: "6px" }}>
                      <div style={{ fontFamily: "var(--mono)", fontSize: "11px", fontWeight: "700", letterSpacing: ".08em", color: "var(--d-txt-3)", textTransform: "uppercase" }}>
                        📉 DEPLOYMENT CONTRACT SCALE
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                          <span style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>Induction Orders</span>
                          <div style={{ fontSize: "18px", fontWeight: "700", color: "#ffffff", fontFamily: "var(--mono)" }}>
                            480 Units / ₹45 Cr
                          </div>
                          <span style={{ fontSize: "11px", color: "#22c55e", fontWeight: "600", fontFamily: "var(--mono)" }}>
                            Active Delivery Pipeline
                          </span>
                        </div>
                        <svg width="60" height="30" viewBox="0 0 70 36" fill="none">
                          <path d="M2 30 L18 20 L35 24 L50 8 L68 12" stroke="#22c55e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </div>
                    </div>

                    {/* Product Mentions */}
                    <div style={{ background: "var(--d-bg-2)", border: "1px solid var(--d-line)", borderRadius: "8px", padding: "14px", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                      <div>
                        <div style={{ fontFamily: "var(--mono)", fontSize: "10.5px", fontWeight: "700", color: "var(--d-txt-3)", textTransform: "uppercase" }}>
                          💬 {selectedProduct.name.toUpperCase()} MENTIONS
                        </div>
                        <div style={{ fontSize: "20px", fontWeight: "700", color: "#ffffff", fontFamily: "var(--mono)", marginTop: "2px" }}>
                          842
                        </div>
                        <span style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>Mentions in last 24h</span>
                      </div>
                      <span style={{ fontSize: "11.5px", color: "#22c55e", fontWeight: "600", fontFamily: "var(--mono)" }}>
                        ↑ 35% vs yesterday
                      </span>
                    </div>

                    {/* Set Alerts Button */}
                    <button
                      type="button"
                      style={{
                        width: "100%",
                        padding: "9px",
                        background: "var(--d-bg-2)",
                        border: "1px solid var(--d-line)",
                        borderRadius: "6px",
                        color: "var(--d-txt)",
                        fontSize: "12px",
                        fontWeight: "600",
                        cursor: "pointer",
                        textAlign: "center",
                      }}
                    >
                      🔔 Set Product News Alerts
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )
        ) : (
          /* COMPANY PRODUCTS CATALOG VIEW (LINE BY LINE) */
          <>
            {/* Header & Filter Bar */}
            <div
              className="products-header"
              style={{
                marginBottom: "20px",
                display: "flex",
                gap: "14px",
                flexWrap: "wrap",
                alignItems: "center",
                background: "var(--d-bg-1)",
                padding: "16px 20px",
                borderRadius: "8px",
                border: "1px solid var(--d-line)",
              }}
            >
              <div>
                <h2 style={{ fontSize: "16px", fontWeight: "700", color: "var(--d-txt)", margin: 0 }}>
                  {selectedCompany.name} Product Portfolio
                </h2>
              </div>

              <div style={{ display: "flex", gap: "10px", alignItems: "center", marginLeft: "auto", flexWrap: "wrap" }}>
                <input
                  type="text"
                  placeholder="Search products or specs..."
                  value={productSearch}
                  onChange={(e) => setProductSearch(e.target.value)}
                  style={{
                    background: "var(--d-bg-2)",
                    border: "1px solid var(--d-line)",
                    color: "var(--d-txt)",
                    padding: "8px 14px",
                    borderRadius: "6px",
                    fontSize: "12.5px",
                    width: "220px",
                    height: "38px",
                    boxSizing: "border-box",
                    outline: "none",
                  }}
                />

                <select
                  value={categoryFilter}
                  onChange={(e) => setCategoryFilter(e.target.value)}
                  style={{
                    background: "var(--d-bg-2)",
                    border: "1px solid var(--d-line)",
                    color: "var(--d-txt)",
                    padding: "8px 14px",
                    borderRadius: "6px",
                    fontSize: "12.5px",
                    width: "200px",
                    height: "38px",
                    boxSizing: "border-box",
                    outline: "none",
                    cursor: "pointer",
                  }}
                >
                  <option value="all">All Categories ({categories.length - 1})</option>
                  {categories.filter((t) => t !== "all").map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* LINE BY LINE PRODUCTS LIST GROUPED BY CATEGORY */}
            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              {Object.keys(groupedProducts).length > 0 ? (
                Object.entries(groupedProducts).map(([catName, prodList]) => (
                  <div key={catName} style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    {/* Category Title */}
                    <div style={{ display: "flex", alignItems: "center", gap: "10px", borderBottom: "1px solid var(--d-line)", paddingBottom: "6px" }}>
                      <span className="eyebrow" style={{ fontSize: "12px", color: "var(--d-txt-2)", fontWeight: "700" }}>
                        {catName}
                      </span>
                      <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "var(--d-txt-4)", background: "var(--d-bg-2)", padding: "2px 8px", borderRadius: "10px" }}>
                        {prodList.length}
                      </span>
                    </div>

                    {/* Line-by-Line Products Container */}
                    <div style={{ background: "var(--d-bg-1)", border: "1px solid var(--d-line)", borderRadius: "8px", overflow: "hidden" }}>
                      {prodList.map((p, idx) => (
                        <div
                          key={p.id}
                          onClick={() => {
                            setSelectedProduct(p);
                            setRailCollapsed(true);
                          }}
                          role="button"
                          tabIndex={0}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            padding: "12px 18px",
                            borderBottom: idx < prodList.length - 1 ? "1px solid var(--d-line)" : "none",
                            cursor: "pointer",
                            transition: "background .12s",
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              setSelectedProduct(p);
                            }
                          }}
                          className="product-line-item"
                        >
                          <span style={{ fontSize: "14px", fontWeight: "600", color: "var(--d-txt)" }}>
                            {p.name}
                          </span>

                          <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
                            <span style={{ fontSize: "11.5px", color: "var(--d-txt-3)", fontFamily: "var(--mono)" }}>
                              {p.category}
                            </span>
                            <span style={{ fontSize: "12px", color: "var(--fav-badge)", fontFamily: "var(--mono)", fontWeight: "600" }}>
                              View Specs ↗
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              ) : (
                <div
                  style={{
                    padding: "32px",
                    textAlign: "center",
                    background: "var(--d-bg-1)",
                    border: "1px solid var(--d-line)",
                    borderRadius: "8px",
                    color: "var(--d-txt-3)",
                    fontSize: "13px",
                  }}
                >
                  No products found for {selectedCompany.name} matching "{productSearch}".
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
