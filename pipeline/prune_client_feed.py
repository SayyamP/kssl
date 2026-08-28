"""Take the client's own announcements out of the rival-intelligence feeds.

    python prune_client_feed.py --dry
    python prune_client_feed.py --apply
    python prune_client_feed.py --demo

The Innovation Pipeline and the Technology signal feed exist to say what OTHER
companies are doing. Half of what they showed was KSSL reading its own press
releases back to itself -- 13 of 26 innovations, 5 of the 8 rows under Artillery,
and 5 of 10 technology signals, one of them the client's own Simha 4x4 filed
twice under a partner's name.

The generators (enrich_serving.step_innovations, serving_fill) now refuse these
at the point of writing. This removes the rows already stored, using THE SAME
predicate, so a re-run and this prune can never disagree.

Only origin='pipeline' is touched. The archived reference rows are a different
writer's id-space and several of them are multi-party programme entries where the
client is one participant among several -- not the same thing at all.
"""
import os
import argparse
import sys
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from aliases import client_led, is_client                       # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
LANES = ("competitive", "tech")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def own_item(actor, headline):
    """The one predicate. Shared with the generators, never re-expressed."""
    return bool(is_client(actor) or client_led(headline))


def main(apply=False):
    con = psycopg2.connect(DSN)
    cur = con.cursor()

    cur.execute("""SELECT area, ord, driver, t FROM serving.innovation
                    WHERE origin='pipeline' ORDER BY area, ord""")
    inn = [r for r in cur.fetchall() if own_item(r[2], r[3])]
    cur.execute("""SELECT id, lane, company, title FROM serving.signal_card
                    WHERE origin='pipeline' AND lane IN %s ORDER BY lane, ord""",
                (LANES,))
    cards = [r for r in cur.fetchall() if own_item(r[2], r[3])]

    print("innovations to remove : %d" % len(inn))
    for a, o, d, t in inn:
        print("   %-11s %-26s %s" % (a, (d or "")[:26], t[:60]))
    print("\nsignal cards to remove: %d" % len(cards))
    for i, ln, c, t in cards:
        print("   %-5s %-26s %s" % (ln, (c or "")[:26], t[:60]))

    if apply:
        for a, o, _d, _t in inn:
            cur.execute("""DELETE FROM serving.innovation
                            WHERE origin='pipeline' AND area=%s AND ord=%s""", (a, o))
        for i, _l, _c, _t in cards:
            cur.execute("DELETE FROM serving.signal_card WHERE origin='pipeline' AND id=%s",
                        (i,))
            cur.execute("DELETE FROM serving.signal_detail WHERE id=%s", (i,))
        con.commit()
        print("\nremoved %d innovation(s) and %d card(s)" % (len(inn), len(cards)))
        cur.execute("""SELECT area, count(*) FROM serving.innovation
                        WHERE origin='pipeline' GROUP BY area ORDER BY area""")
        print("innovations remaining by area: %s"
              % ", ".join("%s %d" % r for r in cur.fetchall()))
    else:
        print("\n(dry run -- nothing removed)")
    con.close()
    return inn, cards


def _demo():
    assert own_item("Kalyani Strategic Systems", "KSSL demonstrated MARG 155")
    # filed under a partner, but the client is the actor
    assert own_item("Paramount", "Kalyani and Paramount unveil Simha 4x4")
    assert own_item("Bharat Forge Ltd", "anything at all")
    # a rival's move stays, including one that merely mentions the client
    assert not own_item("Rheinmetall", "Rheinmetall Demonstrates FV-014 LM from CML")
    assert not own_item("GDLS Canada", "GRIZZLY SPH received drone detection capability")
    assert not own_item("Saab", "Saab wins the order KSSL also bid for")
    assert not own_item(None, None)
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply)
