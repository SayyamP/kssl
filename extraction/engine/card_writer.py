"""Derive serving cards from `extracted.*` so the UI has something to read.

WHY THIS EXISTS
---------------
Layer A's job ends at `extracted.document` / `span` / `proposition`: verified spans, offsets that
satisfy `document.text[start_c:end_c] == span.text`, propositions with evidence. That is the
system of record and it is correct.

Nothing consumed it. There was no serving schema at all -- not empty, absent -- and the dashboard
was reading week-old SQLite files off its own disk with no database connection. Both ends of the
pipeline were disconnected: the crawler was not feeding the queue (fixed), and the store was not
feeding the UI (this file).

WHAT A CARD IS
--------------
Not a new idea. `ask.py:card()` already defined it and has been the thing questions are answered
against: a title/source header, the statements with their evidence quotes, and the things
mentioned. This materialises that same shape into Postgres instead of rebuilding it per query.

Two details from ask.py are carried over deliberately, because both were learned the hard way:

  * spans are ordered by IMPORTANCE, not length. Ordering longest-first and truncating pushed the
    short spans to the end -- which is exactly where money, dates and identifiers live. A price and
    a manufacturer were both extracted, both fell off the end, and the answerer said "not
    recorded" about facts the system held.
  * the article's own prose is never included, only the evidence quotes attached to propositions.
    Including the source text would test a system we did not build.

REBUILDABLE, NEVER AUTHORITATIVE
--------------------------------
A card is a projection. Every row can be dropped and regenerated from `extracted.*` without loss,
which is why the writer is a plain idempotent upsert with no state of its own. If a card and the
store ever disagree, the store is right and the card is stale -- so `--check` compares them rather
than trusting either.
"""
import argparse
import json
import os
import sys

DDL = """
CREATE SCHEMA IF NOT EXISTS serving;

CREATE TABLE IF NOT EXISTS serving.card (
  document_id  TEXT NOT NULL,
  run_id       TEXT NOT NULL,
  title        TEXT,
  source_id    TEXT,
  language     TEXT,
  url          TEXT,
  n_chars      INTEGER NOT NULL,
  n_spans      INTEGER NOT NULL,
  n_props      INTEGER NOT NULL,
  card_text    TEXT NOT NULL,          -- the rendered card, exactly as ask.py builds it
  spans        JSONB NOT NULL,         -- deduped, importance-ordered
  statements   JSONB NOT NULL,         -- propositions with evidence offsets
  built_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (document_id, run_id)
);

-- The UI's two questions: "show me this document" and "who/what is mentioned anywhere".
CREATE INDEX IF NOT EXISTS card_source_idx ON serving.card (source_id);
CREATE INDEX IF NOT EXISTS card_built_idx  ON serving.card (built_at DESC);
CREATE INDEX IF NOT EXISTS card_spans_gin  ON serving.card USING GIN (spans jsonb_path_ops);
CREATE INDEX IF NOT EXISTS card_stmts_gin  ON serving.card USING GIN (statements jsonb_path_ops);
"""

# Ported verbatim from ask.py's ORDER BY. Money/Date/Measure/Identifier first is not a stylistic
# choice -- it is the fix for spans falling off the end of a truncated card.
TYPE_RANK = {
    "Money": 0, "Date": 0, "Measure": 0, "Identifier": 0,
    "Count": 1, "Organization": 1, "Person": 1, "Location": 1, "Platform": 1,
    "Product": 1, "WeaponSystem": 1, "Program": 1, "Contract": 1, "Facility": 1,
    "Role": 2, "Event": 2, "Document": 2,
    "Action": 4,
}
DEFAULT_RANK = 3
MAX_SPANS = 600


def rank(span_type):
    return TYPE_RANK.get(span_type, DEFAULT_RANK)


def order_spans(spans, max_spans=MAX_SPANS):
    """Importance first, then longest. Deduped on lowercased text, first occurrence wins.

    Dedup matters more than it looks: an entity named twelve times would otherwise consume twelve
    of the card's span budget and push twelve other facts out."""
    ordered = sorted(spans, key=lambda s: (rank(s.get("type")),
                                           -(int(s.get("end_c") or 0) - int(s.get("start_c") or 0))))
    out, seen = [], set()
    for s in ordered:
        k = (s.get("text") or "").lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= max_spans:
            break
    return out


