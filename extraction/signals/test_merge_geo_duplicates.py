"""A company folded in the roster can still be standing twice on the map.

    python test_merge_geo_duplicates.py        (no database, no network)

merge_roster_duplicates.py finds what to repoint by asking the catalogue:

    SELECT ... FROM pg_constraint WHERE contype='f'
                AND confrelid = 'serving.competitors'::regclass

That is the right instinct and it is exactly why the geographic footprint was missed.
serving.geo_comp.id and serving.geo_presence.comp_id are bare text -- db/02_serving.sql
declares no foreign key from either to serving.competitors -- so both tables are
invisible to that query. A roster merge repoints every child it can see, prints a
success line, and leaves the loser's pin on the map. `adani` won its roster merge in an
earlier session and ADANI is still carrying four India rows today; BAE/bae-systems,
ELBIT/elbit-systems, HANWHA/hanwha-aerospace and KNDS/knds are the same shape.

This pins three things:

  1. THE INVARIANT, not the workaround. Either the geo tables have that foreign key --
     in which case the roster merge does reach them -- or a dedicated geo merge exists.
     Neither being true is the state that produced the twins, and it is the state this
     test refuses. Deleting merge_geo_duplicates.py without adding the constraint puts
     the repository straight back into it.
  2. The pairing decision itself, over the real geo_comp shapes, including the three
     things that must never happen: folding the client off its own map, guessing between
     two live companies with the same name, and letting whole-word containment merge a
     parent with its joint venture by default.
  3. Dry run is the DEFAULT. This script deletes curated archive rows, so the outcome
     you get by typing nothing has to be the safe one -- the opposite of
     merge_roster_duplicates.py, where --dry-run is the flag.
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

bad = []


def check(ok, msg):
    if not ok:
        bad.append(msg)
        print("  FAIL %s" % msg)


# ---- 1. the invariant ------------------------------------------------------------
schema = (ROOT / "db" / "02_serving.sql").read_text(encoding="utf-8", errors="replace")
start = schema.index("CREATE TABLE serving.geo_presence")
geo_ddl = schema[start:schema.index("CREATE TABLE", start + 10)]
start2 = schema.index("CREATE TABLE serving.geo_comp")
geo_ddl += schema[start2:start2 + 600]
has_fk = "REFERENCES serving.competitors" in geo_ddl
merge_exists = (HERE / "merge_geo_duplicates.py").is_file()
check(has_fk or merge_exists,
      "the geo tables have no foreign key to serving.competitors AND there is no "
      "merge_geo_duplicates.py -- a roster merge cannot see them, so a folded company "
      "keeps its twin on the map")
if not has_fk:
    print("  (confirmed: serving.geo_comp / serving.geo_presence declare no FK to "
          "serving.competitors, so pg_constraint discovery cannot reach them)")

roster = (HERE / "merge_roster_duplicates.py").read_text(encoding="utf-8", errors="replace")
check("pg_constraint" in roster,
      "merge_roster_duplicates.py no longer discovers by foreign key -- re-read this "
      "test, its premise has changed")

if not merge_exists:
    print("\n%d failure(s)" % len(bad))
    sys.exit(1)

import merge_geo_duplicates as M                                     # noqa: E402

# ---- 2. the pairing decision -----------------------------------------------------
# serving.geo_comp shapes: uppercase archive codes at origin='reference', slugs at
# origin='pipeline', the client flagged isBf.
ROWS = [
    ("KSSL", "Kalyani Strategic Systems", "reference", True),
    ("kalyani-strategic-systems", "Kalyani Strategic Systems", "pipeline", False),
    ("BAE", "BAE Systems", "reference", False),
    ("bae-systems", "BAE Systems", "pipeline", False),
    ("ELBIT", "Elbit Systems", "reference", False),
    ("elbit-systems", "Elbit Systems", "pipeline", False),
    ("HANWHA", "Hanwha Aerospace", "reference", False),
    ("hanwha-aerospace", "Hanwha Aerospace", "pipeline", False),
    ("hanwha-ocean", "Hanwha Ocean", "pipeline", False),
    ("KNDS", "KNDS", "reference", False),
    ("knds", "KNDS", "pipeline", False),
    ("ADANI", "Adani Defence & Aerospace", "reference", False),
    ("adani", "Adani Defence", "pipeline", False),
    ("BEML", "BEML Land Systems", "reference", False),
    ("beml", "BEML", "pipeline", False),
    ("NORINCO", "Norinco", "reference", False),
]

plan, notes = M.plan_merges(ROWS)
got = {loser: winner for loser, winner, _rule, _why in plan}
check(got == {"BAE": "bae-systems", "ELBIT": "elbit-systems",
              "HANWHA": "hanwha-aerospace", "KNDS": "knds"},
      "the four confirmed duplicate pairs are not the plan: %r" % (got,))

# THE CLIENT IS NOT A DUPLICATE. geo_comp keys it 'KSSL' and serving.competitors keys it
# 'kalyani-strategic-systems'; discover_geo puts the client's presence rows on the isBf
# id on purpose, so folding this pair takes the client off its own map.
check("KSSL" not in got, "the client (isBf) was folded away")
check(any("isBf" in n for n in notes), "the refusal to fold the client is not reported")

# A reference company nothing in the pipeline answers to is left alone, never deleted.
check("NORINCO" not in got, "a reference company with no twin was folded into nothing")

# A NEAR NAME IS NOT THE SAME COMPANY.
check(got.get("HANWHA") == "hanwha-aerospace",
      "Hanwha Aerospace did not land on hanwha-aerospace")
check("hanwha-ocean" not in got.values(),
      "Hanwha Aerospace's rows were about to be moved onto Hanwha Ocean")

# Whole-word containment reaches ADANI/adani, and it is OPT-IN because it also reaches
# BEML / BEML Land Systems, which are a parent and a joint venture.
plan2, _ = M.plan_merges(ROWS, fold_divisions=True)
got2 = {loser: winner for loser, winner, _r, _w in plan2}
check(got2.get("ADANI") == "adani",
      "--fold-divisions does not reach the ADANI/adani pair")
check("BEML" not in got, "containment leaked into the default rule")
check(got2.get("BEML") == "beml",
      "the containment rule's own risk is no longer demonstrated -- re-read the note "
      "in merge_geo_duplicates about why it is opt-in")

# Two live companies with one archive name: refused, never guessed.
plan3, notes3 = M.plan_merges(ROWS + [("bae-systems-plc", "BAE Systems", "pipeline", False)])
check("BAE" not in {p[0] for p in plan3}, "an ambiguous pair was merged on a guess")
check(any("AMBIGUOUS" in n for n in notes3), "an ambiguous pair was dropped silently")

# The merge only ever runs archive -> pipeline. The map serves origin='pipeline'
# (serving_live), so merging the other way would move live rows onto an unserved code.
check(all(w in {r[0] for r in ROWS if r[2] == "pipeline"} for w in got.values()),
      "a merge target is not a pipeline id")

# ---- 3. dry run is the default ---------------------------------------------------
tree = ast.parse((HERE / "merge_geo_duplicates.py").read_text(encoding="utf-8"))
flags = {a.value for n in ast.walk(tree)
         if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_argument"
         for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
check("--apply" in flags, "there is no --apply flag")
check("--dry-run" not in flags,
      "--dry-run exists, which means writing is what you get by typing nothing")

if bad:
    print("\n%d failure(s)" % len(bad))
    sys.exit(1)
print("ok - geo merge: the FK gap is pinned, 4 pairs by canonical name, +1 with "
      "--fold-divisions, client and ambiguity refused, dry run is the default")
