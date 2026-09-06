"""Give the technology lane a capability-threat direction it could never have had.

    python backfill_capability_direction.py            # dry run
    python backfill_capability_direction.py --apply

274 of 274 served technology signals sat at dir='watch', so the Technology tab's
"Capability threats" tile read "not assessed" and always would have. Three layers each
moved cards one way only -- serving_fill writes a threat only for pillar='competitive',
grade() returns early unless a card is ALREADY a threat, and backfill_card_direction
skips anything that is not one. The tile asked a question with no path to an answer.

threat_gate.capability_dir is that path. It classifies; severity (already computed, and
already served) ranks. This applies it to lane='tech' and nothing else -- the competitive
lane keeps its own rule, untouched.

dir_reason is NOT written: the column does not exist on serving.signal_card yet (it is
in an unrun migration). The reasons are printed instead, so the demotions are still
readable, and nothing here depends on a schema change.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, "/app/signals")

import psycopg2                       # noqa: E402
import threat_gate                    # noqa: E402

APPLY = "--apply" in sys.argv
LANE = "tech"

con = psycopg2.connect(os.environ["DSN"])
cur = con.cursor()

cur.execute("SELECT name, threat, products FROM serving.competitors WHERE name IS NOT NULL")
comps = {}
for name, threat, products in cur.fetchall():
    comps[str(name).strip()] = {"threat": threat, "products": products or []}

gate = threat_gate.gate_from_db(cur)          # raises rather than pass everything

cur.execute("SELECT id, dir, company, tags, meta, sec FROM serving.signal_card "
            "WHERE origin='pipeline' AND lane=%s", (LANE,))
cards = [{"id": r[0], "dir": r[1], "company": r[2], "tags": r[3], "meta": r[4],
          "sec": r[5] if isinstance(r[5], list) else []} for r in cur.fetchall()]

promote, reasons, by_company = [], collections.Counter(), collections.Counter()
for card in cards:
    name = gate.resolve(card["company"])
    comp = comps.get(name) if name else None
    newdir, why = threat_gate.capability_dir(card, comp, gate)
    if newdir == "threat" and card["dir"] != "threat":
        promote.append((card["id"], name or card["company"],
                        threat_gate.severity_of((comp or {}).get("threat"),
                                                threat_gate.impact_of(card, comp))))
        by_company[name or card["company"]] += 1
    elif newdir != "threat":
        reasons[why or "already watch"] += 1

print("technology signals: %d" % len(cards))
print("would become capability threats: %d" % len(promote))
print()
print("why the rest stay watch:")
for k, v in reasons.most_common():
    print("   %-38s %d" % (k, v))
print()
print("severity of the promoted:")
sev = collections.Counter(s for _i, _n, s in promote)
for k, v in sev.most_common():
    print("   %-38s %d" % (k or "not assessed", v))
print()
print("by company:")
for k, v in by_company.most_common(12):
    print("   %-38s %d" % (k, v))

# A capability threat that cannot be graded is not one -- severity is what ranks it, and
# an ungraded badge would sit at the bottom of every ordering while shouting at the top.
ungraded = [p for p in promote if p[2] is None]
if ungraded:
    print("\nREFUSING: %d promoted card(s) carry no severity: %r" % (len(ungraded), ungraded[:5]))
    sys.exit(1)

if not APPLY:
    print("\ndry run -- nothing written. Re-run with --apply")
    sys.exit(0)

ids = [p[0] for p in promote]
cur.execute("UPDATE serving.signal_card SET dir='threat', updated_at=now() "
            "WHERE id = ANY(%s) AND lane=%s AND origin='pipeline'", (ids, LANE))
n1 = cur.rowcount
cur.execute("UPDATE serving.signal_detail SET dir='threat', updated_at=now() "
            "WHERE id = ANY(%s)", (ids,))
n2 = cur.rowcount
con.commit()
print("\napplied: %d card(s), %d detail row(s)" % (n1, n2))
