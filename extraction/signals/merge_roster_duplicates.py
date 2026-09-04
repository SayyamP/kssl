"""One company, one roster row -- and a ledger so the merge can be undone.

    python merge_roster_duplicates.py --dry-run
    python merge_roster_duplicates.py

The Competitor tab counted 156 rivals, and four of those rows were not four
companies. Three were one company served twice under two spellings, and one was
not a company at all.

WHO DECIDES. Not this file. It asks aliases.canonical(), which is the identity
layer serving_fill and enrich_serving already share, and aliases.is_description(),
which refuses a phrase carried out of a sentence. Encoding the pairs here would
put a fourth identity rule in a repo that already has two.

WHY IT NEEDS A LEDGER. A merge deletes a row that a human curated -- an
assessment, sources, partners -- and the join is not one key: signal_card holds
the display NAME, competitor_news holds the comp_id. Getting that wrong loses
evidence silently, so every deleted row is written to
serving.competitor_merge_ledger first, whole, as jsonb. Undoing a merge is then a
read of that table rather than a re-crawl.

WHAT MOVES. Cards are repointed by NAME; every table with a foreign key to
serving.competitors is repointed by comp_id, and that list is read out of the
catalogue rather than typed here. The first apply died on a lock held by an INSERT
into serving.competitor_metrics -- a third referencing table this script had never
heard of, whose FK is ON DELETE CASCADE. A merge that does not know what points at
the row it deletes does not fail loudly; it drops those rows and says nothing.

The loser's products, partners and sources are unioned into the survivor,
deduplicated, because the same source URL usually appears under both spellings.
The survivor's own scalar fields (assessment, sector, HQ, website) are NOT
overwritten -- a merge should not leave a row thinner than it found it.
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
CREATE TABLE IF NOT EXISTS serving.competitor_merge_ledger (
    comp_id      text        NOT NULL,
    name         text        NOT NULL,
    merged_into  text,                      -- NULL when the row was not a company
    reason       text        NOT NULL,
    row          jsonb       NOT NULL,      -- the whole deleted row
    moved        jsonb       NOT NULL,      -- what was repointed, and how much
    at           timestamptz NOT NULL DEFAULT now()
)
"""


def jlist(v):
    return v if isinstance(v, list) else []


