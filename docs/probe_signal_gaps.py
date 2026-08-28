"""Measure the three joins that stand between the corpus and a signal.

    python probe_signal_gaps.py

Not a fix -- a measurement. The signal design in SIGNALS.html rests on these
numbers, so they are produced by querying the live store rather than asserted.

Gap 1  entity -> ontology node      (extracted.entity.ont_node_id)
Gap 2  free-text predicate -> the closed predicate vocabulary (ontology.yaml)
Gap 3  Measure/Date/Money span -> a typed comparable value (extracted.span_value)
"""
import collections
import io
import json
import os
import re
import sys
from pathlib import Path

import psycopg2

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
ONT = Path(__file__).parent.parent.parent / "l2" / "ontology" / "ontology.yaml"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# The 18 closed predicates, read off the ontology rather than retyped, so this
# probe cannot drift from the artefact it is measuring.
PRED_RE = re.compile(r"^  ([a-z_]+):\s+\{since:", re.M)

# A deliberately GENEROUS surface -> closed-predicate map. Generous is the point:
# it puts an UPPER BOUND on what a lexical mapping can reach, so the shortfall it
# leaves is a floor on how much work is genuinely semantic.
MAP = {
    "manufactures": ["manufactur", "produces", "produce", "builds", "build", "makes",
                     "fabricat", "assembl"],
    "supplies":     ["supplies", "supply", "supplied", "delivers", "deliver", "provides",
                     "provide", "offers", "offer", "ships"],
    "operates":     ["operates", "operate", "fields", "flies", "deploys", "uses", "use",
                     "employs", "in service with"],
    "procures":     ["procures", "procure", "orders", "order", "buys", "purchas",
                     "acquir", "selects", "select"],
    "awarded":      ["awarded", "awards", "won", "wins", "secured", "receives a contract"],
    "party_to":     ["signed", "signs", "signed with", "agreed", "entered into",
                     "party to", "participates"],
    "subsidiary_of": ["subsidiary", "unit of", "division of", "owned by", "arm of"],
    "partners_with": ["partner", "teamed", "collaborat", "joint venture", "cooperat",
                      "alliance", "mou with"],
    "variant_of":   ["variant", "version of", "derivative", "based on"],
    "component_of": ["component of", "part of", "subsystem of", "fitted to"],
    "integrates":   ["integrat", "equipped with", "fitted with", "carries", "mounts",
                     "incorporat", "includes", "include"],
    "replaces":     ["replac", "succeeds", "supersed", "retires"],
    "delivers":     ["delivers", "delivered under", "covers delivery"],
    "covers":       ["covers", "cover", "comprises"],
    "located_at":   ["located", "based at", "based in", "headquarter", "plant at",
                     "facility in", "site in"],
    "produced_at":  ["produced at", "manufactured at", "built at", "assembled at"],
    "realises":     ["enables", "enable", "provides capability", "supports", "support",
                     "allows", "gives"],
    "has_spec":     ["has a range", "weighs", "measures", "calibre", "caliber",
                     "range of", "speed of", "capacity of"],
}


def closed_predicates():
    txt = io.open(ONT, encoding="utf-8").read()
    tail = txt.split("predicates:")[-1]
    return PRED_RE.findall(tail)


def map_predicate(surface):
    s = (surface or "").strip().lower()
    for pred, cues in MAP.items():
        for c in cues:
            if c in s:
                return pred
    return None


