"""Recompute the date on cards that are already on the dashboard.

The date logic is fixed for cards written from now on; this corrects the ones
already stored. It rewrites `signal_card.ago` and the "Date" fact in
`signal_detail.facts`, using exactly the same article_date() the pipeline now
uses, so the two can never disagree.

    python fix_card_dates.py --dry-run     # show what would change
    python fix_card_dates.py               # apply refinements
    python fix_card_dates.py --allow-move  # also apply the ones that move a date
    python fix_card_dates.py --list-stale  # cards now outside the recency window

TWO KINDS OF CHANGE, and they do not carry the same risk.

A REFINEMENT keeps the year and month and only sharpens the day: "Sep 2026" ->
"1 Sep 2026". It cannot reorder the feed across months and it cannot contradict
anything already on screen, so it applies by default.

A MOVE changes the year or month, or drops precision the stored row already had.
A dry run on 2026-09-04 wanted five of those, and every one was a LOSS -- "Jul
2026" to "2017", "Jun 2026" to "2024", three more down to a bare year -- while
the corpus was timing out and article_date was therefore reading less evidence
than the run that wrote the row. A migration that quietly makes the dashboard
vaguer is worse than no migration, so moves are reported and skipped unless an
operator asks for them.

The bug this file had until 2026-09-04: it compared only `signal_card.ago`,
which is month-precision by construction (`ago_of(ymd[:2])`). A card whose month
was right but whose "Date" fact had no day therefore counted as "already
correct" and was never touched -- so the fix that taught article_date to keep a
non-English day could not reach a single stored row. It compares the fact now.

It does NOT delete anything. Cards that turn out to be older than the recency
window are reported, never removed -- dropping a client's feed is an operator's
decision, not a migration's.
"""
import argparse
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import serving_fill as sf                                            # noqa: E402


def load_env(p):
    out = {}
    if not os.path.exists(p):
        return out
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--env", default="/opt/kssl/app/extraction/.env")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-stale", action="store_true")
    ap.add_argument("--allow-move", action="store_true",
                    help="also apply changes that move the year/month or lose precision")
    a = ap.parse_args()

    import psycopg2
    env = load_env(a.env)
    dsn = a.dsn or env.get("KSSL_DSN") or env.get("KSSL_CORPUS_DSN")
    if not dsn:
        sys.exit("no DSN")
    con = psycopg2.connect(dsn)
    cur = con.cursor()

    cutoff, cur_year = sf.recent_cutoff()
    cur.execute("""SELECT c.id, c.ago, d.facts FROM serving.signal_card c
                    LEFT JOIN serving.signal_detail d ON d.id = c.id
                    WHERE c.origin='pipeline' AND c.id LIKE 'pl_%'""")
    cards = cur.fetchall()
    print("pipeline cards: %d" % len(cards))

    def date_fact(facts):
        """The 'Date' the drawer shows, which is where the DAY lives."""
        if not facts:
            return None
        rows = facts if isinstance(facts, list) else json.loads(facts)
        for f in rows:
            if isinstance(f, list) and len(f) == 2 and f[0] == "Date":
                return f[1]
        return None

    fix, moves, unchanged, undated, stale = [], [], 0, 0, []
    for cid, ago, facts in cards:
        ymd = sf.article_date(cur, cid[3:])
        if ymd is None:
            undated += 1
            continue
        want = sf.ago_of(ymd[:2])
        want_fact = sf.date_label(ymd)
        have_fact = date_fact(facts)
        if not sf.is_recent_ym(ymd[:2], cutoff, cur_year):
            stale.append((cid, want))
        if want == (ago or "") and want_fact == have_fact:
            unchanged += 1
            continue
        # A refinement keeps the month the row already claims and only sharpens
        # it; anything else moves the date and is held back (see the module note).
        old = sf.parse_date(have_fact or ago or "")
        refine = (old is not None and old[:2] == ymd[:2]
                  and old[2] is None and ymd[2] is not None)
        (fix if refine else moves).append((cid, have_fact or ago, want_fact, ymd))

    print("  already correct : %d" % unchanged)
    print("  TO REFINE       : %d  (same month, gains a day)" % len(fix))
    print("  moves (%s): %d"
          % ("will apply" if a.allow_move else "reported, NOT applied", len(moves)))
    print("  undated         : %d" % undated)
    print("  outside the %d-day window (reported, NOT removed): %d"
          % (sf.RECENT_WINDOW_DAYS, len(stale)))

    if a.list_stale:
        print("\n--- cards older than the recency window ---")
        for cid, want in sorted(stale, key=lambda x: x[1]):
            print("   %-28s %s" % (cid, want))
        return

    if a.allow_move:
        fix = fix + moves
    elif moves:
        print("\n--- moves held back (re-run with --allow-move to apply) ---")
        for cid, old, want, _y in moves:
            print("   %-28s %-12s -> %s" % (cid, old or "(none)", want))

    print("\n--- %s ---" % ("would correct" if a.dry_run else "correcting"))
    for cid, old, want, _y in fix[:20]:
        print("   %-28s %-12s -> %s" % (cid, old or "(none)", want))
    if len(fix) > 20:
        print("   ... and %d more" % (len(fix) - 20))

    if a.dry_run:
        print("\nDRY RUN -- nothing written.")
        return

    n = 0
    for cid, _old, _want, ymd in fix:
        want = sf.ago_of(ymd[:2])
        cur.execute("UPDATE serving.signal_card SET ago=%s, updated_at=now() "
                    "WHERE id=%s", (want, cid))
        # signal_detail carries the same date as a fact; leaving it stale would
        # make the drawer contradict the card it was opened from.
        cur.execute("SELECT facts FROM serving.signal_detail WHERE id=%s", (cid,))
        row = cur.fetchone()
        if row and row[0]:
            facts = row[0] if isinstance(row[0], list) else json.loads(row[0])
            hit = False
            for f in facts:
                if isinstance(f, list) and len(f) == 2 and f[0] == "Date":
                    f[1] = sf.date_label(ymd)
                    hit = True
            if hit:
                cur.execute("UPDATE serving.signal_detail SET facts=%s, updated_at=now() "
                            "WHERE id=%s", (json.dumps(facts), cid))
        n += 1
    con.commit()
    print("\ncorrected %d card(s)" % n)


if __name__ == "__main__":
    main()
