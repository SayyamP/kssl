import { useMemo, useState } from "react";

/* The competitor-product list: kVA band → KSSL anchor product → the rivals paired
   against it. Bands collapse; the four selects narrow each other, so a combination
   that matches nothing can't be chosen. */
export default function MatchupList({ data, selected, onSelect }) {
  const { matchups, POS_CATS, CAT_KEY } = data;
  const [query, setQuery] = useState("");
  const [co, setCo] = useState("");
  const [cat, setCat] = useState("");
  const [koel, setKoel] = useState("");
  const [country, setCountry] = useState("");
  const [collapsed, setCollapsed] = useState({});

  /* label lookups, built once from the corpus */
  const labels = useMemo(() => {
    const catLabel = {};
    POS_CATS.forEach(([v, lab]) => {
      catLabel[v] = lab;
    });
    const coLabel = {};
    const ctLabel = {};
    const koelLabel = {};
    Object.keys(matchups).forEach((id) => {
      const m = matchups[id];
      if (m.compBy) coLabel[m.compBy.toLowerCase()] = m.compBy;
      if (m.country) ctLabel[m.country.toLowerCase()] = m.country;
      const a = m.anchor || m.bf;
      if (a) koelLabel[a.toLowerCase()] = a;
    });
    return { catLabel, coLabel, ctLabel, koelLabel };
  }, [matchups, POS_CATS]);

  /* Given the current selections, which values remain valid for each dimension —
     computed excluding that dimension's own filter, so choosing one never empties
     the others. */
  const options = useMemo(() => {
    const cosSet = new Set();
    const catSet = new Set();
    const koelSet = new Set();
    const ctSet = new Set();
    Object.keys(matchups).forEach((id) => {
      const m = matchups[id];
      const mco = (m.compBy || "").toLowerCase();
      const mcat = CAT_KEY[m.cat];
      const mct = (m.country || "").toLowerCase();
      const mk = (m.anchor || m.bf || "").toLowerCase();
      if ((!cat || mcat === cat) && (!koel || mk === koel) && (!country || mct === country))
        cosSet.add(mco);
      if ((!co || mco === co) && (!koel || mk === koel) && (!country || mct === country) && mcat)
        catSet.add(mcat);
      if ((!co || mco === co) && (!cat || mcat === cat) && (!country || mct === country) && mk)
        koelSet.add(mk);
      if ((!co || mco === co) && (!cat || mcat === cat) && (!koel || mk === koel) && mct)
        ctSet.add(mct);
    });
    const sortBy = (set, map) =>
      [...set].sort((a, b) => (map[a] || a).localeCompare(map[b] || b));
    return {
      co: sortBy(cosSet, labels.coLabel),
      cat: sortBy(catSet, labels.catLabel),
      koel: sortBy(koelSet, labels.koelLabel),
      country: sortBy(ctSet, labels.ctLabel),
    };
  }, [matchups, CAT_KEY, co, cat, koel, country, labels]);

  /* band → anchor → matchups, filtered. Anchors are ordered by how many rivals they
     face, and within an anchor global primes lead. */
  const groups = useMemo(() => {
    const q = query.toLowerCase().trim();
    /* An unknown cat must still render somewhere — mirror how wireDataset appends a
       chip for unknown techCats. Without this, the row counts in the nav badge but
       appears in no group. */
    const catDefs = [...POS_CATS, ["__uncat", "Uncategorised"]];
    return catDefs.map(([key, label]) => {
      const items = Object.keys(matchups).filter((id) =>
        key === "__uncat"
          ? CAT_KEY[matchups[id].cat] == null
          : CAT_KEY[matchups[id].cat] === key,
      );
      if (!items.length) return null;
      const byAnchor = {};
      items.forEach((id) => {
        const m = matchups[id];
        const a = m.anchor || m.bf;
        (byAnchor[a] = byAnchor[a] || []).push(id);
      });
      const anchors = Object.keys(byAnchor)
        .sort((a, b) => byAnchor[b].length - byAnchor[a].length)
        .map((anchor) => {
          const ids = byAnchor[anchor]
            .sort((a, b) => (matchups[b].global ? 1 : 0) - (matchups[a].global ? 1 : 0))
            .filter((id) => {
              const m = matchups[id];
              const search = `${m.comp || ""} ${m.compBy || ""} ${m.cat || ""} ${m.country || ""} ${m.anchor || ""}${
                m.global ? " global prime benchmark" : ""
              }`.toLowerCase();
              if (q && !search.includes(q)) return false;
              if (co && (m.compBy || "").toLowerCase() !== co) return false;
              if (cat && CAT_KEY[m.cat] !== cat) return false;
              if (koel && (m.anchor || m.bf || "").toLowerCase() !== koel) return false;
              if (country && (m.country || "").toLowerCase() !== country) return false;
              return true;
            });
          return { anchor, ids };
        })
        .filter((a) => a.ids.length);
      const shown = anchors.reduce((n, a) => n + a.ids.length, 0);
      if (!shown) return null;
      return { key, label, total: items.length, anchors };
    }).filter(Boolean);
  }, [matchups, POS_CATS, CAT_KEY, query, co, cat, koel, country]);

  const select = (setter) => (e) => setter(e.target.value);

  return (
    <div className="mu-list">
      <div className="mu-list-h">
        <span className="eyebrow">Competitor Products</span>
        <div className="sub">{data.client?.short || "KSSL"} models vs rival products</div>
        <div className="mu-search">
          <span className="si">⌕</span>
          <input
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search product or competitor…"
            type="text"
            value={query}
          />
        </div>
        <div className="mu-filters">
          <select className="mu-fsel" onChange={select(setCo)} value={co}>
            <option value="">All companies</option>
            {options.co.map((v) => (
              <option key={v} value={v}>
                {labels.coLabel[v] || v}
              </option>
            ))}
          </select>
          <select className="mu-fsel" onChange={select(setCat)} value={cat}>
            <option value="">All categories</option>
            {options.cat.map((v) => (
              <option key={v} value={v}>
                {labels.catLabel[v] || v}
              </option>
            ))}
          </select>
          <select className="mu-fsel" onChange={select(setKoel)} value={koel}>
            <option value="">All {data.client?.short || "KSSL"} products</option>
            {options.koel.map((v) => (
              <option key={v} value={v}>
                {labels.koelLabel[v] || v}
              </option>
            ))}
          </select>
          <select className="mu-fsel" onChange={select(setCountry)} value={country}>
            <option value="">All countries</option>
            {options.country.map((v) => (
              <option key={v} value={v}>
                {labels.ctLabel[v] || v}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div id="mu-list-body">
        {groups.map((g) => (
          <div key={g.key}>
            <div
              className={`mu-cat${collapsed[g.key] ? " collapsed" : ""}`}
              data-cat={g.key}
              onClick={() => setCollapsed((c) => ({ ...c, [g.key]: !c[g.key] }))}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setCollapsed((c) => ({ ...c, [g.key]: !c[g.key] }));
                }
              }}
            >
              <span className="cleft">
                <i className="chev">▾</i> {g.label}
              </span>
              <span className="ccount">{g.total}</span>
            </div>
            <div className={`mu-group${collapsed[g.key] ? " collapsed" : ""}`} data-group={g.key}>
              {g.anchors.map(({ anchor, ids }) => (
                <div key={anchor}>
                  <div className="mu-anchor">
                    <span className="ma-koel">{data.client?.short || "KSSL"}</span> {anchor}{" "}
                    <span className="ma-count">
                      {ids.length} rival{ids.length > 1 ? "s" : ""}
                    </span>
                  </div>
                  {ids.map((id) => {
                    const m = matchups[id];
                    return (
                      <div
                        className={`mu-item${selected === id ? " active" : ""}`}
                        data-mu={id}
                        key={id}
                        onClick={() => onSelect(id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onSelect(id);
                          }
                        }}
                      >
                        <div className="comp-prod">
                          <span className="wdot watch" />
                          {m.comp}
                        </div>
                        <div className="vs">
                          <span className="arrow">vs {data.client?.short || "KSSL"}</span>{" "}
                          <span className="bfp">{anchor}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        ))}
        {!groups.length ? (
          <div className="pat-li-none" style={{ padding: "18px" }}>
            {query.trim() || co || cat || koel || country
              ? "No product matches these filters"
              : "No competitor products served yet"}
          </div>
        ) : null}
      </div>
    </div>
  );
}
