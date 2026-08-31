import { useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";

export default function SubHead({ title, count }) {
  const { pillar, view } = useAppState();
  const { data } = useData();
  const [toast, setToast] = useState(null);

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  };

  const handleCopySummary = () => {
    const timeStr = new Date().toLocaleDateString();
    let text = `137PARALLAX COMPETITIVE INTELLIGENCE BRIEF\n`;
    text += `Pillar: ${pillar.toUpperCase()} | View: ${title} | Date: ${timeStr}\n`;
    text += `Status: ${count}\n\n`;

    if (data.overviewConfig && data.overviewConfig[pillar]) {
      const cfg = data.overviewConfig[pillar];
      text += `--- TOP SIGNALS ---\n`;
      (cfg.cards || []).slice(0, 5).forEach((c, idx) => {
        text += `${idx + 1}. [${c.company || "MARKET"}] ${c.title}\n   So What: ${c.sowhat || "N/A"}\n\n`;
      });
    }

    navigator.clipboard.writeText(text);
    showToast("Executive Summary copied to clipboard");
  };

  const handleDownloadJson = () => {
    const exportData = {
      pillar,
      view,
      title,
      timestamp: new Date().toISOString(),
      count,
      dataSummary: {
        cards: data.overviewConfig?.[pillar]?.cards?.slice(0, 10) || [],
        tendersCount: data.tenders?.length || 0,
        competitorsCount: Object.keys(data.competitors || {}).length,
      },
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Parallax_Intel_Report_${pillar}_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast("Intelligence JSON downloaded");
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="subhead">
      <div className="left">
        <h1>{title}</h1>
        <span className="cnt">{count}</span>
        {toast && <span className="subhead-toast">{toast}</span>}
      </div>

      <div className="subhead-actions">
        <button
          className="subhead-btn"
          onClick={handleCopySummary}
          title="Copy Executive Summary to Clipboard"
        >
          Copy Summary
        </button>
        <button
          className="subhead-btn"
          onClick={handleDownloadJson}
          title="Download View JSON Data"
        >
          Export JSON
        </button>
        <button
          className="subhead-btn primary"
          onClick={handlePrint}
          title="Print / Save PDF Report"
        >
          Print Report
        </button>
      </div>
    </div>
  );
}

