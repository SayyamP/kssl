import { useEffect, useRef } from "react";
import AskBox from "../askBox/AskBox";
import { statementRows } from "../../lib/detail";
import { srcChips, attr } from "../../lib/html";
import { formatLabel } from "../../lib/profile";
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

  /* "At a glance" used to be four rows out of the pipeline — Company, Category, Date,
     Primary lens (serving_fill.py) — and this panel used to append Publisher and Stance.

     TASKS #16 removes three of them: Stance, Date and Publisher. None is lost to the
     reader — each is still on screen, in the place it belongs:

       Stance     the coloured pill in this panel's own header, and the dirtag on the
                  feed row. A word in a fact list restated what the colour already says.
       Date       the feed row's `ago`, from signalDate(), which is the one value the
                  card and this panel are guaranteed to agree on.
       Publisher  the source chips at the foot of the panel, which carry the link as
                  well as the host — a bare hostname was the same fact without the URL.

     So the list keeps only what nothing else shows. The rows that were missing (deal
     value, quantity, counterparty, programme, system, key person) are now written by
     serving_fill.py from the document's TYPED spans (glance.py), each with the sentence
     that proves it in f[2] -- the tooltip and the "sourced" mark below. They were not
     regexed out of prose here, because that would be manufacturing structure the
     extractor never asserted.

     Primary lens goes the same way as Stance: the pillar is the coloured pill in this
     header and the dirtag on the feed row (the client: "we already tagged it there, so
     no need of redundant info"). The writer no longer emits it; this filter also hides
     the row on every card stored before the change, and on the reference rows, which
     carry it too. */
  const DROPPED_FACTS = new Set(["stance", "date", "publisher", "primary lens"]);
  const facts = (detail.facts || []).filter(
    (f) => !DROPPED_FACTS.has(String(f[0]).trim().toLowerCase()),
  );
  const statements = statementRows(detail.lens);

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

        {/* The article's own lead image, resolved from its page markup by
            serving_fill.py and carried on the record. No placeholder when it is
            absent: a stock photo standing in for a story we could not illustrate
            is the same fabrication as an invented figure, just quieter. */}
        {detail.image ? (
          <div className="ctx-sec">
            <img
              alt=""
              src={detail.image}
              style={{ width: "100%", borderRadius: "6px", display: "block",
                       aspectRatio: "16 / 9", objectFit: "cover",
                       background: "var(--d-bg-1)" }}
            />
          </div>
        ) : null}

        <div className="ctx-sec">
          <span className="eyebrow">At a glance</span>
          <div className="cd-facts">
            {facts.map((f, i) => (
              <div
                className={`cd-frow${f[2] ? " sourced" : ""}`}
                key={`${f[0]}-${i}`}
                title={f[2] || undefined}
              >
                {/* The KEY is a label and wears the house capitalisation; the VALUE
                    is data and is never touched. These keys are written by the
                    pipeline ("Primary lens") and by Tenders.jsx ("Estimated value",
                    "Closing date"), and .cd-fk sets no text-transform, so whatever
                    a writer typed reached the screen -- sentence case sitting
                    beside Company, Category and Date. Doing it here fixes both
                    writers' labels, and every row already stored, at once. */}
                <span className="cd-fk">{formatLabel(f[0])}</span>
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

        {/* The statements the record already carried and nothing rendered: up to six
            propositions from the extraction layer, each shown WITH the article sentence
            that proves it. They are the article's own words, in the article's own
            language -- a signal off an Italian or Polish source reads in Italian or
            Polish here, and translating it would be putting words the publisher never
            wrote inside quotation marks. */}
        {!isTender && statements.length ? (
          <div className="ctx-sec">
            <span className="eyebrow">What the article says</span>
            <div className="cd-stmts">
              {statements.map((s, i) => (
                <div
                  className="cd-stmt"
                  dangerouslySetInnerHTML={{ __html: s }}
                  key={`stmt-${i}`}
                />
              ))}
            </div>
          </div>
        ) : null}

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
