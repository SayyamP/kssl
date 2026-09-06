"""Mark the comparisons where the two products are not the same KIND of thing.

    python class_axis.py --dry
    python class_axis.py --apply
    python class_axis.py --demo

PORTED FROM pipeline/, which is not what the containers run (see
pipeline/_superseded.py; deploy/selfcheck.sh does `cd extraction/signals`). It sat
beside positioning_gate.py in a tree nothing executes, so a pass written to stop
"K9 Thunder 47 t vs ATAGS 18 t -- KSSL AHEAD 75/100" had never marked a served row.

Positioning reads "K9 Thunder 47 t vs ATAGS 18 t -- KSSL AHEAD 75/100". The K9 is
a tracked self-propelled howitzer and ATAGS is a towed gun; one carries its own
engine, hull and armour and the other is pulled behind a truck. The weight
difference is what those two things ARE, not an advantage either holds, and the
matchup reviver already refuses calibre and MTOW for exactly this reason -- 155 mm
against 105 mm is a class, not a lead.

The class is not asserted from a name. It is read from the documents: near a
mention of the product, does the corpus call it towed, self-propelled, tracked,
wheeled? A product the corpus never classifies stays unclassified, and an
unclassified pairing is left alone -- refusing a comparison needs evidence too.

Where the two sides are different classes, the mass dimensions are stamped
`classAxis` with the reason. Nothing is deleted: the number stays visible, it just
stops counting as a lead.

THIS IS A SECOND PASS, NOT A SECOND OPINION. positioning_gate refuses a pairing whose
two products are different KINDS by name; this one marks a DIMENSION as uninformative
where the corpus says the two platforms are differently mounted. They answer different
questions and both run.
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
from revive_matchups import (load_docs, norm, product_of,          # noqa: E402
                             mention_spans, designators, index_df, _wins,
                             edge_of, comparable)

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
NEAR = 40               # the classifying word has to be talking about THIS product
                        # ("the towed ATAGS", "ATAGS, a towed 155 mm gun"). At 220
                        # it picked up the OTHER gun in every comparison article:
                        # ATAGS came out 20 towed against 17 self-propelled.
MIN_HITS = 2            # said in more than one document
MAJORITY = 0.7          # and by this share of the documents that say anything
# Dimensions that measure the platform rather than the capability. Mass is the
# obvious one; a hull and an engine weigh what they weigh.
MASS_DIMS = {"weight", "combat weight", "mass", "gross weight"}
CLASSES = [
    ("self-propelled", re.compile(r"self-propelled|self propelled|\bsph\b")),
    ("tracked", re.compile(r"\btracked\b|\btrack-laying\b")),
    ("towed", re.compile(r"\btowed\b|\btowed gun\b|\btowed howitzer\b")),
    ("truck-mounted", re.compile(r"truck-mounted|truck mounted|mounted gun system")),
]
# Two classes that are really one platform family: a truck-mounted gun IS
# self-propelled, and a self-propelled gun may be tracked or wheeled. Only the
# towed/self-propelled split is a different KIND of machine.
FAMILY = {"self-propelled": "sp", "tracked": "sp", "truck-mounted": "sp",
          "towed": "towed"}
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def classify(docs, product, maker=None):
    """-> (family, [(class, url)]) read from documents that mention the product.

    Mentions are found the way the spec grounder finds them -- the product's
    designators, anchored on the rarest one, with the whole name required when that
    anchor is a word the corpus uses for everything else."""
    ds = designators(product)
    if not ds:
        return None, []
    votes, seen = {}, {}
    for _did, url, text in docs:
        spans = mention_spans(text, ds, product, maker)
        if not spans:
            continue
        for cls, rx in CLASSES:
            for m in rx.finditer(text):
                if any(abs(m.start() - s) <= NEAR for s in spans):
                    votes.setdefault(cls, set()).add(url)
                    seen.setdefault(cls, url)
                    break
    fam, ev = {}, {}
    for cls, urls in votes.items():
        f = FAMILY[cls]
        fam[f] = fam.get(f, set()) | urls
        ev.setdefault(f, (cls, seen[cls]))
    if not fam:
        return None, []
    total = sum(len(u) for u in fam.values())
    best = max(fam, key=lambda f: len(fam[f]))
    # A comparison article names both kinds of gun, so a handful of crossed votes
    # is normal and unanimity would classify nothing. A clear majority is the test.
    if len(fam[best]) < MIN_HITS or len(fam[best]) / float(total) < MAJORITY:
        return None, []
    return best, [ev[best]]


def re_edge(specs):
    """The 0-100 edge, recomputed with the class axes taken out.

    Leaving the stored number alone would have kept "KSSL AHEAD 75/100" printed over a
    comparison whose only decided dimension has just been marked as not a comparison.

    ONE DEFINITION. This used to be a private copy of the matchup reviver's formula,
    kept in step by hand; it is revive_matchups.edge_of now, which already excludes a
    spec carrying `classAxis` for exactly this reason. A number computed in two places
    is a number with two definitions."""
    return edge_of(specs)


def main(apply=False):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    docs = load_docs(cur)
    cur.execute("""SELECT matchup_id, cat, comp, "compBy", bf, "bfBy", specs
                     FROM serving.matchup WHERE origin='pipeline'
                    ORDER BY matchup_id""")
    rows = cur.fetchall()
    print("%d pipeline matchup(s)" % len(rows))
    # mention_spans decides whether a product's rarest token can stand alone from
    # how common it is in THIS corpus, so the frequencies have to be measured first
    index_df(docs, [t for r in rows for side in (r[2], r[4])
                    for t in designators(product_of(side) or "")])

    cache = {}

    def cls_of(side, maker):
        p = product_of(side)
        if not p:
            return None, []
        if p not in cache:
            cache[p] = classify(docs, p, maker)
        return cache[p]

    marked, checked, unknown = 0, 0, 0
    changes = []
    for mid, cat, comp, compby, bf, bfby, specs in rows:
        sl = specs if isinstance(specs, list) else json.loads(specs or "[]")
        if not any((s.get("l") or "").lower() in MASS_DIMS for s in sl):
            continue
        checked += 1
        fc, evc = cls_of(comp, compby)
        fk, evk = cls_of(bf, bfby)
        if not fc or not fk:
            unknown += 1
            continue
        if fc == fk:
            continue
        why = ("%s is %s and %s is %s: mass is what the two platforms ARE, not a "
               "lead either holds" % (product_of(comp), evc[0][0], product_of(bf),
                                      evk[0][0]))
        hit = False
        for s in sl:
            if (s.get("l") or "").lower() in MASS_DIMS:
                s["classAxis"] = why
                s["classSrc"] = [evc[0][1], evk[0][1]]
                hit = True
        if hit:
            marked += 1
            changes.append((mid, comp, bf, why, sl, re_edge(sl)))

    print("%d compare on mass; %d could not be classified from the corpus" %
          (checked, unknown))
    print("%d pairing(s) compare two different platform classes:\n" % marked)
    for mid, comp, bf, why, _sl, edge in changes:
        print("  %-6s %-30s vs %-20s edge -> %-4s %s"
              % (mid, comp[:30], product_of(bf)[:20],
                 "none" if edge is None else edge, why[:60]))

    if apply and changes:
        for mid, _c, _b, _w, sl, edge in changes:
            cur.execute("UPDATE serving.matchup SET specs=%s, edge=%s, updated_at=now() "
                        "WHERE matchup_id=%s AND origin='pipeline'",
                        (json.dumps(sl), edge, mid))
        con.commit()
        print("\napplied to %d matchup(s)." % len(changes))
    elif not apply:
        print("\n(dry run -- nothing written)")
    con.close()
    return changes


def _demo():
    sp = norm("The K9 Thunder is a tracked self-propelled howitzer weighing 47 tonnes.")
    tw = norm("ATAGS is a towed 155 mm gun, the towed howitzer developed by DRDO.")
    docs = [("d1", "https://a.com/1", sp), ("d2", "https://b.com/2", sp),
            ("d3", "https://c.com/3", tw), ("d4", "https://d.com/4", tw)]
    index_df(docs, designators("K9 Thunder") + designators("ATAGS")
             + designators("M777") + designators("Bharat 52"))
    f1, _e1 = classify(docs, "K9 Thunder")
    f2, _e2 = classify(docs, "ATAGS")
    assert f1 == "sp", f1
    assert f2 == "towed", f2
    # one document is not a classification
    assert classify([("d1", "https://a.com/1", sp)], "K9 Thunder")[0] is None
    # a few crossed votes do not overturn a clear majority...
    mixed = docs + [("dx", "https://x.com/1", sp), ("dy", "https://y.com/2", sp),
                    ("d7", "https://e.com/7",
                     norm("the towed K9 Thunder was mentioned once in error"))]
    assert classify(mixed, "K9 Thunder")[0] == "sp"
    # ...but an evenly split corpus is not a classification either
    split = docs + [("d8", "https://f.com/8", norm("the towed K9 Thunder rolled")),
                    ("d9", "https://g.com/9", norm("a towed K9 Thunder was seen")),
                    ("da", "https://h.com/3", norm("towed K9 Thunder in the parade"))]
    assert classify(split, "K9 Thunder")[0] is None, classify(split, "K9 Thunder")
    # a product the corpus never classifies stays unclassified -- refusing a
    # comparison needs evidence too
    assert classify(docs, "Bharat 52")[0] is None
    # and a word about a DIFFERENT product does not classify this one
    other = norm("The M777 is a towed howitzer. " + ("filler " * 80)
                 + " The K9 Thunder entered service in 1999.")
    assert classify([("d5", "https://a.com/5", other),
                     ("d6", "https://b.com/6", other)], "K9 Thunder")[0] is None
    assert FAMILY["truck-mounted"] == FAMILY["tracked"] == "sp"
    # the edge is recomputed without the class axis: a matchup decided ONLY by mass
    # has no verdict left, and one with another decided field keeps that one
    mass_only = [{"l": "Weight", "cn": 47000, "kn": 18000, "hi": False,
                  "classAxis": "different class"}]
    assert re_edge(mass_only) is None
    with_range = mass_only + [{"l": "Max range", "cn": 40, "kn": 41, "hi": True}]
    assert re_edge(with_range) is None, "1 km on 40 is inside the parity deadband"
    real = mass_only + [{"l": "Max range", "cn": 30, "kn": 41, "hi": True}]
    assert re_edge(real) == 75, re_edge(real)
    # a matched field does not dilute the side that leads the decided one
    with_tie = real + [{"l": "Rate of fire", "cn": 6, "kn": 6, "hi": True}]
    assert re_edge(with_tie) == re_edge(real), (re_edge(with_tie), re_edge(real))
    # and the marked dimension is excluded by the ONE definition of comparable, not
    # by a filter copied into this file
    assert comparable(mass_only) == []
    assert re_edge is not None and re_edge(real) == edge_of(real)
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply)
