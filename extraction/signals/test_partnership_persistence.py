"""Which partnership ties survive a pass, asserted against a real Postgres.

    python3 test_partnership_persistence.py     (needs KSSL_DSN; rolls everything back)

THREE WAYS THE TAB WENT EMPTY, and this file is one test for each.

  1. THE REBUILD. step_companies deletes and re-inserts every pipeline competitor, and
     its INSERT wrote '[]' into `partners`. Every two-hourly pass emptied the tab. Only
     Adani and Mahindra still held ties on 2026-09-06, and only because their profile
     call kept failing, so the whole-row carry-forward put them back -- their
     updated_at sat eleven days behind every other row on the table.

  2. THE RESET. step_partnerships blanks its own previous output before writing new
     output, and the predicate decides what "its own" means. It was `p ? 'origin'`,
     which keeps every row that HAS an origin key -- including the enriched rows the
     step itself wrote last pass. Invisible for as long as the step never reached its
     commit; a tie-doubling bug the first time it did.

  3. THE APPEND. The write must not re-filter what the reset already decided to keep,
     or a hand-written tie is deleted by the pass that writes next to it. That happened
     once already, to the archive revival.

REAL SQL, REAL TABLE, NO COMMIT. These are three jsonb predicates. A mock cursor would
assert that the strings are the strings someone wrote and prove nothing about what
Postgres does with them, which is the entire question. This inserts throwaway rows,
runs the SQL that SHIPS (imported, never retyped), then ROLLBACKs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import roster
    from enrich_serving import (PART_APPEND_SQL, PART_RESET_ONE_SQL,
                                PART_RESET_REST_SQL)
except Exception as e:                                              # noqa: BLE001
    print("SKIP test_partnership_persistence: cannot import enrich_serving (%s: %s)"
          % (type(e).__name__, e))
    sys.exit(0)

CID = "__partpersist__"

# One of each provenance the column actually carries, taken from production shapes.
ENRICHED = {"id": "adani", "label": "Adani", "ptype": "Joint venture", "rel": "jv",
            "note": "what this writer found last pass", "origin": "enriched"}
REVIVED = {"id": "saab", "label": "Saab", "ptype": "Supplier / Contract", "rel": "tech",
           "note": "republished from the archive", "origin": "revived",
           "src": "https://example.com/a"}
# No `origin` key at all -- the shape a research agent writes, and 166 of the 169 rows
# in production on 2026-09-06.
HANDWRITTEN = {"id": "ELBIT", "label": "Elbit Systems", "ptype": "Joint venture",
               "rel": "jv", "kind": "Foreign OEM", "sig": 3,
               "note": "typed in by a human"}

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print("  ok   %s" % name)
    else:
        fail += 1
        print("  FAIL %s\n    got  %r\n    want %r" % (name, got, want))


def main():
    global fail
    import psycopg2
    dsn = os.environ.get("KSSL_DSN") or os.environ.get("KSSL_CORPUS_DSN")
    if not dsn:
        # SKIP, NOT FAIL -- the same reason test_carry_columns gives: deploy.yml runs
        # every test_*.py here on a GitHub runner that has no database and must not
        # hold credentials for the production one. A non-zero exit there fails
        # selfcheck, and the deploy job is `needs: selfcheck`, so nothing would ship.
        print("SKIP test_partnership_persistence: no KSSL_DSN "
              "(needs a real database; runs on a machine that has one)")
        return 0
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("SET statement_timeout='60s'")
    cur.execute("SET lock_timeout='10s'")

    def ids():
        cur.execute("SELECT partners FROM serving.competitors WHERE comp_id=%s", (CID,))
        row = cur.fetchone()[0]
        return [p.get("id") for p in (row or [])]

    def seed(partners):
        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (CID,))
        cur.execute("""INSERT INTO serving.competitors
                       (comp_id, ord, name, origin, partners)
                       VALUES (%s, 1998, 'Persist Test', 'pipeline', %s::jsonb)""",
                    (CID, json.dumps(partners)))

    try:
        # --- 2. THE RESET -------------------------------------------------------
        print("the reset keeps what this writer did not put there")
        seed([ENRICHED, REVIVED, HANDWRITTEN])
        cur.execute(PART_RESET_ONE_SQL, (CID,))
        check("last pass's own output goes", "adani" in ids(), False)
        check("a revived tie stays", "saab" in ids(), True)
        check("a hand-written tie with no origin key stays", "ELBIT" in ids(), True)

        # Running it twice must be a no-op: a pass is interrupted and re-run, and the
        # second reset must not eat the survivors of the first.
        before = ids()
        cur.execute(PART_RESET_ONE_SQL, (CID,))
        check("a second reset changes nothing", ids(), before)

        # A competitor freshly rebuilt has NULL here, not '[]'. jsonb_array_elements
        # of NULL is not an error but the coalesce has to be in the right place.
        seed([])
        cur.execute("UPDATE serving.competitors SET partners=NULL WHERE comp_id=%s",
                    (CID,))
        cur.execute(PART_RESET_ONE_SQL, (CID,))
        check("a NULL column resets to an empty array, not to NULL", ids(), [])

        # And a row that is all enriched empties completely rather than keeping one.
        seed([ENRICHED, dict(ENRICHED, id="other")])
        cur.execute(PART_RESET_ONE_SQL, (CID,))
        check("a row holding only this writer's ties empties", ids(), [])

        # --- 3. THE APPEND ------------------------------------------------------
        print("\nthe append adds without deleting")
        seed([REVIVED, HANDWRITTEN])
        cur.execute(PART_APPEND_SQL, (json.dumps([ENRICHED]), CID))
        check("the new tie lands", "adani" in ids(), True)
        check("and neither neighbour is touched",
              sorted(i for i in ids() if i != "adani"), ["ELBIT", "saab"])
        check("the new ties lead", ids()[0], "adani")

        # Two buckets in one pass both write to the same competitor -- a tie between
        # two tracked rivals lands under both, and the second flush must not drop the
        # first. This is the case the per-bucket commits made possible.
        cur.execute(PART_APPEND_SQL, (json.dumps([dict(ENRICHED, id="second")]), CID))
        check("a second flush in the same pass keeps the first",
              sorted(ids()), ["ELBIT", "adani", "saab", "second"])

        # An append onto a freshly rebuilt NULL column must not produce NULL.
        seed([])
        cur.execute("UPDATE serving.competitors SET partners=NULL WHERE comp_id=%s",
                    (CID,))
        cur.execute(PART_APPEND_SQL, (json.dumps([ENRICHED]), CID))
        check("appending to a NULL column works", ids(), ["adani"])

        # The append is scoped: it must never write onto a reference row.
        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (CID,))
        cur.execute("""INSERT INTO serving.competitors
                       (comp_id, ord, name, origin, partners)
                       VALUES (%s, 1998, 'Persist Test', 'reference', '[]'::jsonb)""",
                    (CID,))
        cur.execute(PART_APPEND_SQL, (json.dumps([ENRICHED]), CID))
        check("a reference competitor is never written to", cur.rowcount, 0)

        # --- THE SCOPE, which is what makes partial progress true ----------------
        # A global reset committed before the first model call would empty all 44
        # competitors up front, and an interrupted pass would then leave the tab
        # EMPTIER than it found it -- worse than the rollback it replaced. So the
        # reset must touch exactly one row, and the end-of-pass sweep must skip the
        # rows already rewritten.
        print("\nthe reset is scoped, so an interrupted pass cannot empty a row")
        OTHER = CID + "2"
        cur.execute("DELETE FROM serving.competitors WHERE comp_id IN (%s,%s)",
                    (CID, OTHER))
        for c in (CID, OTHER):
            cur.execute("""INSERT INTO serving.competitors
                           (comp_id, ord, name, origin, partners)
                           VALUES (%s, 1998, 'Persist Test', 'pipeline', %s::jsonb)""",
                        (c, json.dumps([ENRICHED, HANDWRITTEN])))

        def ids_of(c):
            cur.execute("SELECT partners FROM serving.competitors WHERE comp_id=%s",
                        (c,))
            return [p.get("id") for p in (cur.fetchone()[0] or [])]

        cur.execute(PART_RESET_ONE_SQL, (CID,))
        check("resetting one competitor leaves the other alone",
              ids_of(OTHER), ["adani", "ELBIT"])
        check("  while the one it named is reset", ids_of(CID), ["ELBIT"])

        # The sweep clears last pass's ties from every competitor this pass did NOT
        # rewrite -- otherwise a tie the corpus no longer supports lives forever.
        cur.execute(PART_RESET_REST_SQL, ([CID],))
        check("the sweep clears the competitors the pass never wrote to",
              ids_of(OTHER), ["ELBIT"])

        # ...and it must not undo the rows the pass DID write. Re-seed CID with a
        # fresh enriched tie, as a flush would leave it, then sweep with CID excluded.
        cur.execute(PART_APPEND_SQL, (json.dumps([dict(ENRICHED, id="fresh")]), CID))
        cur.execute(PART_RESET_REST_SQL, ([CID],))
        check("the sweep does not undo what this pass just wrote",
              ids_of(CID), ["fresh", "ELBIT"])

        # An empty exclusion list is the shape of a pass that found nothing at all.
        # `= ANY('{}')` is false, so NOT(...) is true and every row is swept -- the
        # cast is what stops Postgres refusing to infer a type for an empty array.
        cur.execute(PART_RESET_REST_SQL, ([],))
        check("an empty exclusion list sweeps everything", ids_of(CID), ["ELBIT"])
        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (OTHER,))

        # --- 1. THE REBUILD -----------------------------------------------------
        print("\nties survive the company rebuild")
        seed([REVIVED, HANDWRITTEN])
        snap = roster.carry_snapshot(cur, "comp_id=%s", (CID,))
        check("the snapshot picks the column up at all",
              [p.get("id") for p in (snap.get(CID, {}).get("partners") or [])],
              ["saab", "ELBIT"])
        # exactly what step_companies does: delete, re-insert with partners NULL,
        # then carry back.
        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (CID,))
        cur.execute("""INSERT INTO serving.competitors (comp_id, ord, name, origin)
                       VALUES (%s, 1998, 'Persist Test', 'pipeline')""", (CID,))
        check("the rebuild leaves the column empty", ids(), [])
        roster.carry_restore(cur, snap)
        check("the carry-forward puts every tie back", ids(), ["saab", "ELBIT"])

        # THE '[]' TRAP, stated as a test. carry_restore is a COALESCE, so it only
        # fills a column the rebuild left NULL -- an empty ARRAY is not NULL, and the
        # carry would silently do nothing. This is why step_companies now writes NULL.
        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (CID,))
        cur.execute("""INSERT INTO serving.competitors
                       (comp_id, ord, name, origin, partners)
                       VALUES (%s, 1998, 'Persist Test', 'pipeline', '[]'::jsonb)""",
                    (CID,))
        roster.carry_restore(cur, snap)
        check("an empty array would have beaten the carry (why the INSERT writes NULL)",
              ids(), [])

        # And the whole sequence, in the order a pass runs it: rebuild, carry, reset,
        # append. The hand-written tie has to be there at the end -- that is the
        # promise this change makes to the Partnerships tab.
        print("\none whole pass, in order")
        seed([REVIVED, HANDWRITTEN, ENRICHED])
        snap = roster.carry_snapshot(cur, "comp_id=%s", (CID,))
        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (CID,))
        cur.execute("""INSERT INTO serving.competitors (comp_id, ord, name, origin)
                       VALUES (%s, 1998, 'Persist Test', 'pipeline')""", (CID,))
        roster.carry_restore(cur, snap)
        cur.execute(PART_RESET_ONE_SQL, (CID,))
        cur.execute(PART_APPEND_SQL, (json.dumps([dict(ENRICHED, id="fresh")]), CID))
        check("after a full pass: this pass's tie, plus everything a human wrote",
              ids(), ["fresh", "saab", "ELBIT"])
        check("  and last pass's output is not doubled", ids().count("adani"), 0)
    finally:
        con.rollback()
        con.close()

    print()
    if fail:
        print("%d failure(s)" % fail)
        sys.exit(1)
    print("ok - hand-written and revived ties survive a pass; this writer's do not "
          "accumulate")


if __name__ == "__main__":
    main()
