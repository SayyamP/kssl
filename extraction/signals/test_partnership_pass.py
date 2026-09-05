"""One whole partnership pass, end to end, against a real Postgres and a stub model.

    createdb kssl_parttest && psql kssl_parttest -f db/00_*.sql ...   (db/[0-9][0-9]_*.sql)
    KSSL_TEST_DSN=postgresql://.../kssl_parttest python3 test_partnership_pass.py

test_partnership_buckets pins which questions get asked; test_partnership_persistence
pins which ties survive one SQL statement. Neither runs step_partnerships. This does --
the shipped function, against real tables, with `_ask` swapped for a scripted model so
the answers are known and the assertions are about the STEP, not about a 7B model's
mood.

WHAT ONLY AN END-TO-END RUN CATCHES:

  * The commit boundary. The whole point of this change is that a pass killed by the
    two-hourly timer keeps what it found. That is not visible in a function that
    returns a dict; it is visible when you kill the run and look at the table.
  * Both sides landing. A tie between two tracked rivals must appear under both, and
    the per-bucket flush made it possible to write a competitor whose own bucket has
    not been reached yet.
  * The client roster. serving.partner is deleted and rebuilt at the END now, in one
    transaction, because deleting it at the start would have left it empty for the
    whole pass and empty for good if the pass died.

REFUSES TO RUN ON A REAL DATABASE. This function COMMITS -- it cannot be wrapped in a
rollback like its two sibling tests -- so it needs a database of its own, and the guard
below is the only thing standing between a careless DSN and the production serving
tables. Same shape as the guard in db/sanitise_replica.sql, and for the same reason.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import enrich_serving as E
except Exception as e:                                              # noqa: BLE001
    print("SKIP test_partnership_pass: cannot import enrich_serving (%s: %s)"
          % (type(e).__name__, e))
    sys.exit(0)

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print("  ok   %s" % name)
    else:
        fail += 1
        print("  FAIL %s\n    got  %r\n    want %r" % (name, got, want))


# --------------------------------------------------------------- the scripted model
# Keyed on a word in the statement, so a reordered corpus still gets the same answers.
ANSWERS = {
    # `basis` is the words the model says decided the type; a narrow type without one
    # is downgraded to the catch-all, so every scripted answer carries one that really
    # appears in its statement or quote.
    "REPLY_JV": '{"a":"Saab","b":"Adani Defence","rel":"jv","basis":"joint venture",'
                '"note":"agreed to jointly manufacture Carl-Gustaf rounds in India",'
                '"date":"2024-03-01","country":"India"}',
    "REPLY_BOTH": '{"a":"Saab","b":"Rheinmetall","rel":"strategic",'
                  '"note":"signed a memorandum to co-develop a turret for wheeled '
                  'vehicles","date":null,"country":"Germany"}',
    "REPLY_CLIENT": '{"a":"Bharat Forge","b":"Paramount Group","rel":"technology",'
                    '"basis":"technology transfer",'
                    '"note":"agreed to transfer technology for a mine protected '
                    'vehicle","date":null,"country":"South Africa"}',
    "REPLY_NONE": "NONE",
    # NOT a partnership: must be counted and named, never stored.
    "REPLY_ACQ": '{"a":"Elbit Systems","b":"Sparton","rel":"acquisition",'
                 '"note":"acquired a majority stake in the sonobuoy maker",'
                 '"date":null,"country":"United States"}',
    "REPLY_ORPHAN": '{"a":"Thales","b":"Hensoldt","rel":"jv",'
                    '"note":"agreed to jointly build a radar for naval vessels",'
                    '"date":null,"country":"France"}',
    "REPLY_BOOM": None,          # raises: the farm 502ing mid-pass
}


def scripted(prompt, npredict=600, timeout=None):
    for tag, reply in ANSWERS.items():
        if tag in prompt:
            if reply is None:
                raise RuntimeError("502 Bad Gateway (scripted farm failure)")
            return reply
    return "NONE"


def prop(s, p, o, q=""):
    return {"s": s, "p": p, "o": o, "q": q, "t": None, "pl": None, "m": None}


COMPETITORS = [("saab", "Saab"), ("rheinmetall", "Rheinmetall"),
               ("adani-defence", "Adani Defence"), ("elbit-systems", "Elbit Systems")]

# Every proposition carries its scripted answer's tag in the OBJECT, so the stub can
# find it in the prompt the real function builds.
CORPUS = {
    "d_jv":     [prop("Saab", "signed a joint venture with", "Adani REPLY_JV",
                      "Saab and Adani Defence signed the agreement")],
    "d_both":   [prop("Saab", "signed an MoU with", "Rheinmetall REPLY_BOTH",
                      "Saab and Rheinmetall signed a memorandum")],
    "d_client": [prop("Bharat Forge", "signed a licence with", "Paramount REPLY_CLIENT",
                      "Bharat Forge and Paramount Group agreed a technology transfer")],
    "d_none":   [prop("Elbit Systems", "partnered with", "somebody REPLY_NONE")],
    "d_acq":    [prop("Elbit Systems", "partnered with", "Sparton REPLY_ACQ",
                      "Elbit Systems and Sparton")],
    "d_boom":   [prop("Elbit Systems", "signed an MoU with", "anybody REPLY_BOOM")],
    # names no tracked company: never asked about, so its scripted answer never fires
    "d_skip":   [prop("Thales", "signed a joint venture with", "Hensoldt REPLY_ORPHAN")],
}
DOCS = {d: {"title": "T " + d, "source": "src", "lang": "en",
            "url": "https://defencenews%s.example.com/a" % i, "set": None}
        for i, d in enumerate(CORPUS)}


def seed(cur):
    cur.execute("TRUNCATE serving.competitors CASCADE")
    cur.execute("TRUNCATE serving.partner")
    for i, (cid, name) in enumerate(COMPETITORS, start=1):
        cur.execute("""INSERT INTO serving.competitors
                       (comp_id, ord, name, dir, origin, partners)
                       VALUES (%s,%s,%s,'rival','pipeline',%s::jsonb)""",
                    (cid, 1000 + i, name, json.dumps([
                        # one hand-written and one revived tie per competitor: the
                        # things a pass must never eat
                        {"id": "HUMAN", "label": "A Human Tie", "ptype": "Joint venture",
                         "rel": "jv", "note": "typed in by a person"},
                        {"id": "revived-co", "label": "Revived Co", "rel": "tech",
                         "ptype": "Technology / ToT", "note": "from the archive",
                         "origin": "revived"}])))
    # a reference competitor: nothing in this step may ever touch it
    cur.execute("""INSERT INTO serving.competitors
                   (comp_id, ord, name, origin, partners)
                   VALUES ('ref-co', 5, 'Reference Co', 'reference',
                           '[{"id":"ref-tie","label":"Ref Tie"}]'::jsonb)""")


def ties(cur, cid):
    cur.execute("SELECT partners FROM serving.competitors WHERE comp_id=%s", (cid,))
    return [p.get("id") for p in (cur.fetchone()[0] or [])]


def main():
    global fail
    import psycopg2
    dsn = os.environ.get("KSSL_TEST_DSN")
    if not dsn:
        print("SKIP test_partnership_pass: no KSSL_TEST_DSN "
              "(needs a THROWAWAY database -- this step commits and cannot roll back)")
        return 0
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("SELECT current_database()")
    db = cur.fetchone()[0]
    # THE GUARD. This function commits. A DSN pointing at `kssl` would truncate the
    # serving tables of whichever environment it reached.
    if db == "kssl" or not db.endswith("test"):
        print("REFUSED: KSSL_TEST_DSN points at %r. This test TRUNCATEs and COMMITs; "
              "it runs only on a throwaway database whose name ends in 'test'." % db)
        return 2
    cur.execute("SET statement_timeout='120s'")

    real_ask = E._ask
    E._ask = scripted
    try:
        seed(con.cursor())
        con.commit()

        print("a full pass")
        out = E.step_partnerships(cur, con, DOCS, CORPUS)

        # ---- what the model was asked -----------------------------------------
        # d_skip names neither a competitor nor the client, so it is never asked --
        # and its scripted answer (a perfectly good Thales/Hensoldt tie) never fires.
        # That is the saving: 71% of the old pass's calls were shaped exactly like it.
        check("a statement naming no tracked company is never asked about",
              out["candidates"] - out["named"], 1)
        check("  and so it cannot become an orphan", out["dropped_unprofiled"], 0)

        # ---- errors are not refusals ------------------------------------------
        check("a farm failure is counted as an error", out["errored"], 1)
        check("  and not as the model refusing", out["refused"], 1)

        # ---- the ties landed ---------------------------------------------------
        check("Saab has this pass's ties, in front of the human's",
              ties(cur, "saab"), ["adani-defence", "rheinmetall", "HUMAN", "revived-co"])
        check("a tie between two tracked rivals lands under BOTH",
              ties(cur, "rheinmetall"), ["saab", "HUMAN", "revived-co"])
        check("  including the side whose own bucket came later",
              ties(cur, "adani-defence"), ["saab", "HUMAN", "revived-co"])
        check("a competitor the pass found nothing for keeps what it had",
              ties(cur, "elbit-systems"), ["HUMAN", "revived-co"])
        check("a reference competitor is untouched", ties(cur, "ref-co"), ["ref-tie"])

        # ---- the client roster -------------------------------------------------
        cur.execute("SELECT id, label, ptype FROM serving.partner ORDER BY ord")
        check("the client's own tie becomes a serving.partner row",
              cur.fetchall(), [("plp_01", "Paramount Group", "Technology / ToT")])

        # ---- evidence ----------------------------------------------------------
        cur.execute("""SELECT p->>'src' IS NOT NULL AND p->>'srcnote' IS NOT NULL
                         FROM serving.competitors c, jsonb_array_elements(c.partners) p
                        WHERE c.comp_id='saab' AND p->>'origin'='enriched'""")
        check("every tie this pass wrote carries a source and a source note",
              sorted({r[0] for r in cur.fetchall()}), [True])

        # ---- what Part 2 added, on the table rather than in a dict --------------
        # An acquisition reached the model, was correctly identified, and must be
        # counted and named rather than stored -- the two on the tab in September were
        # never noticed precisely because nothing counted them.
        check("an acquisition is counted, not stored", out.get("not_a_tie"), 1)
        check("  and it is named by kind",
              out.get("not_a_tie_by_kind"), {"acquisition": 1})
        cur.execute("""SELECT count(*) FROM serving.competitors c,
                              jsonb_array_elements(c.partners) p
                        WHERE p->>'rel' = 'acquisition'""")
        check("  no acquisition reached the table", cur.fetchone()[0], 0)

        # Every stored tie carries the source verdict, not just prose about it, and a
        # status -- the two fields that had no representation at all before.
        cur.execute("""SELECT DISTINCT p->>'confidence', p->>'status'
                         FROM serving.competitors c, jsonb_array_elements(c.partners) p
                        WHERE p->>'origin'='enriched'""")
        got = sorted(cur.fetchall())
        check("every tie carries a confidence and a status",
              [g for g in got if g[0] and g[1]], got)
        check("  a single scripted source grades as single_source",
              sorted({g[0] for g in got}), ["single_source"])

        # The precise type reaches the row, instead of collapsing into tech/other.
        cur.execute("""SELECT DISTINCT p->>'rel', p->>'ptype'
                         FROM serving.competitors c, jsonb_array_elements(c.partners) p
                        WHERE p->>'origin'='enriched' ORDER BY 1""")
        check("the precise type and its label are both stored",
              cur.fetchall(), [("jv", "Joint venture"),
                               ("strategic", "Partnership / MoU")])

        # ---- IDEMPOTENCE: the thing the old reset predicate got wrong -----------
        print("\nand again, on the same corpus")
        before = ties(cur, "saab")
        out2 = E.step_partnerships(cur, con, DOCS, CORPUS)
        check("a second pass writes the same ties, not twice as many",
              ties(cur, "saab"), before)
        check("  the human's tie is still there", "HUMAN" in ties(cur, "saab"), True)
        check("  and so is the revived one", "revived-co" in ties(cur, "saab"), True)
        # Asserted against the TABLE, not against out2["client_rows"] -- that is an
        # in-memory counter, and a serving.partner rebuilt with duplicates would still
        # have reported 1.
        cur.execute("SELECT count(*) FROM serving.partner WHERE origin='pipeline'")
        check("  the client roster is rebuilt, not duplicated", cur.fetchone()[0], 1)

        # ---- PARTIAL PROGRESS: the whole reason for the per-bucket commits ------
        print("\nan interrupted pass keeps what it found")
        seed(con.cursor())
        con.commit()
        # Buckets are built in sorted document order, so the first is elbit-systems
        # (d_boom, d_none) -- two calls that produce nothing, one of them the scripted
        # farm failure. Four calls therefore finish saab's bucket and stop at the start
        # of rheinmetall's, which is exactly the state the old code threw away.
        #
        # SEED IT WITH LAST PASS'S OUTPUT. Without an origin:'enriched' entry already on
        # the row, this cannot tell a scoped reset from a global one -- both leave the
        # human ties alone, and the assertion below would pass against the very bug it
        # exists to catch.
        cur.execute("""UPDATE serving.competitors
                          SET partners = partners || %s::jsonb
                        WHERE origin='pipeline'""",
                    (json.dumps([{"id": "lastpass", "label": "Last Pass Co",
                                  "rel": "jv", "ptype": "Joint venture",
                                  "origin": "enriched"}]),))
        con.commit()
        out3 = E.step_partnerships(cur, con, DOCS, CORPUS, limit=4)
        check("the limit is honoured", out3["calls"], 4)
        cur.execute("""SELECT count(*) FROM serving.competitors c,
                              jsonb_array_elements(c.partners) p
                        WHERE p->>'origin' = 'enriched'""")
        check("what it found before stopping is on the table", cur.fetchone()[0] > 0,
              True)
        # Adani's OWN bucket is never reached at this limit -- and it has its tie
        # anyway, landed from Saab's bucket, because a tie is written to every side
        # that has a row. Under the old shape this whole state was rolled back.
        check("a competitor gets its tie from the other side's bucket",
              ties(cur, "adani-defence"), ["saab", "HUMAN", "revived-co"])
        # THE ASSERTION THE WHOLE CHANGE RESTS ON. elbit-systems was reached, both its
        # calls produced nothing, and the pass then stopped before its bucket could be
        # rewritten. It must still hold LAST PASS's tie. A global reset committed up
        # front -- the shape this replaced -- would have taken 'lastpass' from every
        # competitor before the first model call, leaving the tab thinner than it
        # found it, which is worse than the rollback it was meant to improve on.
        # sorted(): the seed above appended, so position here says nothing. What is
        # being asserted is that the entry is still on the row at all.
        check("an interrupted pass leaves last pass's ties where it did not rewrite",
              sorted(ties(cur, "elbit-systems")),
              ["HUMAN", "lastpass", "revived-co"])
        # ...and where it DID write, last pass's output is replaced, not stacked.
        check("  and replaces them where it did",
              "lastpass" in ties(cur, "saab"), False)
    finally:
        E._ask = real_ask
        con.rollback()
        con.close()

    print()
    if fail:
        print("%d failure(s)" % fail)
        sys.exit(1)
    print("ok - a pass lands ties on both sides, keeps human work, does not double, "
          "and commits as it goes")


if __name__ == "__main__":
    # `main()` alone would discard the return code, and the REFUSED path would exit 0 --
    # a DSN pointing at a real database would read as a pass. A skip is 0; a refusal
    # is not.
    sys.exit(main() or 0)
