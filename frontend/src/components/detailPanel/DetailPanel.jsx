import { useEffect, useRef } from "react";
import AskBox from "../askBox/AskBox";
import { srcChips, attr } from "../../lib/html";
import { useData } from "../../state/DataProvider";

const DIR_WORD = { threat: "Threat", watch: "Watch", fav: "Favourable" };

export default function DetailPanel({ detail, onClose }) {
  const { data } = useData();
  const panelRef = useRef(null);

  useEffect(() => {
    if (panelRef.current) {
      panelRef.current.scrollTop = 0;
    }
  }, [detail]);

  if (!detail) return null;
  const dir = detail.dir || "watch";
  const isTender = detail.kind === "tender";
  const srcHtml =
    srcChips(detail.srcs) ||
    srcChips(detail.url ? [{ label: "", url: detail.url }] : null);

  /* "At a glance" is four rows out of the pipeline — Company, Category, Date, Primary
     lens (serving_fill.py). Two more are already on the record and cost nothing:

       Publisher — the host the article came from
       Stance    — threat / watch / favourable, otherwise readable only as a colour

     The rows still missing (contract value, quantity, counterparty, programme) live
     inside the free-text ev_quote of extracted.proposition. Pulling them out with
     regexes HERE would be manufacturing structure from prose; they belong in
     serving_fill.py, emitted from the typed spans that already carry their quote. */
  const facts = (detail.facts || []).slice();
  const known = new Set(facts.map((f) => String(f[0]).toLowerCase()));
  let publisher = "";
  try {
    publisher = detail.url ? new URL(detail.url).hostname.replace(/^www\./, "") : "";
  } catch (e) {
    publisher = "";
  }
  if (publisher && !known.has("publisher")) facts.push(["Publisher", publisher]);
  if (!known.has("stance")) facts.push(["Stance", DIR_WORD[dir] || dir]);

  return (
    <div className="ctx v-overview revealed">
      <div className="ctx-scroll" ref={panelRef}>
        <div className={`ctx-h dir-${dir}`}>
          <div className="ctx-h-actions">
            <button aria-label="Close" className="col-close" onClick={onClose} title="Close" type="button">
              ✕
            </button>
            <span className={`dirpill dir-${dir}`}>{DIR_WORD[dir]}</span>
          </div>
          <span className="eyebrow">{detail.rank}</span>
          <div className="ct">
            <span dangerouslySetInnerHTML={{ __html: detail.title }} />
          </div>
        </div>

        <div className="ctx-sec">
          <span className="eyebrow">At a glance</span>
          <div className="cd-facts">
            {facts.map((f, i) => (
              <div
                className={`cd-frow${f[2] ? " sourced" : ""}`}
                key={`${f[0]}-${i}`}
                title={f[2] || undefined}
              >
                <span className="cd-fk">{f[0]}</span>
                <span className="cd-fv" dangerouslySetInnerHTML={{ __html: f[1] }} />
                {f[2] ? <span aria-hidden="true" className="cd-fq">❝</span> : null}
              </div>
            ))}
          </div>
        </div>

        {!isTender && (
          <div className="ctx-sec">
            <span className="eyebrow">What happened</span>
            <div className="cd-prose" dangerouslySetInnerHTML={{ __html: detail.what }} />
          </div>
        )}

        {isTender && detail.match && detail.match.length ? (
          <div className="ctx-sec">
            <span className="eyebrow">Matched {data.client?.short || "KSSL"} product</span>
            <div>
              {detail.match.map((m, i) => (
                <div className="cd-match" key={`${m.n}-${i}`}>
                  <div className="cm-h">
                    <span className="cm-n">{m.n}</span>
                    <span className={`cm-fit ${m.fit}`}>{m.pct} fit</span>
                  </div>
                  {(m.lines || []).map((l, j) => (
                    <div className="cm-line" key={`${l[1]}-${j}`}>
                      <span className={`cm-mk ${l[0]}`}>{l[0] === "up" ? "▲" : "▼"}</span>
                      <span dangerouslySetInnerHTML={{ __html: l[1] }} />
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {srcHtml ? (
          <div className="ctx-sec">
            <span className="eyebrow">Source</span>
            <div>
              <span dangerouslySetInnerHTML={{ __html: srcHtml }} />
              {detail.provenance ? (
                <div
                  className="cd-src-prov"
                  style={{
                    fontFamily: "var(--mono)",
                    fontSize: "9.5px",
                    color: "var(--l-txt-3)",
                    marginTop: "6px",
                  }}
                >
                  provenance · <span dangerouslySetInnerHTML={{ __html: attr(detail.provenance) }} />
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      <AskBox suggest={detail.suggest} />
    </div>
  );
}
