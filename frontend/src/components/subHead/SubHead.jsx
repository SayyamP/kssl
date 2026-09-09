import { useEffect, useRef, useState } from "react";
import { useAppState, PILLAR_LABEL } from "../../state/AppState";
import { plainText, rowText } from "../../lib/report";

/* The view heading, its count line, and the print report action.
   Print Report reads the report the open view published through useHeaderReport (lib/report.js).
   A view that has published nothing gets a truthful brief (heading, count, and
   a line saying so), never another view's content. */
const TOAST_MS = 2600;

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

  const handlePrint = () => {
    if (typeof window === "undefined" || typeof window.print !== "function") {
      showToast("Printing is not available in this browser", "warn");
      return;
    }
    window.print();
  };

  return (
    <div className="subhead">
      <div className="left">
        <h1>{title}</h1>
        {count ? <span className="cnt">{count}</span> : null}
        {toast && <span className={`subhead-toast${toast.kind === "warn" ? " warn" : ""}`}>{toast.msg}</span>}
      </div>

      <div className="subhead-actions">
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
    </div>
  );
}
