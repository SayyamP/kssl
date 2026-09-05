import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import HtmlBlock from "../../components/htmlBlock/HtmlBlock";
import ScopeChat from "../../components/scopeChat/ScopeChat";
import { useAppState, useHeaderReport } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { techReportHtml } from "../../lib/reports";
import { gapCorrelateStrip } from "../../lib/gapModel";
import { srcChips, attr } from "../../lib/html";
import { MAT_LAB, NOT_ASSESSED, has, maturityLabel, positionPill, filterInnovations } from "../../lib/innovation";

/* Not every pipeline row carries an assessed position. `gap`, `horizon`, `whatsNew`
   and `compNote` are analyst fields, and the served record leaves them null when
   nobody assessed them — which is a different thing from a neutral verdict. Printing
   the raw field put the words UNDEFINED / null on screen, so every site that reads
   one is gated (lib/innovation.js, tested under node), and the headings that survive
   say "not assessed" out loud. */
/* one shared empty list, so a domain with no rows does not mint a new array per render
   (the header report is memoised on `list`) */
const EMPTY = [];

export default function Innovation() {
  const { data, gapModel } = useData();
  const { setScope, jumpTo, takePending, searchQuery } = useAppState();
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

  const list = useMemo(() => data.innovations[cat] || EMPTY, [data.innovations, cat]);
  const iv = sel !== null ? list[sel] : null;

  /* The rows on screen: the domain's list narrowed to the global search box, as the
     box's footer promises ("the open page is filtered to this query where it has a
     list"). Each keeps its ORIGINAL index -- selection is by index into `list`. */
  const shown = useMemo(() => filterInnovations(list, searchQuery), [list, searchQuery]);
  const filtering = String(searchQuery || "").trim() !== "";

  /* A domain the reader picks starts unselected. Carrying the index across kept
     "row 2" selected in a list the reader had not chosen it from, and the detail
     pane -- and the chat scope -- silently switched to a record nobody clicked. The
     search jump below sets the domain directly and then selects by title. */
  const pickCat = (id) => {
    setCat(id);
    setSel(null);
    setReport(null);
  };

  /* Opened from the global search: switch to the row's domain first, then select it by
     title once `list` is that domain's list. */
  const [pendingTitle, setPendingTitle] = useState(null);
  useEffect(() => {
    const p = takePending("innovation");
    if (p && p.title) {
      if (p.catId && data.innovations[p.catId]) setCat(p.catId);
      setPendingTitle(p.title);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takePending]);
  useEffect(() => {
    if (pendingTitle === null) return;
    const i = list.findIndex((x) => x && x.t === pendingTitle);
    if (i >= 0) select(i);
    setPendingTitle(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingTitle, list]);

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

  /* What the header's Copy / Export / Print act on: the open innovation with every
     field the record carries, or the domain's list when none is open. Fields the
     record leaves null are printed as "not stated" / "not assessed", never filled. */
  const headerReport = useMemo(() => {
    const matOf = (x) => MAT_LAB[x.mat] || x.mat || "not stated";
    if (iv) {
      return {
        title: iv.t,
        subtitle: `${catName} · ${matOf(iv)}`,
        sections: [
          {
            h: "Status",
            rows: [
              ["Maturity", matOf(iv)],
              ["Driven by", has(iv.driver) ? iv.driver : "not stated"],
              ["Horizon", has(iv.horizon) ? iv.horizon : "not stated"],
              [`${clientName} position`, has(iv.gap) && GAP_LAB[iv.gap] ? GAP_LAB[iv.gap] : NOT_ASSESSED],
            ],
          },
          has(iv.impact) ? { h: `Why this matters to ${clientName}`, rows: [iv.impact] } : null,
          has(iv.compNote) ? { h: "Competitive landscape", rows: [iv.compNote] } : null,
          has(iv.whatsNew) ? { h: "What's new", rows: [iv.whatsNew] } : null,
          has(iv.body) ? { h: "Background", rows: [iv.body] } : null,
          {
            h: "Sources",
            rows:
              iv.srcs && iv.srcs.length
                ? iv.srcs.map((s) => [s.label || "Source", s.url || ""])
                : iv.url
                  ? [["Source", iv.url]]
                  : has(iv.sources)
                    ? [iv.sources]
                    : [],
          },
        ].filter(Boolean),
        payload: { domain: catName, innovation: iv },
      };
    }
    return {
      title: `${catName} · Innovations`,
      subtitle: `${list.length} tracked in this domain · none selected`,
      sections: [
        {
          h: "Innovations",
          rows: list.map((x) => [x.t, [matOf(x), x.driver, x.horizon].filter(has).join(" · ")]),
        },
      ],
      payload: { domain: catName, innovations: list },
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [iv, list, catName, clientName]);
  useHeaderReport(headerReport);

  const detailBody = () => {
    if (!iv) return "";
    const impactClean = (iv.impact || "").replace(/<b>\[Analysis\][^<]*<\/b>\s*/, "");
    /* "not stated" for the rows that carry no maturity -- `MAT_LAB[mat] || mat`
       printed the word "null" for them (15 of 1,101 on production) */
    const matLab = maturityLabel(iv.mat);
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
      /* LEAD: what's new (the dated development).
         Rendered only when the row carries one. enrich_serving.py writes whatsNew as a
         literal NULL -- it is not extracted at all -- so this heading appeared above
         "not assessed" on all 1,101 served rows, which is what the report meant by
         "data is missing from the What's New section". A heading that is empty every
         single time is worse than no heading: it reads as a page that failed to load.

         Deliberately NOT synthesised from `body` or `impact`. Those are the background
         and the analyst read; neither is a dated development, and passing one off as
         one would be inventing the field rather than filling it. */
      (has(iv.whatsNew)
        ? `<div class="tech-d-sec lead"><span class="eyebrow accent">What's new</span><div class="body">${iv.whatsNew}</div></div>`
        : "") +
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
            onClick={() => pickCat(c.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                pickCat(c.id);
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
              {filtering
                ? `${shown.length} of ${list.length} match "${String(searchQuery).trim()}" · `
                : ""}
              {list.length} technological innovation{list.length !== 1 ? "s" : ""} tracked in this
              domain
            </span>
          </div>
          {filtering && list.length && !shown.length ? (
            <div className="empty-note" style={{ padding: "18px 0" }}>
              {`— no innovation in this domain matches "${String(searchQuery).trim()}" — clear the search box or pick another domain —`}
            </div>
          ) : null}
          {/* Stated ONCE for the domain, not per record. "What's new" -- the dated
              development behind an innovation -- is written as a literal NULL by
              enrich_serving.py, so it is absent on every served row. Printing "not
              assessed" 1,101 times reads as a page that failed to load, and printing
              nothing at all leaves a reader wondering whether the field exists. */}
          {list.length && !list.some((iv) => has(iv.whatsNew)) ? (
            <div className="lh-note" style={{ padding: "6px 0 2px", opacity: 0.75 }}>
              Dated developments are not assessed on these records — the extractor does
              not yet emit that field. Background, maturity and analyst impact below are.
            </div>
          ) : null}
          {shown.map(({ item, index: i }) => (
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
                {/* mat is null on 15 of 1,101 rows. The label rendered empty but .mat
                    still carries border:1px solid + padding, leaving a bare ~16x18px
                    rectangle beside the title -- the "small Box symbol" in the report. */}
                {has(item.mat) ? (
                  <span className={`mat ${item.mat}`}>{MAT_LAB[item.mat] || item.mat}</span>
                ) : null}
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
                    <div className="ctx-h-actions">
                      <button
                        aria-label="Close"
                        className="col-close"
                        onClick={() => setSel(null)}
                        title="Close"
                        type="button"
                      >
                        ✕
                      </button>
                      {/* The pill is a verdict, so a record with no assessed position
                          gets none. This read `gap === "behind" ? "GAP" : gap ===
                          "parity" ? "WATCH" : "AHEAD"`, and `gap` is null on every
                          served row: every innovation opened under a green AHEAD
                          that nobody had assessed, above a Status row saying
                          "not assessed". */}
                      {(() => {
                        const pill = positionPill(iv.gap);
                        return pill ? <span className={`dirpill ${pill.cls}`}>{pill.text}</span> : null;
                      })()}
                    </div>
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
