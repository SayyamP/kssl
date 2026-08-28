"""The missing HALF of a comparison that is otherwise ready.

    python _halves.py
    python _halves.py --demo

Different from corroborate.json: those values were found once and need a second
publisher. These were never found at all -- but their PARTNER is already
published, so one page turns each into a measurable gap. Measured on the live
rows rather than the archive, so the list is what is actually blocking now.

Emits the same shape corroborate.json uses, so the same fetcher consumes it.
"""
import argparse
import collections
import io
import json
import sys
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import revive_matchups as R                                   # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build(cur):
    # what the archive claims, so the value can go into the search query
    cur.execute("""select comp, "compBy", bf, "bfBy", specs from serving.matchup
                    where origin='reference'""")
    claim = {}
    for comp, compby, bf, bfby, specs in cur.fetchall():
        for nm, mk, side in ((comp, compby, "c"), (bf, bfby, "k")):
            for s in specs or []:
                key = (R.product_of(nm), s.get("l"))
                if s.get(side + "v") and key not in claim:
                    claim[key] = (s.get(side + "v"), mk or "")

    cur.execute("""select comp, "compBy", bf, "bfBy", specs from serving.matchup
                    where origin='pipeline' and matchup_id >= 20000""")
    need = collections.Counter()
    for comp, compby, bf, bfby, specs in cur.fetchall():
        for s in specs or []:
            if s.get("hi") is None:
                continue                      # only a directional field makes a gap
            hc, hk = s.get("cn") is not None, s.get("kn") is not None
            if hc == hk:
                continue                      # both sides, or neither: not a HALF
            nm = bf if hc else comp           # the side that is missing
            need[(R.product_of(nm), s.get("l"))] += 1

    out = []
    for (p, lab), n in need.most_common():
        v, mk = claim.get((p, lab), (None, ""))
        if not v:
            continue
        out.append({"product": p, "maker": mk, "field": lab, "value": v,
                    "have": [], "rows": n})
    return out


def main():
    con = psycopg2.connect(R.DSN)
    out = build(con.cursor())
    con.close()
    io.open(HERE / "halves.json", "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print("%d missing half/halves, each with its partner already published\n" % len(out))
    for r in out[:24]:
        print("  %-22s %-15s %-20s unlocks %d row(s)"
              % (r["product"][:22], r["field"][:15], str(r["value"])[:20], r["rows"]))
    print("\nwrote halves.json")


def _demo():
    # a half is one side present and the other absent -- not both, not neither
    for hc, hk, is_half in ((True, False, True), (False, True, True),
                            (True, True, False), (False, False, False)):
        assert ((hc != hk) is is_half)
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main()
