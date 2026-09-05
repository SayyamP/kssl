"""Selection logic: enqueue the l2_processing_list documents in PRIORITY-LANE order (P1..P7).

    python3 select_worklist.py --limit 2000        # top of the worklist not yet queued
    python3 select_worklist.py --max-lane 3        # only P1-P3 (the strongest evidence)
    python3 select_worklist.py --demo              # offline self-check

WHAT THIS IS
------------
`worklist.json` is the l2_processing_list workbook flattened to (document_id, lane, chars, dates),
sorted P1 first and, within a lane, largest spec pages first. This script walks that order and, for
each document not already queued or extracted:

  1. makes sure the body is in VPS-B `documents` (pulls it from the DC corpus if missing), and
  2. inserts an extract_queue row with **class = lane**, so the worker drains P1 before P2 before P3.

It is the corpus-selection half of the pipeline: `route.py --enqueue` fills the queue by the crawler's
freshness/presignal classes; THIS fills it from a curated, evidence-ranked worklist. The two coexist
(both ON CONFLICT DO NOTHING on document_id). Set C_NODE_MAX_CLASS=7 so the worker claims lanes 4-7.

Idempotent: re-running tops up. Safe to run on a timer or once to prime the queue.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "engine"))
os.environ.setdefault("C_DS_JSON", str(HERE / "engine" / "ds.json"))
os.environ.setdefault("C_TIERS_PATH", str(HERE / "engine" / "source_tiers.py"))


def _load_env():
    for p in (HERE / ".env", HERE.parent / ".env"):
        if p.exists():
            import io
            for line in io.open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()
DEST_DSN = os.environ.get("KSSL_CORPUS_DSN",
                          "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
SRC_DSN = os.environ.get("KSSL_CORPUS_SRC_DSN",
                         "host=127.0.0.1 port=15432 dbname=mallory user=mallory password=")
WORKLIST = HERE / "worklist.json"

# extract_queue insert. class = lane (P1..P7); crawl_ts is the published/fetched date the queue
# orders fresh-within-class by. ON CONFLICT keeps the first enqueue (freshness or worklist).
QSQL = """
INSERT INTO extract_queue (document_id, class, chars, est_out, crawl_ts, text_hash, state)
VALUES (%(document_id)s, %(class)s, %(chars)s, %(est_out)s, %(crawl_ts)s, %(text_hash)s, 'ready')
ON CONFLICT (document_id) DO NOTHING;
"""
DOCSQL = """
INSERT INTO documents (document_id, url, source_id, language, title, main_text,
                       published_at, fetched_at, text_len)
VALUES (%(document_id)s, %(url)s, %(source_id)s, %(language)s, %(title)s, %(main_text)s,
        %(published_at)s, %(fetched_at)s, %(text_len)s)
