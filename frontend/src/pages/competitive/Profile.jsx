import { useEffect, useMemo, useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildProfile, rosterOf, NOT_COLLECTED } from "../../lib/profile";

/* The three sections harvested from the maker's own site, in the order an analyst reads
   a company: who runs it, where it builds, what it earns. */
const SOURCED = [
  ["leadership", "Leadership", "named on the company's own pages"],
  ["facilities", "Facilities", "plants and sites the company names itself"],
  ["sales", "Sales", "as published by the company"],
];
import { srcChips } from "../../lib/html";

/* One rival, everything the corpus holds on it.

   A section renders only when it has rows. The four things the corpus does not carry
   at all — leadership, facilities, sales, a forward timeline — are named at the foot
   of the profile rather than drawn as empty boxes, because an empty box under a
   heading claims a measurement that was never taken. */

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
  const { setScope } = useAppState();
  const [query, setQuery] = useState("");
  const roster = useMemo(() => rosterOf(data), [data]);
  const [cid, setCid] = useState(() => (roster[0] ? roster[0].cid : ""));

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
      view: "Company Profile",
      selection: p.name,
    });
  }, [p, setScope]);

  return (
    <div className="pos-view v-profile" style={{ gridTemplateColumns: "300px 1fr" }}>
      <div className="mu-list">
        <div className="mu-list-h">
          <span className="eyebrow">Companies</span>
          <div className="sub">{roster.length} rivals tracked</div>
          <div className="mu-search">
            <span className="si">⌕</span>
            <input
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search company…"
              type="text"
              value={query}
            />
          </div>
        </div>
        {list.map((r) => (
          <div
            className={`pg-comp${cid === r.cid ? " active" : ""}`}
            key={r.cid}
            onClick={() => setCid(r.cid)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setCid(r.cid);
              }
            }}
            role="button"
            tabIndex={0}
          >
            <div className="cn">
              <span className={`wdot ${r.threat === "high" ? "threat" : r.threat === "low" ? "fav" : "watch"}`} />
              {r.name}
            </div>
            <div className="cmeta">
              {r.sector ? (
                <>
                  <span>{r.sector}</span>
                  <span className="sep">·</span>
                </>
              ) : null}
              {/* "0" would read as a measurement; this is coverage, so say it as one */}
              <span className={r.filled ? "" : "cp-thin"}>
                {r.filled ? `${r.filled} of ${r.total} sections` : "nothing collected yet"}
              </span>
            </div>
          </div>
        ))}
        {!list.length ? <div className="cp-empty">no company matches “{query}”</div> : null}
      </div>

      <div className="cp-body">
        {!p ? (
          <div className="cp-empty">select a company</div>
        ) : (
          <>
            <div className="cp-head">
              <div className="cp-name">{p.name}</div>
              <div className="cp-ident">
                {[p.sector, p.hq].filter(Boolean).map((x, i) => (
                  <span key={`${x}-${i}`}>{x}</span>
                ))}
                {p.threat ? <span className={`cp-threat ${p.threat}`}>{p.threat} threat</span> : null}
                {p.site ? (
                  <a className="ovt-link" href={p.site} rel="noopener noreferrer" target="_blank">
                    {p.site.replace(/^https?:\/\/(www\.)?/, "")} ↗
                  </a>
                ) : null}
              </div>
              {p.threatNote ? <div className="cp-note">{p.threatNote}</div> : null}
            </div>

            {p.assess ? (
              <Sec title="Assessment">
                <div className="cp-prose" dangerouslySetInnerHTML={{ __html: p.assess }} />
              </Sec>
            ) : null}

            {p.products.length ? (
              <Sec note={`${p.products.length} stated by the company or its sources`} title="Products">
                <div className="cp-chips">
                  {p.products.map((n, i) => (
                    <span className="cp-chip" key={`${n}-${i}`}>
                      {typeof n === "string" ? n : n.name || n.n || ""}
                    </span>
                  ))}
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
                    <div className="cp-row-x" dangerouslySetInnerHTML={{ __html: m.reason || "" }} />
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
                      <span className="cp-tag">{iv.domain}</span>
                      {iv.mat ? <span className="cp-tag">{iv.mat}</span> : null}
                    </div>
                    <div className="cp-row-x">{iv.body}</div>
                  </div>
                ))}
              </Sec>
            ) : null}

            {p.cards.length ? (
              <Sec note={`${p.cards.length} signal(s) naming this company`} title="News">
                {p.cards.map((c) => (
                  <div className="cp-row" key={c.id}>
                    <div className="cp-row-h">
                      <span className="cp-row-t" dangerouslySetInnerHTML={{ __html: c.title }} />
                      <span className={`cp-tag dir-${c.dir}`}>{c.dir}</span>
                      <span className="cp-tag">{c.ago}</span>
                    </div>
                    <div className="cp-row-x" dangerouslySetInnerHTML={{ __html: c.sowhat }} />
                    {c.url ? (
                      <a className="ovt-link" href={c.url} rel="noopener noreferrer" target="_blank">
                        source ↗
                      </a>
                    ) : null}
                  </div>
                ))}
              </Sec>
            ) : null}

            {p.partners.length ? (
              <Sec note={`${p.partners.length} relationship(s) on file`} title="Partnerships">
                {p.partners.map((t, i) => (
                  <div className="cp-row" key={`${t.id}-${i}`}>
                    <div className="cp-row-h">
                      <span className="cp-row-t">{t.label}</span>
                      <span className="cp-tag">{t.ptype || t.rel}</span>
                      {t.country ? <span className="cp-tag">{t.country}</span> : null}
                    </div>
                    <div className="cp-row-x">{t.note}</div>
                  </div>
                ))}
              </Sec>
            ) : null}

            {p.presence.length ? (
              <Sec
                note="product presence by country — what the company offers or has delivered there. NOT a list of sites."
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

            {/* Leadership, Facilities and Sales, harvested from this company's OWN
                site. Each row carries the sentence it was read from — hover the ❝ — so
                a name or a figure on this page can always be checked against its source
                rather than trusted. */}
            {SOURCED.map(([key, title, note]) =>
              (p[key] || []).length ? (
                <Sec key={key} note={note} title={title}>
                  <div className="cp-src-list">
                    {p[key].map((r, i) => (
                      <a
                        className="cp-src-row"
                        href={r.url}
                        key={`${r.value}-${i}`}
                        rel="noopener noreferrer"
                        target="_blank"
                        title={r.line}
                      >
                        <span className="cp-src-v">{r.value}</span>
                        {r.detail ? <span className="cp-src-d">{r.detail}</span> : null}
                        <span aria-hidden="true" className="cp-src-q">❝</span>
                      </a>
                    ))}
                  </div>
                </Sec>
              ) : null,
            )}

            {/* What the corpus still does not hold FOR THIS COMPANY — stated per
                company, because a missing section and an empty one look identical, and
                a heading we filled for the rival next door reads as a finding here. */}
            {(() => {
              const missing = SOURCED.filter(([k]) => !(p[k] || []).length)
                .map(([k]) => [k, NOT_COLLECTED[k]])
                .concat([["timeline", NOT_COLLECTED.timeline]]);
              return missing.length ? (
                <div className="cp-gap">
                  <span className="eyebrow">Not collected</span>
                  {missing.map(([k, why]) => (
                    <div className="cp-gap-row" key={k}>
                      <span className="cp-gap-k">{k}</span>
                      <span className="cp-gap-v">{why}</span>
                    </div>
                  ))}
                </div>
              ) : null;
            })()}
          </>
        )}
      </div>
    </div>
  );
}
