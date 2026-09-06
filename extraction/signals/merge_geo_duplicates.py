"""One company, one pin -- and a ledger so the merge can be undone.

    python merge_geo_duplicates.py                 # dry run, the default
    python merge_geo_duplicates.py --apply
    python merge_geo_duplicates.py --fold-divisions --apply

WHAT IS WRONG. The geographic footprint carries four companies twice, each under an
uppercase archive code AND the canonical pipeline slug, with geo rows on both ids:

    BAE     + bae-systems        ELBIT  + elbit-systems
    HANWHA  + hanwha-aerospace   KNDS   + knds
    ADANI   + adani              (adani was merged in serving.competitors already)

WHY merge_roster_duplicates.py DID NOT CATCH THEM -- this is the whole point of this
file. That script discovers what to repoint by asking the catalogue:

    SELECT ... FROM pg_constraint WHERE contype='f'
                AND confrelid = 'serving.competitors'::regclass

which is the right instinct, and exactly why it missed these. serving.geo_comp.id and
serving.geo_presence.comp_id are BARE TEXT: db/02_serving.sql declares no foreign key
from either of them to serving.competitors (geo_presence's primary key is
(comp_id, country, ord) and there is no REFERENCES clause anywhere in the table). So
the geo tables are invisible to a query over pg_constraint, a roster merge repoints
every child it CAN see, reports success, and leaves the loser's twin standing on the
map. The ADANI/adani pair is that failure already on the board: `adani` won the roster
merge in an earlier session and ADANI still carries four India rows.

The FK is missing for a reason -- geo_comp holds archived reference companies that were
never in the pipeline roster, so a foreign key would refuse the very rows the archive is
made of. That is a defensible schema decision and it is not this script's job to change
it. What it means is that catalogue-driven discovery is structurally incapable of
covering these two tables, and they need a merge of their own. Adding the constraint
later would not make this file redundant either: it repoints rows the roster merge has
no reason to touch, because a geo twin can exist for a company that was never duplicated
in serving.competitors at all.

The pairing decision is `plan_merges`, which is pure and takes serving.geo_comp verbatim;
extraction/signals/test_merge_geo_duplicates.py exercises it -- and the missing foreign
key -- with no database. There is deliberately no --demo here: two copies of one fixture
do not stay in step by hand.

WHO DECIDES IDENTITY. Not this file. It asks aliases.canonical() / aliases.same(), the
identity layer serving_fill, enrich_serving and merge_roster_duplicates already share.
Writing the five pairs above into a constant here would put a fifth identity rule into a
repository that already has one too many.

  * default            -- only canonical-name equality ("BAE Systems" == "BAE Systems").
  * --fold-divisions   -- also aliases.same_org(), which admits a whole-word containment
                          ("Adani Defence" inside "Adani Defence & Aerospace"). That rule
                          would also swallow "BEML" into "BEML Land Systems", which are a
                          parent and a joint venture, so it is opt-in and every pair it
                          proposes is printed with the rule that produced it.

WHAT NEVER MOVES. The client. serving.geo_comp keys the client 'KSSL' while
serving.competitors keys it 'kalyani-strategic-systems', and discover_geo.sync_geo_comps
deliberately writes the client's presence rows onto the isBf id the map already plots it
under. Folding that pair would take the client off its own map. Any row with isBf true is
refused, loudly.

WHAT MOVES. geo_presence rows are repointed comp_id -> survivor, keeping their own
country and ord. The primary key is (comp_id, country, ord), so a row whose slot is
already taken on the survivor cannot move: that is the SAME market recorded twice, which
is what made the ids duplicates, and it is ledgered and dropped rather than left as an
orphan pointing at a geo_comp row this script is about to delete. (discover_geo hit
exactly this on hanwha-aerospace/Canada/1000 on production and it took the whole run
down.) origin is PRESERVED -- an archived reference row stays archived. Publishing it
is revive_geo.py's job and it has a grounding bar this script has no business skipping.

WHY IT NEEDS A LEDGER. Same reason merge_roster_duplicates has one: the deleted rows are
curated, the survivor's geo_comp row is updated in place, and undoing a merge should be a
read of a table rather than a restore. Every deleted geo_comp row and every deleted or
repointed geo_presence row is written to serving.geo_merge_ledger, whole, as jsonb,
BEFORE anything is changed.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import aliases                                                       # noqa: E402

LEDGER = """
CREATE TABLE IF NOT EXISTS serving.geo_merge_ledger (
    comp_id      text        NOT NULL,   -- the id that was folded away
    name         text        NOT NULL,
    merged_into  text        NOT NULL,   -- the id that survived
    rule         text        NOT NULL,   -- which identity rule matched
    reason       text        NOT NULL,
    geo_comp     jsonb       NOT NULL,   -- the whole deleted serving.geo_comp row
    presence     jsonb       NOT NULL,   -- every geo_presence row, and what became of it
    at           timestamptz NOT NULL DEFAULT now()
)
"""


def plan_merges(rows, fold_divisions=False):
    """[(id, name, origin, isBf)] -> ([(loser, winner, rule, reason)], [notes]).

    Pure, and the only place the decision is made, so test_merge_geo_duplicates.py can
    exercise every trap without a database. `rows` is serving.geo_comp verbatim.

    A loser is always an archive id (origin='reference'); a winner is always a pipeline
    id. The archive is the older id space, the map plots the pipeline one, and merging in
    the other direction would move live rows onto a code the dashboard does not serve.
    """
    notes = []
    live = [r for r in rows if r[2] == "pipeline"]
    plan = []
    for cid, name, origin, isbf in rows:
        if origin != "reference":
            continue
        if isbf:
            # The client. geo_comp keys it 'KSSL', serving.competitors keys it
            # 'kalyani-strategic-systems', and discover_geo puts the client's rows on
            # the isBf id on purpose. Folding it would unplot the client.
            notes.append("%s: the client (isBf) is never folded -- the map plots it by this id" % cid)
            continue
        exact = [r for r in live if aliases.same(name, r[1])]
        rule = "aliases.same(): one canonical name"
        if not exact and fold_divisions:
            exact = [r for r in live if aliases.same_org(name, r[1])]
            rule = "aliases.same_org(): whole-word containment (--fold-divisions)"
        if not exact:
            notes.append("%s (%s): no pipeline company matches -- left alone" % (cid, name))
            continue
        if len(exact) > 1:
            # Two live companies answer to one archive name. Guessing here is how a
            # subsidiary's rows end up on its parent's pin. Report and refuse.
            notes.append("%s (%s): AMBIGUOUS, matches %s -- refused, resolve by hand"
                         % (cid, name, ", ".join(r[0] for r in exact)))
            continue
        winner = exact[0]
        if winner[0] == cid:
            continue
        plan.append((cid, winner[0], rule,
                     "same company as %s (%s)" % (winner[0], winner[1])))
    return plan, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=None)
    # DRY RUN IS THE DEFAULT, unlike merge_roster_duplicates.py where apply is. This one
    # deletes curated archive rows, so the safe outcome has to be the one you get by
    # typing nothing.
    ap.add_argument("--apply", action="store_true",
                    help="write. Without it nothing is changed.")
    ap.add_argument("--fold-divisions", action="store_true",
                    help="also merge on whole-word containment (aliases.same_org)")
    a = ap.parse_args()

    import psycopg2
    dsn = a.dsn or os.environ.get("KSSL_DSN")
    if not dsn:
        sys.exit("no DSN: set KSSL_DSN")
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("SET statement_timeout = '60s'")
    cur.execute("SET lock_timeout = '8s'")

    # Say out loud that the catalogue cannot see these tables -- the sentence a future
    # reader needs is the one merge_roster_duplicates prints for the roster.
    cur.execute("""SELECT count(*) FROM pg_constraint
                    WHERE contype = 'f'
                      AND confrelid = 'serving.competitors'::regclass
                      AND conrelid IN ('serving.geo_comp'::regclass,
                                       'serving.geo_presence'::regclass)""")
    n_fk = cur.fetchone()[0]
    print("foreign keys from the geo tables to serving.competitors: %d%s"
          % (n_fk, "   <- why a roster merge cannot reach them" if not n_fk else ""))

    cur.execute("""SELECT id, name, origin, "isBf" FROM serving.geo_comp ORDER BY ord""")
    rows = [(r[0], r[1], r[2], bool(r[3])) for r in cur.fetchall()]
    print("geo_comp rows: %d (%d pipeline, %d reference)"
          % (len(rows), sum(1 for r in rows if r[2] == "pipeline"),
             sum(1 for r in rows if r[2] == "reference")))

    plan, notes = plan_merges(rows, fold_divisions=a.fold_divisions)
    for n in notes:
        print("   note  %s" % n)
    if not plan:
        print("\nnothing to merge")
        con.close()
        return 0

    print("\n--- plan ---")
    for loser, winner, rule, _why in plan:
        cur.execute("SELECT count(*) FROM serving.geo_presence WHERE comp_id=%s", (loser,))
        n_rows = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM serving.geo_presence WHERE comp_id=%s", (winner,))
        n_win = cur.fetchone()[0]
        print("   %-10s -> %-24s %d row(s) move onto %d   [%s]"
              % (loser, winner, n_rows, n_win, rule))

    if not a.apply:
        print("\nDRY RUN -- nothing written. Re-run with --apply.")
        con.close()
        return 0

    cur.execute(LEDGER)
    for loser, winner, rule, why in plan:
        cur.execute("SELECT to_jsonb(g) FROM serving.geo_comp g WHERE id=%s", (loser,))
        got = cur.fetchone()
        if not got:
            continue
        comp_row = got[0]

        # Which of the loser's rows can move, and which are the same market twice.
        cur.execute("""SELECT to_jsonb(g), EXISTS (SELECT 1 FROM serving.geo_presence t
                                                    WHERE t.comp_id=%s AND t.country=g.country
                                                      AND t.ord=g.ord)
                         FROM serving.geo_presence g WHERE g.comp_id=%s""",
                    (winner, loser))
        presence = [{"row": r[0], "fate": "dropped (survivor already holds this country+ord)"
                     if r[1] else "moved"} for r in cur.fetchall()]

        cur.execute("""INSERT INTO serving.geo_merge_ledger
                       (comp_id, name, merged_into, rule, reason, geo_comp, presence)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (loser, comp_row.get("name") or loser, winner, rule, why,
                     json.dumps(comp_row, ensure_ascii=False, default=str),
                     json.dumps(presence, ensure_ascii=False, default=str)))

        # origin is NOT rewritten: an archived row stays archived, and publishing it is
        # revive_geo.py's decision, behind its grounding bar.
        cur.execute("""UPDATE serving.geo_presence g SET comp_id=%s
                        WHERE g.comp_id=%s
                          AND NOT EXISTS (SELECT 1 FROM serving.geo_presence t
                                           WHERE t.comp_id=%s AND t.country=g.country
                                             AND t.ord=g.ord)""",
                    (winner, loser, winner))
        moved = cur.rowcount
        cur.execute("DELETE FROM serving.geo_presence WHERE comp_id=%s", (loser,))
        dropped = cur.rowcount
        # Fill a gap on the survivor rather than overwrite it -- a merge must not leave
        # the surviving row thinner than it found it.
        cur.execute("""UPDATE serving.geo_comp
                          SET hq = COALESCE(hq, %s), dir = COALESCE(dir, %s),
                              updated_at = now()
                        WHERE id = %s""",
                    (comp_row.get("hq"), comp_row.get("dir"), winner))
        cur.execute("DELETE FROM serving.geo_comp WHERE id=%s", (loser,))
        print("   %s -> %s: %d moved, %d dropped as duplicates; ledgered"
              % (loser, winner, moved, dropped))

    con.commit()
    cur.execute("SELECT count(*) FROM serving.geo_comp")
    print("\ngeo_comp now: %d" % cur.fetchone()[0])
    cur.execute("SELECT count(*) FROM serving.geo_merge_ledger")
    print("ledger rows: %d  (undo reads this table)" % cur.fetchone()[0])
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
