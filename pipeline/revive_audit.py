"""What of the archived reference data can the corpus actually support?

    python revive_audit.py            # the report
    python revive_audit.py --demo

Nothing is written. This decides the shape of the revival: a reference row may
only come back as `origin='pipeline'` if the extracted corpus can carry it, so
first we measure how much of it the corpus carries TODAY. Whatever it cannot
carry is the targeted-fetch worklist, not a row to quietly wave through.

The reference matchups assert spec tables with `srcs` NULL -- values with no
source at all. That is the thing to fix, not to re-publish.
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

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from aliases import fold as afold  # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A product name is only "in the corpus" if a DESIGNATOR of it appears -- not a
# generic word from it. "howitzer" occurring somewhere does not source the
# "CAESAR 6x6" row; see the forge/Bharat-Forge trap in the ontology work.
GENERIC = {
    "system", "systems", "vehicle", "vehicles", "gun", "guns", "howitzer", "howitzers",
    "tank", "tanks", "missile", "missiles", "rifle", "rifles", "drone", "drones",
    "uav", "uas", "artillery", "ammunition", "armoured", "armored", "protected",
    "mounted", "towed", "self", "propelled", "main", "battle", "light", "heavy",
    "series", "mk", "mm", "cal", "new", "the", "and", "of", "for", "with",
}


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def designators(name):
    """Tokens specific enough to source a claim: proper nouns and alphanumerics."""
    out = []
    for t in norm(name).replace("/", " ").replace("-", " ").replace("·", " ").split():
        t = t.strip("(),.:;")
        if not t or t in GENERIC or len(t) < 2:
            continue
        if any(ch.isdigit() for ch in t) or len(t) >= 4:
            out.append(t)
    return out


def corpus_index(cur):
    """Every surface the corpus knows, folded, plus the raw text for phrase checks."""
    cur.execute("select distinct surface_folded from extracted.entity_alias")
    surfaces = {r[0] for r in cur.fetchall() if r[0]}
    cur.execute("select distinct lower(text) from extracted.span where length(text) < 80")
    spans = {norm(r[0]) for r in cur.fetchall() if r[0]}
    return surfaces | spans


def in_corpus(name, idx):
    """A name is carried if the corpus holds a designator of it."""
    ds = designators(name)
    if not ds:
        return False, []
    hit = [d for d in ds if any(d in s for s in idx)]
    return (len(hit) > 0), hit


def main(show=12):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    idx = corpus_index(cur)
    print("corpus surface index: %d distinct strings\n" % len(idx))

    # ---- matchups -----------------------------------------------------------
    cur.execute("""select matchup_id, cat, comp, "compBy", bf, specs, srcs, "advComp", "advBf"
                     from serving.matchup where origin='reference'""")
    rows = cur.fetchall()
    n_spec = n_srcs = 0
    comp_seen, comp_missing = set(), collections.Counter()
    for _mid, _cat, comp, compby, _bf, specs, srcs, ac, ab in rows:
        if specs:
            n_spec += 1
        if srcs:
            n_srcs += 1
        ok, _ = in_corpus(comp, idx)
        comp_seen.add(comp)
        if not ok:
            comp_missing[compby or comp] += 1
    print("MATCHUPS  %d archived, %d distinct competitor products" % (len(rows), len(comp_seen)))
    print("          %d carry a spec table, %d carry ANY source  <- the whole problem"
          % (n_spec, n_srcs))
    unsourced = sum(comp_missing.values())
    print("          %d row(s) name a product the corpus has never seen (%d compan(ies))"
          % (unsourced, len(comp_missing)))
    for who, n in comp_missing.most_common(show):
        print("            %-42s %d row(s)" % (str(who)[:42], n))

    # ---- patents ------------------------------------------------------------
    cur.execute("""select column_name from information_schema.columns
                    where table_schema='serving' and table_name='patent'
                    order by ordinal_position""")
    pcols = [r[0] for r in cur.fetchall()]
    cur.execute("select count(*) from serving.patent where origin='reference'")
    n_pat = cur.fetchone()[0]
    print("\nPATENTS   %d archived, columns: %s" % (n_pat, ", ".join(pcols)))

    # ---- geo, cards, competitors, innovations -------------------------------
    for tbl, namecol in (("geo_presence", "comp"), ("signal_card", "company"),
                         ("competitors", "name"), ("innovation", "driver")):
        cur.execute("""select column_name from information_schema.columns
                        where table_schema='serving' and table_name=%s""", (tbl,))
        cols = {r[0] for r in cur.fetchall()}
        if namecol not in cols:
            namecol = next((c for c in ("name", "comp", "company", "driver") if c in cols), None)
        if not namecol:
            continue
        cur.execute('select "%s" from serving.%s where origin=\'reference\'' % (namecol, tbl))
        names = [r[0] for r in cur.fetchall() if r[0]]
        got = sum(1 for n in names if in_corpus(n, idx)[0])
        print("%-14s %3d archived, %3d name something the corpus carries (%.0f%%)"
              % (tbl, len(names), got, 100.0 * got / max(len(names), 1)))

    con.close()


def _demo():
    idx = {"caesar 6x6", "rheinmetall l55a1", "atags", "bharat forge"}
    # a designator sources a row; a generic word must not
    ok, hit = in_corpus("KNDS · CAESAR 6x6", idx)
    assert ok and "caesar" in hit, hit
    ok2, _ = in_corpus("155mm towed howitzer", idx)
    assert not ok2, "a generic description must not count as a source"
    assert designators("Rheinmetall · 120mm smoothbore howitzer L55A1")
    assert "howitzer" not in designators("120mm howitzer")
    # alphanumeric designators survive even when short
    assert "6x6" in designators("CAESAR 6x6")
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=12)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.show)
