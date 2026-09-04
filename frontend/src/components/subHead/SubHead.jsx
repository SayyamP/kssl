import { useEffect, useRef, useState } from "react";
import { useAppState, PILLAR_LABEL } from "../../state/AppState";
import { plainText, reportFilename, reportRecord, reportText, rowText } from "../../lib/report";

/* The view heading, its count line, and the three report actions.

   Copy Summary, Export JSON and Print Report all read ONE thing: the report the open
   view published through useHeaderReport (lib/report.js). They used to read
   overviewConfig[pillar].cards whatever the view, so on the Products page they copied,
   exported and printed overview signals -- FE 16 / FE 26 / FE 27 in the acceptance
   sheet. A view that has published nothing gets a truthful brief (heading, count, and
   a line saying so), never another view's content.

   Every action degrades out loud. The clipboard API is absent on a plain-http origin
   and can be refused by the browser; both used to throw inside the handler with the
   "copied" toast never shown, which reads as a dead button. Now the summary opens in a
   sheet the reader can copy from by hand, with a line saying why. */
const TOAST_MS = 2600;

function SummarySheet({ sheet, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.select();
  }, [sheet]);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="sheet-overlay" onClick={onClose} role="presentation">
      <div
        aria-label={sheet.title}
        className="sheet"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
      >
        <div className="sheet-h">
          <span className="eyebrow">{sheet.title}</span>
          <button className="subhead-btn" onClick={onClose} type="button">
            Close
          </button>
        </div>
        {sheet.note ? <div className="sheet-note">{sheet.note}</div> : null}
        <textarea className="sheet-text" readOnly ref={ref} spellCheck={false} value={sheet.text} />
      </div>
    </div>
  );
}

/* What the page prints: the same sections Copy Summary renders, as a sheet. On screen
   it is display:none; in print it is the only thing shown (chrome.css). */
function PrintSheet({ report, meta }) {
  const sections = ((report && report.sections) || []).filter((s) => s && (s.rows || []).length);
  return (
    <div aria-hidden="true" className="print-sheet">
      <div className="ps-brand">137Parallax</div>
      <h1>{plainText((report && report.title) || meta.title)}</h1>
      <div className="ps-meta">{`Pillar: ${meta.pillar} | Date: ${meta.date}`}</div>
      {meta.count ? <div className="ps-meta">{plainText(meta.count)}</div> : null}
      {report && report.subtitle ? <div className="ps-sub">{plainText(report.subtitle)}</div> : null}
      {sections.length ? (
        sections.map((s, i) => (
          <div className="ps-sec" key={`${s.h}-${i}`}>
            <h2>{plainText(s.h)}</h2>
            {s.rows.map((row, j) =>
              Array.isArray(row) ? (
                <div className="ps-row" key={j}>
                  <span className="ps-k">{plainText(row[0])}</span>
                  <span className="ps-v">{plainText(row[1])}</span>
                </div>
              ) : (
                <div className="ps-line" key={j}>
                  {rowText(row)}
                </div>
              ),
            )}
          </div>
        ))
      ) : (
        <div className="ps-line">This view publishes no summary. Nothing else is held for it here.</div>
      )}
    </div>
  );
}

export default function SubHead({ title, count }) {
  const { pillar, view, headerReport } = useAppState();
  const [toast, setToast] = useState(null);
  const [sheet, setSheet] = useState(null);
  const toastTimer = useRef(0);

  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const showToast = (msg, kind = "ok") => {
    clearTimeout(toastTimer.current);
    setToast({ msg, kind });
    toastTimer.current = setTimeout(() => setToast(null), TOAST_MS);
  };

  const meta = () => {
    const now = new Date();
    return {
      pillar: PILLAR_LABEL[pillar] || pillar,
      pillarKey: pillar,
      view,
      title,
      count,
      date: now.toLocaleDateString(),
      iso: now.toISOString(),
    };
  };

  const handleCopySummary = async () => {
    const m = meta();
    const text = reportText(headerReport, m);
    const lines = text.split("\n").length;
    const clip = typeof navigator !== "undefined" && navigator.clipboard;
    if (!clip || typeof clip.writeText !== "function") {
      setSheet({
        title: "Summary",
        note: "The clipboard is not available in this browser context (it needs HTTPS or localhost). The text is selected below: copy it by hand.",
        text,
      });
      return;
    }
    try {
      await clip.writeText(text);
      showToast(`Summary copied (${lines} lines)`);
    } catch (err) {
      setSheet({
        title: "Summary",
        note: `The browser refused clipboard access (${(err && err.name) || "error"}). The text is selected below: copy it by hand.`,
        text,
      });
    }
  };

  const handleExportJson = () => {
    const m = meta();
    const record = reportRecord(headerReport, m);
    const json = JSON.stringify(record, null, 2);
    const name = reportFilename(view, m.iso);
    try {
      if (typeof Blob === "undefined" || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
        throw new Error("no file download in this browser");
      }
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      const n = record.sections.reduce((t, s) => t + s.rows.length, 0);
      showToast(`Exported ${name} (${n} rows)`);
    } catch (err) {
      setSheet({
        title: "Export JSON",
        note: `This browser could not save ${name} (${(err && err.message) || "error"}). The JSON is selected below: copy it into a file by hand.`,
        text: json,
      });
    }
  };

  const handlePrint = () => {
    if (typeof window === "undefined" || typeof window.print !== "function") {
      showToast("Printing is not available in this browser", "warn");
      return;
    }
    window.print();
  };

  const published = !!(headerReport && (headerReport.sections || []).some((s) => s && (s.rows || []).length));

  return (
    <div className="subhead">
      <div className="left">
        <h1>{title}</h1>
        <span className="cnt">{count}</span>
        {toast && <span className={`subhead-toast${toast.kind === "warn" ? " warn" : ""}`}>{toast.msg}</span>}
      </div>

      <div className="subhead-actions">
        <button
          className="subhead-btn"
          onClick={handleCopySummary}
          title={published ? "Copy this view's summary as text" : "Copy the heading and count (this view publishes no summary)"}
          type="button"
        >
          Copy Summary
        </button>
        <button
          className="subhead-btn"
          onClick={handleExportJson}
          title={published ? "Save this view's data as JSON" : "Save the heading and count as JSON (this view publishes no summary)"}
          type="button"
        >
          Export JSON
        </button>
        <button
          className="subhead-btn primary"
          onClick={handlePrint}
          title="Print this view's report, or save it as PDF"
          type="button"
        >
          Print Report
        </button>
      </div>

      <PrintSheet meta={meta()} report={headerReport} />
      {sheet ? <SummarySheet onClose={() => setSheet(null)} sheet={sheet} /> : null}
    </div>
  );
}
