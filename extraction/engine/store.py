"""Storage for comprehension records + the per-word JSON trail.

SQLite, one row per token / span / proposition, so the article can be queried as data rather than
re-read as text. The trail is the point: for any word in the article you can ask "what is this,
what does it mean, what does it mean HERE, what statements is it part of, where exactly is it" and
get an answer with character offsets back into the source.

Offsets are the join key everywhere. Nothing stores a copy of the text as its identity, because two
occurrences of "Cubic" in one article are different mentions of the same thing and must stay
distinguishable.
"""
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "data" / "comprehend.db"

DDL = """
CREATE TABLE IF NOT EXISTS doc (
  document_id TEXT PRIMARY KEY, url TEXT, source_id TEXT, language TEXT, title TEXT,
  text TEXT, n_sentences INT, elapsed_s REAL, model TEXT, gliner TEXT, built_at TEXT,
  run_id TEXT);

-- One row per extraction batch. `doc.run_id` points here, so any stored span or statement can be
-- traced to the exact code, models and settings that produced it. Everything else the normalized
-- layer will want is derivable offline from verbatim text and exact offsets; this is not, because
-- after the batch nothing else records which commit ran.
CREATE TABLE IF NOT EXISTS extraction_run (
  run_id TEXT PRIMARY KEY, started_at TEXT, pipeline_version TEXT, lexicon_version TEXT,
  model TEXT, model_digest TEXT, gliner TEXT, config TEXT, note TEXT);

CREATE TABLE IF NOT EXISTS sentence (
  document_id TEXT, i INT, start INT, end INT, text TEXT,
  PRIMARY KEY (document_id, i));

CREATE TABLE IF NOT EXISTS token (
  document_id TEXT, i INT, start INT, end INT, text TEXT,
  kind TEXT, cls TEXT, covered INT,
  PRIMARY KEY (document_id, i));
CREATE INDEX IF NOT EXISTS token_cov ON token(document_id, cls, covered);

CREATE TABLE IF NOT EXISTS span (
  document_id TEXT, id TEXT, start INT, end INT, text TEXT,
  type TEXT, type_ner TEXT, gloss TEXT, in_article TEXT,
  source TEXT, score REAL, sent INT, type_before_lexicon TEXT, lexicon TEXT,
  PRIMARY KEY (document_id, id));
CREATE INDEX IF NOT EXISTS span_pos ON span(document_id, start, end);
CREATE INDEX IF NOT EXISTS span_type ON span(document_id, type);

CREATE TABLE IF NOT EXISTS proposition (
  document_id TEXT, i INT, subject TEXT, predicate TEXT, object TEXT,
  time TEXT, place TEXT, polarity TEXT, modality TEXT,
  ev_start INT, ev_end INT, ev_quote TEXT, ev_fragment INT DEFAULT 0,
  PRIMARY KEY (document_id, i));
CREATE INDEX IF NOT EXISTS prop_ev ON proposition(document_id, ev_start, ev_end);

CREATE TABLE IF NOT EXISTS coverage (
  document_id TEXT PRIMARY KEY,
  tokens INT, covered INT, pct_all REAL,
  content_tokens INT, content_covered INT, pct_content REAL,
  function_tokens INT, punct_tokens INT, n_uncovered_content INT,
  spans INT, spans_with_gloss INT, spans_with_in_article INT,
  pct_spans_explained REAL, pct_spans_contextual REAL,
  referential_spans INT, pct_referential_contextual REAL);

CREATE TABLE IF NOT EXISTS audit (
  document_id TEXT, i INT, kind TEXT, detail TEXT,
  PRIMARY KEY (document_id, i));
"""


