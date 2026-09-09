import { useEffect, useMemo, useState } from "react";
import MatchupList from "../../components/matchupList/MatchupList";
import MatchupDossier from "../../components/matchupDossier/MatchupDossier";
import { useAppState, useHeaderReport, useCompetitiveState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";

/* Positioning: every rating-matched KSSL-vs-rival pair, and the dossier for the one
   selected. Gap Analysis jumps in here with a matchup id, which arrives as `pending`. */
export default function Positioning() {
  const { data, gapModel } = useData();
  const { setScope, takePending, jumpTo } = useAppState();
  const [selected, setSelectedState] = useCompetitiveState("positioning", "selected", null);

  const setSelected = (val) => {
    setSelectedState(val);
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

  /* What the header's Copy / Export / Print act on: the open matchup -- its verdict,
     every spec row as served, both advantage lists -- or, with nothing selected, the
     list of pairs that survived the comparability gate. */
  const clientShort = (data.client && data.client.short) || "KSSL";
  const report = useMemo(() => {
    if (m) {
      const val = (v) => (v == null || v === "" ? "—" : String(v));
      return {
        title: `${m.comp} vs ${m.bf}`,
        subtitle: `${m.cat || ""} · edge index ${m.edge == null ? "not measured" : `${m.edge}/100`}`,
        sections: [
          { h: "Verdict", rows: [m.verdict || "No verdict on file."] },
          {
            h: `Specifications (${m.compBy || "rival"} vs ${clientShort})`,
            rows: (m.specs || []).map((s) => [s.l, `${val(s.cv)} vs ${val(s.kv)}${s.u ? ` ${s.u}` : ""}`]),
          },
          { h: `${clientShort} advantages`, rows: m.advBf || [] },
          { h: "Competitor strengths", rows: m.advComp || [] },
          { h: "Pairing logic", rows: m.reason ? [m.reason] : [] },
        ],
        payload: {
          id: selected,
          category: m.cat || null,
          competitor: m.comp || null,
          competitorBy: m.compBy || null,
          client: m.bf || null,
          country: m.country || null,
          edge: m.edge == null ? null : m.edge,
          specs: m.specs || [],
          advantagesClient: m.advBf || [],
          advantagesCompetitor: m.advComp || [],
          verdict: m.verdict || null,
        },
      };
    }
    const all = Object.entries(data.matchups || {});
    return {
      title: "Positioning",
      subtitle: `${all.length} comparable pairs · none selected`,
      sections: [{ h: "Class-matched pairs", rows: all.map(([, x]) => [x.comp, `${x.bf} · ${x.cat}`]) }],
      payload: {
        pairs: all.map(([id, x]) => ({
          id,
          category: x.cat || null,
          competitor: x.comp || null,
          client: x.bf || null,
          edge: x.edge == null ? null : x.edge,
        })),
      },
    };
  }, [m, selected, data.matchups, clientShort]);
  useHeaderReport(report);

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
          /* The rival product's own page. `comp` is "Maker · Product"; Products resolves
             the company from the roster the same way the search bar does, and opens the
             named product once it is there. */
          onOpenProduct={(mu) =>
            jumpTo("competitive", "products", {
              company: mu.compBy || mu.comp,
              productName: String(mu.comp || "").split("·").pop().trim(),
            })
          }
        />
      ) : (
        <div className="mu-dossier">
          <div className="mu-d-h">
            <span className="eyebrow">Category · comparable pair</span>
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
                Paired because both sides publish the same measurables.
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
