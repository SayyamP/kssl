"""Recompute the date on cards that are already on the dashboard.

The date logic is fixed for cards written from now on; this corrects the ones
already stored. It rewrites `signal_card.ago` and the "Date" fact in
`signal_detail.facts`, using exactly the same article_date() the pipeline now
uses, so the two can never disagree.

    python fix_card_dates.py --dry-run     # show what would change
    python fix_card_dates.py               # apply
    python fix_card_dates.py --list-stale  # cards now outside the recency window

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
    a = ap.parse_args()

    import psycopg2
    env = load_env(a.env)
    dsn = a.dsn or env.get("KSSL_DSN") or env.get("KSSL_CORPUS_DSN")
    if not dsn:
        sys.exit("no DSN")
    con = psycopg2.connect(dsn)
    cur = con.cursor()

    cutoff, cur_year = sf.recent_cutoff()
    cur.execute("""SELECT c.id, c.ago FROM serving.signal_card c
                    WHERE c.origin='pipeline' AND c.id LIKE 'pl_%'""")
    cards = cur.fetchall()
    print("pipeline cards: %d" % len(cards))

    fix, unchanged, undated, stale = [], 0, 0, []
    for cid, ago in cards:
        ymd = sf.article_date(cur, cid[3:])
        if ymd is None:
            undated += 1
            continue
        want = sf.ago_of(ymd[:2])
        if not sf.is_recent_ym(ymd[:2], cutoff, cur_year):
            stale.append((cid, want))
        if want != (ago or ""):
            fix.append((cid, ago, want, ymd))
        else:
            unchanged += 1

    print("  already correct : %d" % unchanged)
    print("  TO CORRECT      : %d" % len(fix))
    print("  undated         : %d" % undated)
    print("  outside the %d-day window (reported, NOT removed): %d"
          % (sf.RECENT_WINDOW_DAYS, len(stale)))

    if a.list_stale:
        print("\n--- cards older than the recency window ---")
        for cid, want in sorted(stale, key=lambda x: x[1]):
            print("   %-28s %s" % (cid, want))
        return

    print("\n--- %s ---" % ("would correct" if a.dry_run else "correcting"))
    for cid, old, want, _y in fix[:20]:
        print("   %-28s %-10s -> %s" % (cid, old or "(none)", want))
    if len(fix) > 20:
        print("   ... and %d more" % (len(fix) - 20))

    if a.dry_run:
        print("\nDRY RUN -- nothing written.")
        return

    n = 0
    for cid, _old, want, ymd in fix:
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
