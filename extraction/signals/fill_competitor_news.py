"""Per-company news for the Profile / Products / Geo panels, from the signal feed.

    python fill_competitor_news.py --dry-run     # default: report, write nothing
    python fill_competitor_news.py --apply
    python fill_competitor_news.py --demo        # parser asserts, no DB

`serving.competitor_news` was created with a serving_live view and never given a
writer, so the four news panels in the dashboard read from a hard-coded template
with the company name substituted into it -- the same five invented stories for
all 119 competitors, attributed to real publishers.

Nothing here generates text. Every row is a signal card the pipeline already
produced, wrote a date for from the article's own markup, and cited:

    title        the card's headline          serving.signal_card.title
    description  the card's one-line read     serving.signal_card.sowhat
    source       the publisher                parsed from meta / the url host
    url          the article                  serving.signal_card.url
    image        the article's own picture    serving.signal_card.image
    category     the portfolio band           serving.signal_card.tags
    published_date  the article's date        serving_fill.article_date (markup first)

Two fields are deliberately NOT written. `is_trending` stays false: nothing in the
pipeline measures trend, and the UI's "top story" slot is served honestly by the
newest row, which the ordering already gives it. There is no `impact` or
`fullText`: the panel's long-form fields are fed from signal_detail, which is real,
not from prose invented here.

Identity goes through aliases.canonical/same -- the SAME layer serving_fill and
enrich_serving use -- so "Kongsberg Defence & Aerospace" and "KONGSBERG" reach one
competitor row instead of being two feeds.
"""
import argparse
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

DSN = os.environ.get("KSSL_SERVING_DSN") or os.environ.get("DSN") or ""

# Only the publisher's own host is a source name. A card whose meta lost its
# "from <host>" tail still has the url, and the url host is the publisher.
_FROM = re.compile(r"\bfrom\s+([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\s*$")
_HOST = re.compile(r"^https?://(?:www\.)?([^/:]+)", re.I)


def source_of(meta, url):
    """-> the publishing host, or None. Never a guess: meta's own tail, else the url."""
    m = _FROM.search(meta or "")
    if m:
        return m.group(1).lower()
    m = _HOST.match(url or "")
    return m.group(1).lower() if m else None


def as_date(ymd):
    """-> 'YYYY-MM-DD' from article_date's (y, m, d), or None.

    A partial date stays partial by REFUSING, not by inventing a first-of-month.
    published_date is a timestamp column: writing 2026-07-01 for a card the
    publisher only dated to July would print "1 Jul 2026" in the panel, which is a
    day the article was not published on. The card keeps its month label; the news
    row is simply not written with a date it cannot prove.
    """
    if not ymd:
        return None
    y, m, d = (list(ymd) + [None, None])[:3]
    if not (y and m and d):
        return None
    try:
        return "%04d-%02d-%02d" % (int(y), int(m), int(d))
    except (TypeError, ValueError):
        return None


def build(cards, comp_index, date_of):
    """-> (rows, stats). Pure: no DB, no network. `cards` are dicts, `comp_index`
    maps a folded company name to comp_id, `date_of` resolves a document id."""
    rows, stats = [], {"no_company": 0, "unmatched": 0, "no_url": 0, "undated": 0}
    for c in cards:
        if not c.get("company"):
            stats["no_company"] += 1
            continue
        cid = comp_index.get(c["company"])
        if not cid:
            stats["unmatched"] += 1
            continue
        if not c.get("url"):
            # A news item with no link is not checkable, and the panel renders it
            # as a click target. Refuse it rather than ship a dead card.
            stats["no_url"] += 1
            continue
        when = date_of(c["id"])
        if not when:
            stats["undated"] += 1
            continue
        rows.append({
            "comp_id": cid,
            "title": c["title"],
            "description": c.get("sowhat") or None,
            "source": source_of(c.get("meta"), c["url"]),
            "published_date": when,
            "category": c.get("tags") or None,
            "url": c["url"],
            "image": c.get("image") or None,
        })
    rows.sort(key=lambda r: (r["comp_id"], r["published_date"]), reverse=False)
    return rows, stats


# ------------------------------------------------------------------------ db side

def _comp_index(cur):
    """folded competitor name -> comp_id, via the shared identity layer."""
    from aliases import canonical, fold
    cur.execute("SELECT comp_id, name FROM serving.competitors "
                "WHERE origin='pipeline' ORDER BY ord")
    idx = {}
    for cid, name in cur.fetchall():
        for key in {fold(name), fold(canonical(name) or name)}:
            if key:
                idx.setdefault(key, cid)          # first ord wins on a collision
    return idx


def _lookup(idx):
    from aliases import canonical, fold

    def f(name):
        for key in (fold(name), fold(canonical(name) or name)):
            if key and key in idx:
                return idx[key]
        return None
    return f


