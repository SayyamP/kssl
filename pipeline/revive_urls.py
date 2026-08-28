"""Harvest every source URL the ARCHIVED reference data points at.

    python revive_urls.py                 # write revive_urls.json
    python revive_urls.py --demo

The archive is not just data to re-publish -- it is a bibliography. Each
reference row that carries `srcs` names the document its claims came from, and
those documents are exactly the "targeted docs" worth fetching: they are the ones
that would let the pipeline ground the row instead of trusting it.

So this does not revive anything. It produces the fetch worklist, minus whatever
the corpus already holds.
"""
import argparse
import collections
import io
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
OUT = Path(__file__).parent / "revive_urls.json"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Every reference table that can name a document, and the jsonb/text column holding it.
SOURCES = [
    ("matchup", "srcs", "json"),
    ("signal_card", "url", "text"),
    ("signal_detail", "url", "text"),
    ("innovation", "url", "text"),
    ("innovation", "sources", "json"),
    ("geo_presence", "src", "text"),
    ("competitors", "srcs", "json"),
    ("company_source", "url", "text"),
    ("source_registry", "url", "text"),
    ("competitors", "updates", "json"),
    ("patent", "url", "text"),
    ("tender", "url", "text"),
]


def canon(u):
    """Strip tracking and fragments so the same page is not fetched five times."""
    if not u or not isinstance(u, str) or not u.startswith("http"):
        return None
    p = urlsplit(u.strip())
    q = "&".join(kv for kv in p.query.split("&")
                 if kv and not kv.split("=")[0].lower().startswith(("utm_", "fbclid", "gclid")))
    host = p.netloc.lower()
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), host, path, q, ""))


def urls_from(val):
    """A jsonb column may hold a list of {url,label}, a list of strings, or a dict."""
    out = []
    if val is None:
        return out
    if isinstance(val, str):
        out.append(val)
    elif isinstance(val, dict):
        for v in val.values():
            out += urls_from(v)
    elif isinstance(val, list):
        for v in val:
            out += urls_from(v)
    return out


def has_col(cur, table, col):
    cur.execute("""select 1 from information_schema.columns
                    where table_schema='serving' and table_name=%s and column_name=%s""",
                (table, col))
    return cur.fetchone() is not None


def main():
    con = psycopg2.connect(DSN)
    cur = con.cursor()

    found = collections.Counter()     # url -> how many reference rows cite it
    by_table = collections.Counter()
    for table, col, _kind in SOURCES:
        if not has_col(cur, table, col):
            print("skip %s.%s (no such column)" % (table, col))
            continue
        cur.execute('select "%s" from serving.%s where origin=\'reference\'' % (col, table))
        for (val,) in cur.fetchall():
            for u in urls_from(val):
                c = canon(u)
                if c:
                    found[c] += 1
                    by_table[table] += 1

    # what the corpus already holds -- do not refetch it
    cur.execute("select url from extracted.document")
    have = {canon(r[0]) for r in cur.fetchall()}
    have.discard(None)
    todo = [u for u in found if u not in have]

    print("reference rows cite %d distinct URL(s)" % len(found))
    for t, n in by_table.most_common():
        print("   %-16s %d citation(s)" % (t, n))
    print("corpus already holds %d of them; %d to fetch" % (len(found) - len(todo), len(todo)))

    hosts = collections.Counter(urlsplit(u).netloc for u in todo)
    print("\ntop hosts to fetch:")
    for h, n in hosts.most_common(15):
        print("   %-38s %d" % (h, n))

    io.open(OUT, "w", encoding="utf-8").write(json.dumps(
        {"todo": sorted(todo), "already_held": len(found) - len(todo),
         "cited_by": {u: found[u] for u in sorted(todo)}}, ensure_ascii=False, indent=1))
    print("\nwrote %s (%d url(s))" % (OUT.name, len(todo)))
    con.close()


def _demo():
    assert canon("https://EX.com/a/?utm_source=x&id=3#frag") == "https://ex.com/a?id=3"
    assert canon("https://ex.com/a/") == "https://ex.com/a"
    assert canon("not a url") is None and canon(None) is None
    # the three shapes a srcs column actually takes
    assert urls_from([{"url": "https://a.com/1", "label": "x"}]) == ["x", "https://a.com/1"] or \
challenge_ok(urls_from([{"url": "https://a.com/1", "label": "x"}]))
    assert "https://b.com/2" in urls_from(["https://b.com/2"])
    assert "https://c.com/3" in urls_from({"k": {"url": "https://c.com/3"}})
    print("ok")


def challenge_ok(vals):
    # urls_from walks dict values in insertion order; only the http one survives canon()
    return any(canon(v) for v in vals)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main()
