import { useEffect, useMemo, useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildProfile, rosterOf } from "../../lib/profile";
import { srcChips, plainText } from "../../lib/html";

/* Clean company short name — drop the legal suffix and any parenthetical. */
const cleanCompanyName = (rawName) => {
  if (!rawName) return "";
  let name = rawName.split("(")[0].split(" - ")[0].trim();
  name = name.replace(/,?\s*(Private|Pvt|Limited|Ltd|Inc|Corp|Corporation)\b.*/gi, "").trim();
  return name || rawName;
};

const DIR_WORD = { threat: "Threat", watch: "Watch", fav: "Favourable" };
/* Company threat is high/medium/low (a different vocabulary from card dir); some
   records carry a prose paragraph in this field. Only the three enum values are a badge. */
const THREAT_WORD = { high: "High threat", medium: "Medium threat", low: "Low threat" };

function Sec({ title, note, children }) {
  return (
    <div className="cp-sec">
      <div className="cp-sec-h">
        <span className="eyebrow">{title}</span>
        {note ? <span className="cp-note">{note}</span> : null}
      </div>
      {children}
    </div>
  );
}

export default function Profile() {
  const { data } = useData();
  const { setScope, jumpTo, takePending } = useAppState();
  const [query, setQuery] = useState("");
  const roster = useMemo(() => rosterOf(data), [data]);
  const [cid, setCid] = useState(() => (roster[0] ? roster[0].cid : ""));
  const [listOpen, setListOpen] = useState(true);
  const [activeCard, setActiveCard] = useState(null);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return roster;
    return roster.filter(
      (r) => `${r.name} ${r.sector}`.toLowerCase().indexOf(q) >= 0,
    );
  }, [roster, query]);

  const p = useMemo(() => (cid ? buildProfile(data, cid) : null), [data, cid]);

  useEffect(() => {
    if (!p) return;
    setScope("profile", { company: p.name, cid: p.cid }, {
      pillar: "Competitive",
      view: "Competitor",
      selection: p.name,
    });
  }, [p, setScope]);

  // switching company clears the open article
  useEffect(() => {
    setActiveCard(null);
  }, [cid]);

  // Opened from global search (or another panel) targeting a specific competitor.
  useEffect(() => {
    const pend = takePending("profile");
    if (pend && pend.cid) {
      setCid(pend.cid);
      setListOpen(false);
      setActiveCard(null);
    }
  }, [takePending]);

  const displayName = p ? cleanCompanyName(p.name) : "";

  const openProduct = (name) => {
    jumpTo("competitive", "products", { cid: p.cid, product: name });
  };

  return (
    <div className="pos-view v-profile" style={{ gridTemplateColumns: listOpen ? "300px 1fr" : "44px 1fr" }}>
      {/* LEFT: competitor list — collapses to a thin rail once a rival is open */}
      {listOpen ? (
        <div className="mu-list">
          <div className="mu-list-h">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span className="eyebrow">Competitors</span>
              <button
                type="button"
                className="cp-collapse-btn"
                title="Collapse list"
                aria-label="Collapse competitor list"
                onClick={() => setListOpen(false)}
              >
                «
              </button>
            </div>
            <div className="sub">Select for profile</div>
            <div className="mu-search">
              <span className="si">⌕</span>
              <input
                aria-label="Search competitors"
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search competitor…"
                type="text"
                value={query}
              />
            </div>
          </div>
          <div id="patc-list">
            {list.map((r) => (
              <div
                className={`pat-li${cid === r.cid ? " active" : ""}`}
                key={r.cid}
                onClick={() => {
                  setCid(r.cid);
                  setListOpen(false);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setCid(r.cid);
                    setListOpen(false);
                  }
                }}
                role="button"
                tabIndex={0}
              >
                <span className="pli-n" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span className={`wdot ${r.threat === "high" ? "threat" : r.threat === "low" ? "fav" : "watch"}`} />
                  {cleanCompanyName(r.name)}
                </span>
              </div>
            ))}
            {!list.length ? <div className="cp-empty">no competitor matches “{query}”</div> : null}
          </div>
        </div>
      ) : (
        <div className="mu-rail-collapsed">
          <button
            type="button"
            className="cp-collapse-btn"
            title="Show competitor list"
            aria-label="Show competitor list"
            onClick={() => setListOpen(true)}
          >
            »
          </button>
        </div>
      )}

      {/* RIGHT: profile, or the open news article */}
      <div className="cp-body">
        {!p ? (
          <div className="cp-empty">select a competitor</div>
        ) : activeCard ? (() => {
          /* The feed card carries the headline and one-line so-what; the full "what
             happened" prose and the sourced facts live in data.details[id] (same object
             the Overview drawer renders). Merge so the article view shows real body. */
          const det = { ...activeCard, ...((data.details && data.details[activeCard.id]) || {}) };
          return (
          <div className="cp-sec">
            <button type="button" className="cp-back-btn" onClick={() => setActiveCard(null)}>
              ← Back to profile
            </button>
            <div className="cp-article-meta">
              <span className={`cp-tag dir-${det.dir || "watch"}`}>
                {DIR_WORD[det.dir] || "Signal"}
              </span>
              {det.ago ? <span className="cp-note">{det.ago}</span> : null}
            </div>
            <h2 className="cp-article-title" dangerouslySetInnerHTML={{ __html: det.title }} />
            {det.what ? (
              <div className="cp-prose" style={{ marginTop: "14px" }} dangerouslySetInnerHTML={{ __html: det.what }} />
            ) : det.sowhat ? (
              <div className="cp-prose" style={{ marginTop: "14px" }} dangerouslySetInnerHTML={{ __html: det.sowhat }} />
            ) : null}
            {det.facts && det.facts.length ? (
              <div className="cp-meta-rows" style={{ marginTop: "18px" }}>
                {det.facts.map((f, i) => (
                  <div className="cp-fact-row" key={`${f[0]}-${i}`}>
                    <span className="cp-fact-k">{f[0]}</span>
                    <span className="cp-fact-v" dangerouslySetInnerHTML={{ __html: f[1] }} />
                  </div>
                ))}
              </div>
            ) : null}
            {(() => {
              const html =
                srcChips(det.srcs) ||
                srcChips(det.url ? [{ label: "", url: det.url }] : null);
              return html ? (
                <div style={{ marginTop: "18px" }}>
                  <span className="eyebrow" style={{ display: "block", marginBottom: "8px", color: "var(--d-txt-3)" }}>
                    Raw source
                  </span>
                  <span dangerouslySetInnerHTML={{ __html: html }} />
                </div>
              ) : (
                <div className="cp-thin" style={{ marginTop: "18px", fontSize: "12px" }}>
                  No source link captured for this item.
                </div>
              );
            })()}
          </div>
          );
        })() : (
          <>
            <div className="cp-head">
              <div className="cp-name">{displayName}</div>
              <div className="cp-ident">
                {p.sector ? <span>{p.sector}</span> : null}
                {p.hq ? <span>{p.hq}</span> : null}
                {THREAT_WORD[p.threat] ? <span className={`cp-threat ${p.threat}`}>{THREAT_WORD[p.threat]}</span> : null}
                {p.site ? (
                  <a className="ovt-link" href={p.site} rel="noopener noreferrer" target="_blank">
                    {p.site.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗
                  </a>
                ) : null}
              </div>
              {p.threatNote && !THREAT_WORD[p.threat] ? <div className="cp-note">{p.threatNote}</div> : null}
            </div>

            {p.assess ? (
              <Sec title="Assessment">
                <div className="cp-prose" dangerouslySetInnerHTML={{ __html: p.assess }} />
              </Sec>
            ) : null}

            {p.products.length ? (
              <Sec note={`${p.products.length} stated by the company or its sources · click to open specs`} title="Products">
                <div className="cp-chips">
                  {p.products.map((n, i) => {
                    const name = typeof n === "string" ? n : n.name || n.n || "";
                    return (
                      <span
                        className="cp-chip cp-chip-btn"
                        key={`${name}-${i}`}
                        role="button"
                        tabIndex={0}
                        onClick={() => openProduct(name)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            openProduct(name);
                          }
                        }}
                      >
                        {name}
                      </span>
                    );
                  })}
                </div>
              </Sec>
            ) : null}

            {p.matchups.length ? (
              <Sec
                note={`${p.matchups.length} spec comparison(s) against ${data.client?.short || "KSSL"}`}
                title="Product detail"
              >
                {p.matchups.map((m) => (
                  <div className="cp-row" key={m.id}>
                    <div className="cp-row-h">
                      <span className="cp-row-t">{m.comp}</span>
                      <span className="cp-tag">{m.cat}</span>
                      {m.country ? <span className="cp-tag">{m.country}</span> : null}
                    </div>
                    {m.reason ? <div className="cp-row-x" dangerouslySetInnerHTML={{ __html: m.reason }} /> : null}
                  </div>
                ))}
              </Sec>
            ) : null}

            {p.development.length ? (
              <Sec note="what this company is building, from tracked technology signals" title="In development">
                {p.development.map((iv, i) => (
                  <div className="cp-row" key={`${iv.t}-${i}`}>
                    <div className="cp-row-h">
                      <span className="cp-row-t">{iv.t}</span>
                      {iv.domain ? <span className="cp-tag">{iv.domain}</span> : null}
                      {iv.mat ? <span className="cp-tag">{iv.mat}</span> : null}
                    </div>
                    {iv.body ? <div className="cp-row-x">{iv.body}</div> : null}
                  </div>
                ))}
              </Sec>
            ) : null}

            {/* NEWS — real signal cards; click a row to open the full article + raw source */}
            {p.cards.length ? (
              <Sec note={`${p.cards.length} signal(s) naming this company`} title="News">
                {p.cards.map((c) => (
                  <div
                    className="cp-row cp-row-click"
                    key={c.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setActiveCard(c)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setActiveCard(c);
                      }
                    }}
                    style={{ cursor: "pointer" }}
                  >
                    <div className="cp-row-h">
                      <span className="cp-row-t" dangerouslySetInnerHTML={{ __html: c.title }} />
                      <span className={`cp-tag dir-${c.dir}`}>{DIR_WORD[c.dir] || "Signal"}</span>
                      {c.ago ? <span className="cp-tag">{c.ago}</span> : null}
                    </div>
                    {c.sowhat ? <div className="cp-row-x">{plainText(c.sowhat)}</div> : null}
                  </div>
                ))}
              </Sec>
            ) : null}

            {p.partners.length ? (
              <Sec note={`${p.partners.length} relationship(s) on file`} title="Partnerships">
                {p.partners.map((t, i) => (
                  <div className="cp-row" key={`${t.id || t.label}-${i}`}>
                    <div className="cp-row-h">
                      <span className="cp-row-t">{t.label}</span>
                      {t.ptype || t.rel ? <span className="cp-tag">{t.ptype || t.rel}</span> : null}
                      {t.country ? <span className="cp-tag">{t.country}</span> : null}
                    </div>
                    {t.note ? <div className="cp-row-x">{t.note}</div> : null}
                  </div>
                ))}
              </Sec>
            ) : null}

            {p.presence.length ? (
              <Sec
                note="product presence by country — what the company offers or has delivered there"
                title="Country presence"
              >
                {p.presence.map((r, i) => (
                  <div className="cp-row" key={`${r.country}-${r.name}-${i}`}>
                    <div className="cp-row-h">
                      <span className="cp-row-t">{r.name}</span>
                      <span className="cp-tag">{r.country}</span>
                      {r.stage ? <span className="cp-tag">{r.stage}</span> : null}
                      {r.qty ? <span className="cp-tag">{r.qty}</span> : null}
                    </div>
                    {r.note ? <div className="cp-row-x">{r.note}</div> : null}
                  </div>
                ))}
              </Sec>
            ) : null}

            {/* LEADERSHIP — harvested rows; each carries its source + the sentence it was read from */}
            {p.leadership.length ? (
              <Sec note="named on the company's own pages or sourced press" title="Leadership">
                {p.leadership.map((r, i) => (
                  <div className="cp-row" key={`${r.value}-${i}`}>
                    <div className="cp-row-h">
                      <span className="cp-row-t">{r.value}</span>
                      {r.detail ? <span className="cp-tag">{r.detail}</span> : null}
                      {r.url ? (
                        <a className="ovt-link" href={r.url} target="_blank" rel="noopener noreferrer">source ↗</a>
                      ) : null}
                    </div>
                    {r.line ? <div className="cp-row-x">{r.line}</div> : null}
                  </div>
                ))}
              </Sec>
            ) : null}

            {p.facilities.length ? (
              <Sec note="plants and sites the company names itself" title="Facilities">
                {p.facilities.map((fac, i) => (
                  <div className="cp-row" key={`${fac.value}-${i}`}>
                    <div className="cp-row-h">
                      <span className="cp-row-t">{fac.value}</span>
                      {fac.detail ? <span className="cp-tag">{fac.detail}</span> : null}
                      {fac.url ? (
                        <a className="ovt-link" href={fac.url} target="_blank" rel="noopener noreferrer">source ↗</a>
                      ) : null}
                    </div>
                    {fac.line ? <div className="cp-row-x">{fac.line}</div> : null}
                  </div>
                ))}
              </Sec>
            ) : null}

            {p.patents.length ? (
              <Sec note={`${p.patents.length} filing(s) attributed to this company`} title="Patents">
                {p.patents.map((r, i) => (
                  <div className="cp-row" key={`${r.id || r.title}-${i}`}>
                    <div className="cp-row-h">
                      <span className="cp-row-t">{r.title}</span>
                      {r.number ? <span className="cp-tag">{r.number}</span> : null}
                    </div>
                  </div>
                ))}
              </Sec>
            ) : null}

            {p.sources.length ? (
              <Sec note={`${p.sources.length} document(s) behind this profile`} title="Sources">
                <span dangerouslySetInnerHTML={{ __html: srcChips(p.sources) || "" }} />
              </Sec>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
