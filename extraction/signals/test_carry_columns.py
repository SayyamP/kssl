"""A curated column must survive the rebuild that deletes its row.

    python3 test_carry_columns.py          (needs KSSL_DSN; rolls everything back)

THE BUG THIS PINS. step_companies DELETEs the pipeline competitors and re-INSERTs them
from the corpus, and its INSERT writes 16 columns. Anything written by something else --
pipeline/harvest/promote.py extracts leadership, facilities and sales, hand-audited --
survives only because a carry-forward snapshots it first. That carry-forward listed
leadership, facilities and hq. It did not list `sales`. So the harvest wrote annual
revenue, the next two-hourly pass deleted it, and the Competitor tab showed 0 of 42 for
a field that had already been extracted correctly.

Every column in roster.CARRIED_COLUMNS is asserted individually, so adding a column to
the list without teaching the SQL about it fails here rather than two hours later in
production.

Scoped to one throwaway row: the carry's default predicate is every pipeline
competitor, and touching those collides with the live rebuild.

REAL SQL, REAL TABLE, NO COMMIT. The carry is dynamic SQL over a column list; a mock
cursor would assert that the strings are the strings I wrote and prove nothing about
whether Postgres accepts them. This inserts a throwaway row, exercises snapshot ->
delete -> re-insert -> restore, then ROLLBACKs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roster                                                         # noqa: E402

CID = "__carrytest__"
SAMPLE = {
    "leadership": [{"name": "A Person", "role": "CEO"}],
    "facilities": [{"name": "Plant 1", "where": "Pune"}],
    "sales": [{"value": "Rs 1,234 cr", "year": "2025"}],
    "starting_year": "1961",
    "global_locations": [{"country": "India"}],
    "company_size": "5,000 employees",
    "strategic_positioning": "a sentence about positioning",
    "hq": "Pune, India",
}


def main():
    import psycopg2
    dsn = os.environ.get("KSSL_DSN") or os.environ.get("KSSL_CORPUS_DSN")
    if not dsn:
        # SKIP, NOT FAIL. This test needs a real Postgres on purpose -- the carry is
        # dynamic SQL over a column list, and a mock cursor would assert that the
        # strings are the strings someone wrote and prove nothing about whether
        # Postgres accepts them. But deploy.yml runs every test_*.py in this directory
        # on a GitHub runner, which has no database and must not have credentials for
        # the production one. Exiting non-zero there failed the selfcheck job, and the
        # deploy job is `needs: selfcheck` -- so from the commit that added this file
        # (99c1fab) NOTHING reached production. Six consecutive Deploy runs on main
        # failed here, all of them on this line.
        #
        # It still fails loudly wherever a DSN exists, which is the only place it can
        # tell you anything.
        print("SKIP test_carry_columns: no KSSL_DSN "
              "(needs a real database; runs on a machine that has one)")
        return 0
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("SET statement_timeout='60s'")
    cur.execute("SET lock_timeout='10s'")
    bad = 0
    try:
        cols = roster.CARRIED_COLUMNS + roster.CARRY_IF_BLANK
        # every name in the list must be a real column -- a typo would otherwise show up
        # as a silently un-carried field
        cur.execute("""SELECT column_name FROM information_schema.columns
                        WHERE table_schema='serving' AND table_name='competitors'""")
        actual = {r[0] for r in cur.fetchall()}
        for c in cols:
            if c not in actual:
                bad += 1
                print("  FAIL %s is in the carry list but not a column" % c)
            if c not in SAMPLE:
                bad += 1
                print("  FAIL %s is carried but this test has no sample for it" % c)

        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (CID,))
        setcols = ", ".join('"%s"' % c for c in cols)
        cur.execute("""INSERT INTO serving.competitors
                       (comp_id, ord, name, origin, %s)
                       VALUES (%%s, 1999, 'Carry Test', 'pipeline', %s)"""
                    % (setcols, ", ".join(["%s"] * len(cols))),
                    [CID] + [json.dumps(SAMPLE[c]) if isinstance(SAMPLE[c], (list, dict))
                             else SAMPLE[c] for c in cols])

        # --- the rebuild: snapshot, delete, re-insert bare, restore -----------------
        # scoped to THIS row. The default predicate is every pipeline competitor, and
        # restoring those collides with the two-hourly rebuild's locks -- a test must
        # not touch production rows to prove a mechanism.
        snap = roster.carry_snapshot(cur, "comp_id=%s", (CID,))
        if CID not in snap:
            bad += 1
            print("  FAIL snapshot did not pick the row up at all")
        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (CID,))
        cur.execute("""INSERT INTO serving.competitors (comp_id, ord, name, origin)
                       VALUES (%s, 1999, 'Carry Test', 'pipeline')""", (CID,))
        roster.carry_restore(cur, snap)

        cur.execute('SELECT %s FROM serving.competitors WHERE comp_id=%%s' % setcols,
                    (CID,))
        got = dict(zip(cols, cur.fetchone()))
        for c in cols:
            want, have = SAMPLE[c], got[c]
            if isinstance(want, (list, dict)):
                ok = have == want
            else:
                ok = str(have or "") == str(want)
            if not ok:
                bad += 1
                print("  FAIL %s did not survive the rebuild\n    got  %r\n    want %r"
                      % (c, have, want))

        # --- and the rebuild's OWN value must win over a stale carried one ----------
        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (CID,))
        cur.execute("""INSERT INTO serving.competitors
                       (comp_id, ord, name, origin, hq, company_size)
                       VALUES (%s, 1999, 'Carry Test', 'pipeline', 'Fresh HQ', 'fresh')""",
                    (CID,))
        roster.carry_restore(cur, snap)
        cur.execute('SELECT hq, company_size FROM serving.competitors WHERE comp_id=%s',
                    (CID,))
        hq, size = cur.fetchone()
        if hq != "Fresh HQ":
            bad += 1
            print("  FAIL a carried hq overwrote the value the rebuild found: %r" % hq)
        if size != "fresh":
            bad += 1
            print("  FAIL a carried column overwrote a freshly rebuilt value: %r" % size)
    finally:
        con.rollback()
        con.close()

    if bad:
        print("\n%d failure(s)" % bad)
        sys.exit(1)
    print("ok - carry survives a rebuild for all %d curated column(s), "
          "and never overwrites a fresh value"
          % len(roster.CARRIED_COLUMNS + roster.CARRY_IF_BLANK))


if __name__ == "__main__":
    main()
