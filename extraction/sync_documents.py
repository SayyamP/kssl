"""Sync the corpus subset we actually extract from the data-centre crawler DB into VPS-B's own
`documents` table, so the whole queue path (enqueue -> worker -> store) runs on one database.

    python3 sync_documents.py --since 2026-08-25 --limit 500
    python3 sync_documents.py --demo          # offline self-check, no DB

DESIGN
------
* SOURCE is the data-centre corpus (KSSL_CORPUS_SRC_DSN, reached over an SSH tunnel). DEST is
  VPS-B Postgres (KSSL_CORPUS_DSN) -- the SAME database the queue and extracted.* live in.
* The candidate scan touches ONLY small columns + text_len. `documents` at the DC is 81 GB, almost
  all of it main_text/html in TOAST; selecting or ordering by those detoasts the table and has taken
  the corpus offline before. Body text is fetched per chosen row, in one reconnecting connection.
* It is a GATE, not a firehose: recent, a real length band, and (by default) a PROVEN publish date
  -- the crawler's own metadata, which the serving date-gate needs. Relevance scoring itself is left
  to route.py --enqueue's presignal, so this stays cheap and deterministic.
* It is IDEMPOTENT: rows already in VPS-B `documents` or already in `extracted.document` are skipped,
  so re-running tops up rather than duplicating. Safe to run on a timer forever.
"""
import argparse
import datetime
import io
import os
import re
import sys
from pathlib import Path