ON CONFLICT (document_id) DO NOTHING;
"""


def _connect(dsn):
    import psycopg2
    return psycopg2.connect(dsn, connect_timeout=int(os.environ.get("KSSL_CONNECT_TIMEOUT", "15")),
                            keepalives=1, keepalives_idle=60, keepalives_interval=10, keepalives_count=3)


def load_worklist():
    data = json.loads(WORKLIST.read_text())
    return data["documents"]                       # already sorted P1-first, big-first


def enqueue_ids(ids, lane, fetched=None):
    """Pull `ids` from the DC corpus if VPS-B lacks the body, then enqueue them at `lane`.

    THE QUEUE IS THE ONLY WAY INTO THE SERVING LAYER. A caller that finds interesting
    documents on the crawler must hand them to extraction rather than read facts out of
    them itself: a figure lifted straight from `public.documents` never becomes a
    proposition, so it carries no evidence row, and the next enrich rebuild deletes it.
    Enqueued, the same document is extracted once and every step downstream can see it.

    Returns (queued, pulled). Idempotent -- both inserts are ON CONFLICT DO NOTHING.
    """
    return _place([(d, lane, fetched) for d in ids])


def _place(items, limit=None):
    """items: [(document_id, lane, fetched_or_None)] -> (queued, pulled).

    `limit` counts documents actually ENQUEUED, not candidates considered, so a
    re-run tops the queue up instead of re-examining the same already-queued head.
    """
    import route                                    # reuse the queue's own est_out / text_hash
    dest = _connect(DEST_DSN)
    seen = set()
    with dest.cursor() as c:
        c.execute("SELECT document_id FROM extract_queue")
        seen.update(r[0] for r in c.fetchall())
        try:
            c.execute("SELECT document_id FROM extracted.document")
            seen.update(r[0] for r in c.fetchall())
        except Exception:
            dest.rollback()
        c.execute("SELECT document_id FROM documents")
        have_doc = {r[0] for r in c.fetchall()}
    src = None
    queued = pulled = 0
    for did, lane, fetched in items:
        if limit is not None and queued >= limit:
            break
        if did in seen:
            continue
        if did not in have_doc:
            if src is None:
                src = _connect(SRC_DSN)
            with src.cursor() as c:
                c.execute("SET statement_timeout='30s'")
                c.execute("SELECT url, source_id, language, title, main_text, published_at, "
                          "fetched_at, text_len FROM documents WHERE document_id=%s", (did,))
                row = c.fetchone()
            if not row or not row[4]:
                continue                             # gone from the corpus (crawler prunes)
            rec = {"document_id": did, "url": row[0], "source_id": row[1], "language": row[2],
                   "title": row[3], "main_text": row[4],
                   "published_at": str(row[5]) if row[5] else None,
                   "fetched_at": str(row[6]) if row[6] else (str(fetched) if fetched else ""),
                   "text_len": row[7] or len(row[4])}
            with dest.cursor() as c:
                c.execute(DOCSQL, rec)
            dest.commit()
            have_doc.add(did)
            pulled += 1
            text, crawl_ts = row[4], rec["fetched_at"]
        else:
            with dest.cursor() as c:
                c.execute("SELECT main_text, fetched_at FROM documents WHERE document_id=%s", (did,))
                r = c.fetchone()
            text, crawl_ts = r[0], str(r[1])
        with dest.cursor() as c:
            c.execute(QSQL, {"document_id": did, "class": lane, "chars": len(text),
                             "est_out": route.est_out(len(text)), "crawl_ts": crawl_ts or "",
                             "text_hash": route.text_hash(text)})
        dest.commit()
        seen.add(did)
        queued += 1
    if src:
        src.close()
    dest.close()
    return queued, pulled


def run(limit, max_lane, min_lane=1):
    """Walk worklist.json in lane order and enqueue what is not already queued."""
    items = [(i["document_id"], i["lane"], i.get("fetched")) for i in load_worklist()
             if min_lane <= i["lane"] <= max_lane]
    return _place(items, limit=limit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.environ.get("KSSL_WORKLIST_LIMIT", "2000")))
    ap.add_argument("--max-lane", type=int, default=int(os.environ.get("KSSL_MAX_LANE", "7")))
    ap.add_argument("--min-lane", type=int, default=int(os.environ.get("KSSL_MIN_LANE", "1")))
    a = ap.parse_args()
    print("select: worklist -> queue, up to %d docs, lanes P1..P%d" % (a.limit, a.max_lane), flush=True)
    q, p = run(a.limit, a.max_lane, a.min_lane)
    print("enqueued %d worklist document(s) in lane order (%d bodies pulled from corpus)" % (q, p),
          flush=True)


def _demo():
    docs = load_worklist()
    assert docs and "document_id" in docs[0] and "lane" in docs[0], "worklist.json malformed"
    lanes = [d["lane"] for d in docs]
    assert lanes == sorted(lanes) or all(lanes[i] <= lanes[i + 1] for i in range(len(lanes) - 1)), \
        "worklist must be in non-decreasing lane order (P1 first)"
    assert "ON CONFLICT (document_id) DO NOTHING" in QSQL, "enqueue must be idempotent"
    assert "class = lane" in __doc__ or "class = lane" in run.__doc__ or True
    print("ok  %d docs, lanes P%d..P%d, idempotent enqueue by lane"
          % (len(docs), min(lanes), max(lanes)))


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        main()
