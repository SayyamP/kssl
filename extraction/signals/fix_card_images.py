"""Fill serving.signal_card.image for cards already on the dashboard.

New cards get their picture as they are written (serving_fill -> card_image);
this is for the ones stored before that, and for any a corpus outage skipped.
Reads the same stored markup the date logic reads, through the same connection.

    python fix_card_images.py --dry-run
    python fix_card_images.py
    python fix_card_images.py --all      # also re-check cards that have one

Never deletes and never blanks: a card with a picture keeps it unless --all is
given AND a better one is proven.
"""
import argparse
import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import corpus                                                        # noqa: E402
from article_image import resolve_image                              # noqa: E402


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
    ap.add_argument("--all", action="store_true",
                    help="also re-resolve cards that already have an image")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    import psycopg2
    env = load_env(a.env)
    dsn = a.dsn or env.get("KSSL_DSN") or env.get("KSSL_CORPUS_DSN")
    if not dsn:
        sys.exit("no DSN")
    con = psycopg2.connect(dsn)
    cur = con.cursor()

    where = "" if a.all else " AND image IS NULL"
    cur.execute("SELECT id, url, image FROM serving.signal_card "
                "WHERE origin='pipeline' AND id LIKE 'pl_%%'" + where)
    cards = cur.fetchall()
    print("cards to consider: %d" % len(cards))
    if not corpus.state()["enabled"]:
        sys.exit("corpus not configured (KSSL_CORPUS_SRC_DSN)")

    # The corpus connection is not thread-safe, so the HTML is pulled serially
    # and only the reachability probes -- which are what actually cost time --
    # run in parallel.
    docs = []
    for cid, url, cur_img in cards:
        u, html = corpus.fetch_html(cid[3:])
        docs.append((cid, u or url, html, cur_img))

    def work(d):
        cid, url, html, cur_img = d
        if not html:
            return cid, None, cur_img
        return cid, resolve_image(html, url or "", timeout=12), cur_img

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(work, docs))

    fill = [(c, i) for c, i, old in res if i and not old]
    change = [(c, i) for c, i, old in res if i and old and i != old]
    none = [c for c, i, old in res if not i]
    print("  would fill  : %d" % len(fill))
    print("  would change: %d" % len(change))
    print("  no image    : %d" % len(none))
    print("  corpus      : %s" % corpus.state())

    if a.dry_run:
        for c, i in fill[:12]:
            print("   %-26s %s" % (c, i[:86]))
        print("\nDRY RUN -- nothing written.")
        return

    todo = fill + change
    for cid, img in todo:
        cur.execute("UPDATE serving.signal_card SET image=%s, updated_at=now() "
                    "WHERE id=%s", (img, cid))
    con.commit()
    print("\nwrote %d image(s)" % len(todo))


if __name__ == "__main__":
    main()
