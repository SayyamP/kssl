import { useEffect, useState } from "react";
import MatchupList from "../../components/matchupList/MatchupList";
import MatchupDossier from "../../components/matchupDossier/MatchupDossier";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";

/* Positioning: every rating-matched KSSL-vs-rival pair, and the dossier for the one
   selected. Gap Analysis jumps in here with a matchup id, which arrives as `pending`. */
export default function Positioning() {
  const { data, gapModel } = useData();
  const { setScope, takePending, jumpTo } = useAppState();
  const [selected, setSelectedState] = useState(() => {
    try {
      return localStorage.getItem("kssl_pos_selected") || null;
    } catch (e) {
      return null;
    }
  });

  const setSelected = (val) => {
    setSelectedState(val);
    try {
      if (val) localStorage.setItem("kssl_pos_selected", val);
      else localStorage.removeItem("kssl_pos_selected");
    } catch (e) {}
  };

  const select = (id) => {
    if (!id) {
      setSelected(null);
      return;
    }
    const m = data.matchups[id];
    if (!m) return;
    setSelected(id);
    setScope("matchup", { type: "matchup", data: m }, {
      pillar: "Competitive",
      view: "Positioning",
      selection: `${m.comp} vs ${m.bf}`,
    });
  };

  // restore selection scope if selected is present on mount
  useEffect(() => {
    if (selected && data.matchups[selected]) {
      const m = data.matchups[selected];
      setScope("matchup", { type: "matchup", data: m }, {
        pillar: "Competitive",
        view: "Positioning",
        selection: `${m.comp} vs ${m.bf}`,
      });
    }
  }, [selected, data.matchups, setScope]);

  // a cross-pillar jump from Gap Analysis lands here with the matchup to open
  useEffect(() => {
    const p = takePending("positioning");
    if (p && p.matchupId) select(String(p.matchupId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takePending]);

  const m = selected ? data.matchups[selected] : null;

  return (
    <div className={`pos-view v-positioning ${m ? "has-sel" : "no-sel"}`}>
      <MatchupList data={data} onSelect={select} selected={selected} />
      {m ? (
        <MatchupDossier
          data={data}
          gapModel={gapModel}
          m={m}
          onClose={() => setSelected(null)}
          onJumpToTender={(title) => jumpTo("market", "tender", { tenderTitle: title })}
        />
      ) : (
        <div className="mu-dossier">
          <div className="mu-d-h">
            <span className="eyebrow">Category · class-matched pair</span>
            <div className="matchup">
              <div className="side comp">
                <div className="pn">Select a rival model</div>
              </div>
              <span className="vsbadge">VS</span>
              <div className="side bf">
                <div className="pn">{data.client?.short || "KSSL"} · —</div>
              </div>
            </div>
            <div style={{ marginTop: "11px", paddingTop: "11px", borderTop: "1px dashed var(--l-line-2)" }}>
              <span className="eyebrow" style={{ fontSize: "10px", color: "var(--l-txt-3)", display: "block", marginBottom: "6px", letterSpacing: ".08em", textTransform: "uppercase", fontWeight: "700" }}>
                PAIRING LOGIC
              </span>
              <div className="mu-match-reason" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
                Matched on spec class.
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
