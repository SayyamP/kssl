"""How the harvest is going. Run it any time.

    python status.py            # the live task list
    python status.py --gaps     # which companies still have nothing, per need
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from targets import DSN, NEEDS                      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def q(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


def main(gaps=False):
    import psycopg2 as pg
    with pg.connect(DSN, connect_timeout=10) as cx, cx.cursor() as cur:
        rows = q(cur, "select state, count(*) from harvest.task group by 1 order by 2 desc")
        total = sum(n for _, n in rows)
        print("== tasks == %d total" % total)
        for st, n in rows:
            bar = "#" * int(40.0 * n / max(total, 1))
            print("  %-9s %5d  %s" % (st, n, bar))

        print()
        print("== per need ==")
        print("  %-11s %6s %6s %7s %8s" % ("need", "done", "left", "blocked", "chars"))
        for need, _ in sorted(NEEDS.items(), key=lambda kv: kv[1][0]):
            r = q(cur, """select
                    count(*) filter (where state='done'),
                    count(*) filter (where state in ('pending','running')),
                    count(*) filter (where state='blocked'),
                    coalesce(sum(chars) filter (where state='done'),0)
                  from harvest.task where need=%s""", (need,))[0]
            print("  %-11s %6d %6d %7d %8s" % (need, r[0], r[1], r[2], "{:,}".format(r[3])))

        print()
        r = q(cur, """select count(distinct cid), count(*), coalesce(sum(length(text)),0)
                      from harvest.page""")[0]
        print("== pages ==  %d companies, %d pages, %s chars" % (r[0], r[1], "{:,}".format(r[2])))
        r = q(cur, "select field, count(*) from harvest.fact group by 1 order by 2 desc")
        print("== facts ==  %s" % (", ".join("%s %d" % (f, n) for f, n in r) or "none yet"))

        print()
        print("== workers ==")
        for w, n, last in q(cur, """select worker, count(*), max(ended_at)
                                    from harvest.task where worker is not null
                                    group by 1 order by 1"""):
            print("  %-8s %5d done   last %s" % (w, n, last.strftime("%H:%M:%S") if last else "-"))

        if gaps:
            print()
            print("== companies with NOTHING for a priority-1 need ==")
            for cid, name in q(cur, """
                select distinct t.cid, t.company from harvest.task t
                where not exists (select 1 from harvest.page p
                                  where p.cid=t.cid and p.need in
                                  ('products','leadership','facilities','about'))
                order by 2"""):
                print("  %s" % name)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gaps", action="store_true")
    main(ap.parse_args().gaps)
