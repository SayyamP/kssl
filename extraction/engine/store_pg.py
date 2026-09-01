"""Write one extracted document to Postgres, atomically with its queue commit.

WHY THIS EXISTS
---------------
The first version of the queue worker wrote spans to `--db /tmp/run_a.db`, a SQLite file inside
the compute container, and separately marked the queue row `done`. Both halves of that were wrong
and the second one is the dangerous half:

  * container-local /tmp does not survive `docker rm`. Recreating a worker to change one
    environment variable destroyed a completed document's extraction, and nothing noticed.
  * `done` therefore meant "the worker finished", not "the result is stored". Those two came
    apart the moment the file vanished, and the queue went on reporting success for output that
    no longer existed. A dashboard reading it would have been confidently wrong.

So the rule here: **the spans and the `done` mark are written in ONE transaction, fenced on the
lease epoch.** Either both land or neither does. A crash mid-write rolls back and the lease
expires, and the document is simply claimed again -- which is safe because the write is an upsert
keyed on (document_id, run_id, span_id).

WHAT IT DOES NOT DO
-------------------
It does not write to the `serving` schema. Those are UI cards, derived downstream from these rows
by the card writer. Layer A's job ends at `extracted`.
"""
import hashlib
import sys
import json


try:                              # psycopg3 if present; the constants are all we need
    from psycopg.pq import TransactionStatus as _TS
    _TX_IDLE, _TX_UNKNOWN = _TS.IDLE, _TS.UNKNOWN
except Exception:                 # keeps the module importable on a laptop with no psycopg
    _TX_IDLE, _TX_UNKNOWN = 0, 4