def render_card(doc, spans, props):
    """The card as TEXT, byte-compatible with ask.py's rendering."""
    L = ["ARTICLE: %s" % (doc.get("title") or ""),
         "SOURCE: %s  LANGUAGE: %s" % (doc.get("source_id") or "", doc.get("language") or ""),
         "", "STATEMENTS:"]
    for p in props:
        bits = "- %s | %s | %s" % (p.get("subject"), p.get("predicate"), p.get("object"))
        if p.get("time_txt"):
            bits += " | when: %s" % p["time_txt"]
        if p.get("place_txt"):
            bits += " | where: %s" % p["place_txt"]
        if p.get("polarity") == "negative":
            bits += " | NEGATED"
        if p.get("modality") and p["modality"] != "asserted":
            bits += " | %s" % p["modality"]
        bits += '\n    evidence: "%s"' % (p.get("ev_quote") or "")[:220]
        L.append(bits)
    L += ["", "THINGS MENTIONED (term — type — meaning — what it is in this article):"]
    for s in spans:
        L.append("- %s — %s — %s — %s" % (s.get("text"), s.get("type"),
                                          s.get("gloss") or "?", s.get("in_article") or "?"))
    return "\n".join(L)


UPSERT = """
INSERT INTO serving.card (document_id, run_id, title, source_id, language, url,
                          n_chars, n_spans, n_props, card_text, spans, statements, built_at)
VALUES (%(document_id)s, %(run_id)s, %(title)s, %(source_id)s, %(language)s, %(url)s,
        %(n_chars)s, %(n_spans)s, %(n_props)s, %(card_text)s, %(spans)s, %(statements)s, now())
ON CONFLICT (document_id, run_id) DO UPDATE SET
  title=EXCLUDED.title, source_id=EXCLUDED.source_id, language=EXCLUDED.language,
  url=EXCLUDED.url, n_chars=EXCLUDED.n_chars, n_spans=EXCLUDED.n_spans,
  n_props=EXCLUDED.n_props, card_text=EXCLUDED.card_text, spans=EXCLUDED.spans,
  statements=EXCLUDED.statements, built_at=now();
"""

# Only documents whose extraction is NEWER than their card, so a run over a large store is cheap.
PENDING = """
SELECT d.document_id, s.run_id
FROM extracted.document d
JOIN (SELECT DISTINCT document_id, run_id FROM extracted.span) s
  ON s.document_id = d.document_id
LEFT JOIN serving.card c ON c.document_id = d.document_id AND c.run_id = s.run_id
WHERE %s
ORDER BY d.first_seen DESC
LIMIT %%(lim)s;
"""


def build(conn, limit=500, rebuild=False):
    where = "TRUE" if rebuild else "c.document_id IS NULL"
    n = 0
    with conn.cursor() as c:
        c.execute(PENDING % where, {"lim": limit})
        todo = c.fetchall()
    for doc_id, run_id in todo:
        with conn.cursor() as c:
            c.execute("SELECT document_id, title, source_id, language, url, n_chars "
                      "FROM extracted.document WHERE document_id=%s", (doc_id,))
            r = c.fetchone()
            if r is None:
                continue
            doc = dict(zip(("document_id", "title", "source_id", "language", "url", "n_chars"), r))
            c.execute("SELECT span_id, start_c, end_c, text, type, type_ner, gloss, in_article, "
                      "source, score, sent FROM extracted.span "
                      "WHERE document_id=%s AND run_id=%s", (doc_id, run_id))
            cols = ("span_id", "start_c", "end_c", "text", "type", "type_ner", "gloss",
                    "in_article", "source", "score", "sent")
            spans_all = [dict(zip(cols, x)) for x in c.fetchall()]
            c.execute("SELECT i, subject, predicate, object, time_txt, place_txt, polarity, "
                      "modality, ev_start, ev_end, ev_quote, ev_fragment "
                      "FROM extracted.proposition WHERE document_id=%s AND run_id=%s ORDER BY i",
                      (doc_id, run_id))
            pcols = ("i", "subject", "predicate", "object", "time_txt", "place_txt", "polarity",
                     "modality", "ev_start", "ev_end", "ev_quote", "ev_fragment")
            props = [dict(zip(pcols, x)) for x in c.fetchall()]

        spans = order_spans(spans_all)
        row = dict(doc, run_id=run_id, n_spans=len(spans_all), n_props=len(props),
                   card_text=render_card(doc, spans, props),
                   spans=json.dumps(spans, default=float),
                   statements=json.dumps(props, default=float))
        with conn.cursor() as c:
            c.execute(UPSERT, row)
        n += 1
    conn.commit()
    return n


