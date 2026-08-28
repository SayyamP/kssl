import { useEffect, useRef, useState } from "react";
import HtmlBlock from "../htmlBlock/HtmlBlock";
import ScopeChat from "../scopeChat/ScopeChat";
import { specPanelHtml, matchupGapHtml } from "../../lib/specs";
import { positioningReportHtml } from "../../lib/reports";
import { srcKvRow } from "../../lib/html";

const TABS = [
  ["adv", "Advantages"],
  ["specs", "Spec Comparison"],
  ["comp", "Competitor Detail"],
];

/* The right-hand dossier for one matchup: verdict, gap block, product identity,
   then three tabs. The CEO report is generated on demand into the third tab. */
export default function MatchupDossier({ m, data, gapModel, onClose, onJumpToTender }) {
  const [tab, setTab] = useState("adv");
  const [report, setReport] = useState(null);
  const [generating, setGenerating] = useState(false);
  const dossierRef = useRef(null);

  // a new matchup resets the panel to its default tab with no stale report and scrolls to top
  useEffect(() => {
    setTab("adv");
    setReport(null);
    setGenerating(false);
    if (dossierRef.current) {
      dossierRef.current.scrollTop = 0;
    }
  }, [m]);

  const prodRow = (m.specs || []).find((s) => s.l === "Product (sourced)") || {};
  const compDesc = prodRow.cv && prodRow.cv !== "—" ? prodRow.cv : "";
  const bfDesc = prodRow.kv && prodRow.kv !== "—" ? prodRow.kv : "";

  const generate = () => {
    setGenerating(true);
    setTimeout(() => {
      setReport(positioningReportHtml(m, data.tenders));
      setGenerating(false);
    }, 600);
  };

  return (
    <div className="mu-dossier" ref={dossierRef}>
      <div className="mu-d-h">
        <button aria-label="Close" className="col-close" onClick={onClose} title="Close" type="button">
          ✕
        </button>
        <span className="eyebrow">
          {m.cat}{" "}
          <span className="srcbadge" style={{ marginLeft: "6px" }}>
            {m.global ? "Verified specs · analysed" : "Verified · analysed"}
          </span>
        </span>
        <div className="matchup">
          <div className="side comp">
            <div className="lab">Competitor product</div>
            <div className="pn">{m.comp}</div>
            <div className="by">{m.compBy}</div>
          </div>
          <span className="vsbadge">VS</span>
          <div className="side bf">
            <div className="lab">{data.client?.short || "KSSL"} product</div>
            <div className="pn">{m.bf}</div>
            <div className="by">{m.bfBy}</div>
          </div>
        </div>
        <div className="mu-match-reason" dangerouslySetInnerHTML={{ __html: m.reason }} />
      </div>

      {/* verdict always visible */}
      <div className="mu-sec" style={{ background: "var(--l-bg-2)" }}>
        <div className="pos-takeaway">
          <span className="tl">{m.verdictH || "Positioning verdict"}</span>
          <span dangerouslySetInnerHTML={{ __html: m.verdict || "" }} />
        </div>
      </div>

      {/* gap block — this matchup's gap in cross-pillar context */}
      <HtmlBlock
        className="mu-sec"
        handlers={{
          "[data-tender]": (el) => onJumpToTender(el.getAttribute("data-tender")),
        }}
        html={matchupGapHtml(m, gapModel)}
      />

      {/* product profile: name + thin accent line + sourced descriptor */}
      <div className="mu-sec pp2-sec">
        <div className="pp2">
          <div className="pp2-col comp">
            <div className="pp2-name">{m.comp}</div>
            <div className="pp2-line comp" />
            {compDesc ? <div className="pp2-desc">{compDesc}</div> : null}
          </div>
          <div className="pp2-col bf">
            <div className="pp2-name">{m.bf}</div>
            <div className="pp2-line bf" />
            {bfDesc ? <div className="pp2-desc">{bfDesc}</div> : null}
          </div>
        </div>
      </div>

      <div className="mu-tabs">
        {TABS.map(([k, label]) => (
          <div
            className={`mu-tab${tab === k ? " on" : ""}`}
            key={k}
            onClick={() => setTab(k)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setTab(k);
              }
            }}
          >
            {label}
          </div>
        ))}
      </div>

      <div className={`mu-panel${tab === "adv" ? " on" : ""}`} data-panel="adv">
        <div className="mu-sec" style={{ padding: 0 }}>
          <div className="adv-grid">
            <div className="adv-col comp">
              <div className="ah">
                <span className="dot" />
                <span>Competitor advantages</span>
              </div>
              <div>
                {(m.advComp || []).length ? null : (
                  <div className="adv-empty">None recorded from the sources for this matchup.</div>
                )}
                {(m.advComp || []).map((a, i) => (
                  <div className="adv-item" key={i}>
                    <span className="mk">▲</span>
                    <span dangerouslySetInnerHTML={{ __html: a }} />
                  </div>
                ))}
              </div>
            </div>
            <div className="adv-col bf">
              <div className="ah">
                <span className="dot" />
                {data.client?.short || "KSSL"} advantages
              </div>
              <div>
                {(m.advBf || []).length ? null : (
                  <div className="adv-empty">None recorded from the sources for this matchup.</div>
                )}
                {(m.advBf || []).map((a, i) => (
                  <div className="adv-item" key={i}>
                    <span className="mk">▲</span>
                    <span dangerouslySetInnerHTML={{ __html: a }} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className={`mu-panel${tab === "specs" ? " on" : ""}`} data-panel="specs">
        <div className="mu-sec">
          <div className="spec-head">
            <span className="sh-comp">{m.comp}</span>
            <span className="sh-bf">{m.bf}</span>
          </div>
          <HtmlBlock html={specPanelHtml(m)} />
        </div>
      </div>

      <div className={`mu-panel${tab === "comp" ? " on" : ""}`} data-panel="comp">
        <div className="mu-sec">
          <span className="eyebrow">Competitor Detail</span>
          <HtmlBlock
            className="compdet"
            html={
              (m.det || [])
                .map((dd) => `<div class="kv"><span class="k">${dd[0]}</span><span class="v">${dd[1]}</span></div>`)
                .join("") + srcKvRow(m.srcs)
            }
          />
          {report ? null : (
            <>
              <button
                className="tech-report-btn"
                disabled={generating}
                onClick={generate}
                style={{ margin: "16px 0 0", width: "100%" }}
                type="button"
              >
                {generating ? "▤ Generating…" : "▤ Generate detailed intelligence report"}
              </button>
              <div className="tech-report-hint" style={{ margin: "7px 0 0" }}>
                CEO briefing · spec gap, competitive edge &amp; cross-pillar market exposure
              </div>
            </>
          )}
          {report ? (
            <HtmlBlock
              handlers={{ "[data-print]": () => window.print() }}
              html={report}
              id="pos-report-out"
            />
          ) : null}
        </div>
      </div>

      <ScopeChat placeholder="Ask about this matchup…" scopeKey="matchup" />
    </div>
  );
}
