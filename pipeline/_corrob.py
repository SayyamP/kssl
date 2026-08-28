"""What Positioning is one source short of.

    python _corrob.py            # the worklist
    python _corrob.py --demo

The reviver reports "N value(s) found but too weakly sourced to show". That is
not a missing value -- it is a value we located in exactly one place, held back
because one news page is not enough to put a number about a real weapon on
screen. Those rows need a SECOND INDEPENDENT DOMAIN, not another search for the
value itself, and that is a different fetch: aim at publishers we do not already
hold for this product.

Emits (product, maker, field, n_domains_now) so the fetcher can target them.
"""
import argparse
import collections
import io
import json
import re
import sys
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import revive_matchups as R                                   # noqa: E402
from source_tiers import domain as st_domain, publishable     # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DIRECTIONAL_ONLY = True     # a gap can only be measured on a directional field


def build(cur, directional=True):
    docs = R.load_docs(cur)
    cur.execute("""select comp, "compBy", bf, "bfBy", specs from serving.matchup
                    where origin='reference'""")
    rows = cur.fetchall()
    toks = set()
    for c, _cb, b, _bb, _sp in rows:
        for nm in (c, b):
            toks.update(R.designators(R.product_of(nm)))
            toks.update(p for p in re.split(r"[\s/,()·-]+", R.norm(R.product_of(nm))) if p)
    R.index_df(docs, toks)
    R.index_rivals(toks)

    need = {}          # (product, field) -> dict
    done = set()
    for comp, compby, bf, bfby, specs in rows:
        for nm, mk, side in ((comp, compby, "c"), (bf, bfby, "k")):
            p = R.product_of(nm)
            for s in specs or []:
                lab = s.get("l") or ""
                if directional and s.get("hi") is None:
                    continue
                key = (p, lab)
                if key in done:
                    continue
                v = s.get(side + "v")
                if not v:
                    continue
                done.add(key)
                hits = R.ground_value(docs, R.designators(p), v, s.get("u") or "",
                                      lab, name=p)
                ok, _why, _t, n = publishable([h[1] for h in hits], mk)
                if ok or not hits:
                    continue          # already publishable, or nothing found at all
                need[key] = {"product": p, "maker": mk or "", "field": lab,
                             "value": v, "have": sorted({st_domain(h[1]) for h in hits})}
    return sorted(need.values(), key=lambda x: (-len(x["have"]), x["product"]))


def main():
    con = psycopg2.connect(R.DSN)
    out = build(con.cursor())
    con.close()
    io.open(HERE / "corroborate.json", "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print("\n%d (product, field) value(s) found but ONE domain short\n" % len(out))
    for r in out[:30]:
        print("  %-22s %-14s %-18s have: %s"
              % (r["product"][:22], r["field"][:14], str(r["value"])[:18],
                 ", ".join(r["have"])[:44]))
    c = collections.Counter(r["field"] for r in out)
    print("\nby field:", dict(c))
    print("wrote corroborate.json")


def _demo():
    assert DIRECTIONAL_ONLY
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main()
