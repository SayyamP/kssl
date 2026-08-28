"""Move the extraction stores into KSSL_Deploy's Postgres `extracted` schema.

    python load_extracted.py                     # all known sets -> :5460
    python load_extracted.py --sets kssl_demo
    python load_extracted.py --demo

Reads the SQLite stores the engine wrote (Layer A: doc/span/proposition; Layer B:
entity/entity_alias) and upserts them into Postgres. Sets loaded by default:

    kssl       100 docs, KSSL/competitor news pull of 2026-08-20 (finished)
    parallax   500 docs, the production comprehension set (finished)
    kssl_demo  the current corpus extraction (loads whatever is stored so far;
               re-running picks up newly finished documents -- idempotent)

The offset contract travels with the data: before a document's spans are written,
each span's [start,end) is checked against the document text, and a document that
fails is REFUSED -- loading it would poison every downstream reader that trusts
the offsets.

Column mapping is against the REAL extracted schema (document carries text_sha256/
n_chars/meta; span and proposition carry run_id) -- the first version of this file
guessed the schema and its demo only exercised the offset checker, which is exactly
how a wrong shape survives a green test.
"""
import os
import argparse
import hashlib
import json
import sqlite3

import psycopg2
from psycopg2.extras import execute_values
import sys
from pathlib import Path

