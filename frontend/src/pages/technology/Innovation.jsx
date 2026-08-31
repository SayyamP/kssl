import { Fragment, useEffect, useRef, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import ScopeChat from "../../components/scopeChat/ScopeChat";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { techReportHtml } from "../../lib/reports";
import { gapCorrelateStrip } from "../../lib/gapModel";
import { srcChips, attr } from "../../lib/html";

/* Not every pipeline row carries an assessed position. `gap`, `horizon`, `whatsNew`
   and `compNote` are analyst fields, and the served record leaves them null when
   nobody assessed them — which is a different thing from a neutral verdict. Printing
   the raw field put the words UNDEFINED / null on screen, so every site that reads
   one is gated, and the headings that survive say "not assessed" out loud. */
const NOT_ASSESSED = "not assessed";
const has = (v) => v != null && String(v).trim() !== "";

/* maturity labels — one map, covering every `mat` value in the dataset
   (lab / dev / prod / fielded). 'prod' was once missing and rendered `undefined`. */
const MAT_LAB = {
  lab: "Lab / research",
  dev: "In development",
  prod: "In production",
  fielded: "Fielded / in service",
};

export default function Innovation() {
  const { data, gapModel } = useData();
  const { setScope, jumpTo } = useAppState();
  const clientName = (data.client && (data.client.short || data.client.name)) || "KSSL";

  const GAP_LAB = { behind: `${clientName} behind`, parity: `${clientName} at parity`, ahead: `${clientName} ahead` };
  const GAP_HEAD = {
    behind: `Why ${clientName} is behind`,
    parity: `Why ${clientName} is at parity`,
    ahead: `Why ${clientName} is ahead`,
  };
  const GAP_VERB = { behind: `${clientName} is BEHIND`, parity: `${clientName} is AT PARITY`, ahead: `${clientName} is AHEAD` };

  const getSavedInnov = () => {
    try {
      const s = localStorage.getItem("kssl_innov_state");
      return s ? JSON.parse(s) : {};
    } catch (e) { return {}; }
  };
  const savedInnov = getSavedInnov();

  const [cat, setCat] = useState(savedInnov.cat || (data.techCats && data.techCats[0] ? data.techCats[0].id : null));
  const [sel, setSel] = useState(savedInnov.sel !== undefined ? savedInnov.sel : null);
  const [report, setReport] = useState(null);
  const [generating, setGenerating] = useState(false);
  const detRef = useRef(null);

  useEffect(() => {
    if (detRef.current) {
      detRef.current.scrollTop = 0;
    }
  }, [sel, cat]);

  useEffect(() => {
    try {
      localStorage.setItem("kssl_innov_state", JSON.stringify({ cat, sel }));
    } catch (e) {}
  }, [cat, sel]);

  const list = data.innovations[cat] || [];
  const iv = sel !== null ? list[sel] : null;

  const select = (i) => {
    const item = list[i];
    if (!item) return;
    setSel(i);
    setReport(null);
    setScope("tech", { type: "tech", data: item }, {
      pillar: "Technology",
      view: "Innovation Pipeline",
      selection: item.t,
    });
  };

  const generate = () => {
    setGenerating(true);
    setTimeout(() => {
      setReport(techReportHtml(iv, data, cat));
      setGenerating(false);
    }, 600);
  };

  const catName = (data.techCats.find((c) => c.id === cat) || {}).name || "";

  const detailBody = () => {
    if (!iv) return "";
    const impactClean = (iv.impact || "").replace(/<b>\[Analysis\][^<]*<\/b>\s*/, "");
    const matLab = MAT_LAB[iv.mat] || iv.mat;
    const gapKnown = has(iv.gap) && GAP_VERB[iv.gap];
    const na = `<div class="body na">${NOT_ASSESSED} — not carried on this record</div>`;
    return (
      // LEAD: position verdict band — only where a position was actually assessed
      (gapKnown ? `<div class="tech-verdict-band ${iv.gap}">${GAP_VERB[iv.gap]}</div>` : "") +
      // LEAD: why it matters (the headline insight)
      (has(impactClean)
        ? `<div class="tech-d-sec lead"><span class="eyebrow accent">Why this matters to ${clientName}</span><div class="lead-body">${impactClean}</div></div>`
        : "") +
      // LEAD: why this position — the heading itself names the position, so it needs one
      (gapKnown && has(iv.compNote)
        ? `<div class="tech-d-sec lead"><span class="eyebrow accent">${GAP_HEAD[iv.gap]}</span><div class="body">${iv.compNote}</div></div>`
        : "") +
      // LEAD: what's new (the dated development)
      `<div class="tech-d-sec lead"><span class="eyebrow accent">What's new</span>${
        has(iv.whatsNew) ? `<div class="body">${iv.whatsNew}</div>` : na
      }</div>` +
      // recommended action deliberately omitted (editorial policy: no decision-influencing moves)
      // SUPPORTING: what it is
      (has(iv.body)
        ? `<div class="tech-d-sec"><span class="eyebrow">Background · what it is</span><div class="body">${iv.body}</div></div>`
        : "") +
      '<div class="tech-d-sec"><span class="eyebrow">Status</span>' +
      `<div class="tech-kv"><span class="k">Maturity</span><span class="v">${matLab}</span></div>` +
      `<div class="tech-kv"><span class="k">Driven by</span><span class="v${has(iv.driver) ? "" : " na"}">${has(iv.driver) ? iv.driver : "not stated"}</span></div>` +
      `<div class="tech-kv"><span class="k">Horizon</span><span class="v${has(iv.horizon) ? "" : " na"}">${has(iv.horizon) ? iv.horizon : "not stated"}</span></div>` +
      `<div class="tech-kv"><span class="k">${clientName} position</span><span class="v${gapKnown ? "" : " na"}">${gapKnown ? GAP_LAB[iv.gap] : NOT_ASSESSED}</span></div>` +
      '<div class="tech-kv"><span class="k">Sources</span><span class="v">' +
      (srcChips(iv.srcs && iv.srcs.length ? iv.srcs : iv.url ? [{ label: iv.sources || "Source", url: iv.url }] : null) ||
        attr(iv.sources || "—")) +
      "</span></div></div>" +
      gapCorrelateStrip(gapModel, "technology", iv.t)
    );
  };

  return (
    <div className="tech-view v-innovation">
      <div className="tech-cats" id="tech-cats">
        {data.techCats.map((c, i) => (
          <div
            className={`tech-cat${cat === c.id ? " active" : ""}`}
            key={c.id}
            onClick={() => setCat(c.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setCat(c.id);
              }
            }}
          >
            <span className="cc">{String(i + 1).padStart(2, "0")}</span>
            {c.name}
          </div>
        ))}
      </div>

      <div className={`tech-body ${iv ? "has-sel" : "no-sel"}`} id="tech-body">
        <div className="tech-list" id="tech-list">
          <div className="tech-list-h">
            <span className="eyebrow">
              {catName} · Innovations{" "}
              <span className="srcbadge" style={{ marginLeft: "6px" }}>
                Verified · analysed
              </span>
            </span>
            <span className="lh-note">
              {list.length} technological innovation{list.length !== 1 ? "s" : ""} tracked in this
              domain
            </span>
          </div>
          {list.map((item, i) => (
            <div
              className={`innov${sel === i ? " sel" : ""}`}
              key={`${item.t}-${i}`}
              onClick={() => select(i)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  select(i);
                }
              }}
            >
              <div className="ih">
                <span className="it">{item.t}</span>
                <span className={`mat ${item.mat}`}>{MAT_LAB[item.mat] || item.mat}</span>
              </div>
              <div
                className="ides"
                dangerouslySetInnerHTML={{ __html: (item.body || "").replace(/<\/?b>/g, "") }}
              />
              {/* built from the parts the record HAS — a null field used to leave its
                  separator behind, so the row read " ·  · " */}
              <div className="imeta">
                {[
                  has(item.driver) ? <span key="driver">{item.driver}</span> : null,
                  has(item.horizon) ? <span key="horizon">{item.horizon}</span> : null,
                  has(item.gap) && GAP_LAB[item.gap] ? (
                    <span className={`gappill ${item.gap}`} key="gap">
                      {GAP_LAB[item.gap]}
                    </span>
                  ) : null,
                ]
                  .filter(Boolean)
                  .map((el, n) => (
                    <Fragment key={el.key}>
                      {n ? <span className="sep">·</span> : null}
                      {el}
                    </Fragment>
                  ))}
              </div>
            </div>
          ))}
        </div>

        {/* No inline `display` — CSS owns show/hide via .tech-body.has-sel/.no-sel.
            An inline display:flex here overrode `.no-sel .tech-det{display:none}`, so
            with nothing selected the white detail pane stacked below the list in the
            single-column no-sel grid and ate the bottom half of the page. */}
        <div className="tech-det" id="tech-det" style={{ height: "100%", overflow: "hidden", flexDirection: "column" }}>
          <div id="tech-dossier-inner" style={{ display: "flex", flex: 1, flexDirection: "column", height: "100%", overflow: "hidden" }}>
            <div className="tech-dossier-scroll" ref={detRef} style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", paddingBottom: "24px" }}>
              <div className={`tech-d-h ${iv && iv.gap ? iv.gap : ""}`} id="tech-d-h">
                {iv ? (
                  <>
                    <button
                      aria-label="Close"
                      className="col-close"
                      onClick={() => setSel(null)}
                      title="Close"
                      type="button"
                    >
                      ✕
                    </button>
                    <span className="eyebrow">
                      Innovation Detail{" "}
                      <span className="srcbadge" style={{ marginLeft: "6px" }}>
                        Verified · analysed
                      </span>
                    </span>
                    <div className="ct">{iv.t}</div>
                    <div className="sub">
                      {[
                        MAT_LAB[iv.mat] || iv.mat,
                        has(iv.horizon) ? iv.horizon : null,
                        has(iv.gap) ? GAP_LAB[iv.gap] : null,
                      ]
                        .filter((p) => p != null && String(p).trim() !== "")
                        .map((p, n) => (
                          <Fragment key={p}>
                            {n ? <span className="sep">·</span> : null}
                            <span>{p}</span>
                          </Fragment>
                        ))}
                    </div>
                  </>
                ) : null}
              </div>
              <div id="tech-d-body">
                <HtmlBlock
                  handlers={{
                    "[data-tender]": (el) =>
                      jumpTo("market", "tender", { tenderTitle: el.getAttribute("data-tender") }),
                  }}
                  html={detailBody()}
                />
                {iv && !report ? (
                  <div className="tech-d-sec" style={{ borderBottom: "none" }}>
                    <button
                      className="tech-report-btn"
                      disabled={generating}
                      onClick={generate}
                      type="button"
                    >
                      {generating ? "Generating…" : "Generate detailed intelligence report"}
                    </button>
                    <div className="tech-report-hint">
                      Full CEO briefing · adds competitive landscape &amp; live market exposure across
                      pillars
                    </div>
                  </div>
                ) : null}
                {report ? (
                  <HtmlBlock
                    handlers={{ "[data-print]": () => window.print() }}
                    html={report}
                    id="tech-report-out"
                  />
                ) : null}
              </div>
            </div>
            <ScopeChat placeholder="Ask about this technology…" scopeKey="tech" />
          </div>
        </div>
      </div>
    </div>
  );
}