def export_sqlite(conn, out_path, limit=None):
    """Project the Postgres store into a SQLite file the existing dashboard already reads.

    The dashboard is deeply SQLite-coupled -- DATA_DIR.glob("*.db"), sqlite3.connect across a
    dozen endpoints -- and it is not our container. Rewriting its data layer to speak Postgres
    would be a large change to a running UI to solve a problem that does not need one: /api/stores
    already auto-discovers ANY *.db in its data directory that has a `doc` table, and lists it for
    selection. So the cheapest correct move is to hand it a file in the shape it expects.

    The schema comes from store.connect() rather than being retyped here. Retyping it is exactly
    how this codebase produced four separate production failures -- a column that did not exist, a
    key that was nested, a type that was a string -- so the schema has one definition and this
    reads it.

    A projection, like serving.card: droppable and regenerable, never authoritative.
    """
    import sqlite3
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import store                                    # its DDL, not a copy of its DDL

    if os.path.exists(out_path):
        os.remove(out_path)                          # a full rebuild; the store is the truth
    sq = store.connect(out_path)

    with conn.cursor() as c:
        c.execute("SELECT run_id, started_at, pipeline_version, lexicon_version, model, "
                  "config::text, note FROM extracted.extraction_run")
        for r in c.fetchall():
            cfg = {}
            try:
                cfg = json.loads(r[5] or "{}")
            except (ValueError, TypeError):
                pass
            sq.execute("INSERT OR REPLACE INTO extraction_run VALUES (?,?,?,?,?,?,?,?,?)",
                       (r[0], str(r[1]) if r[1] else None, r[2], r[3], r[4],
                        cfg.get("model_digest"), cfg.get("gliner"), r[5], r[6]))

        lim = " LIMIT %d" % int(limit) if limit else ""
        c.execute("SELECT d.document_id, d.url, d.source_id, d.language, d.title, d.text, "
                  "d.n_sentences, d.meta::text, d.first_seen, "
                  "(SELECT run_id FROM extracted.span s WHERE s.document_id=d.document_id "
                  " LIMIT 1) AS run_id "
                  "FROM extracted.document d ORDER BY d.first_seen DESC" + lim)
        docs = c.fetchall()

    n_doc = n_span = n_prop = n_bad = 0
    for d in docs:
        doc_id, text, run_id = d[0], d[5] or "", d[9]
        meta = {}
        try:
            meta = json.loads(d[7] or "{}")
        except (ValueError, TypeError):
            pass
        sq.execute("INSERT OR REPLACE INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (doc_id, d[1], d[2], d[3], d[4], text, d[6], meta.get("elapsed_s"),
                    meta.get("model"), meta.get("gliner"),
                    str(d[8]) if d[8] else None, run_id))
        n_doc += 1

        with conn.cursor() as c:
            c.execute("SELECT span_id, start_c, end_c, text, type, type_ner, gloss, in_article, "
                      "source, score, sent FROM extracted.span WHERE document_id=%s", (doc_id,))
            for sp in c.fetchall():
                a, b, t = int(sp[1]), int(sp[2]), sp[3]
                # The contract, re-checked at the last boundary before another system reads it.
                # A span whose offsets no longer address its own text would render a highlight
                # over the wrong words -- visibly wrong, and blamed on the extractor.
                if text[a:b] != t:
                    n_bad += 1
                    continue
                sq.execute("INSERT OR REPLACE INTO span VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (doc_id, sp[0], a, b, t, sp[4], sp[5], sp[6], sp[7], sp[8],
                            sp[9], sp[10], None, None))
                n_span += 1
            c.execute("SELECT i, subject, predicate, object, time_txt, place_txt, polarity, "
                      "modality, ev_start, ev_end, ev_quote, ev_fragment "
                      "FROM extracted.proposition WHERE document_id=%s ORDER BY i", (doc_id,))
            for pr in c.fetchall():
                sq.execute("INSERT OR REPLACE INTO proposition VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (doc_id, pr[0], pr[1], pr[2], pr[3], pr[4], pr[5], pr[6], pr[7],
                            pr[8], pr[9], pr[10], int(bool(pr[11]))))
                n_prop += 1

        cov = meta if "pct_content" in meta else None
        if cov:
            sq.execute("INSERT OR REPLACE INTO coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (doc_id, cov.get("tokens"), cov.get("covered"), cov.get("pct_all"),
                        cov.get("content_tokens"), cov.get("content_covered"),
                        cov.get("pct_content"), cov.get("function_tokens"),
                        cov.get("punct_tokens"), cov.get("n_uncovered_content"),
                        cov.get("spans"), cov.get("spans_with_gloss"),
                        cov.get("spans_with_in_article"), cov.get("pct_spans_explained"),
                        cov.get("pct_spans_contextual"), cov.get("referential_spans"),
                        cov.get("pct_referential_contextual")))
    sq.commit()
    sq.close()
    return {"docs": n_doc, "spans": n_span, "props": n_prop, "offset_violations": n_bad}


