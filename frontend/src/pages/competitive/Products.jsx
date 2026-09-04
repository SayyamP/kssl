import { useState, useMemo, useEffect } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { productNews } from "../../lib/news";
import { formatLabel, formatSectorName } from "../../lib/profile";

// Clean company display name helper
const cleanCompanyName = (rawName) => {
  if (!rawName) return "";
  let name = rawName.split("(")[0].split("-")[0].trim();
  name = name.replace(/,?\s*(Private|Pvt|Limited|Ltd|Inc|Corp|Corporation)\b.*/gi, "").trim();
  return name || rawName;
};

/* Portfolio categories go through the SAME formatter as every other label.
   This file used to carry its own, with a different acronym list and an American
   default ('Defense Systems') against profile.js's British one, which is how the
   Product and Competitive views ended up disagreeing on both case and spelling. */
const formatCategoryTitle = (cat) => formatLabel(cat) || "Defence Systems";

/* Product and spec labels take the same rule. Keeping a third variant here is what
   let the acronym lists drift apart in the first place. */
const formatTitleCase = (str) => formatLabel(str);

function nameKey(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

/* Words that appear in half the roster and identify nobody. Matching on these is how a
   substring join pairs the wrong two companies; dropping them is what lets a token
   comparison be strict. */
const CO_NOISE = new Set(
  ("limited ltd pvt private plc inc incorporated corp corporation company co gmbh ag sa " +
   "nv bv spa srl as ab oyj group holdings holding the and of").split(" "),
);
/* Geography deliberately stays OUT of that list. It is not identity for a DOMAIN, but it
   is identity for a company: dropping "india" reduced "India Aerospace Industries" to
   {aerospace, industries}, a subset of "Israel Aerospace Industries", and the two merged.
   A noise word must be one that identifies nobody -- a legal form does, a country does
   not. */

export function coTokens(name) {
  return new Set(nameKey(name).split(" ").filter((t) => t.length > 1 && !CO_NOISE.has(t)));
}

/* The acronym a company's name reduces to: "Advanced Weapons and Equipment India
   Limited" -> "aweil". The roster serves that company as the bare string "AWEIL", which
   shares NO token with its own full name, so token comparison alone leaves it stranded
   exactly as the substring join did. Joining words are skipped, or "and" would put an
   extra letter in the middle. */
const CO_JOINERS = new Set(["and", "of", "the", "for"]);

function coAcronym(name) {
  const w = nameKey(name).split(" ").filter((t) => t && !CO_JOINERS.has(t));
  return w.length > 1 ? w.map((t) => t[0]).join("") : "";
}

/* Does a matchup's company label denote the same company as this roster entry?

   The old test was `a.includes(b) || b.includes(a)` on the normalised display names,
   which stranded 40 of 160 matchups -- a quarter of the only spec data the corpus holds.

   Comparing distinctive tokens survives punctuation, ampersands and legal suffixes, but
   needs two guards that a plain subset test does not give:

   1. A single-token name must match EXACTLY. The roster carries Hanwha Aerospace,
      Hanwha Defense USA, Hanwha Ocean and Hanwha Group; "group" is a noise word, so
      Hanwha Group reduces to {hanwha}, a subset of all three siblings -- and every
      Hanwha Aerospace matchup would list its products under Hanwha Group as well.
      Attributing one company's products to another is worse than missing the join.

   2. An acronym is checked separately, because it shares no token with the words it
      stands for. */
export function sameCompany(a, b) {
  const A = coTokens(a);
  const B = coTokens(b);
  if (!A.size || !B.size) return false;

  const [small, big] = A.size <= B.size ? [A, B] : [B, A];

  // a bare acronym against the full name it abbreviates
  if (small.size === 1) {
    const one = [...small][0];
    if (one.length >= 3 && (coAcronym(a) === one || coAcronym(b) === one)) return true;
  }

  // one distinctive word cannot claim a longer name -- see guard 1 above
  if (small.size === 1 && big.size !== 1) return false;

  let hit = 0;
  small.forEach((t) => {
    if (big.has(t)) hit += 1;
  });
  return hit === small.size;
}

/* Product news, and the sidebar's country / category / revenue facets.
 *
 * getProductNewsData() used to return four invented articles per product —
 * "Indian Army Issues ₹45 Cr Procurement Order for 480 {product} Units",
 * "100% target accuracy" at Ladakh — attributed to ET, Business Standard,
 * Financial Express and NDTV Profit. It is replaced by productNews(), which
 * filters the company's REAL pipeline news down to the articles that name this
 * product, and returns [] when none do.
 *
 * getCompanyFilterMeta() guessed the same three facets from substrings of the HQ
 * string and the company id — defaulting country to "India", so with hq filled on
 * 24.4% of rows three quarters of the roster was silently filed as Indian, and the
 * filter chips presented that guess as a fact. Each facet now comes from the value
 * the pipeline actually holds, or is null and simply does not participate in the
 * filter.
 */
const countryOf = (hq) => {
  /* The pipeline writes hq as "City, Country" — the tail is the country, and a
     string with no comma states a place, not a country. Nothing is inferred from
     the company id. */
  const parts = String(hq || "").split(",").map((s) => s.trim()).filter(Boolean);
  return parts.length > 1 ? parts[parts.length - 1] : null;
};

/* The country facet, from the catalogued column first and the hq string only as a
   fallback. hq alone offered 11 values for a 178-company roster -- only 42 companies
   carry one at all, and three of the values it yielded ("Virginia", "Telangana",
   "Calif.") are not countries, because a "City, Region" hq has a region in its tail.
   competitors.global_locations is structured {url, value} written by the profile-facts
   writer and sourced per value, and it covers 75 companies. A sourced value beats a
   string split every time. */
const countriesOf = (co) => {
  const gl = Array.isArray(co.global_locations) ? co.global_locations : [];
  const named = gl
    .map((g) => (g && typeof g === "object" ? g.value : g))
    .filter(Boolean)
    .map((v) => String(v).trim());
  /* UNION, not either/or. Taking global_locations INSTEAD of the hq country dropped the
     one country a reader is most likely to look under: global_locations holds countries
     a company was mentioned in, which is not where it is. Live, that made RTX
     ("Arlington, Virginia") reachable only under Ukraine, Sikorsky ("Jupiter, FL, USA")
     only under the Czech Republic, and Exail ("Paris, France") only under the
     Netherlands and Belgium. Four companies lost their home country to a news mention. */
  const one = countryOf(co.hq);
  return [...new Set([...(one ? [one] : []), ...named])];
};

const getCompanyFilterMeta = (co) => ({
  countries: countriesOf(co),
  country: countriesOf(co)[0] || null,
  /* The maker's own sector, not a bucket mapped onto it -- but normalised through the
     one shared formatter. Rendered raw, the sidebar dropdown listed the same sector six
     times ("Aerospace and Defense", "Defence", "defense technology", "defence and
     aerospace", "Defence manufacturing", "defence technology") as six separate options,
     and each matched only its own spelling when picked. */
  category: (co.sector && formatSectorName(String(co.sector).trim())) || null,
  /* serving.matchup.revenue_filter is the column for this and is not yet written;
     until it is, a company has no revenue tier rather than a guessed one. */
  revenueTier: co.revenue_filter || null,
});

export default function Products() {
  const { data } = useData();
  const { setScope } = useAppState();

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
        const meta = getCompanyFilterMeta(co);
        list.push({
          cid: id,
          name: cleanCompanyName(co.name || id),
          threat: co.threat || "watch",
          sector: co.sector || "",
          country: meta.country,
          countries: meta.countries,
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
    /* Every country a company is present in, not just the first -- Airbus is in five,
       and offering only one of them made the other four unreachable by this filter. */
    // 47 options in roster order is a list to hunt through; 11 was not.
    const set = new Set(
      companyRoster.flatMap((c) => c.countries || []).filter(Boolean).sort((a, b) => a.localeCompare(b)),
    );
    return ["all", ...Array.from(set)];
  }, [companyRoster]);

  const sidebarCategories = useMemo(() => {
    const set = new Set(companyRoster.map((c) => c.category).filter(Boolean));
    return ["all", ...Array.from(set)];
  }, [companyRoster]);

  const { searchQuery } = useAppState();

  // Filter company sidebar roster based on search + country + category + revenue
  const filteredCompanyRoster = useMemo(() => {
    const q = (companyQuery || searchQuery || "").trim().toLowerCase();
    const tokens = q.split(/\s+/).filter(Boolean);
    return companyRoster.filter((c) => {
      if (tokens.length > 0) {
        const fullText = `${c.name || ""} ${c.sector || ""} ${c.hq || ""} ${c.cid || ""}`.toLowerCase();
        if (!tokens.every((tok) => fullText.includes(tok))) return false;
      }
      if (sidebarCountryFilter !== "all" && !(c.countries || []).includes(sidebarCountryFilter))
        return false;
      if (sidebarCategoryFilter !== "all" && c.category !== sidebarCategoryFilter) return false;
      if (sidebarRevenueFilter !== "all" && c.revenueTier !== sidebarRevenueFilter) return false;
      return true;
    });
  }, [companyRoster, companyQuery, searchQuery, sidebarCountryFilter, sidebarCategoryFilter, sidebarRevenueFilter]);

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
              specsObj[formatCategoryTitle(s.l)] = s.kv;
            }
          });
          prods.push({
            id: `kssl-${name}`,
            name: formatTitleCase(name),
            company: clientName,
            category: formatCategoryTitle(m.cat),
            specs: specsObj,
            reason: m.reason || "",
          });
        }
      });
    } else {
      const co = (data.competitors || {})[selectedCid] || {};

      matchups.forEach((m) => {
        if (sameCompany(m.compBy || m.comp || "", co.name || selectedCid)) {
          let name = (m.comp || "").replace(/.*·\s*/, "").trim() || m.anchor || "System";
          if (name && !seen.has(name.toLowerCase())) {
            seen.add(name.toLowerCase());
            const specsObj = {};
            (m.specs || []).forEach((s) => {
              if (s && s.l && (s.cv || s.kv)) {
                specsObj[formatCategoryTitle(s.l)] = s.cv || s.kv;
              }
            });
            prods.push({
              id: `comp-${m.id || name}`,
              name: formatTitleCase(name),
              company: selectedCompany.name,
              category: formatCategoryTitle(m.cat),
              specs: specsObj,
              reason: m.reason || "",
            });
          }
        }
      });

      (co.products || []).forEach((pName) => {
        const obj = typeof pName === "string" ? { name: pName } : pName || {};
        const name = obj.name || obj.n || "";
        if (name && !seen.has(name.toLowerCase())) {
          seen.add(name.toLowerCase());
          prods.push({
            id: obj.id ? `co-prod-${obj.id}` : `co-prod-${name}`,
            name: formatTitleCase(name),
            company: selectedCompany.name,
            /* The product's OWN band when the record carries one -- this used to be the
               company's sector for every product it makes, so a firm's radars and its
               trucks came out under one label. It is a narrow win: measured over the
               real corpus only 4 products in 112 carry a band, because real names are
               model designations (Switchblade, VSR-700) with no category word in them.
               co.sector stays the fallback, and is also what the reference archive's
               bare-string products still use. */
            category: formatCategoryTitle(obj.category || co.sector),
            source: obj.source || "",
            sourceUrl: obj.source_url || "",
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
    return productNews(data, selectedCompany.cid, selectedProduct.name);
  }, [data, selectedProduct, selectedCompany]);

  /* "480 Units / ₹45 Cr" and "Active Delivery Pipeline" were printed here as
     literals for every product. No column states an induction order, so the tile
     shows what the pipeline can prove -- the number of sourced articles naming
     this product -- and a dash when that is nothing. */
  const productScale = productNewsArticles.length
    ? `${productNewsArticles.length} sourced ${productNewsArticles.length === 1 ? "story" : "stories"}`
    : "—";
  const productScaleNote = productNewsArticles.length
    ? "From the crawled corpus"
    : "Not stated in the corpus";

  /* The pills used to be a fixed list -- Sales, Technology, Testing -- matched against
     each article's `category`. But `category` is the pipeline's PRODUCT category
     ("UAVs & Drones", "Missiles & Air Defence", "Artillery", ...), and not one of the
     492 served articles carries any of those three words. Every pill emptied the feed,
     always, for every product. So the pills are built from the categories the articles
     actually have; a category that appears in the data is a category you can filter by. */
  const prodNewsCats = useMemo(
    () => ["All", ...Array.from(new Set(productNewsArticles.map((a) => a.category).filter(Boolean)))],
    [productNewsArticles],
  );

  const filteredProdArticles = useMemo(() => {
    if (!prodNewsFilter || prodNewsFilter === "All") {
      return productNewsArticles;
    }
    return productNewsArticles.filter((a) => a.category === prodNewsFilter);
  }, [productNewsArticles, prodNewsFilter]);

  /* No `|| productNewsArticles[0]` tail: falling back to the unfiltered list meant a
     filter that matched nothing still displayed an off-filter article as TOP STORY, so
     the filter looked half-applied rather than empty. */
  const topProdStory = useMemo(() => {
    return filteredProdArticles.find((a) => a.isTopStory) || filteredProdArticles[0] || null;
  }, [filteredProdArticles]);

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
              <option value="all">All Countries</option>
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
                  <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#992424", display: "inline-block" }} />
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
                Source Publisher: <span style={{ color: "#f87171" }}><span className="src-dot"></span>{activeProdArticle.source}</span>
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
                          {formatTitleCase(val)}
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
                    No specifications are held for {selectedProduct.name}. This corpus
                    carries measured specs only where a product is paired in a KSSL
                    matchup and those figures cleared the publish gate. Nothing is shown
                    here in preference to a figure with no source behind it.
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
                    <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#992424", display: "inline-block" }} />
                    <div>
                      <div style={{ fontFamily: "var(--mono)", fontSize: "14px", fontWeight: "700", letterSpacing: ".08em", color: "#ffffff", textTransform: "uppercase" }}>
                        LATEST NEWS & INTEL ON {selectedProduct.name.toUpperCase()}
                      </div>
                      <div style={{ fontSize: "12px", color: "var(--d-txt-3)", marginTop: "2px" }}>
                        {/* "Real-time" promised something nothing delivers: these are
                            corpus articles, dated when they were published. The three
                            named categories were also the impossible pill list. */}
                        Sourced articles naming {selectedProduct.name}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Pills come from the served articles, not a fixed list -- see prodNewsCats */}
                <div style={{ display: "flex", gap: "8px", marginBottom: "16px", flexWrap: "wrap" }}>
                  {prodNewsCats.map((cat) => (
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
                      {cat === "All" ? "All Product News" : cat}
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
                        <img src={topProdStory.image || undefined} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
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
                            <span className="src-dot"></span>{topProdStory.source}
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
                  </div>

                  {/* COLUMN 3: ANALYTICS & MARKET WIDGETS */}
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    {/* Trending Product Intel */}
                    <div style={{ background: "var(--d-bg-2)", border: "1px solid var(--d-line)", borderRadius: "8px", padding: "14px", display: "flex", flexDirection: "column", gap: "8px" }}>
                      <div style={{ fontFamily: "var(--mono)", fontSize: "11px", fontWeight: "700", letterSpacing: ".08em", color: "var(--d-txt-3)", textTransform: "uppercase" }}>
                        TRENDING PRODUCT INTEL
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
                        DEPLOYMENT CONTRACT SCALE
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                          <span style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>Induction Orders</span>
                          <div style={{ fontSize: "18px", fontWeight: "700", color: "#ffffff", fontFamily: "var(--mono)" }}>
                            {productScale}
                          </div>
                          <span style={{ fontSize: "11px", color: "#22c55e", fontWeight: "600", fontFamily: "var(--mono)" }}>
                            {productScaleNote}
                          </span>
                        </div>
                        {/* A rising sparkline was drawn here from a hardcoded path, beside
                            a real induction-order figure, which read as that figure's trend.
                            There is no time series behind it. */}
                      </div>
                    </div>

                    {/* A "product mentions in the last 24h", with a percentage change
                        against yesterday, stood here. Both figures were literals in the
                        JSX. Nothing in this system counts mentions and no part of the
                        pipeline has a 24-hour window, so the tile could only ever have
                        been decoration shaped like a measurement. Removed rather than
                        zeroed: a counter reading zero still claims we are counting.

                        A "Set Product News Alerts" button sat below it with no onClick,
                        and a "View More News" button did the same at the foot of the feed.
                        Both are gone; there is no alerting or paging behind either. */}
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
                          onClick={() => setSelectedProduct(p)}
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