def _load_env():
    """Read KEY=VALUE from ../.env (and this dir's .env) without overriding the real environment."""
    for p in (Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"):
        if p.exists():
            for line in io.open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()
SRC_DSN = os.environ.get("KSSL_CORPUS_SRC_DSN",
                         "host=127.0.0.1 port=15432 dbname=mallory user=mallory password=")
DEST_DSN = os.environ.get("KSSL_CORPUS_DSN",
                          "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
MIN_TEXT = int(os.environ.get("KSSL_MIN_TEXT", "600"))
MAX_TEXT = int(os.environ.get("KSSL_MAX_TEXT", "9000"))
# candidate_factor: scan this many small rows per wanted doc (dated+length filters reject most)
CAND_FACTOR = int(os.environ.get("KSSL_CANDIDATE_FACTOR", "6"))


def _connect(dsn, **kw):
    import psycopg2  # noqa: E402  (psycopg2 is the driver already installed here)
    return psycopg2.connect(dsn, connect_timeout=int(os.environ.get("KSSL_CONNECT_TIMEOUT", "15")),
                            keepalives=1, keepalives_idle=60, keepalives_interval=10,
                            keepalives_count=3, **kw)


def _existing(dest):
    """document_ids already known to VPS-B -- in `documents` OR already extracted -- so we never
    re-sync a row that will only be skipped downstream."""
    have = set()
    with dest.cursor() as c:
        c.execute("SELECT document_id FROM documents")
        have.update(r[0] for r in c.fetchall())
        try:
            c.execute("SELECT document_id FROM extracted.document")
            have.update(r[0] for r in c.fetchall())
        except Exception:
            dest.rollback()   # extracted schema may not exist yet on a fresh box; not fatal
    return have


def candidates(src, since, want, dated_only):
    """Small-column scan of the corpus: (document_id, url, source_id, language, title, published_at,
    fetched_at, text_len) for recent, length-banded rows. NEVER selects the body text here -- that
    detoasts an 81 GB table; body() fetches it per chosen row instead."""
    # SCAN ON ingested_at, NOT fetched_at. The corpus indexes document_id, url, source_id,
    # node_id, pushed_at and ingested_at -- fetched_at has NO index, so filtering and ordering
    # on it seq-scans 1.97M rows and blows the statement timeout below. That took this sync
    # down completely on 2026-09-09: every feeder cycle logged QueryCanceled and nothing
    # reached VPS-B, while the crawler kept adding ~50k documents a day. The two columns are
    # written within seconds of each other, so the window this selects is unchanged.
    where = ["ingested_at >= %s", "text_len BETWEEN %s AND %s"]
    args = [since, MIN_TEXT, MAX_TEXT]
    if dated_only:
        where.append("published_at IS NOT NULL AND published_at <> ''")
    with src.cursor() as c:
        # 30s was tuned for an indexed scan; keep headroom for a cold cache on a busy DC.
        c.execute("SET statement_timeout='180s'")
        c.execute(
            "SELECT document_id, url, source_id, language, title, published_at, fetched_at, text_len "
            "FROM documents WHERE " + " AND ".join(where) +
            " ORDER BY ingested_at DESC LIMIT %s",
            args + [want * CAND_FACTOR])
        return c.fetchall()


def body(src, doc_id):
    with src.cursor() as c:
        c.execute("SET statement_timeout='30s'")
        c.execute("SELECT main_text FROM documents WHERE document_id = %s", (doc_id,))
        r = c.fetchone()
    return r[0] if r and r[0] else None


UPSERT = """
INSERT INTO documents (document_id, url, source_id, language, title, main_text,
                       published_at, fetched_at, text_len)
VALUES (%(document_id)s, %(url)s, %(source_id)s, %(language)s, %(title)s, %(main_text)s,
        %(published_at)s, %(fetched_at)s, %(text_len)s)
ON CONFLICT (document_id) DO NOTHING;
"""


def sync(since, limit, dated_only=True):
    src = _connect(SRC_DSN)
    dest = _connect(DEST_DSN)
    have = _existing(dest)
    cands = candidates(src, since, limit, dated_only)
    inserted = scanned = 0
    for row in cands:
        if inserted >= limit:
            break
        doc_id = row[0]
        scanned += 1
        if doc_id in have:
            continue
        txt = body(src, doc_id)
        if not txt or not (MIN_TEXT <= len(txt) <= MAX_TEXT):
            continue
        rec = {"document_id": doc_id, "url": row[1], "source_id": row[2], "language": row[3],
               "title": row[4], "main_text": txt, "published_at": str(row[5]) if row[5] else None,
               "fetched_at": str(row[6]), "text_len": row[7] or len(txt)}
        with dest.cursor() as c:
            c.execute(UPSERT, rec)
        dest.commit()
        have.add(doc_id)
        inserted += 1
    src.close()
    dest.close()
    return inserted, scanned


def main():
    ap = argparse.ArgumentParser()
    default_since = (datetime.datetime.utcnow() - datetime.timedelta(
        days=int(os.environ.get("KSSL_SINCE_DAYS", "3")))).strftime("%Y-%m-%dT%H:%M:%SZ")
    ap.add_argument("--since", default=default_since, help="ISO timestamp; default KSSL_SINCE_DAYS ago")
    ap.add_argument("--limit", type=int, default=int(os.environ.get("KSSL_SYNC_LIMIT", "500")))
    ap.add_argument("--undated", action="store_true",
                    help="also sync docs with no proven publish date (they fail the serving "
                         "date-gate later, so off by default)")
    a = ap.parse_args()
    print("sync: corpus(%s) -> VPS-B, since %s, limit %d"
          % (SRC_DSN.split("port=")[-1].split()[0], a.since, a.limit), flush=True)
    ins, scanned = sync(a.since, a.limit, dated_only=not a.undated)
    print("synced %d new document(s) (%d candidates scanned)" % (ins, scanned), flush=True)


def _demo():
    # Pure-logic checks: the candidate SQL must never select a big column, and the upsert must be
    # idempotent by construction (ON CONFLICT DO NOTHING). Offline -- no DB, no network.
    assert "ON CONFLICT (document_id) DO NOTHING" in UPSERT, "upsert must be idempotent"
    assert MIN_TEXT < MAX_TEXT
    # the candidate scan string must not mention main_text/html (the TOAST columns)
    import inspect
    csrc = inspect.getsource(candidates)
    assert "main_text" not in csrc and "html" not in csrc, \
        "candidate scan must not touch big TOAST columns"
    # The corpus has no index on fetched_at. Filtering or ordering the candidate scan by it
    # seq-scans ~2M rows and dies on the statement timeout -- silently, every cycle, which is
    # exactly how this sync stopped feeding VPS-B on 2026-09-09. Pin the indexed column here
    # so a future edit cannot quietly reintroduce it.
    body = csrc.split('"""', 2)[-1]
    assert "ingested_at >=" in body and "ORDER BY ingested_at" in body, \
        "candidate scan must filter AND order on ingested_at (the indexed column)"
    assert "fetched_at >=" not in body and "ORDER BY fetched_at" not in body, \
        "fetched_at carries no index on the corpus -- do not scan on it"
    print("ok  dated+length gate, idempotent upsert, no big-column scan, "
          "candidate scan stays on the indexed column")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        main()
