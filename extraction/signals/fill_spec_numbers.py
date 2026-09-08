"""Fill kn/cn on served specs where BOTH sides state the same quantity, and recompute.

    python apply_spec_numbers.py            # dry run, prints what would change
    python apply_spec_numbers.py --apply

Runs inside the extraction image, where revive_matchups already lives. edge_of and
verdict_of are imported from it rather than reimplemented -- the stored edge and the
drawn edge have to stay one number, and this repo has already been bitten once by a
formula that existed in three places.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, "/app/signals")   # the deployed image lays the modules out here

import psycopg2                                        # noqa: E402
import spec_number                                     # noqa: E402
from revive_matchups import edge_of, verdict_of        # noqa: E402

APPLY = "--apply" in sys.argv
con = psycopg2.connect(os.environ["DSN"])
cur = con.cursor()
cur.execute("""SELECT matchup_id, comp, bf, "compBy", "bfBy", specs, edge, verdict
                 FROM serving.matchup WHERE origin='pipeline' ORDER BY matchup_id""")
rows = cur.fetchall()

changed, filled_total = [], 0
for mid, comp, bf, compby, bfby, specs, edge, verdict in rows:
    specs = specs or []
    before = json.dumps(specs, sort_keys=True)
    n_before = sum(1 for s in specs
                   if isinstance(s, dict) and s.get("kn") is not None and s.get("cn") is not None)
    spec_number.fill(specs)
    n_after = sum(1 for s in specs
                  if isinstance(s, dict) and s.get("kn") is not None and s.get("cn") is not None)
    if json.dumps(specs, sort_keys=True) == before:
        continue
    filled_total += n_after - n_before
    new_edge = edge_of(specs)
    new_verdict = verdict_of(specs, compby or comp, bfby or bf)
    changed.append((mid, comp, bf, edge, new_edge, n_before, n_after, specs, new_verdict))

print("matchups whose specs gain a comparison: %d" % len(changed))
print("specs newly comparable:                 %d" % filled_total)
print()
print("%-6s %-32s %-22s %8s %8s %s" % ("id", "competitor", "KSSL", "edge", "-> edge", "cmp"))
for mid, comp, bf, e0, e1, n0, n1, _s, _v in changed:
    print("%-6s %-32s %-22s %8s %8s %d->%d"
          % (mid, str(comp)[:32], str(bf)[:22], e0, e1, n0, n1))

# NOTHING MAY SHRINK. A pass whose job is to ADD comparisons must never remove one, and
# an edge that already existed was computed from numbers the extraction layer grounded.
bad = [(m, e0, e1, n0, n1) for m, c, b, e0, e1, n0, n1, _s, _v in changed
       if n1 < n0 or (e0 is not None and e1 is None)]
if bad:
    print("\nREFUSING: %d row(s) would lose a comparison: %r" % (len(bad), bad))
    sys.exit(1)

if not APPLY:
    print("\ndry run -- nothing written. Re-run with --apply")
    sys.exit(0)

for mid, _c, _b, _e0, e1, _n0, _n1, specs, verd in changed:
    cur.execute("UPDATE serving.matchup SET specs=%s, edge=%s, verdict=%s "
                "WHERE matchup_id=%s AND origin='pipeline'",
                (json.dumps(specs), e1, verd, mid))
con.commit()
print("\napplied to %d matchup(s)" % len(changed))