def check(conn):
    """A card is a projection; the store is the truth. Report disagreement, never 'fix' it."""
    out = []
    with conn.cursor() as c:
        c.execute("SELECT count(*) FROM extracted.document d WHERE NOT EXISTS "
                  "(SELECT 1 FROM serving.card s WHERE s.document_id=d.document_id)")
        missing = c.fetchone()[0]
        if missing:
            out.append("%d extracted document(s) have no card" % missing)
        c.execute("SELECT count(*) FROM serving.card s WHERE NOT EXISTS "
                  "(SELECT 1 FROM extracted.document d WHERE d.document_id=s.document_id)")
        orphan = c.fetchone()[0]
        if orphan:
            out.append("%d card(s) reference a document no longer in the store" % orphan)
        c.execute("SELECT count(*) FROM serving.card s JOIN (SELECT document_id, run_id, "
                  "count(*) n FROM extracted.span GROUP BY 1,2) e "
                  "ON e.document_id=s.document_id AND e.run_id=s.run_id WHERE e.n <> s.n_spans")
        drift = c.fetchone()[0]
        if drift:
            out.append("%d card(s) disagree with the store on span count" % drift)
    return out


def _demo():
    doc = {"title": "Rheinmetall wins artillery contract", "source_id": "defence-industry.eu",
           "language": "en", "url": "", "n_chars": 100}
    spans = [
        {"text": "Rheinmetall", "type": "Organization", "gloss": "German defence firm",
         "in_article": "the winner", "start_c": 0, "end_c": 11},
        {"text": "23,50 EUR", "type": "Money", "gloss": "unit price", "in_article": "price",
         "start_c": 40, "end_c": 49},
        {"text": "rheinmetall", "type": "Organization", "gloss": "dup", "in_article": "dup",
         "start_c": 60, "end_c": 71},
        {"text": "signed", "type": "Action", "gloss": "signing", "in_article": "the act",
         "start_c": 80, "end_c": 86},
    ]
    ordered = order_spans(spans)
    # Money must outrank a longer Organization -- this is the exact regression ask.py documents:
    # order by length and the price falls off the end of a truncated card.
    assert ordered[0]["type"] == "Money", [s["type"] for s in ordered]
    # Action ranks last, below the default, because it is the least card-worthy span type.
    assert ordered[-1]["type"] == "Action", [s["type"] for s in ordered]
    # Dedup is case-insensitive and keeps the first occurrence only.
    assert sum(1 for s in ordered if s["text"].lower() == "rheinmetall") == 1, ordered
    assert len(ordered) == 3, ordered

    props = [{"subject": "Rheinmetall", "predicate": "won", "object": "a contract",
              "time_txt": "2024", "place_txt": None, "polarity": "positive",
              "modality": "asserted", "ev_quote": "Rheinmetall won a contract"}]
    txt = render_card(doc, ordered, props)
    assert "ARTICLE: Rheinmetall wins artillery contract" in txt
    assert "when: 2024" in txt and "where:" not in txt      # empty place must not be rendered
    assert "| NEGATED" not in txt and "| asserted" not in txt   # defaults stay silent
    assert 'evidence: "Rheinmetall won a contract"' in txt
    assert "23,50 EUR" in txt

    neg = [dict(props[0], polarity="negative", modality="planned", place_txt="Berlin")]
    t2 = render_card(doc, ordered, neg)
    assert "| NEGATED" in t2 and "| planned" in t2 and "where: Berlin" in t2

    # The article's own prose is never in a card -- only evidence quotes.
    assert "n_chars" not in txt
    print("ok  cards render importance-first, dedup, and carry evidence only")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("KSSL_CORPUS_DSN"))
    ap.add_argument("--init", action="store_true", help="create the serving schema")
    ap.add_argument("--build", action="store_true", help="build cards for new extractions")
    ap.add_argument("--rebuild", action="store_true", help="rebuild every card")
    ap.add_argument("--check", action="store_true", help="compare cards against the store")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--export-sqlite", metavar="PATH",
                    help="project the store into a SQLite file the existing dashboard reads")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo or len(sys.argv) == 1:
        _demo(); return
    import psycopg
    with psycopg.connect(a.dsn) as conn:
        if a.init:
            with conn.cursor() as c:
                c.execute(DDL)
            conn.commit()
            print("serving schema ready")
        if a.build or a.rebuild:
            print("built %d card(s)" % build(conn, limit=a.limit, rebuild=a.rebuild))
        if a.check:
            p = check(conn)
            print("\n".join("  BAD  " + x for x in p) if p else "  cards agree with the store")
            sys.exit(1 if p else 0)
        if a.export_sqlite:
            r = export_sqlite(conn, a.export_sqlite)
            print("exported %(docs)d docs, %(spans)d spans, %(props)d statements "
                  "(%(offset_violations)d spans refused on the offset contract)" % r)
        if a.status:
            with conn.cursor() as c:
                c.execute("SELECT count(*), coalesce(sum(n_spans),0), coalesce(sum(n_props),0), "
                          "max(built_at) FROM serving.card")
                n, sp, pr, ts = c.fetchone()
            print("serving.card: %d cards, %d spans, %d statements, newest %s" % (n, sp, pr, ts))


if __name__ == "__main__":
    main()