HERE = Path(__file__).parent
ENGINE = HERE.parent.parent / "l2" / "comprehend"
DSN = os.environ.get("KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
SETS = ["kssl", "parallax", "kssl_demo"]
# per-set Layer B store (kssl has none)
LAYER_B = {"parallax": "parallax_layer_b.db", "kssl_demo": "kssl_demo_layer_b.db"}
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ro(path):
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    c.row_factory = sqlite3.Row
    return c


def nul(v):
    """'' -> None: the extracted schema CHECKs every text column against empty
    string -- absence must be NULL, never ''."""
    return v if v not in ("",) else None


def check_offsets(text, spans):
    """-> [span_id] whose recorded offsets do not reproduce their text."""
    return [s["id"] for s in spans if text[s["start"]:s["end"]] != s["text"]]



_CORPUS_DIR = Path(__file__).parent / "corpus"
_pub_cache = {}


def _published_at(document_id):
    """The crawler's publication date for this document, from the staged
    corpus file. None when the document did not come through pull_corpus."""
    if not _pub_cache:
        for q in _CORPUS_DIR.glob("doc_*.json"):
            try:
                j = json.loads(q.read_text(encoding="utf-8"))
            except Exception:                           # noqa: BLE001
                continue
            if j.get("published_at"):
                _pub_cache[j.get("document_id") or q.stem[4:]] = j["published_at"]
        _pub_cache.setdefault("__loaded__", "")
    return _pub_cache.get(document_id)


def load_set(cur, set_name, stats, verbose=True):
    path = ENGINE / "data" / ("%s.db" % set_name)
    if not path.exists():
        print("set %s: store missing, skipped" % set_name, flush=True)
        return
    a = ro(path)
    n0 = stats["docs"]
    for d in a.execute("SELECT * FROM doc"):
        spans = a.execute("SELECT * FROM span WHERE document_id=?",
                          (d["document_id"],)).fetchall()
        bad = check_offsets(d["text"], spans)
        if bad:
            # The contract is the point. A repaired offset is an invented quote.
            print("REFUSED %s: %d span(s) fail the offset contract (%s...)"
                  % (d["document_id"], len(bad), bad[:3]), flush=True)
            stats["refused"] += 1
            continue
        run_id = d["run_id"] or set_name
        cur.execute("""INSERT INTO extracted.extraction_run (run_id, started_at, model, note)
                       VALUES (%s,%s,%s,%s) ON CONFLICT (run_id) DO NOTHING""",
                    (run_id, nul(d["built_at"]), nul(d["model"]),
                     "loaded from engine set %s" % set_name))
        meta = {"set": set_name, "run_id": run_id, "model": d["model"],
                "built_at": d["built_at"], "elapsed_s": d["elapsed_s"]}
        # The crawler already knows when the article was published -- it reads it
        # from the page's own metadata. That is a far stronger proof than the
        # dates in the body text, which are whatever the article happens to talk
        # about ('January 2022', 'early 2020s'). Without carrying it here, a
        # 2026 story about a 2022 contract is judged four years old and refused.
        pub = _published_at(d["document_id"])
        if pub:
            meta["published_at"] = pub
        cur.execute("""INSERT INTO extracted.document
                         (document_id, url, source_id, language, title, text,
                          text_sha256, n_chars, n_sentences, meta)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (document_id) DO UPDATE SET
                         url=EXCLUDED.url, title=EXCLUDED.title,
                         language=EXCLUDED.language, text=EXCLUDED.text,
                         text_sha256=EXCLUDED.text_sha256, n_chars=EXCLUDED.n_chars,
                         n_sentences=EXCLUDED.n_sentences, meta=EXCLUDED.meta""",
                    (d["document_id"], nul(d["url"]), nul(d["source_id"]),
                     nul(d["language"]), nul(d["title"]), d["text"],
                     hashlib.sha256(d["text"].encode("utf-8")).hexdigest(),
                     len(d["text"]), d["n_sentences"], json.dumps(meta)))
        # children are replaced wholesale so a re-run cannot duplicate them
        cur.execute("DELETE FROM extracted.span WHERE document_id=%s", (d["document_id"],))
        cur.execute("DELETE FROM extracted.proposition WHERE document_id=%s",
                    (d["document_id"],))
        ok_spans = [s for s in spans
                    if s["text"] and s["type"] and s["end"] > s["start"]]
        stats["dropped_spans"] += len(spans) - len(ok_spans)
        # execute_values, NOT executemany: executemany is one round trip per
        # row, which is invisible on localhost and pathological through the SSH
        # tunnel that the split deployment uses (220k spans -> over an hour).
        execute_values(cur, """INSERT INTO extracted.span
                             (document_id, run_id, span_id, start_c, end_c, text,
                              type, type_ner, gloss, in_article, source, score, sent)
                           VALUES %s""",
                        [(d["document_id"], run_id, s["id"], s["start"], s["end"],
                          s["text"], s["type"], nul(s["type_ner"]), nul(s["gloss"]),
                          nul(s["in_article"]), nul(s["source"]), s["score"], s["sent"])
                         for s in ok_spans], page_size=500)
        props = a.execute("SELECT * FROM proposition WHERE document_id=?",
                          (d["document_id"],)).fetchall()
        ok_props = [p for p in props
                    if p["subject"] and p["predicate"] and p["object"]
                    and p["ev_quote"] and p["ev_end"] > p["ev_start"]]
        stats["dropped_props"] += len(props) - len(ok_props)
        execute_values(cur, """INSERT INTO extracted.proposition
                             (document_id, run_id, i, subject, predicate, object,
                              time_txt, place_txt, polarity, modality,
                              ev_start, ev_end, ev_quote, ev_fragment)
                           VALUES %s""",
                        [(d["document_id"], run_id, p["i"], p["subject"],
                          p["predicate"], p["object"], nul(p["time"]), nul(p["place"]),
                          nul(p["polarity"]), nul(p["modality"]), p["ev_start"],
                          p["ev_end"], p["ev_quote"], bool(p["ev_fragment"]))
                         for p in ok_props], page_size=500)
        stats["docs"] += 1
        stats["spans"] += len(spans)
        stats["props"] += len(props)
    a.close()
    if verbose:
        print("set %s: %d document(s) loaded" % (set_name, stats["docs"] - n0),
              flush=True)


def load_layer_b(cur, set_name, stats):
    path = ENGINE / "data" / LAYER_B.get(set_name, "___none___")
    if not path.exists():
        return
    b = ro(path)
    for e in b.execute("SELECT * FROM entity"):
        if not (e["canonical"] and e["type"]):
            continue
        cur.execute("""INSERT INTO extracted.entity
                         (entity_id, entity_type, canonical_name, created_by_run)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (entity_id) DO NOTHING""",
                    (e["entity_id"], e["type"], e["canonical"],
                     "layer_b:%s" % set_name))
        stats["entities"] += 1
    for al in b.execute("SELECT * FROM entity_alias"):
        cur.execute("""INSERT INTO extracted.entity_alias
                         (entity_id, surface, surface_folded, lang, script,
                          alias_kind, n_mentions)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (al["entity_id"], al["surface"], al["surface"].casefold(),
                     al["lang"] or "und", "und", "name", al["n"] or 0))
        stats["aliases"] += 1
    b.close()


def load(dsn=DSN, sets=None, verbose=True):
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    stats = {"docs": 0, "spans": 0, "props": 0, "refused": 0,
             "entities": 0, "aliases": 0, "dropped_spans": 0, "dropped_props": 0}
    todo = sets or SETS
    b_sets = [s for s in todo
              if LAYER_B.get(s) and (ENGINE / "data" / LAYER_B[s]).exists()]
    if b_sets:
        # Aliases have no natural key to upsert on, so the rows for a set have
        # to be replaced wholesale -- but only that set's rows. TRUNCATE emptied
        # the whole table, which meant every autopilot cycle silently deleted
        # the finished `kssl` and `parallax` reference entities and reloaded
        # only the one set it had just extracted. It went unnoticed because
        # nothing reads extracted.entity yet; the first reader would have found
        # a table that quietly lost most of itself every half hour.
        cur.execute("""DELETE FROM extracted.entity_alias
                        WHERE entity_id IN (SELECT entity_id FROM extracted.entity
                                             WHERE created_by_run = ANY(%s))""",
                    ([("layer_b:%s" % s) for s in b_sets],))
        cur.execute("DELETE FROM extracted.entity WHERE created_by_run = ANY(%s)",
                    ([("layer_b:%s" % s) for s in b_sets],))
    for s in todo:
        load_set(cur, s, stats, verbose)
        load_layer_b(cur, s, stats)
        con.commit()
    con.close()
    if verbose:
        print("loaded: %(docs)d doc / %(spans)d span / %(props)d proposition / "
              "%(entities)d entit(ies) / %(aliases)d alias(es); %(refused)d doc(s) "
              "refused, %(dropped_spans)d span / %(dropped_props)d prop dropped "
              "(empty or inverted -- the schema refuses '' )" % stats, flush=True)
    return stats


def _demo():
    # The offset check is the load's whole authority; prove it in both directions.
    text = "Saab builds the Gripen."
    good = [{"id": "s1", "start": 0, "end": 4, "text": "Saab"}]
    bad = [{"id": "s2", "start": 0, "end": 4, "text": "Saag"}]
    assert check_offsets(text, good) == []
    assert check_offsets(text, bad) == ["s2"]
    assert check_offsets(text, good + bad) == ["s2"], "one bad span must not hide behind a good one"
    # The column mapping is the second authority: the INSERT lists must match the
    # real schema (the first version of this file died on a guessed column).
    import psycopg2
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    import re
    src = Path(__file__).read_text(encoding="utf-8")
    for table in ("document", "span", "proposition", "entity", "entity_alias"):
        m = re.search(r"INSERT INTO extracted\.%s\s*\(([^)]*)\)" % table, src)
        assert m, table
        ins_cols = {c.strip() for c in m.group(1).split(",")}
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema='extracted' AND table_name=%s""", (table,))
        real = {r[0] for r in cur.fetchall()}
        assert ins_cols <= real, "%s: inserting nonexistent %s" % (table, ins_cols - real)
    con.close()
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--sets", nargs="*", default=None)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        load(a.dsn, sets=a.sets)
