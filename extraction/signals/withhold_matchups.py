# -*- coding: utf-8 -*-
"""Stop showing a pairing that is not a comparison. Keep the product.

    python withhold_matchups.py            # dry run: what would be withheld, and why
    python withhold_matchups.py --apply
    python withhold_matchups.py --restore  # put every withheld row back

THE RULE, in the operator's words: "no need to delete a client's product -- instead if
no correct matchup is there, don't show it."

So nothing here touches a product, a catalogue or a competitor. It sets
serving.matchup.withheld_reason, which serving_live.matchup now excludes, and leaves the
row whole -- which is why `--restore` is one UPDATE and the reason travels with the row.

NOT origin. That column is CHECK-constrained to 'reference'/'pipeline', and it means
WHERE a row came from; "we decline to publish this" is a different fact about the same
row. See db/migrations/2026-09-06_matchup_withheld.sql.

TWO REASONS A PAIRING IS NOT A COMPARISON, and both are findings, not guesses:

  not_like_for_like  positioning_gate refuses it with a stated reason -- KSSL sells
                     EMPTY shell bodies (catalogue p37, "Only empties") and Excalibur is
                     a complete guided round; a 3 kg carbine against a tripod-mounted
                     machine gun; a rifle against a remote weapon station, which is a
                     mount. The gate's `unresolved` verdict is NOT withheld: it means a
                     keyword table has never heard of "MaxxPro", which is a gap in a word
                     list, not a finding about the products.

  nothing_published  every value on the KSSL side is placeholder prose -- "no published
                     figure", "specifications undisclosed". There is no number to set
                     beside the rival's, so the row is a rival's spec sheet wearing a
                     comparison's chrome. This is what made "Bayonet vs SkyStriker" read
                     as nonsense: the client column had nothing in it at all.

A row is withheld if EITHER holds. Everything else keeps publishing.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import positioning_gate                                       # noqa: E402

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
# a column, not an origin: serving.matchup's CHECK constraint allows only
# 'reference'/'pipeline', and origin means WHERE a row came from -- "we decline to
# publish this" is a different fact. See db/migrations/2026-09-06_matchup_withheld.sql
# placeholder prose the archive uses where a figure was never published
_NOFIG = re.compile(r"no published|undisclosed|not stated|not disclosed|n/?a\b|^-+$", re.I)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _specs(raw):
    try:
        return json.loads(raw or "[]") or []
    except Exception:                                          # noqa: BLE001
        return []


def nothing_published(specs):
    """True when the KSSL side carries no figure at all -- only placeholder prose.

    A row with NO spec entries is not judged here: it never claimed to compare.
    """
    vals = [str(s.get("kv") or "").strip() for s in specs]
    if not vals:
        return False
    return all((not v) or _NOFIG.search(v) for v in vals)


def classify(cur):
    cur.execute("""SELECT matchup_id, anchor, comp, cat, specs::text
                     FROM serving.matchup
                    WHERE origin = 'pipeline' AND withheld_reason IS NULL
                    ORDER BY matchup_id""")
    rows = cur.fetchall()
    keep, drop = [], []
    for mid, anchor, comp, cat, raw in rows:
        specs = _specs(raw)
        verdict, _caveat, why = positioning_gate.gate(anchor, comp)
        if verdict == "refuse":
            drop.append((mid, anchor, comp, "not_like_for_like", why))
        elif nothing_published(specs):
            drop.append((mid, anchor, comp, "nothing_published",
                         "every KSSL-side value is placeholder prose"))
        else:
            keep.append((mid, anchor, comp))
    return keep, drop, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    cur.execute("SET lock_timeout = '20s'")   # the two-hourly pass writes this table

    if a.restore:
        cur.execute("UPDATE serving.matchup SET withheld_reason=NULL "
                    "WHERE withheld_reason IS NOT NULL")
        print("restored %d withheld pairing(s)" % cur.rowcount)
        con.commit()
        return 0

    keep, drop, total = classify(cur)
    by_reason = {}
    for _mid, _a, _c, reason, why in drop:
        by_reason.setdefault(reason, []).append(why)
    print("%d served pairing(s)" % total)
    print("  keep     %3d  a comparison" % len(keep))
    print("  withhold %3d  not a comparison" % len(drop))
    for reason, whys in sorted(by_reason.items()):
        print("     %-18s %d" % (reason, len(whys)))
    print()
    for mid, anchor, comp, reason, why in drop:
        print("  %-6s %-18s vs %-42s %s" % (mid, anchor, comp[:42], reason))
        if reason == "not_like_for_like":
            print("           %s" % (why or "")[:96])

    if not a.apply:
        print("\ndry run -- nothing written. --apply to withhold, --restore to undo.")
        return 0

    ids = [mid for mid, _a, _c, _r, _w in drop]
    if not ids:
        print("nothing to withhold")
        return 0
    # REFUSE TO EMPTY THE TAB. If a rule change ever made this withhold everything, the
    # honest outcome is a loud stop, not a blank Positioning page.
    if len(ids) >= total:
        raise SystemExit("refusing: that would withhold every pairing (%d of %d)"
                         % (len(ids), total))
    for mid, _a, _c, reason, _w in drop:
        cur.execute("UPDATE serving.matchup SET withheld_reason=%s, updated_at=now() "
                    "WHERE matchup_id=%s AND origin='pipeline'", (reason, mid))
    n = len(ids)
    con.commit()
    cur.execute("SELECT count(*) FROM serving_live.matchup")
    print("\nwithheld %d pairing(s); %d still served" % (n, cur.fetchone()[0]))
    return 0


def _demo():
    ck = lambda n, ok: print("  %-58s %s" % (n, "ok" if ok else "FAIL")) or ok
    bad = 0
    bad += not ck("placeholder-only KSSL side is withheld",
                  nothing_published([{"kv": "no published figure"},
                                     {"kv": "specifications undisclosed"}]))
    bad += not ck("one real figure is enough to keep the row",
                  not nothing_published([{"kv": "no published figure"}, {"kv": "155"}]))
    bad += not ck("a row with no specs at all is not judged here",
                  not nothing_published([]))
    bad += not ck("an empty string counts as no figure",
                  nothing_published([{"kv": ""}, {"kv": "  "}]))
    print("all checks passed" if not bad else "%d FAILED" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    if "--demo" in sys.argv:
        sys.exit(_demo())
    sys.exit(main())