def connect(path=DB):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False because run.py --workers hands this connection to a thread pool.
    # sqlite3 refuses cross-thread use by DEFAULT even when every write is already serialized by a
    # lock, so a 2-worker batch died on its first save with "created in thread X, this is thread Y".
    # Safe ONLY because run.py holds a single write lock around save(); drop the lock and this
    # becomes a corruption bug rather than an exception.
    c = sqlite3.connect(str(path), check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    # The WAL once ate a 1,020-row store: readers replay it, so everything looks fine until the WAL
    # is reset instead of checkpointed and the main file is an empty 4 KB. Consume the cursor --
    # an unconsumed PRAGMA cursor holds a read lock and the next statement fails "database locked".
    c.execute("PRAGMA synchronous=NORMAL").fetchall()
    c.executescript(DDL)
    # CREATE TABLE IF NOT EXISTS leaves an existing table at its old shape, so a store written
    # before run_id existed would keep an 11-column doc and every INSERT would fail on arity.
    if "run_id" not in {r[1] for r in c.execute("PRAGMA table_info(doc)").fetchall()}:
        c.execute("ALTER TABLE doc ADD COLUMN run_id TEXT")
        c.commit()
    return c


def save_run(conn, lineage):
    """Record one extraction run. Idempotent so a resumed batch reuses its run_id."""
    conn.execute(
        "INSERT OR REPLACE INTO extraction_run VALUES (?,?,?,?,?,?,?,?,?)",
        tuple(lineage.get(k, "") for k in
              ("run_id", "started_at", "pipeline_version", "lexicon_version", "model",
               "model_digest", "gliner", "config", "note")))
    conn.commit()
    return lineage["run_id"]


def save(conn, rec, tokens, run_id=None):
    """Write one comprehension record. Idempotent: re-running a document replaces it."""
    import datetime
    d = rec["document_id"]
    for t in ("doc", "sentence", "token", "span", "proposition", "coverage", "audit"):
        conn.execute(f"DELETE FROM {t} WHERE document_id=?", (d,))
    conn.execute(
        "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (d, rec.get("url", ""), rec.get("source_id", ""), rec.get("language", ""),
         rec.get("title", ""), rec["text"], rec["n_sentences"], rec.get("elapsed_s"),
         rec.get("model", ""), rec.get("gliner", ""),
         datetime.datetime.now().isoformat(timespec="seconds"),
         run_id or rec.get("run_id", "")))
    conn.executemany("INSERT INTO sentence VALUES (?,?,?,?,?)",
                     [(d, s["i"], s["start"], s["end"], s["text"]) for s in rec["sentences"]])
    conn.executemany("INSERT INTO token VALUES (?,?,?,?,?,?,?,?)",
                     [(d, t["i"], t["start"], t["end"], t["text"], t["kind"], t["cls"],
                       int(bool(t.get("covered")))) for t in tokens])
    conn.executemany("INSERT INTO span VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     [(d, s["id"], s["start"], s["end"], s["text"], s.get("type", ""),
                       s.get("type_ner", ""), s.get("gloss", ""), s.get("in_article", ""),
                       s.get("source", ""), s.get("score"), s.get("sent"),
                       s.get("type_before_lexicon", ""), s.get("lexicon", ""))
                      for s in rec["spans"]])
    conn.executemany("INSERT INTO proposition VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     [(d, i, p["subject"], p["predicate"], p["object"], p.get("time", ""),
                       p.get("place", ""), p.get("polarity", ""), p.get("modality", ""),
                       p["evidence"]["start"], p["evidence"]["end"], p["evidence"]["quote"],
                       int(bool(p.get("ev_fragment"))))
                      for i, p in enumerate(rec["propositions"])])
    c = rec["coverage"]
    conn.execute("INSERT INTO coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (d, c["tokens"], c["covered"], c["pct_all"], c["content_tokens"],
                  c["content_covered"], c["pct_content"], c["function_tokens"], c["punct_tokens"],
                  c["n_uncovered_content"], c.get("spans"), c.get("spans_with_gloss"),
                  c.get("spans_with_in_article"), c.get("pct_spans_explained"),
                  c.get("pct_spans_contextual"), c.get("referential_spans"),
                  c.get("pct_referential_contextual")))
    conn.executemany("INSERT INTO audit VALUES (?,?,?,?)",
                     [(d, i, a.get("kind", ""), json.dumps(a, ensure_ascii=False)[:600])
                      for i, a in enumerate(rec["audit"])])
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()


def trail(conn, document_id, word=None, start=None):
    """The JSON trail for a word: what it is, what it means, what it means here, and every
    statement it participates in — with offsets back to the article."""
    q = "SELECT i,start,end,text,kind,cls,covered FROM token WHERE document_id=?"
    args = [document_id]
    if start is not None:
        q += " AND start=?"; args.append(start)
    elif word:
        q += " AND lower(text)=lower(?)"; args.append(word)
    out = []
    for i, s, e, txt, kind, cls, cov in conn.execute(q, args).fetchall():
        spans = conn.execute(
            "SELECT id,start,end,text,type,gloss,in_article,source,sent FROM span "
            "WHERE document_id=? AND start<? AND end>? ORDER BY (end-start)",
            (document_id, e, s)).fetchall()
        sent = conn.execute(
            "SELECT i,start,end,text FROM sentence WHERE document_id=? AND start<=? AND end>? ",
            (document_id, s, s)).fetchone()
        props = conn.execute(
            "SELECT subject,predicate,object,time,place,polarity,modality,ev_start,ev_end,ev_quote "
            "FROM proposition WHERE document_id=? AND ev_start<=? AND ev_end>=?",
            (document_id, s, e)).fetchall()
        out.append({
            "word": txt, "token_index": i, "offset": [s, e], "kind": kind, "class": cls,
            "covered": bool(cov),
            "sentence": {"index": sent[0], "offset": [sent[1], sent[2]], "text": sent[3]}
            if sent else None,
            "spans": [{"id": sp[0], "offset": [sp[1], sp[2]], "text": sp[3], "type": sp[4],
                       "meaning": sp[5], "meaning_in_article": sp[6], "found_by": sp[7],
                       "sentence": sp[8]} for sp in spans],
            "statements": [{"subject": p[0], "predicate": p[1], "object": p[2], "time": p[3],
                            "place": p[4], "polarity": p[5], "modality": p[6],
                            "evidence": {"offset": [p[7], p[8]], "quote": p[9]}} for p in props],
        })
    return out


