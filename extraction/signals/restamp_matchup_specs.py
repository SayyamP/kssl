# -*- coding: utf-8 -*-
"""Put KSSL's own published specifications onto the pairings that are already served.

    python restamp_matchup_specs.py                # dry run: every row, every change
    python restamp_matchup_specs.py --id 20102     # one pairing, in full
    python restamp_matchup_specs.py --apply

WHY THIS EXISTS SEPARATELY FROM revive_matchups.py
--------------------------------------------------
revive_matchups builds the pairings and now calls spec_join, so a full rebuild carries
the client's figures. A full rebuild needs the corpus and takes hours; the rows on
screen keep the old shape until it runs. This pass corrects only the spec list, from
serving.client_product, and is the same trade spec_direction.py already makes for `hi`.

WHAT IT WRITES, AND WHAT IT WILL NOT
------------------------------------
  * `specs`, `edge` and `verdict` on serving.matchup, and nothing else. edge and
    verdict go through revive_matchups' own edge_of / verdict_of -- never a second copy
    of the formula, because a stored edge left beside a changed spec list is the "one
    number, two definitions" fault this project has already paid for.
  * A row's existing values are never replaced, only gaps filled and fields appended;
    spec_join.join is where that rule lives and this script does not have its own.
  * A rival value is never invented. A KSSL figure with nothing to compare against is
    written with cv/cn None and `noCounterpart` true, so it is shown and not scored.

THE FOUR REFUSALS
-----------------
  1. WITHHELD ROWS ARE NOT TOUCHED, at all. withhold_matchups.py has decided that ten
     pairings publish nothing and that Shell forgings / Sniper / two carbine rows are
     not like-for-like. Adding specs to a withheld row cannot un-withhold it -- the
     column is separate -- but the honest thing is not to rewrite a row we have already
     decided not to publish, and the count is printed so the decision stays visible.
  2. ONE WRITER'S ID RANGE. enrich_serving.py owns serving.matchup below 20000 and
     revive_matchups.py owns 20000+. verdict_of is REVIVE's definition of that sentence;
     applying it to a card-derived row would overwrite another writer's text.
  3. A ROW MAY NEVER LOSE A SPEC. This pass only adds and fills. If any row would come
     out shorter than it went in, the whole run stops before writing anything.
  4. A REWRITE THAT GAINS NOTHING IS NOT APPLIED. If rows would change but not one
     value is added or filled, that is a bug in the join, not a migration, and it stops.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import client_portfolio                                           # noqa: E402
import revive_matchups                                            # noqa: E402
import spec_join                                                  # noqa: E402

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _specs(raw):
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw or "[]") or []
    except Exception:                                             # noqa: BLE001
        return []


def plan(cur):
    """-> (changes, skipped_withheld, total). Reads only; decides nothing about writing."""
    prows = client_portfolio.load_db(cur)
    if not prows:
        raise SystemExit("serving.client_product is empty -- run client_portfolio.py "
                         "--apply first. A join with nothing on one side is not a "
                         "migration, it is a no-op that looks like one.")
    cur.execute("""SELECT matchup_id, cat, comp, "compBy", bf, "bfBy", "catKey",
                          anchor, specs, withheld_reason
                     FROM serving.matchup
                    WHERE origin='pipeline' AND matchup_id >= %s
                    ORDER BY matchup_id""", (revive_matchups.MATCHUP_ID0,))
    rows = cur.fetchall()
    changes, withheld = [], []
    for (mid, cat, comp, compby, bf, bfby, catkey, anchor, raw, wr) in rows:
        specs = _specs(raw)
        if wr:
            withheld.append((mid, anchor, comp, wr))
            continue
        fit = client_portfolio.match(bf, catkey, specs, prows)
        if not isinstance(fit, client_portfolio.Fit):
            continue
        if len(fit.rows) != 1:
            # A grouped alias (Shell forgings is four workbook rows) has no single
            # product's figure to state; the consensus path in client_portfolio already
            # covers the labels the archive named, and nothing is guessed for the rest.
            continue
        new, rep = spec_join.join(specs, fit.rows[0], bore_differs=bool(fit.bore))
        if not (rep["added"] or rep["filled"]) and _same(specs, new):
            continue
        shown = spec_join.scored(new)
        edge = revive_matchups.edge_of(shown)
        verdict = revive_matchups.verdict_of(shown, compby or comp, bfby or bf)
        changes.append({"id": mid, "cat": cat, "anchor": anchor, "comp": comp,
                        "product": fit.rows[0]["name"], "before": specs, "after": new,
                        "edge": edge, "verdict": verdict, "rep": rep})
    return changes, withheld, len(rows)


def _same(a, b):
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True,
                                                                    default=str)


def report(changes, withheld, total, verbose_id=None):
    added = sum(c["rep"]["added"] for c in changes)
    filled = sum(c["rep"]["filled"] for c in changes)
    bore = sum(c["rep"]["bore_refused"] for c in changes)
    print("%d revived pairing(s) in serving.matchup (>= %d)"
          % (total, revive_matchups.MATCHUP_ID0))
    print("  withheld, not touched   %3d" % len(withheld))
    print("  restamped               %3d" % len(changes))
    print("  KSSL value(s) appended  %3d  (shown, no rival counterpart, not scored)" % added)
    print("  KSSL value(s) filled    %3d  (a field that had a rival value and no KSSL one)"
          % filled)
    print("  refused, bore differs   %3d" % bore)
    print()
    for c in sorted(changes, key=lambda c: -c["rep"]["added"])[:40]:
        print("  %-6s %-22s vs %-34s %2d -> %2d spec(s)  [%s]"
              % (c["id"], str(c["anchor"])[:22], str(c["comp"])[:34],
                 len(c["before"]), len(c["after"]), c["product"][:28]))
    if withheld:
        print("\n  withheld pairings left exactly as they are:")
        for mid, anchor, comp, wr in withheld:
            print("    %-6s %-22s vs %-34s %s" % (mid, str(anchor)[:22],
                                                  str(comp)[:34], wr))
    if verbose_id is not None:
        for c in changes:
            if c["id"] != verbose_id:
                continue
            print("\n  matchup %s -- %s vs %s" % (c["id"], c["anchor"], c["comp"]))
            for s in c["after"]:
                mark = ("  (KSSL only, not scored)" if s.get("noCounterpart")
                        else "  (bore differs: shown, not scored)"
                        if s.get("boreUnscored") else "")
                print("    %-24s KSSL %-46s rival %s%s"
                      % (str(s.get("k"))[:24], str(s.get("kv"))[:46],
                         str(s.get("cv")), mark))
            print("    edge %s" % c["edge"])
    if spec_join.UNKNOWN:
        print("\n  field labels spec_join.FIELDS has never seen (kept under their own "
              "name, not merged, %d):" % sum(spec_join.UNKNOWN.values()))
        for lab, n in spec_join.UNKNOWN.most_common(25):
            print("    %4d  %s" % (n, lab))
    if spec_join.REFUSALS:
        print("\n  refusals:")
        for why, n in spec_join.REFUSALS.most_common():
            print("    %4d  %s" % (n, why))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--id", type=int, help="print one pairing's new spec list in full")
    a = ap.parse_args()
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    cur.execute("SET lock_timeout = '20s'")   # the two-hourly pass writes this table

    changes, withheld, total = plan(cur)
    report(changes, withheld, total, verbose_id=a.id)

    # -- the refusals, checked before a single UPDATE is issued -------------------
    shrunk = [c for c in changes if len(c["after"]) < len(c["before"])]
    if shrunk:
        raise SystemExit("refusing: %d row(s) would LOSE a spec (%s). This pass only "
                         "adds and fills; a shorter list means the join dropped "
                         "something."
                         % (len(shrunk), ", ".join(str(c["id"]) for c in shrunk[:8])))
    gained = sum(c["rep"]["added"] + c["rep"]["filled"] for c in changes)
    if changes and not gained:
        raise SystemExit("refusing: %d row(s) would be rewritten and not one value is "
                         "added or filled. That is a bug in the join, not a migration."
                         % len(changes))

    if not a.apply:
        print("\ndry run -- nothing written. --apply to restamp.")
        con.close()
        return 0
    if not changes:
        print("\nnothing to restamp")
        con.close()
        return 0
    for c in changes:
        cur.execute("""UPDATE serving.matchup
                          SET specs=%s, edge=%s, verdict=%s, updated_at=now()
                        WHERE matchup_id=%s AND origin='pipeline'
                          AND matchup_id >= %s AND withheld_reason IS NULL""",
                    (json.dumps(c["after"], default=str), c["edge"], c["verdict"],
                     c["id"], revive_matchups.MATCHUP_ID0))
    con.commit()
    print("\napplied: %d pairing(s) restamped, %d KSSL value(s) now on the panel"
          % (len(changes), gained))
    con.close()
    return 0


def _demo():
    """Hermetic: the guards, with no database anywhere near them."""
    ok = [0]

    def ck(name, cond):
        print("  %-58s %s" % (name, "ok" if cond else "FAIL"))
        if not cond:
            ok[0] += 1

    prow = {"name": "CQB Carbine - F90", "catKey": "sa",
            "sources": ["https://www.kssl.in/small-arms"],
            "specs": [{"k": "Weight, carbine only", "v": "3.15 kg", "ctx": None},
                      {"k": "Magazine capacity", "v": "30 rounds", "ctx": None}]}
    before = [{"l": "Calibre", "cv": "7.62x39mm", "cn": 7.62, "kv": "5.56 mm",
               "kn": None, "u": "mm", "hi": None}]
    after, rep = spec_join.join(before, prow)
    ck("the pass only ever grows a spec list", len(after) >= len(before))
    ck("...and it grew this one", rep["added"] == 2)
    ck("the rival's own value is carried through untouched",
       after[0]["cv"] == "7.62x39mm" and after[0]["cn"] == 7.62)
    ck("edge is unchanged by values nobody can compare",
       revive_matchups.edge_of(spec_join.scored(after))
       == revive_matchups.edge_of(before))
    ck("_same() sees an unchanged list", _same(before, [dict(s) for s in before]))
    ck("_same() sees a changed one", not _same(before, after))
    # A pass that must be safe to re-run is a pass that has to notice it already ran:
    # the second call adds nothing and produces a byte-identical list, so `plan` skips
    # the row and the UPDATE is never issued.
    again, rep2 = spec_join.join(after, prow)
    ck("running it twice adds nothing the second time",
       rep2["added"] == 0 and rep2["filled"] == 0 and _same(after, again))
    print("all checks passed" if not ok[0] else "%d FAILED" % ok[0])
    return 1 if ok[0] else 0


if __name__ == "__main__":
    if "--demo" in sys.argv:
        sys.exit(_demo())
    sys.exit(main())
