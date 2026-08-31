import { useState, useMemo, useEffect } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildProfile } from "../../lib/profile";
import { srcChips, plainText } from "../../lib/html";

const cleanCompanyName = (rawName) => {
  if (!rawName) return "";
  let name = rawName.split("(")[0].split(" - ")[0].trim();
  name = name.replace(/,?\s*(Private|Pvt|Limited|Ltd|Inc|Corp|Corporation)\b.*/gi, "").trim();
  return name || rawName;
};

function nameKey(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

const DIR_WORD = { threat: "Threat", watch: "Watch", fav: "Favourable" };

export default function Products() {
  const { data } = useData();
  const { setScope, takePending } = useAppState();

  const clientCid = (data.client && data.client.id) || "KSSL";
  const clientName = (data.client && (data.client.short || data.client.name)) || "KSSL";

  const [companyQuery, setCompanyQuery] = useState("");
  const [listOpen, setListOpen] = useState(true);

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
        list.push({
          cid: id,
          name: cleanCompanyName(co.name || id),
          threat: co.threat || "watch",
          sector: co.sector || "",
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
  const [pendingProduct, setPendingProduct] = useState(null);
  const [activeProdCard, setActiveProdCard] = useState(null);

  useEffect(() => {
    if (!selectedCid && firstCompCid) setSelectedCid(firstCompCid);
  }, [selectedCid, firstCompCid]);

  // Opened from a Profile portfolio chip: preselect the company (+ product below).
  useEffect(() => {
    const pend = takePending("products");
    if (pend && pend.cid) {
      setSelectedCid(pend.cid);
      setListOpen(false);
      setSelectedProduct(null);
      if (pend.product) setPendingProduct(pend.product);
    }
  }, [takePending]);

  useEffect(() => {
    setActiveProdCard(null);
  }, [selectedProduct]);

  const filteredCompanyRoster = useMemo(() => {
    const q = companyQuery.trim().toLowerCase();
    if (!q) return companyRoster;
    return companyRoster.filter((c) => `${c.name} ${c.sector}`.toLowerCase().indexOf(q) >= 0);
  }, [companyRoster, companyQuery]);

  const selectedCompany = useMemo(() => {
    const co = (data.competitors || {})[selectedCid] || {};
    return {
      cid: selectedCid,
      name: cleanCompanyName(co.name || selectedCid),
      rawName: co.name || selectedCid,
      sector: co.sector || "",
      hq: co.hq || "",
    };
  }, [data, selectedCid]);

  const companyProducts = useMemo(() => {
    const matchups = Object.values(data.matchups || {});
    const prods = [];
    const seen = new Set();
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
            if (!s || !s.l) return;
            /* cv = the RIVAL's own figure; kv = KSSL's. Show cv where captured. Where
               only kv exists we keep the dimension but mark it unpublished — the spec
               still "appears" without ever printing KSSL's number as the rival's. */
            if (s.cv) specsObj[s.l] = String(s.cv);
            else if (!(s.l in specsObj)) specsObj[s.l] = null;
          });
          prods.push({
            id: `comp-${m.id || name}`,
            name,
            company: selectedCompany.name,
            category: m.cat || "Uncategorised",
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
          name,
          company: selectedCompany.name,
          category: co.sector || "Uncategorised",
          specs: {},
          reason: "",
        });
      }
    });

    return prods;
  }, [data, selectedCid, selectedCompany.name]);

  // Resolve a pending product name to an actual product once the catalog loads.
  useEffect(() => {
    if (!pendingProduct) return;
    const q = pendingProduct.toLowerCase();
    const match =
      companyProducts.find((p) => p.name.toLowerCase() === q) ||
      companyProducts.find((p) => p.name.toLowerCase().includes(q) || q.includes(p.name.toLowerCase()));
    if (match) setSelectedProduct(match);
    setPendingProduct(null);
  }, [companyProducts, pendingProduct]);

  const categories = useMemo(() => {
    const set = new Set(companyProducts.map((p) => p.category).filter(Boolean));
    return ["all", ...Array.from(set)];
  }, [companyProducts]);

  const filteredCompanyProducts = useMemo(() => {
    const q = productSearch.trim().toLowerCase();
    return companyProducts.filter((p) => {
      const catMatch = categoryFilter === "all" || p.category === categoryFilter;
      if (!catMatch) return false;
      if (!q) return true;
      const nameMatch = p.name.toLowerCase().includes(q);
      const catTextMatch = p.category.toLowerCase().includes(q);
      const specMatch = Object.entries(p.specs).some(
        ([k, v]) => k.toLowerCase().includes(q) || (v != null && String(v).toLowerCase().includes(q))
      );
      return nameMatch || catTextMatch || specMatch;
    });
  }, [companyProducts, productSearch, categoryFilter]);

  const groupedProducts = useMemo(() => {
    const groups = {};
    filteredCompanyProducts.forEach((p) => {
      const cat = p.category || "Uncategorised";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(p);
    });
    return groups;
  }, [filteredCompanyProducts]);

  // Real manufacturer signals — product-level news is not in the corpus, so the
  // honest feed is the company's own captured signals, shown as rows without images.
  const companyCards = useMemo(() => {
    if (!selectedCid || selectedCid === clientCid) return [];
    return buildProfile(data, selectedCid).cards || [];
  }, [data, selectedCid, clientCid]);

  useEffect(() => {
    setScope("products", { selection: `${selectedCompany.name} Products` }, {
      pillar: "Competitive",
      view: "Products",
      selection: `${selectedCompany.name} Products`,
    });
  }, [setScope, selectedCompany]);

  const selectCompany = (id) => {
    setSelectedCid(id);
    setSelectedProduct(null);
    setProductSearch("");
    setCategoryFilter("all");
    setListOpen(false);
  };

  return (
    <div className="pos-view v-products" style={{ gridTemplateColumns: listOpen ? "300px 1fr" : "44px 1fr" }}>
      {/* LEFT: company selector — collapses once a company is open */}
      {listOpen ? (
        <div className="mu-list">
          <div className="mu-list-h">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span className="eyebrow">Companies</span>
              <button type="button" className="cp-collapse-btn" title="Collapse list" aria-label="Collapse company list" onClick={() => setListOpen(false)}>«</button>
            </div>
            <div className="sub">Select company to view products</div>
            <div className="mu-search">
              <span className="si">⌕</span>
              <input type="text" aria-label="Search companies" placeholder="Search company…" value={companyQuery} onChange={(e) => setCompanyQuery(e.target.value)} />
            </div>
          </div>
          <div id="patc-list">
            {filteredCompanyRoster.map((r) => (
              <div
                key={r.cid}
                className={`pat-li${selectedCid === r.cid ? " active" : ""}`}
                onClick={() => selectCompany(r.cid)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectCompany(r.cid); }
                }}
              >
                <span className="pli-n" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span className={`wdot ${r.threat === "high" ? "threat" : r.threat === "low" ? "fav" : "watch"}`} />
                  {r.name}
                </span>
              </div>
            ))}
            {!filteredCompanyRoster.length && <div className="cp-empty">no company matches “{companyQuery}”</div>}
          </div>
        </div>
      ) : (
        <div className="mu-rail-collapsed">
          <button type="button" className="cp-collapse-btn" title="Show company list" aria-label="Show company list" onClick={() => setListOpen(true)}>»</button>
        </div>
      )}

      {/* RIGHT */}
      <div className="cp-body" style={{ padding: "20px", background: "var(--d-bg)" }}>
        {selectedProduct ? (
          activeProdCard ? (
            /* ---- real article detail: card fields + the full body from data.details ---- */
            (() => {
            const det = { ...activeProdCard, ...((data.details && data.details[activeProdCard.id]) || {}) };
            return (
            <div className="cp-sec">
              <button type="button" className="cp-back-btn" onClick={() => setActiveProdCard(null)}>← Back to product</button>
              <div className="cp-article-meta">
                <span className={`cp-tag dir-${det.dir || "watch"}`}>{DIR_WORD[det.dir] || "Signal"}</span>
                {det.ago ? <span className="cp-note">{det.ago}</span> : null}
              </div>
              <h2 className="cp-article-title" dangerouslySetInnerHTML={{ __html: det.title }} />
              {det.what ? (
                <div className="cp-prose" style={{ marginTop: "14px" }} dangerouslySetInnerHTML={{ __html: det.what }} />
              ) : det.sowhat ? (
                <div className="cp-prose" style={{ marginTop: "14px" }} dangerouslySetInnerHTML={{ __html: det.sowhat }} />
              ) : null}
              {det.facts && det.facts.length ? (
                <div style={{ marginTop: "18px" }}>
                  {det.facts.map((fct, i) => (
                    <div className="cp-fact-row" key={`${fct[0]}-${i}`}>
                      <span className="cp-fact-k">{fct[0]}</span>
                      <span className="cp-fact-v" dangerouslySetInnerHTML={{ __html: fct[1] }} />
                    </div>
                  ))}
                </div>
              ) : null}
              {(() => {
                const html = srcChips(det.srcs) || srcChips(det.url ? [{ label: "", url: det.url }] : null);
                return html ? (
                  <div style={{ marginTop: "18px" }}>
                    <span className="eyebrow" style={{ display: "block", marginBottom: "8px", color: "var(--d-txt-3)" }}>Raw source</span>
                    <span dangerouslySetInnerHTML={{ __html: html }} />
                  </div>
                ) : (
                  <div className="cp-thin" style={{ marginTop: "18px", fontSize: "12px" }}>No source link captured for this item.</div>
                );
              })()}
            </div>
            );
            })()
          ) : (
            /* ---- product specs + manufacturer signals ---- */
            <div className="prod-specs-tab">
              <div className="prod-specs-head">
                <div>
                  <span className="eyebrow" style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>{selectedProduct.category}</span>
                  <h3 style={{ fontSize: "20px", fontWeight: 700, color: "var(--d-txt)", margin: "4px 0 0 0" }}>{selectedProduct.name}</h3>
                  <span style={{ fontSize: "12.5px", color: "var(--d-txt-3)", marginTop: "2px", display: "block" }}>
                    Manufacturer: <strong style={{ color: "var(--d-txt-2)" }}>{selectedProduct.company}</strong>
                  </span>
                </div>
                <button type="button" className="cp-back-btn" style={{ marginBottom: 0 }} onClick={() => setSelectedProduct(null)}>← Back</button>
              </div>

              {/* TECHNICAL SPECIFICATIONS */}
              <div style={{ marginTop: "22px" }}>
                <span className="eyebrow" style={{ fontSize: "11px", color: "var(--d-txt-3)", display: "block", marginBottom: "10px" }}>Technical Specifications</span>
                {Object.keys(selectedProduct.specs).length > 0 ? (
                  <div className="prod-spec-table">
                    {Object.entries(selectedProduct.specs).map(([label, val]) => (
                      <div className="prod-spec-row" key={label}>
                        <span className="prod-spec-k">{label}</span>
                        <span className="prod-spec-v">{val != null ? val : <em style={{ color: "var(--d-txt-4)", fontStyle: "normal", fontFamily: "var(--mono)", fontSize: "12px" }}>not published</em>}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="cp-thin" style={{ fontSize: "12px", fontFamily: "var(--mono)", padding: "12px", background: "var(--d-bg-1)", border: "1px solid var(--d-line)", borderRadius: "6px" }}>
                    No published specifications for {selectedProduct.name} in the corpus. Specs appear here only where a spec-by-spec comparison was captured.
                  </div>
                )}
              </div>

              {selectedProduct.reason ? (
                <div style={{ marginTop: "18px", padding: "14px 16px", background: "var(--d-bg-1)", border: "1px solid var(--d-line)", borderRadius: "6px" }}>
                  <span className="eyebrow" style={{ fontSize: "10px", color: "var(--d-txt-3)", display: "block", marginBottom: "6px" }}>Evaluation note & comparison basis</span>
                  <div className="cp-prose" dangerouslySetInnerHTML={{ __html: selectedProduct.reason }} />
                </div>
              ) : null}

              {/* MANUFACTURER SIGNALS — rows, no images */}
              <div style={{ marginTop: "26px", borderTop: "1px solid var(--d-line)", paddingTop: "20px" }}>
                <span className="eyebrow" style={{ fontSize: "11px", color: "var(--d-txt-3)", display: "block", marginBottom: "4px" }}>
                  Latest signals on {selectedProduct.company}
                </span>
                <div className="cp-note" style={{ marginBottom: "12px" }}>
                  Product-level news is not held in the corpus; these are the manufacturer's captured signals.
                </div>
                {companyCards.length ? (
                  <div className="cp-news-list" style={{ maxHeight: "none", padding: 0 }}>
                    {companyCards.map((card, i) => (
                      <div
                        className="cp-news-item"
                        key={card.id || i}
                        role="button"
                        tabIndex={0}
                        style={{ cursor: "pointer" }}
                        onClick={() => setActiveProdCard(card)}
                        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setActiveProdCard(card); } }}
                      >
                        <div className="cp-news-item-head">
                          <span className={`cp-tag dir-${card.dir || "watch"}`}>{DIR_WORD[card.dir] || "Signal"}</span>
                          {card.ago ? <span className="cp-note">{card.ago}</span> : null}
                        </div>
                        <div className="cp-news-item-title" dangerouslySetInnerHTML={{ __html: card.title }} />
                        {card.sowhat ? <div className="cp-row-x">{plainText(card.sowhat).slice(0, 220)}</div> : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="cp-thin" style={{ fontSize: "12px" }}>No signals captured for {selectedProduct.company} yet.</div>
                )}
              </div>
            </div>
          )
        ) : (
          /* ---- catalog ---- */
          <>
            <div className="products-header" style={{ marginBottom: "20px", display: "flex", gap: "14px", flexWrap: "wrap", alignItems: "center", background: "var(--d-bg-1)", padding: "16px 20px", borderRadius: "8px", border: "1px solid var(--d-line)" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                <span className="eyebrow" style={{ fontSize: "10px", color: "var(--d-txt-3)" }}>{selectedCompany.name.toUpperCase()} PRODUCTS</span>
                <h2 style={{ fontSize: "16px", fontWeight: 700, color: "var(--d-txt)", margin: 0 }}>{selectedCompany.name} Product Portfolio</h2>
                <div className="sub" style={{ fontSize: "12px", color: "var(--d-txt-3)", marginTop: "2px" }}>
                  {filteredCompanyProducts.length} product{filteredCompanyProducts.length !== 1 ? "s" : ""} tracked · select a line item for specs & signals
                </div>
              </div>
              <div style={{ display: "flex", gap: "10px", alignItems: "center", marginLeft: "auto", flexWrap: "wrap" }}>
                <input type="text" aria-label="Search products or specs" placeholder="Search products or specs..." value={productSearch} onChange={(e) => setProductSearch(e.target.value)}
                  style={{ background: "var(--d-bg-2)", border: "1px solid var(--d-line)", color: "var(--d-txt)", padding: "8px 14px", borderRadius: "6px", fontSize: "12.5px", width: "220px", height: "38px", boxSizing: "border-box", outline: "none" }} />
                <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}
                  style={{ background: "var(--d-bg-2)", border: "1px solid var(--d-line)", color: "var(--d-txt)", padding: "8px 14px", borderRadius: "6px", fontSize: "12.5px", width: "200px", height: "38px", boxSizing: "border-box", outline: "none", cursor: "pointer" }}>
                  <option value="all">All Categories ({categories.length - 1})</option>
                  {categories.filter((t) => t !== "all").map((t) => (<option key={t} value={t}>{t}</option>))}
                </select>
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              {Object.keys(groupedProducts).length > 0 ? (
                Object.entries(groupedProducts).map(([catName, prodList]) => (
                  <div key={catName} style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px", borderBottom: "1px solid var(--d-line)", paddingBottom: "6px" }}>
                      <span className="eyebrow" style={{ fontSize: "12px", color: "var(--d-txt-2)", fontWeight: 700 }}>{catName}</span>
                      <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "var(--d-txt-4)", background: "var(--d-bg-2)", padding: "2px 8px", borderRadius: "10px" }}>{prodList.length}</span>
                    </div>
                    <div style={{ background: "var(--d-bg-1)", border: "1px solid var(--d-line)", borderRadius: "8px", overflow: "hidden" }}>
                      {prodList.map((p, idx) => (
                        <div
                          key={p.id}
                          onClick={() => setSelectedProduct(p)}
                          role="button"
                          tabIndex={0}
                          className="product-line-item"
                          style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 18px", borderBottom: idx < prodList.length - 1 ? "1px solid var(--d-line)" : "none", cursor: "pointer" }}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedProduct(p); } }}
                        >
                          <span style={{ fontSize: "14px", fontWeight: 600, color: "var(--d-txt)" }}>{p.name}</span>
                          <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
                            <span style={{ fontSize: "11.5px", color: "var(--d-txt-3)", fontFamily: "var(--mono)" }}>{p.category}</span>
                            <span style={{ fontSize: "12px", color: "var(--fav-badge)", fontFamily: "var(--mono)", fontWeight: 600 }}>View specs</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              ) : (
                <div style={{ padding: "32px", textAlign: "center", background: "var(--d-bg-1)", border: "1px solid var(--d-line)", borderRadius: "8px", color: "var(--d-txt-3)", fontSize: "13px" }}>
                  No products tracked for {selectedCompany.name}{productSearch ? ` matching "${productSearch}"` : ""}.
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