def run(dsn=DSN, apply=False):
    import psycopg2
    from serving_fill import article_date
    con = psycopg2.connect(dsn, connect_timeout=10, keepalives=1,
                           keepalives_idle=30, keepalives_interval=10)
    cur = con.cursor()
    cur.execute("""SELECT id, title, sowhat, meta, company, tags, url, image
                     FROM serving.signal_card
                    WHERE origin='pipeline' ORDER BY ord""")
    cols = ("id", "title", "sowhat", "meta", "company", "tags", "url", "image")
    cards = [dict(zip(cols, r)) for r in cur.fetchall()]

    idx = _comp_index(cur)
    look = _lookup(idx)

    def date_of(card_id):
        # card ids are 'pl_<document_id>'; article_date reads the article's markup.
        did = card_id[3:] if card_id.startswith("pl_") else card_id
        try:
            return as_date(article_date(cur, did))
        except Exception as e:                                       # noqa: BLE001
            print("  date lookup failed for %s: %s" % (did, e), flush=True)
            return None

    class _Idx(dict):
        def get(self, k, default=None):
            return look(k) or default

    rows, stats = build(cards, _Idx(), date_of)
    per_company = len({r["comp_id"] for r in rows})
    print("cards: %d · rows: %d across %d compan(ies) · skipped: "
          "%d no company, %d not a tracked competitor, %d no link, %d no provable date"
          % (len(cards), len(rows), per_company, stats["no_company"],
             stats["unmatched"], stats["no_url"], stats["undated"]), flush=True)

    if not apply:
        print("dry run: nothing written (pass --apply)", flush=True)
        for r in rows[:5]:
            print("  %-14s %s  %-22s %s" % (r["comp_id"], r["published_date"],
                                            (r["source"] or "-")[:22], r["title"][:60]),
                  flush=True)
        con.close()
        return {"rows": len(rows), "companies": per_company, **stats}

    # Idempotent: this writer owns every origin='pipeline' row in the table.
    cur.execute("DELETE FROM serving.competitor_news WHERE origin='pipeline'")
    deleted = cur.rowcount
    for r in rows:
        cur.execute("""INSERT INTO serving.competitor_news
                       (comp_id, title, description, source, published_date,
                        category, url, image, origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pipeline')""",
                    (r["comp_id"], r["title"], r["description"], r["source"],
                     r["published_date"], r["category"], r["url"], r["image"]))
    con.commit()
    print("written: %d row(s) (%d replaced)" % (len(rows), deleted), flush=True)
    con.close()
    return {"rows": len(rows), "companies": per_company, **stats}


def _demo():
    assert source_of("UAVs · L3Harris · from airandspaceforces.com",
                     "https://x.test/a") == "airandspaceforces.com"
    assert source_of("no tail here", "https://www.seapowermagazine.org/27585-2") \
        == "seapowermagazine.org", "www. is not part of the publisher's name"
    assert source_of(None, None) is None
    assert source_of("from not-a-host", "notaurl") is None, \
        "a bare word after 'from' is not a publisher"

    assert as_date((2026, 7, 13)) == "2026-07-13"
    assert as_date((2026, 7, None)) is None, \
        "a month-only date must NOT become the first of the month"
    assert as_date((2026, None, None)) is None and as_date(None) is None
    assert as_date(("2023", "01", "9")) == "2023-01-09"

    cards = [
        {"id": "pl_d1", "title": "A wins X", "sowhat": "so", "meta": "c · A · from p.com",
         "company": "Saab", "tags": "Artillery", "url": "https://p.com/1", "image": "i"},
        {"id": "pl_d2", "title": "no company", "company": None, "url": "https://p.com/2"},
        {"id": "pl_d3", "title": "untracked", "company": "Nobody Ltd",
         "url": "https://p.com/3"},
        {"id": "pl_d4", "title": "no link", "company": "Saab", "url": None},
        {"id": "pl_d5", "title": "undated", "company": "Saab", "url": "https://p.com/5"},
    ]
    idx = {"Saab": "saab"}
    dates = {"pl_d1": "2026-07-13", "pl_d5": None}
    rows, st = build(cards, idx, lambda i: dates.get(i))
    assert len(rows) == 1 and rows[0]["comp_id"] == "saab", rows
    assert rows[0]["source"] == "p.com" and rows[0]["image"] == "i"
    assert st == {"no_company": 1, "unmatched": 1, "no_url": 1, "undated": 1}, st
    assert "is_trending" not in rows[0], \
        "nothing here measures trend, so nothing here claims it"
    print("fill_competitor_news demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--apply", action="store_true",
                    help="write; without it this is a dry run")
    ap.add_argument("--dry-run", action="store_true", help="the default")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        run(dsn=a.dsn, apply=a.apply)
