import { useEffect, useMemo, useState } from "react";
import MatchupList from "../../components/matchupList/MatchupList";
import MatchupDossier from "../../components/matchupDossier/MatchupDossier";
import { useAppState, useHeaderReport } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { advantageText } from "../../lib/specs";

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
          /* Copy Summary is DISPLAY, so it follows the panel: the pipeline appends an
             inline <a class="adv-src"> to every advantage line and the Positioning tab
             no longer shows it. `payload` below is deliberately left raw -- that is the
             JSON export, and stripping provenance out of exported DATA would be a
             different decision from taking it off the screen. */
          { h: `${clientShort} advantages`, rows: (m.advBf || []).map(advantageText) },
          { h: "Competitor strengths", rows: (m.advComp || []).map(advantageText) },
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
    /* "N COMPARABLE PAIRS" COUNTED EVERY MATCHUP, and "Class-matched pairs" headed the
       same list -- both over rows the comparability gate rejects. A pair is comparable
       when at least one independent dimension is measured on BOTH sides (specDims,
       stored by wireDataset from computeSpecEdge); most rows here have none, and their
       client column reads "no published figure" from top to bottom. The two counts are
       stated separately now, and a row with no shared measurable says so rather than
       being filed under a heading that claims it has one. */
    const all = Object.entries(data.matchups || {});
    const comparable = all.filter(([, x]) => (x.specDims || 0) > 0);
    return {
      title: "Positioning",
      subtitle:
        `${all.length} pair${all.length === 1 ? "" : "s"} on file · ` +
        `${comparable.length} with a measurable published on both sides · none selected`,
      sections: [
        {
          h: "Pairs on file",
          rows: all.map(([, x]) => [
            x.comp,
            `${x.bf} · ${x.cat}${(x.specDims || 0) > 0 ? "" : " · no shared measurable"}`,
          ]),
        },
      ],
      payload: {
        pairs: all.map(([id, x]) => ({
          id,
          category: x.cat || null,
          competitor: x.comp || null,
          client: x.bf || null,
          edge: x.edge == null ? null : x.edge,
          comparableDimensions: x.specDims == null ? null : x.specDims,
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
            {/* not "comparable pair": nothing is selected, so nothing has been
                assessed as comparable. The word was a label on an empty slot. */}
            <span className="eyebrow">Category · pair</span>
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
              {/* "Paired because both sides publish the same measurables." was printed
                  with nothing selected, as if it were the rule the whole corpus obeys.
                  It is not: most pairs here have no dimension published on both sides
                  (specDims 0), so the sentence contradicted the very rows underneath
                  it. Each pair carries its own served pairing logic; this slot now says
                  where to read it instead of speaking for all of them. */}
              <div className="mu-match-reason" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
                Pairing logic is recorded per pair — select a rival model to read it.
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