def main():
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    out = {}

    preds = closed_predicates()
    print("ontology declares %d closed predicates: %s\n" % (len(preds), ", ".join(preds)))
    out["closed_predicates"] = preds

    # ---- Gap 1: entity -> ontology node -------------------------------------
    cur.execute("select count(*), count(ont_node_id) from extracted.entity")
    n_ent, n_typed = cur.fetchone()
    cur.execute("""select entity_type, count(*) from extracted.entity
                   group by 1 order by 2 desc""")
    by_type = cur.fetchall()
    print("GAP 1  entities %d, bound to an ontology node %d (%.1f%%)"
          % (n_ent, n_typed, 100.0 * n_typed / max(n_ent, 1)))
    for t, n in by_type:
        print("         %-16s %6d" % (t, n))
    out["gap1"] = {"entities": n_ent, "typed": n_typed,
                   "by_type": [{"type": t, "n": n} for t, n in by_type]}

    # ---- Gap 2: surface predicate -> closed predicate -----------------------
    cur.execute("""select predicate, count(*) from extracted.proposition
                   group by 1 order by 2 desc""")
    rows = cur.fetchall()
    total = sum(n for _, n in rows)
    hit = collections.Counter()
    miss = []
    for surface, n in rows:
        p = map_predicate(surface)
        if p:
            hit[p] += n
        else:
            miss.append((surface, n))
    mapped = sum(hit.values())
    print("\nGAP 2  propositions %d over %d DISTINCT surface predicates"
          % (total, len(rows)))
    print("         a generous lexical map reaches %d (%.1f%%); %d surfaces (%d rows) "
          "have no closed predicate" % (mapped, 100.0 * mapped / max(total, 1),
                                        len(miss), total - mapped))
    print("         top unmapped: %s"
          % ", ".join('"%s" x%d' % (s, n) for s, n in miss[:12]))
    out["gap2"] = {"propositions": total, "distinct_surfaces": len(rows),
                   "mapped": mapped, "unmapped_rows": total - mapped,
                   "unmapped_surfaces": len(miss),
                   "top_unmapped": [{"surface": s, "n": n} for s, n in miss[:20]],
                   "mapped_by_pred": dict(hit)}

    # ---- Gap 3: measurable spans -> typed values ----------------------------
    cur.execute("""select type, count(*) from extracted.span
                   where type in ('Measure','Date','Count','Identifier')
                   group by 1 order by 2 desc""")
    meas = cur.fetchall()
    cur.execute("select count(*) from extracted.span_value")
    n_val = cur.fetchone()[0]
    cur.execute("select count(*) from extracted.prop_arg")
    n_arg = cur.fetchone()[0]
    n_meas = sum(n for _, n in meas)
    print("\nGAP 3  measurable spans %d (%s)"
          % (n_meas, ", ".join("%s %d" % (t, n) for t, n in meas)))
    print("         parsed into a comparable value: span_value %d, prop_arg %d"
          % (n_val, n_arg))
    out["gap3"] = {"measurable_spans": n_meas, "span_value": n_val, "prop_arg": n_arg,
                   "by_type": [{"type": t, "n": n} for t, n in meas]}

    # ---- What a signal can already stand on --------------------------------
    cur.execute("select count(*) from extracted.document")
    n_doc = cur.fetchone()[0]
    cur.execute("""select count(*) from extracted.entity_alias""")
    n_alias = cur.fetchone()[0]
    cur.execute("select count(*) from extracted.span")
    n_span = cur.fetchone()[0]
    cur.execute("""select e.canonical_name, count(distinct a.surface) s,
                          sum(a.n_mentions) m
                     from extracted.entity e join extracted.entity_alias a using (entity_id)
                    group by 1 order by m desc nulls last limit 12""")
    top = cur.fetchall()
    print("\nCORPUS  %d documents, %d entities, %d aliases" % (n_doc, n_ent, n_alias))
    print("        most-mentioned entities:")
    for name, s, m in top:
        print("          %-42s %2d surface(s)  %s mention(s)" % (name[:42], s, m))
    out["corpus"] = {"documents": n_doc, "entities": n_ent, "aliases": n_alias,
                     "spans": n_span,
                     "top_entities": [{"name": n, "surfaces": s, "mentions": m}
                                      for n, s, m in top]}

    con.close()
    p = Path(__file__).parent / "signal_gaps.json"
    io.open(p, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    print("\nwrote %s" % p.name)


def _demo():
    # The map must only ever emit predicates the ontology actually declares --
    # a lexical map that invents an edge type is worse than no map.
    legal = set(closed_predicates())
    assert legal, "no predicates parsed out of ontology.yaml"
    assert set(MAP) <= legal, "map emits non-ontology predicates: %s" % (set(MAP) - legal)
    assert map_predicate("signed with") == "party_to"
    assert map_predicate("is a") is None          # the commonest surface is NOT an edge
    assert map_predicate(None) is None
    print("ok (%d closed predicates, map covers %d)" % (len(legal), len(MAP)))


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        main()
