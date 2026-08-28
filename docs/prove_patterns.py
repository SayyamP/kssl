"""Step 1 of the SIGNALS.html build order: prove the patterns are worth building.

    python prove_patterns.py            # run the patterns, print what fires
    python prove_patterns.py --demo

The cheapest way to find out the approach is wrong. Does a crude, throwaway
version of the four joins -- lexical only, no model, no embeddings -- fire enough
plausible signals to justify building the real thing?

Deliberately WEAK on purpose. Everything here is a floor:
  J1  lexical match of a surface against the ontology's labels + native terms,
      plus the corpus's own "is a" statements. No embeddings, no model.
  J2  the generous surface->predicate map from probe_signal_gaps.
  J4  a stop-list, no merging.
If a floor this low already fires useful signals, the real joins can only do
better. If it fires nothing, that is worth knowing on day one.
"""
import argparse
import collections
import io
import json
import os
import sys
import unicodedata
from pathlib import Path

import psycopg2
import yaml

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "pipeline"))
from probe_signal_gaps import map_predicate  # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
ONT = HERE.parent.parent / "l2" / "ontology" / "ontology.yaml"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# What KSSL sells. The patterns only fire at or under these nodes.
# Parents only -- under_portfolio() matches descendants, so ontology 0.2.0's new
# artillery/munitions/armoured/uncrewed leaves are picked up without listing them.
PORTFOLIO = ["materiel.weapons.artillery", "materiel.weapons.munitions",
             "materiel.weapons.small_arms", "materiel.platforms.armoured",
             "materiel.platforms.land_support", "materiel.platforms.uncrewed",
             "materiel.sensors.counter_uas", "materiel.systems.protection",
             "materiel.systems.propulsion", "technology.materials",
             "technology.manufacturing"]

# J4, at its laziest: things that are not companies.
STOP = {"cookie", "cookies", "website", "web site", "company", "companies", "google",
        "the company", "we", "it", "they", "this", "that", "user", "users", "page",
        "site", "content", "service", "services", "information", "data", "news"}

# A buyer is a state actor. Kept short and multilingual on purpose -- an
# English-only test here would silently drop every non-English procurement.
FORCE = ["ministry", "ministrstvo", "ministerium", "ministere", "ministero", "ministerio",
         "minister", "department of defen", "army", "armee", "navy", "air force",
         "luftwaffe", "heer", "marine", "government", "gouvernement", "governo",
         "gobierno", "regierung", "regeringen", "defence forces", "armed forces",
         "pentagon", "mod ", "dod ", "bundeswehr", "forsvaret", "министерств",
         "армия", "国防部", "防衛省", "국방부", "وزارة الدفاع", "रक्षा मंत्रालय"]