def _sha256(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


RUN_SQL = """
INSERT INTO extracted.extraction_run (run_id, started_at, pipeline_version, lexicon_version,
                                      model, config, note)
VALUES (%(run_id)s, now(), %(pipeline_version)s, %(lexicon_version)s, %(model)s,
        %(config)s, %(note)s)
ON CONFLICT (run_id) DO NOTHING;
"""

DOC_SQL = """
INSERT INTO extracted.document (document_id, url, source_id, language, title, text,
                                text_sha256, n_chars, n_sentences, meta)
VALUES (%(document_id)s, %(url)s, %(source_id)s, %(language)s, %(title)s, %(text)s,
        %(sha)s, %(n_chars)s, %(n_sentences)s, %(meta)s)
ON CONFLICT (document_id) DO UPDATE SET
  text = EXCLUDED.text, text_sha256 = EXCLUDED.text_sha256, n_chars = EXCLUDED.n_chars,
  n_sentences = EXCLUDED.n_sentences, title = EXCLUDED.title,
  -- MERGE, do not replace: harvest metadata (published_at, band, ...) loaded by another path must
  -- survive a worker re-extraction. EXCLUDED wins per-key, but keys the worker doesn't carry stay.
  meta = COALESCE(extracted.document.meta, '{}'::jsonb) || EXCLUDED.meta;
"""

SPAN_SQL = """
INSERT INTO extracted.span (document_id, run_id, span_id, start_c, end_c, text, type,
                            type_ner, gloss, in_article, source, score, sent)
VALUES (%(document_id)s, %(run_id)s, %(span_id)s, %(start_c)s, %(end_c)s, %(text)s, %(type)s,
        %(type_ner)s, %(gloss)s, %(in_article)s, %(source)s, %(score)s, %(sent)s)
ON CONFLICT (document_id, run_id, span_id) DO UPDATE SET
  start_c = EXCLUDED.start_c, end_c = EXCLUDED.end_c, text = EXCLUDED.text,
  type = EXCLUDED.type, gloss = EXCLUDED.gloss, in_article = EXCLUDED.in_article;
"""

PROP_SQL = """
INSERT INTO extracted.proposition (document_id, run_id, i, subject, predicate, object,
                                   time_txt, place_txt, polarity, modality,
                                   ev_start, ev_end, ev_quote, ev_fragment)
VALUES (%(document_id)s, %(run_id)s, %(i)s, %(subject)s, %(predicate)s, %(object)s,
        %(time_txt)s, %(place_txt)s, %(polarity)s, %(modality)s,
        %(ev_start)s, %(ev_end)s, %(ev_quote)s, %(ev_fragment)s)
ON CONFLICT (document_id, run_id, i) DO NOTHING;
"""

# state='leased' as well as the epoch: REAP can PARK a row without the epoch changing, and a
# worker the queue believes it evicted would otherwise flip that parked row to `done` -- quietly
# undoing the very decision that evicted it.
# Fenced: a worker whose lease expired while it was still alive commits with a stale epoch and is
# rejected here, rather than overwriting whatever the re-run produced.
DONE_SQL = """
UPDATE extract_queue SET state='done', leased_by=NULL, lease_until=NULL
WHERE document_id=%(doc)s AND lease_epoch=%(epoch)s AND state='leased'
RETURNING document_id;
"""


def run_config(lineage):
    """The `config` jsonb for extraction_run, carrying the provenance the table has no column for.

    extracted.extraction_run has no model_digest and no gliner column, but a stored result is
    worthless if it cannot be tied back to the exact weights that produced it -- so both ride
    inside config instead of being dropped.

    lineage["config"] is a JSON STRING (lineage.py json.dumps() it at construction), not a dict.
    Assuming otherwise cost a second silent production failure in this same function: `dict()` on
    a str raises "dictionary update sequence element #0 has length 1; 2 is required", every worker
    extracted perfectly and then threw its document away. Accept either shape and never trust the
    caller's word about which one it is."""
    cfg = lineage.get("config") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except (ValueError, TypeError):
            cfg = {"raw": cfg}
    if not isinstance(cfg, dict):
        cfg = {"raw": cfg}
    cfg = dict(cfg)
    cfg["model_digest"] = lineage.get("model_digest")
    cfg["gliner"] = lineage.get("gliner")
    return cfg


def prop_row(doc_id, run_id, i, p):
    """(is_valid, row) for one proposition.

    The table is strict where it matters: subject, predicate, object and ev_quote are NOT NULL
    with CHECK (col <> ''), and CHECK (ev_end > ev_start). _clean() turns '' into None, so an
    empty subject arrives as a NOT NULL violation rather than as an empty string -- and because
    every proposition is written inside the document's single transaction, that one bad row takes
    the entire document down with it. Validate here and drop the row, not the document."""
    # comprehend() emits evidence NESTED -- {"evidence": {"start", "end", "quote"}} at
    # comprehend.py:814 -- and store.py:134, the SQLite writer whose output imported cleanly,
    # flattens it on the way in. Reading flat p["ev_start"] here silently yielded None for every
    # proposition, so the validator below rejected 100% of them and the document committed with
    # none, marked done, unrecoverable. The flat keys stay as a fallback for salvage-shaped rows.
    ev = p.get("evidence")
    if not isinstance(ev, dict):
        ev = {}
    row = {"document_id": doc_id, "run_id": run_id, "i": i,
           "subject": _clean(p.get("subject")), "predicate": _clean(p.get("predicate")),
           "object": _clean(p.get("object")),
           "time_txt": _clean(p.get("time")), "place_txt": _clean(p.get("place")),
           "polarity": _clean(p.get("polarity")), "modality": _clean(p.get("modality")),
           "ev_start": ev.get("start", p.get("ev_start")),
           "ev_end": ev.get("end", p.get("ev_end")),
           "ev_quote": _clean(ev.get("quote", p.get("ev_quote"))),
           "ev_fragment": bool(p.get("ev_fragment"))}
    if not all(row[k] for k in ("subject", "predicate", "object", "ev_quote")):
        return False, row
    a, b = row["ev_start"], row["ev_end"]
    if a is None or b is None or b <= a:
        return False, row
    return True, row


def _clean(v):
    """Empty string -> NULL. Every text column in this schema carries CHECK (col <> ''), so an
    empty gloss is a constraint violation rather than a missing value. Sending NULL is what the
    schema means by absent."""
    v = (v or "").strip()
    return v or None


def _doc_meta(rec):
    """The JSONB written to extracted.document.meta. Coverage stats stay at the top level (existing
    readers expect them there); published_at is added when the crawler proved one, because the
    serving date-gate reads meta->>'published_at'. Merged (not replaced) on conflict by DOC_SQL, so
    a harvest-loaded date is never clobbered by a worker that lacks one.

    fetched_at is stored alongside it because published_at alone cannot be trusted: the crawler
    stamps the fetch date when the page declares none, and the gate needs both values to tell a
    real publication date from that fallback."""
    meta = dict(rec.get("coverage") or {})
    pub = rec.get("published_at")
    if pub:
        meta["published_at"] = str(pub)
    fetched = rec.get("fetched_at")
    if fetched:
        meta["fetched_at"] = str(fetched)
    return meta


def save_and_commit(conn, rec, lineage, doc_id, epoch, verify=True):
    """-> (n_spans, n_props) on success, or None if the lease was lost.

    ONE transaction. The caller must not have anything else open on this connection.
    """
    spans = rec.get("spans") or []
    text = rec["text"]

    if verify:
        # The offset contract, checked once more at the boundary. Everything upstream enforces it,
        # but this is the last point before the data becomes someone else's input, and a span that
        # fails here would be a silent falsehood in the store rather than a caught error.
        for s in spans:
            if text[s["start"]:s["end"]] != s["text"]:
                raise ValueError("offset contract violated for %r at %d:%d -- refusing to store"
                                 % (s["text"][:40], s["start"], s["end"]))

    run_id = lineage["run_id"]
    # Guard the contract this module's docstring claims. psycopg's conn.transaction() silently
    # degrades to a SAVEPOINT when a transaction is already open, which turns "either both land or
    # neither" into "neither is durable yet" -- the precise failure this file exists to prevent.
    if getattr(conn, "info", None) is not None and conn.info.transaction_status not in (
            _TX_IDLE, _TX_UNKNOWN):
        # Do NOT quietly commit whatever the caller left open -- that would make someone else's
        # uncommitted work durable as a side effect of storing a document, and would hide the
        # next instance of the savepoint bug instead of surfacing it. run_node commits after
        # fetch_doc, so reaching here at all means a new caller defect exists.
        raise RuntimeError(
            "save_and_commit needs a clean connection: a transaction is already open, so "
            "conn.transaction() would nest as a SAVEPOINT and nothing would be durable. "
            "Commit or roll back before calling.")
    with conn.transaction():
        with conn.cursor() as c:
            dropped_props = []
            cfg = run_config(lineage)
            c.execute(RUN_SQL, {"run_id": run_id, "pipeline_version": lineage.get("pipeline_version"),
                                "lexicon_version": lineage.get("lexicon_version"),
                                "model": lineage.get("model"),
                                "config": json.dumps(cfg),
                                "note": lineage.get("note")})
            c.execute(DOC_SQL, {"document_id": doc_id, "url": _clean(rec.get("url")),
                                "source_id": _clean(rec.get("source_id")),
                                "language": _clean(rec.get("language")),
                                "title": _clean(rec.get("title")), "text": text,
                                "sha": _sha256(text), "n_chars": len(text),
                                "n_sentences": rec.get("n_sentences"),
                                "meta": json.dumps(_doc_meta(rec))})
            # Idempotent re-store: clear this run's prior spans/props before re-inserting, so a
            # re-extraction that yields fewer rows cannot leave stale ones behind (SPAN upsert kept
            # leftovers; PROP was DO NOTHING, so a changed proposition kept its old content forever).
            c.execute("DELETE FROM extracted.span WHERE document_id=%(d)s AND run_id=%(r)s",
                      {"d": doc_id, "r": run_id})
            c.execute("DELETE FROM extracted.proposition WHERE document_id=%(d)s AND run_id=%(r)s",
                      {"d": doc_id, "r": run_id})
            for i, s in enumerate(spans):
                c.execute(SPAN_SQL, {
                    "document_id": doc_id, "run_id": run_id,
                    "span_id": s.get("id") or ("s%05d" % i),
                    "start_c": s["start"], "end_c": s["end"], "text": s["text"],
                    "type": s.get("type") or "Other", "type_ner": _clean(s.get("type_ner")),
                    "gloss": _clean(s.get("gloss")), "in_article": _clean(s.get("in_article")),
                    "source": _clean(s.get("source")), "score": s.get("score"),
                    "sent": s.get("sent")})
            props = []
            for i, p in enumerate(rec.get("propositions") or []):
                ok, row = prop_row(doc_id, run_id, i, p)
                # Ground the evidence: the quote a card will show as proof must actually appear in
                # the document. A hallucinated quote passes prop_row's field checks but fails here.
                # Substring (not offset-exact) on purpose -- it catches fabrication without risking
                # over-drop if evidence offsets drift by a few chars from the quote's true position.
                if ok and row["ev_quote"] and row["ev_quote"] not in text:
                    ok = False
                if not ok:
                    # Dropped, never coerced. subject/predicate/object/ev_quote are NOT NULL and
                    # ev_end > ev_start is a CHECK, so ONE malformed proposition inserted blindly
                    # aborts the whole transaction and throws away a document that took 8-25
                    # minutes to extract. A proposition is an inference ABOUT the document; losing
                    # one costs an inference, losing the transaction costs the document.
                    dropped_props.append(row)
                    continue
                c.execute(PROP_SQL, row)
                props.append(row)
            # LAST, and inside the same transaction. If this returns nothing our lease was taken,
            # the whole transaction rolls back, and the spans we just wrote are discarded with it
            # -- which is correct: whoever holds the lease now owns the result.
            c.execute(DONE_SQL, {"doc": doc_id, "epoch": epoch})
            if c.fetchone() is None:
                raise _LeaseLost()
    conn.commit()                 # the block above is a transaction, not a savepoint -- make it so
    if dropped_props:
        print("      [store] %d proposition(s) dropped as malformed" % len(dropped_props),
              flush=True)
    return len(spans), len(props)


class _LeaseLost(Exception):
    pass


def _demo():
    # run_config has now failed in production twice -- once on a column that does not exist, once
    # on assuming a dict where lineage hands a string. Both were invisible until a worker had
    # already finished a document and thrown it away. These four lines are what makes a third
    # variant fail here instead of there.
    # A proposition exactly as comprehend.py:814 emits it. This assertion fails against the
    # flat-key version of prop_row, which is how 100% of propositions were being dropped while
    # every document still reported success.
    _canon = {"subject": "India", "predicate": "ordered", "object": "Rafale jets",
              "time": "2024", "place": "", "polarity": "positive", "modality": "asserted",
              "ev_fragment": False,
              "evidence": {"start": 10, "end": 34, "quote": "India ordered Rafale jets"}}
    _ok, _row = prop_row("d1", "r1", 0, _canon)
    assert _ok, "a canonical comprehend-shaped proposition must be ACCEPTED, got %r" % (_row,)
    assert (_row["ev_start"], _row["ev_end"]) == (10, 34), _row
    assert _row["ev_quote"] == "India ordered Rafale jets", _row
    assert _row["place_txt"] is None and _row["time_txt"] == "2024", _row
    # ...and a genuinely malformed one is still refused rather than corrupting the transaction
    assert not prop_row("d1", "r1", 1, {"subject": "x"})[0], "incomplete proposition must be dropped"

    _s = run_config({"config": '{"a": 1}', "model_digest": "d", "gliner": "g"})
    assert _s == {"a": 1, "model_digest": "d", "gliner": "g"}, _s
    _d = run_config({"config": {"a": 1}, "model_digest": "d", "gliner": "g"})
    assert _d == _s, "a dict config must behave exactly as the JSON string form"
    assert run_config({})["model_digest"] is None, "absent lineage must not raise"
    assert run_config({"config": "not json"})["raw"] == "not json", \
        "unparseable config is kept, never silently dropped"
    _ = json.dumps(run_config({"config": '{"a": 1}'}))   # must be jsonb-serialisable

    # Pure checks -- no database needed, so this runs anywhere.
    assert _clean("  ") is None and _clean(None) is None, "empty must become NULL, not ''"
    assert _clean(" x ") == "x"
    assert len(_sha256("abc")) == 64

    # The offset contract must be enforced at the boundary, not assumed.
    class _C:
        def transaction(self): raise AssertionError("must not reach the database")
    rec = {"text": "MBDA sold Rafale jets.", "spans": [{"start": 0, "end": 4, "text": "WRONG"}]}
    try:
        save_and_commit(_C(), rec, {"run_id": "r"}, "d1", 1)
        raise AssertionError("a bad offset was accepted")
    except ValueError as e:
        assert "offset contract" in str(e)

    # A correct span passes verification and only then reaches the connection.
    rec["spans"] = [{"start": 0, "end": 4, "text": "MBDA"}]
    try:
        save_and_commit(_C(), rec, {"run_id": "r"}, "d1", 1)
        raise AssertionError("should have reached the transaction")
    except AssertionError as e:
        assert "must not reach" in str(e), e

    # The done-mark must be fenced and must be the LAST statement, or a lost lease would leave
    # spans written under a run nobody owns.
    assert "lease_epoch=%(epoch)s" in DONE_SQL
    assert SPAN_SQL.index("INSERT") >= 0 and "ON CONFLICT" in SPAN_SQL
    print("ok  spans + done-mark are one fenced transaction; offsets verified at the boundary")


PREFLIGHT_REC = {
    "text": "India ordered Rafale jets in 2024.", "url": "", "source_id": "preflight",
    "language": "en", "title": "", "n_sentences": 1, "coverage": {},
    "spans": [{"start": 0, "end": 5, "text": "India", "type": "Location", "id": "s0"}],
    "propositions": [{"subject": "India", "predicate": "ordered", "object": "Rafale jets",
                      "polarity": "positive", "modality": "asserted", "ev_fragment": False,
                      "evidence": {"start": 0, "end": 34,
                                   "quote": "India ordered Rafale jets in 2024."}}],
}


def preflight(conn, lineage):
    """Push one canonical record through the REAL store path, then roll it back. Raises on failure.

    A catalogue check is not enough. Of the four store failures this module has had, --check-schema
    would have caught two (a column that does not exist, twice) and MISSED two -- dict() on a JSON
    string, and reading flat ev_start where comprehend emits nested evidence. In both misses every
    column existed and the MAPPING was wrong, which only executing the path can catch.

    _LeaseLost IS the success signal, and that is the whole trick: it is raised after every INSERT
    has run against the live schema and while still inside the transaction, which then rolls back.
    Full path exercised, zero rows written, nothing to clean up.

    Refusing to drain on failure converts "extract for 25 minutes, discard it, silently, for
    hours" into "this worker will not start" -- which even print-based observability cannot miss."""
    problems = check_schema(conn)
    # check_schema SELECTs, which opens a transaction on a non-autocommit connection -- and
    # save_and_commit rightly refuses a dirty one. Caught by this very preflight on its first run,
    # which is the behaviour we wanted: the guard fires instead of silently nesting a savepoint.
    conn.rollback()
    if problems:
        raise RuntimeError("schema mismatch: " + "; ".join(problems[:4]))
    try:
        save_and_commit(conn, PREFLIGHT_REC, lineage, "_preflight_no_such_document", -1)
    except _LeaseLost:
        conn.rollback()
        return True                    # every INSERT executed; the fence found no row; rolled back
    except Exception:
        conn.rollback()
        raise
    raise RuntimeError("preflight done-mark matched a nonexistent document -- the fence is broken")


def check_schema(conn):
    """Validate EVERY INSERT in this module against the live schema. Returns a list of problems.

    This function exists because the same six lines failed in production four separate times --
    a column that did not exist (model_digest), a type assumption (dict() on a JSON string), a
    second nonexistent column (prop_id), and a NOT NULL that _clean() turned into None. Every one
    was invisible until a worker had already spent 8-25 minutes extracting a document, and every
    one then threw that document away. None of them needed a running model to detect: they are all
    a mismatch between text in this file and the catalogue, checkable in milliseconds.

    Run it before trusting a deploy: `python3 store_pg.py --check-schema`."""
    import re
    problems = []
    with conn.cursor() as c:
        c.execute("SELECT table_name, column_name, is_nullable, column_default IS NOT NULL "
                  "FROM information_schema.columns WHERE table_schema='extracted'")
        real = {}
        for t, col, nullable, has_default in c.fetchall():
            real.setdefault(t, {})[col] = (nullable == "YES", has_default)
    src = open(__file__).read()
    for m in re.finditer(r"INSERT INTO extracted\.(\w+)\s*\(([^)]*)\)", src, re.S):
        tbl = m.group(1)
        used = [x.strip() for x in m.group(2).replace("\n", " ").split(",") if x.strip()]
        if tbl not in real:
            problems.append("%s: table does not exist" % tbl)
            continue
        for col in used:
            if col not in real[tbl]:
                problems.append("%s.%s: column does not exist" % (tbl, col))
        for col, (nullable, has_default) in real[tbl].items():
            if not nullable and not has_default and col not in used:
                problems.append("%s.%s: NOT NULL with no default, never supplied" % (tbl, col))
    return problems


if __name__ == "__main__":
    if "--preflight" in sys.argv:
        import os
        import psycopg
        from lineage import run_lineage
        with psycopg.connect(os.environ["KSSL_CORPUS_DSN"]) as _c:
            preflight(_c, run_lineage(note="preflight"))
        print("  preflight ok: the real store path runs clean against the live schema")
        sys.exit(0)
    if "--check-schema" in sys.argv:
        import os
        import psycopg
        with psycopg.connect(os.environ["KSSL_CORPUS_DSN"]) as _c:
            _p = check_schema(_c)
        print("\n".join("  BAD  " + x for x in _p) if _p else "  schema ok: every INSERT matches")
        sys.exit(1 if _p else 0)
    _demo()
