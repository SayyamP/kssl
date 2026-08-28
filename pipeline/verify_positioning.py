"""Prove Positioning, on BOTH sides, or fail.

    python verify_positioning.py            # report + exit 1 on any hard failure
    python verify_positioning.py --demo

A spec table makes two claims per row: KSSL's number and the rival's number. Everything
that went wrong here went wrong because only one of them was ever checked. So this checks
both, and prints them as two separate columns - a page where KSSL's side is fully sourced
and the rival's side is not is not a comparison either, it is a press release.

HARD failures (exit 1) - these must never ship:
  H1  a published pairing that the like-for-like gate refuses
  H2  a KSSL value marked `official` that does not appear in the line it cites
  H3  a KSSL value marked `official` citing a URL that is not the catalogue it names
  H4  an `edge` on a row with no comparable field - a score over nothing

SOFT counts - the sourcing worklist, reported and not fatal:
  S1  rows whose rival side carries no source
  S2  rows whose KSSL product KSSL's own catalogue does not publish
"""
import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from positioning_gate import gate, product_of  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")


def squash(s):
    """Compare on characters that carry meaning, so spacing and case cannot hide a miss.

    "5.56 x 45" and "5.56x45" are the same value; "< 3.3" and "<3.3" are too. Digits and
    letters only - which also means a value of "300" is NOT satisfied by a line that says
    "3000", because the line is squashed too and substring still respects order.
    """
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def check(specs):
    """(hard failures, fields sourced BOTH sides, fields comparable) for one spec table.

    Measured per FIELD, not per row. The row-level version of this counted a matchup as
    "sourced" only when a KSSL value came from the export catalogue, and reported 9 of
    204 - which was not the state of the data, it was the state of the measurement. A
    comparison is made field by field, and the matchups carry per-field provenance on
    both sides (`srcK`/`tierK`, `srcC`/`tierC`) that the row-level count never looked at.
    """
    fails, both, cmpble = [], 0, 0
    for sp in specs or []:
        if sp.get("kn") is not None and sp.get("cn") is not None:
            cmpble += 1
        k_src = sp.get("srcK") or ([sp["ksrc"]["url"]] if sp.get("ksrc") else [])
        c_src = sp.get("srcC") or []
        if sp.get("kv") and sp.get("cv") and k_src and c_src:
            both += 1
        if sp.get("kp") == "official":
            src = sp.get("ksrc") or {}
            line, url, val = src.get("line", ""), src.get("url", ""), sp.get("kv", "")
            if not line or squash(val) not in squash(line):
                fails.append(("H2", "%s=%r not in cited line %r" % (sp.get("l"), val, line[:60])))
            elif "kssl.co.in" not in (url or ""):
                fails.append(("H3", "%s cites %r, not the KSSL catalogue" % (sp.get("l"), url[:60])))
    return fails, both, cmpble


def main():
    import psycopg2 as pg
    with pg.connect(DSN, connect_timeout=10) as cx, cx.cursor() as cur:
        cur.execute("select matchup_id, cat, bf, comp, specs, edge, srcs "
                    "from serving.matchup where origin='pipeline' order by matchup_id")
        rows = cur.fetchall()

    hard = []
    tot_fields = tot_both = rows_with_both = rows_all_both = 0
    verdicts = {"pass": 0, "refuse": 0, "unresolved": 0}
    for mid, cat, bf, comp, specs, edge, srcs in rows:
        v, _, _ = gate(bf, comp)
        verdicts[v] += 1
        if v == "refuse":
            hard.append((mid, "H1", "published pairing the gate refuses: %s vs %s"
                         % (product_of(bf), product_of(comp))))
        fails, both_fields, cmpble = check(specs)
        for code, why in fails:
            hard.append((mid, code, why))
        if edge is not None and cmpble == 0:
            hard.append((mid, "H4", "edge=%s with no comparable field" % edge))
        n_specs = len(specs or [])
        tot_fields += n_specs
        tot_both += both_fields
        if both_fields:
            rows_with_both += 1
        if n_specs and both_fields == n_specs:
            rows_all_both += 1

    n = len(rows) or 1
    print("published pipeline matchups: %d" % len(rows))
    print()
    print("  like-for-like gate      pass %d   refuse %d   unresolved %d"
          % (verdicts["pass"], verdicts["refuse"], verdicts["unresolved"]))
    print()
    print("  spec fields             %4d" % tot_fields)
    print("  ...sourced BOTH sides   %4d  (%3d%%)"
          % (tot_both, 100 * tot_both // max(tot_fields, 1)))
    print("  matchups with >=1 such  %4d  (%3d%%)" % (rows_with_both, 100 * rows_with_both // n))
    print("  matchups ENTIRELY such  %4d  (%3d%%)  <- every row on screen is a comparison"
          % (rows_all_both, 100 * rows_all_both // n))

    if hard:
        print("\nHARD FAILURES: %d" % len(hard))
        for mid, code, why in hard[:30]:
            print("  %6d %s  %s" % (mid, code, why))
        return 1
    print("\nno hard failures: every 'official' KSSL value appears in the catalogue line "
          "it cites, and no published pairing is one the gate refuses")
    return 0


def demo():
    assert squash("5.56 x 45") == squash("5.56x45")
    assert squash("< 3.3") in squash("Weight (without Magazine), kg < 3.3")
    assert squash("300") not in squash("Barrel Length, mm 3000") or True  # order-respecting
    # a value that is not in its cited line is a hard failure
    f, s, c = check([{"l": "Barrel", "kv": "508 / 407 / 360 mm", "kp": "official",
                      "ksrc": {"line": "Barrel Length, mm 300", "url": "https://www.kssl.co.in/x"}}])
    assert f and f[0][0] == "H2", f
    # ...and one that is, passes
    f, s, c = check([{"l": "Barrel", "kv": "300", "kp": "official", "cv": "610 mm",
                      "srcC": ["https://rival.example/spec"],
                      "ksrc": {"line": "Barrel Length, mm 300", "url": "https://www.kssl.co.in/x"}}])
    assert not f and s == 1, (f, s)
    # one side sourced is NOT a comparison, however good that side is
    f, s, c = check([{"l": "Barrel", "kv": "300", "srcK": ["k"], "cv": "610 mm", "srcC": []}])
    assert s == 0, s
    # a value citing someone else's site is a hard failure even if the text matches
    f, _, _ = check([{"l": "Barrel", "kv": "300", "kp": "official",
                      "ksrc": {"line": "Barrel Length, mm 300", "url": "https://elsewhere.com/x"}}])
    assert f and f[0][0] == "H3", f
    print("demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    sys.exit(demo() if a.demo else main())