def min_len(s):
    """A minimum term length in CHARACTERS is a Latin assumption. "장갑차" is a
    complete Korean word in three characters and "装甲车" in three Chinese ones, so a
    flat >=4 filter silently drops the CJK and Hangul half of the ontology --
    the exact routine-calibrated-on-Latin trap that cost us Layer B twice."""
    dense = sum(1 for c in s if "぀" <= c <= "鿿" or "가" <= c <= "힯")
    return 2 if dense >= max(1, len(s) // 2) else 4


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", " ".join(s.split()))


def load_ontology():
    """-> {folded term: node_id}, longest term first so 'armoured vehicle' beats 'vehicle'."""
    doc = yaml.safe_load(io.open(ONT, encoding="utf-8").read())
    idx = {}
    for node, spec in (doc.get("sectors") or {}).items():
        terms = list((spec.get("labels") or {}).values())
        for lst in (spec.get("native") or {}).values():
            terms += list(lst)
        terms.append(node.split(".")[-1].replace("_", " "))
        for t in terms:
            f = fold(t)
            if len(f) >= min_len(f):
                idx.setdefault(f, node)
    return idx, doc


def contains(hay, term):
    """Substring match, but at a WORD BOUNDARY for scripts that have word boundaries.

    A bare `term in hay` typed "the Hornets in the fighter squadrons" as an
    uncrewed system, because "dron" sits inside "squa-dron-s". CJK and Hangul are
    written without spaces, so for those a plain substring IS the correct test --
    applying a boundary rule to them would reject every true match."""
    if min_len(term) == 2:            # CJK / Hangul: no word boundaries to honour
        return term in hay
    i = hay.find(term)
    while i != -1:
        before = hay[i - 1] if i else " "
        after = hay[i + len(term)] if i + len(term) < len(hay) else " "
        if not (before.isalnum() or after.isalnum()):
            return True
        i = hay.find(term, i + 1)
    return False


def type_of(text, idx):
    """J1-lite. Longest matching ontology term wins; no match -> unclassified."""
    f = fold(text)
    if not f or f in STOP:
        return None
    best = None
    for term, node in idx.items():
        if (best is None or len(term) > len(best[0])) and contains(f, term):
            best = (term, node)
    return best[1] if best else None


def under_portfolio(node):
    return bool(node) and any(node == p or node.startswith(p + ".") for p in PORTFOLIO)


def is_force(name):
    f = fold(name)
    return any(c in f for c in FORCE)


def is_client(name):
    f = fold(name)
    return any(c in f for c in ("kalyani", "kssl", "bharat forge"))


def run(limit=None, show=8):
    idx, _doc = load_ontology()
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    cur.execute("""select p.subject, p.predicate, p.object, p.ev_quote,
                          d.source_id, d.url, d.language, d.document_id
                     from extracted.proposition p
                     join extracted.document d using (document_id)""" +
                (" limit %d" % limit if limit else ""))
    rows = cur.fetchall()
    con.close()
    print("ontology index: %d terms over %d portfolio nodes" % (len(idx), len(PORTFOLIO)))
    print("propositions read: %d\n" % len(rows))

    typed_obj = typed_subj = edged = 0
    client_buyers = set()
    hits = collections.defaultdict(list)

    # first pass: who does the client already have a link to? (needed for "open demand")
    for subj, pred, obj, _q, _s, _u, _l, _d in rows:
        if is_client(subj) or is_client(obj):
            for side in (subj, obj):
                if is_force(side):
                    client_buyers.add(fold(side))

    for subj, pred, obj, quote, src, url, lang, did in rows:
        p = map_predicate(pred)
        if p:
            edged += 1
        node_o = type_of(obj, idx)
        node_s = type_of(subj, idx)
        typed_obj += bool(node_o)
        typed_subj += bool(node_s)
        if not p or not under_portfolio(node_o):
            continue
        rec = {"subject": subj, "surface": pred, "pred": p, "object": obj, "node": node_o,
               "quote": (quote or "")[:170], "source": src, "url": url, "lang": lang,
               "doc": did}

        # PATTERN 1 -- rival advance
        if p in ("awarded", "supplies", "manufactures", "delivers") \
                and not is_client(subj) and not is_force(subj) \
                and fold(subj) not in STOP and len(subj) > 3:
            hits["rival advance"].append(rec)

        # PATTERN 2 -- open demand (a buyer we have no link to)
        if p == "procures" and is_force(subj) and fold(subj) not in client_buyers:
            hits["open demand"].append(rec)

        # PATTERN 5 (precursor) -- replacement pressure on a platform class
        if p == "replaces":
            hits["replacement pressure"].append(rec)

    n = len(rows) or 1
    print("J1-lite  objects typed to a node   %6d  (%.1f%%)" % (typed_obj, 100.0 * typed_obj / n))
    print("J1-lite  subjects typed to a node  %6d  (%.1f%%)" % (typed_subj, 100.0 * typed_subj / n))
    print("J2-lite  statements given an edge  %6d  (%.1f%%)\n" % (edged, 100.0 * edged / n))

    total = 0
    for name in ("rival advance", "open demand", "replacement pressure"):
        got = hits[name]
        # one signal per (actor, node) -- the same story repeated is one signal
        uniq = {}
        for r in got:
            uniq.setdefault((fold(r["subject"]), r["node"]), r)
        total += len(uniq)
        print("=== %s: %d statement(s) -> %d distinct signal(s)" % (name, len(got), len(uniq)))
        for r in list(uniq.values())[:show]:
            print("  %-34s -[%s]-> %-30s  %s" % (r["subject"][:34], r["pred"],
                                                 r["object"][:30], r["node"]))
            print("      %s | %s" % (r["source"], r["quote"][:110]))
        print()

    print("TOTAL distinct signals from a floor-level implementation: %d" % total)
    out = HERE / "pattern_proof.json"
    io.open(out, "w", encoding="utf-8").write(json.dumps(
        {"stats": {"propositions": len(rows), "typed_objects": typed_obj,
                   "typed_subjects": typed_subj, "edged": edged, "signals": total,
                   "index_terms": len(idx), "portfolio_nodes": len(PORTFOLIO)},
         "signals": {k: list({(fold(r["subject"]), r["node"]): r for r in v}.values())
                     for k, v in hits.items()}}, ensure_ascii=False, indent=1))
    print("wrote %s" % out.name)
    return total


def _demo():
    idx, doc = load_ontology()
    assert len(idx) > 200, "ontology index too small: %d" % len(idx)
    # the multilingual terms must actually be in the index, or this is an English test
    assert type_of("Gepanzerte Fahrzeuge", idx) == "materiel.platforms.armoured"
    assert min_len("장갑차") == 2 and min_len("tank") == 4
    assert type_of("장갑차", idx) == "materiel.platforms.armoured"
    assert type_of("装甲车", idx) == "materiel.platforms.armoured"
    assert type_of("Бронетехника", idx) == "materiel.platforms.armoured"
    # longest match wins, so a compound does not fall back to its parent
    assert under_portfolio("materiel.weapons.artillery")
    assert not under_portfolio("materiel.platforms.air")
    assert not under_portfolio(None)
    # the stop-list and the client/force tests
    assert type_of("cookie", idx) is None
    # word-boundary regression: "dron" must not match inside "squadrons"
    assert contains("armoured vehicle fleet", "armoured vehicle")
    assert not contains("the hornets in the fighter squadrons", "dron")
    assert contains("uav and dron systems", "dron")
    assert type_of("the Hornets in the fighter squadrons", idx) is None
    assert is_client("Bharat Forge Ltd") and is_client("KSSL")
    assert is_force("Government of India") and is_force("국방부")
    assert not is_force("Hanwha Defense USA")
    print("ok (%d terms, %d sectors)" % (len(idx), len(doc.get("sectors") or {})))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--show", type=int, default=8)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        run(a.limit, a.show)