def union(a, b):
    """Concatenate two jsonb lists, dropping repeats. Dicts compare by their JSON
    text because a source is a {url, label} pair and the same URL arrives under
    both spellings."""
    out, seen = [], set()
    for item in jlist(a) + jlist(b):
        k = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import psycopg2
    dsn = a.dsn or os.environ.get("KSSL_DSN") or os.environ.get("KSSL_CORPUS_DSN")
    if not dsn:
        sys.exit("no DSN: set KSSL_DSN")
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("SET statement_timeout = '60s'")
    cur.execute("SET lock_timeout = '8s'")

    # Every table with a foreign key to serving.competitors, read from the catalogue
    # rather than typed here. The first apply died on a lock held by an INSERT into
    # serving.competitor_metrics -- a referencing table this script had never heard
    # of, and one whose FK is ON DELETE CASCADE. A merge that does not know what
    # points at the row it deletes does not fail loudly; it drops those rows silently.
    cur.execute("""SELECT src.relname, a.attname
                     FROM pg_constraint con
                     JOIN pg_class src ON src.oid = con.conrelid
                     JOIN unnest(con.conkey) WITH ORDINALITY k(attnum, ord) ON true
                     JOIN pg_attribute a ON a.attrelid = src.oid AND a.attnum = k.attnum
                    WHERE con.contype = 'f'
                      AND con.confrelid = 'serving.competitors'::regclass""")
    REFS = cur.fetchall()
    print("tables referencing serving.competitors: %s"
          % ", ".join("%s.%s" % tuple(r) for r in REFS))

    cur.execute("""SELECT comp_id, name, ord, products, partners, srcs, assess
                     FROM serving.competitors WHERE origin='pipeline'""")
    rows = {r[0]: r for r in cur.fetchall()}
    print("pipeline roster: %d" % len(rows))

    # --- group by the shared identity layer, never by a rule written here -------
    groups = {}
    for cid, (cid2, name, ordv, prods, partners, srcs, assess) in rows.items():
        groups.setdefault(aliases.canonical(name), []).append(cid)

    plan = []          # (loser_cid, winner_cid or None, reason)
    for canon, cids in groups.items():
        if len(cids) < 2:
            continue
        # WHICH ROW SURVIVES. The canonical name first, then evidence.
        #
        # Evidence alone chose wrongly on the first dry run: HII carried more
        # products and sources than "Huntington Ingalls Industries", so the merge
        # proposed keeping the acronym as the company's display name. The roster is
        # read by people; the canonical spelling is the answer, and the evidence from
        # the other row is unioned in either way, so nothing is lost by preferring it.
        def weight(c):
            r = rows[c]
            is_canon = aliases.fold(r[1]) == aliases.fold(canon)
            return (is_canon,
                    len(jlist(r[3])) + len(jlist(r[4])) + len(jlist(r[5])),
                    len(r[1] or ""))
        winner = max(cids, key=weight)
        for c in cids:
            if c != winner:
                plan.append((c, winner, "duplicate of %s under aliases.canonical()" % canon))

    for cid, r in rows.items():
        if aliases.is_description(r[1]):
            plan.append((cid, None, "aliases.is_description(): a phrase, not a company"))

    if not plan:
        print("nothing to merge")
        return

    print("\n--- plan ---")
    for loser, winner, why in plan:
        print("   %-26s -> %-26s %s" % (rows[loser][1], rows[winner][1] if winner else "(remove)", why))

    if not a.dry_run:
        cur.execute(LEDGER)

    for loser, winner, why in plan:
        lname = rows[loser][1]
        cur.execute("SELECT count(*) FROM serving.signal_card WHERE company=%s", (lname,))
        n_cards = cur.fetchone()[0]
        moved = {"signal_card.company": n_cards}
        for tbl, col in REFS:
            cur.execute("SELECT count(*) FROM serving.%s WHERE %s=%%s" % (tbl, col), (loser,))
            moved["%s.%s" % (tbl, col)] = cur.fetchone()[0]
        print("\n%s: %d card(s), %s" % (lname, n_cards,
              ", ".join("%d %s" % (v, k) for k, v in moved.items()
                        if k != "signal_card.company")))

        if a.dry_run:
            continue

        cur.execute("""SELECT to_jsonb(c) FROM serving.competitors c WHERE comp_id=%s""", (loser,))
        whole = cur.fetchone()[0]

        if winner:
            wname = rows[winner][1]
            cur.execute("UPDATE serving.signal_card SET company=%s WHERE company=%s",
                        (wname, lname))
            for tbl, col in REFS:
                # A child keyed one-per-company would collide on the survivor, so the
                # loser's copy is dropped rather than repointed onto a duplicate.
                # competitor_news is many-per-company and always moves.
                cur.execute("SELECT count(*) FROM serving.%s WHERE %s=%%s" % (tbl, col),
                            (winner,))
                if cur.fetchone()[0] and tbl != "competitor_news":
                    cur.execute("DELETE FROM serving.%s WHERE %s=%%s" % (tbl, col), (loser,))
                else:
                    cur.execute("UPDATE serving.%s SET %s=%%s WHERE %s=%%s" % (tbl, col, col),
                                (winner, loser))
            for col in ("products", "partners", "srcs"):
                cur.execute("SELECT %s FROM serving.competitors WHERE comp_id=%%s" % col, (winner,))
                wv = cur.fetchone()[0]
                cur.execute("SELECT %s FROM serving.competitors WHERE comp_id=%%s" % col, (loser,))
                lv = cur.fetchone()[0]
                merged = union(wv, lv)
                cur.execute("UPDATE serving.competitors SET %s=%%s, updated_at=now() "
                            "WHERE comp_id=%%s" % col, (json.dumps(merged, ensure_ascii=False), winner))
                moved["%s(+%d)" % (col, len(merged) - len(jlist(wv)))] = len(merged)
        else:
            # nothing to repoint the evidence AT -- the article names no company, so the
            # card and its news row go with the roster entry rather than dangling
            cur.execute("DELETE FROM serving.signal_detail WHERE id IN "
                        "(SELECT id FROM serving.signal_card WHERE company=%s)", (lname,))
            cur.execute("DELETE FROM serving.signal_card WHERE company=%s", (lname,))
            # the CASCADE would take the children anyway; doing it explicitly keeps
            # the ledger's `moved` count honest about what went with the row
            for tbl, col in REFS:
                cur.execute("DELETE FROM serving.%s WHERE %s=%%s" % (tbl, col), (loser,))

        cur.execute("""INSERT INTO serving.competitor_merge_ledger
                       (comp_id, name, merged_into, reason, row, moved)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (loser, lname, winner, why, json.dumps(whole, ensure_ascii=False),
                     json.dumps(moved, ensure_ascii=False)))
        cur.execute("DELETE FROM serving.competitors WHERE comp_id=%s", (loser,))
        print("   merged; ledgered as %s" % loser)

    if a.dry_run:
        print("\nDRY RUN -- nothing written.")
        return

    con.commit()
    cur.execute("SELECT count(*) FROM serving.competitors WHERE origin='pipeline'")
    print("\nroster now: %d" % cur.fetchone()[0])
    cur.execute("SELECT count(*) FROM serving.competitor_merge_ledger")
    print("ledger rows: %d  (undo reads this table)" % cur.fetchone()[0])


if __name__ == "__main__":
    main()