def _demo():
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    conn = connect(tmp)
    text = "Cubic signed a deal in 2026."
    rec = {"document_id": "d1", "url": "u", "source_id": "s", "language": "en", "title": "t",
           "text": text, "n_sentences": 1,
           "sentences": [{"i": 0, "start": 0, "end": len(text), "text": text}],
           "spans": [{"id": "s0", "start": 0, "end": 5, "text": "Cubic", "type": "Organization",
                      "gloss": "a company", "in_article": "the defence supplier",
                      "source": "llm", "sent": 0},
                     {"id": "s1", "start": 23, "end": 27, "text": "2026", "type": "Date",
                      "gloss": "a year", "in_article": "when the deal was signed",
                      "source": "regex", "sent": 0}],
           "propositions": [{"subject": "Cubic", "predicate": "signed", "object": "a deal",
                             "time": "2026", "place": "", "polarity": "positive",
                             "modality": "asserted",
                             "evidence": {"start": 0, "end": len(text), "quote": text}}],
           "coverage": {"tokens": 7, "covered": 2, "pct_all": 28.6, "content_tokens": 4,
                        "content_covered": 2, "pct_content": 50.0, "function_tokens": 2,
                        "punct_tokens": 1, "n_uncovered_content": 2, "spans": 2,
                        "spans_with_gloss": 2, "spans_with_in_article": 2,
                        "pct_spans_explained": 100.0, "pct_spans_contextual": 100.0,
                        "referential_spans": 1, "pct_referential_contextual": 100.0},
           "audit": [{"kind": "span_too_long", "text": "x"}], "elapsed_s": 1.0}
    toks = [{"i": 0, "start": 0, "end": 5, "text": "Cubic", "kind": "word", "cls": "content",
             "covered": True},
            {"i": 1, "start": 23, "end": 27, "text": "2026", "kind": "number", "cls": "content",
             "covered": True}]
    rid = save_run(conn, {"run_id": "run-test", "started_at": "2026-08-20T00:00:00+00:00",
                          "pipeline_version": "abc123", "lexicon_version": "def456",
                          "model": "qwen2.5:7b", "model_digest": "sha256:00", "gliner": "g",
                          "config": '{"chunk_chars": 700}', "note": ""})
    save(conn, rec, toks, run_id=rid)
    # the connection must survive being used from another thread -- run.py --workers does exactly
    # that, and the default sqlite3 setting made a 2-worker batch die on its first write
    import threading as _th
    err = []
    t = _th.Thread(target=lambda: err.append(
        conn.execute("SELECT count(*) FROM doc").fetchone()[0]))
    t.start(); t.join()
    assert err == [1], f"connection is not usable from a worker thread: {err}"
    # every document must be traceable to the run that produced it, or §15 lineage is decorative
    assert conn.execute("SELECT run_id FROM doc WHERE document_id='d1'").fetchone()[0] == "run-test"
    assert conn.execute("SELECT pipeline_version FROM extraction_run WHERE run_id=?",
                        (rid,)).fetchone()[0] == "abc123"
    save_run(conn, {"run_id": "run-test", "started_at": "x", "note": "resumed"})
    assert conn.execute("SELECT count(*) FROM extraction_run").fetchone()[0] == 1, "must upsert"
    # re-saving must replace, not duplicate -- a resumable runner will re-run documents
    save(conn, rec, toks)
    assert conn.execute("SELECT count(*) FROM span WHERE document_id='d1'").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM doc").fetchone()[0] == 1

    tr = trail(conn, "d1", word="Cubic")
    assert len(tr) == 1, tr
    t0 = tr[0]
    assert t0["offset"] == [0, 5] and t0["class"] == "content"
    assert t0["spans"][0]["meaning"] == "a company"
    assert t0["spans"][0]["meaning_in_article"] == "the defence supplier"
    assert t0["sentence"]["text"] == text
    # the word must carry the statement it participates in -- that is the "context" half
    assert t0["statements"][0]["predicate"] == "signed"
    assert t0["statements"][0]["evidence"]["quote"] == text
    # a date token resolves to its own span, not the organisation's
    td = trail(conn, "d1", word="2026")[0]
    assert td["spans"][0]["type"] == "Date" and td["spans"][0]["meaning"] == "a year"
    # offset lookup is exact and unambiguous even when the same word repeats
    assert trail(conn, "d1", start=0)[0]["word"] == "Cubic"
    print("ok")


if __name__ == "__main__":
    _demo() if "--demo" in sys.argv else _demo()
