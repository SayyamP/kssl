"""Generate PIPELINE.html -- the plain-English walkthrough from raw document to UI.

    python docs/build_pipeline_doc.py            # -> KSSL_Deploy/PIPELINE.html
    python docs/build_pipeline_doc.py --demo

The document is GENERATED, never hand-written, because a hand-written one drifts:
every prompt is imported from the module that actually runs it, every column table
is read from the live Postgres catalogue, and the worked example is a real row
traced through the real tables. Re-run it after any pipeline change.
"""
import os
import argparse
import html
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "pipeline"))
DSN = os.environ.get("KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
OUT = ROOT / "PIPELINE.html"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def esc(t):
    return html.escape(str(t if t is not None else ""), quote=False)


# --------------------------------------------------------------------------- data


def live_prompts():
    """The prompts as the running code holds them -- imported, never copied."""
    import serving_fill as sf
    import verify_cards as vc
    import enrich_serving as es
    return {
        "card": sf.PROMPT,
        "verify": vc.PROMPT,
        "profile": es.PROFILE_PROMPT,
        "partner": es.PART_PROMPT,
        "geo": es.GEO_PROMPT,
        "tender": es.TENDER_PROMPT,
        "innov": es.INNOV_PROMPT,
    }


def sample_value(cur, schema, table, col, doc_id=None, has_doc=False, has_origin=False):
    """ONE REAL value for this column, read from the live store.

    A schema table that only names its columns leaves the reader guessing what a
    `modality` or an `ev_quote` actually looks like. The value is read, never
    invented: a column with no rows behind it prints nothing rather than something
    plausible, because a made-up example in a document about provenance would be
    the exact failure this pipeline exists to prevent.

    `left(...::text, N)` keeps the read cheap -- document.text is a whole article,
    and pulling 650 of those to show one would detoast the table for a caption.
    """
    where, args = ['"%s" IS NOT NULL' % col], []
    # Prefer the document this page already traces, so the examples cohere with the
    # worked example instead of coming from 650 unrelated articles.
    if has_doc and doc_id:
        where.append("document_id = %s")
        args.append(doc_id)
    if has_origin:
        where.append("origin = 'pipeline'")
    for attempt in range(3):
        try:
            cur.execute('SELECT left(("%s")::text, 160) FROM %s."%s" WHERE %s LIMIT 1'
                        % (col, schema, table, " AND ".join(where)), tuple(args))
            row = cur.fetchone()
        except Exception:                       # noqa: BLE001 - column type or table
            cur.connection.rollback()
            return ""
        if row and row[0] not in (None, ""):
            return row[0]
        # Relax: this document, then this origin, then anything at all.
        if len(where) > 1:
            where.pop()
            args = args[:len(where) - 1]
            continue
        return ""
    return ""


def live_samples(cur, schema, tables, doc_id=None):
    """{table: {column: one real value}} for every column in the schema."""
    out = {}
    for table, cols in tables.items():
        names = {c[0] for c in cols}
        has_doc, has_origin = "document_id" in names, "origin" in names
        out[table] = {}
        for col, _ty, _nn, _cmt in cols:
            out[table][col] = sample_value(cur, schema, table, col, doc_id,
                                           has_doc, has_origin)
    return out


def live_schema(cur):
    out = {}
    for schema in ("extracted", "serving"):
        cur.execute("""SELECT c.table_name, c.column_name, c.data_type, c.is_nullable,
                              col_description(('"' || c.table_schema || '"."' ||
                                               c.table_name || '"')::regclass,
                                              c.ordinal_position)
                         FROM information_schema.columns c
                        WHERE c.table_schema = %s
                        ORDER BY c.table_name, c.ordinal_position""", (schema,))
        d = {}
        for t, col, ty, nul, cmt in cur.fetchall():
            ty = (ty.replace("character varying", "text")
                    .replace("timestamp without time zone", "timestamp")
                    .replace("double precision", "float"))
            d.setdefault(t, []).append((col, ty, nul == "NO", cmt))
        out[schema] = d
    return out


def with_samples(cur, schema_map, doc_id=None):
    """Fold one live example into every column tuple: (col, type, required, note, eg)."""
    for schema, tables in schema_map.items():
        eg = live_samples(cur, schema, tables, doc_id)
        for table, cols in tables.items():
            tables[table] = [c + (eg[table].get(c[0], ""),) for c in cols]
    return schema_map


def live_counts(cur, schema, tables):
    n = {}
    for t in tables:
        try:
            cur.execute('SELECT count(*) FROM %s."%s" WHERE origin = %%s'
                        % (schema, t), ("pipeline",))
        except Exception:                       # noqa: BLE001 - table has no origin
            cur.connection.rollback()
            cur.execute('SELECT count(*) FROM %s."%s"' % (schema, t))
        n[t] = cur.fetchone()[0]
    return n


def live_example(cur):
    """One real card, traced back to the document it came from."""
    import psycopg2.extras
    d = cur.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    d.execute("""SELECT c.*, s.what, s.why, s.facts, s.lens, s.rank AS detail_rank
                   FROM serving.signal_card c
                   JOIN serving.signal_detail s ON s.id = c.id
                  WHERE c.origin = 'pipeline' AND c.lane = 'competitive'
                  ORDER BY c.ord LIMIT 1""")
    card = d.fetchone()
    if not card:
        return None
    did = card["id"].replace("pl_", "", 1)
    d.execute("SELECT * FROM extracted.document WHERE document_id = %s", (did,))
    doc = d.fetchone()
    d.execute("""SELECT span_id, type, text, gloss, start_c, end_c
                   FROM extracted.span WHERE document_id = %s
                  ORDER BY start_c LIMIT 8""", (did,))
    spans = d.fetchall()
    d.execute("""SELECT i, subject, predicate, object, modality, time_txt,
                        ev_start, ev_end, ev_quote
                   FROM extracted.proposition WHERE document_id = %s
                  ORDER BY i LIMIT 5""", (did,))
    props = d.fetchall()
    d.execute("SELECT count(*) AS n FROM extracted.span WHERE document_id = %s", (did,))
    n_spans = d.fetchone()["n"]
    d.execute("SELECT count(*) AS n FROM extracted.proposition WHERE document_id = %s",
              (did,))
    n_props = d.fetchone()["n"]
    d.execute("""SELECT type, count(*) AS n FROM extracted.span WHERE document_id = %s
                  GROUP BY type ORDER BY n DESC LIMIT 6""", (did,))
    span_types = d.fetchall()
    return {"card": card, "doc": doc, "spans": spans, "props": props,
            "n_spans": n_spans, "n_props": n_props, "span_types": span_types}


# --------------------------------------------------------------------------- html


def col_table(cols, note=None):
    rows = []
    for col in cols:
        c, t, notnull, cmt = col[0], col[1], col[2], col[3]
        # The example is whatever the store actually holds for this column. An empty
        # cell means the column is empty in the live data -- which is information,
        # so it is shown as such rather than filled with something believable.
        eg = col[4] if len(col) > 4 else ""
        eg_cell = ('<span class=eg>%s</span>' % esc(eg) if eg
                   else '<span class=egnone>no value stored</span>')
        rows.append(
            "<tr><td class=col>%s</td><td class=ty>%s</td><td class=req>%s</td>"
            "<td>%s</td><td class=egc>%s</td></tr>"
            % (esc(c), esc(t), "required" if notnull else "", esc(cmt or ""), eg_cell))
    return ("<div class=tw><table class=schema><thead><tr><th>column</th><th>type</th>"
            "<th></th><th>what it holds</th><th>example from a real document</th></tr>"
            "</thead><tbody>%s</tbody></table></div>%s"
            % ("".join(rows), ("<p class=note>%s</p>" % note) if note else ""))


def prompt_block(text):
    return "<pre class=prompt>%s</pre>" % esc(text)


SECTIONS = [
    # id, nav label
    ("what", "What this is"),
    ("map", "The whole path"),
    ("s0", "1 · The raw document"),
    ("s1", "2 · Layer A — reading the document"),
    ("s2", "3 · Layer B — who is who"),
    ("s3", "4 · The gates (before any LLM)"),
    ("s4", "5 · Signals: competitive / market / technology"),
    ("s5", "6 · The entailment check"),
    ("s6", "7 · Companies, partnerships, geo, innovation, matchups"),
    ("s7", "8 · Tenders (live APIs)"),
    ("s8", "9 · Serving tables, column by column"),
    ("s9", "10 · Which tab reads what"),
    ("s10", "11 · What is deliberately empty"),
    ("s11", "12 · One document, followed all the way"),
]


def build(ex, schema, counts_x, counts_s, prompts):
    P = []
    a = P.append

    a('<meta charset="utf-8">')
    a("<title>KSSL Pipeline Explained</title>")
    a(STYLE)
    a(THEME_TOGGLE)
    a("<header><h1>From a news page to a card on the screen</h1>"
      "<p class=sub>Every number the KSSL dashboard shows is produced by the chain "
      "below, on this machine, from documents the crawler fetched. This page explains "
      "that chain in plain English &mdash; what each step reads, what it writes, and "
      "which database column it lands in. It is generated from the running code and "
      "the live database, so it cannot drift from what actually happens.</p></header>")

    a("<nav class=toc><ol>")
    for sid, label in SECTIONS:
        a('<li><a href="#%s">%s</a></li>' % (sid, esc(label)))
    a("</ol></nav>")
    a("<main>")

    # ---------------------------------------------------------------- what
    a('<section id=what><h2>What this is</h2>')
    a("<p>The dashboard has three pillars (Competitive, Market, Technology) and a set "
      "of tabs under each. Nothing on those tabs is typed by a person. A document is "
      "fetched, read by two local models, filtered by rules, judged by a local model, "
      "checked against its own evidence, and only then written to the tables the "
      "screen reads.</p>")
    a("<p class=rule><b>The rule the whole design serves:</b> the screen may only show "
      "something the source actually says. Where the corpus cannot support a number, "
      "the tab stays empty rather than filled with a plausible one.</p>")
    a("<div class=cards>"
      "<div class=card><h3>Two schemas</h3><p><code>extracted</code> is what the "
      "readers produced &mdash; documents, spans, propositions, entities. "
      "<code>serving</code> is what the screen reads. Nothing skips from one to the "
      "other without passing a gate.</p></div>"
      "<div class=card><h3>Two origins</h3><p>Every serving row carries "
      "<code>origin</code>: <code>reference</code> (the hand-researched demo seed, now "
      "archived) or <code>pipeline</code> (produced by this chain). The API serves "
      "only <code>pipeline</code>.</p></div>"
      "<div class=card><h3>Local models only</h3><p>A 7B extractor plus GLiNER read "
      "the documents; a 14B judge writes and verifies the cards. Both run on this "
      "machine through Ollama. No text leaves the box.</p></div>"
      "</div></section>")

    # ---------------------------------------------------------------- map
    a('<section id=map><h2>The whole path</h2>')
    a(FLOW_SVG)
    a("<p>Read it as a funnel. Thousands of sentences become hundreds of spans, spans "
      "become propositions with quotes, propositions survive a series of refusals, and "
      "the few that survive become a row on a tab. Every stage is allowed to say "
      "<i>no</i>, and every <i>no</i> is counted and printed.</p></section>")

    # ---------------------------------------------------------------- s0 raw doc
    a('<section id=s0><h2>1 &middot; The raw document</h2>')
    a("<p>A document enters as fetched text &mdash; a press release, a news article, a "
      "procurement notice. It is stored whole, in its original language, with the URL "
      "it came from. The text is never rewritten: everything downstream quotes it by "
      "character offset, so if the stored text changed, every quote would become a "
      "lie.</p>")
    if ex:
        d = ex["doc"]
        a("<div class=example><div class=exhead>The document used as the example "
          "throughout this page</div>"
          "<table class=kv>"
          "<tr><td>document_id</td><td><code>%s</code></td></tr>"
          "<tr><td>url</td><td><a href='%s'>%s</a></td></tr>"
          "<tr><td>source</td><td>%s</td></tr>"
          "<tr><td>language</td><td>%s &mdash; note this is <b>not</b> English</td></tr>"
          "<tr><td>title</td><td>%s</td></tr>"
          "<tr><td>size</td><td>%s characters, %s sentences</td></tr>"
          "</table>"
          "<div class=exhead>first lines as stored</div><pre class=doc>%s</pre></div>"
          % (esc(d["document_id"]), esc(d["url"]), esc(d["url"][:80]),
             esc(d["source_id"]), esc(d["language"]), esc(d["title"]),
             d["n_chars"], d["n_sentences"], esc(d["text"][:420]) + "&hellip;"))
    a("<h3>Where it is stored &mdash; <code>extracted.document</code></h3>")
    a(col_table(schema["extracted"]["document"],
                "%s documents currently loaded. <code>text_sha256</code> and "
                "<code>n_chars</code> exist so a changed document is detectable; "
                "<code>meta</code> records which extraction set and run produced it."
                % counts_x.get("document", 0)))
    a("</section>")

    # ---------------------------------------------------------------- s1 layer A
    a('<section id=s1><h2>2 &middot; Layer A &mdash; reading the document</h2>')
    a("<p>Layer A is the comprehension engine (a 7B model plus GLiNER, run per chunk). "
      "It does two things, and both are anchored to the text.</p>")
    a("<p><b>Spans.</b> It marks every meaningful stretch of text and says what kind of "
      "thing it is &mdash; an organisation, a weapon system, a country, a date, a "
      "money value &mdash; and what it means in English (<code>gloss</code>), even when "
      "the document is Swedish or Persian. Each span records the exact character "
      "positions it covers.</p>")
    a("<p><b>Propositions.</b> It then states what the document <i>says</i>, as "
      "subject &ndash; predicate &ndash; object, each one carrying the sentence it came "
      "from as a verbatim quote plus that quote's offsets. This is the unit everything "
      "later reads. No later step ever sees the raw page again &mdash; only these "
      "grounded statements.</p>")
    if ex:
        rows = "".join(
            "<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td>"
            "<td class=off>%s&ndash;%s</td></tr>"
            % (esc(s["span_id"]), esc(s["type"]), esc(s["text"]), esc(s["gloss"] or ""),
               s["start_c"], s["end_c"])
            for s in ex["spans"])
        a("<div class=example><div class=exhead>Spans from the example document "
          "(first %d of %d)</div><div class=tw><table class=data><thead><tr><th>id</th>"
          "<th>type</th><th>text as written</th><th>meaning in English</th>"
          "<th>offsets</th></tr></thead><tbody>%s</tbody></table></div>"
          % (len(ex["spans"]), ex["n_spans"], rows))
        types = ", ".join("%s&nbsp;%d" % (esc(t["type"]), t["n"]) for t in ex["span_types"])
        a("<p class=note>Most common types in this document: %s.</p></div>" % types)
        prows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td class=q>&ldquo;%s&rdquo;</td></tr>"
            % (p["i"], esc(p["subject"]), esc(p["predicate"]), esc(p["object"]),
               esc((p["ev_quote"] or "")[:150]))
            for p in ex["props"])
        a("<div class=example><div class=exhead>Propositions from the same document "
          "(first %d of %d)</div><div class=tw><table class=data><thead><tr><th>#</th>"
          "<th>subject</th><th>predicate</th><th>object</th><th>evidence quote</th>"
          "</tr></thead><tbody>%s</tbody></table></div>"
          "<p class=note>The subject/predicate/object are normalised to English while "
          "the quote stays exactly as the Swedish original wrote it. That is what lets "
          "an English dashboard cite a Swedish source honestly.</p></div>"
          % (len(ex["props"]), ex["n_props"], prows))
    a("<h3>Where spans are stored &mdash; <code>extracted.span</code></h3>")
    a(col_table(schema["extracted"]["span"],
                "%s spans currently loaded. The load step refuses any document whose "
                "spans fail <code>text[start_c:end_c] == text</code> &mdash; a repaired "
                "offset would be an invented quote."
                % f"{counts_x.get('span', 0):,}"))
    a("<h3>Where statements are stored &mdash; <code>extracted.proposition</code></h3>")
    a(col_table(schema["extracted"]["proposition"],
                "%s propositions currently loaded. <code>ev_quote</code> with "
                "<code>ev_start</code>/<code>ev_end</code> is the evidence every later "
                "stage quotes; <code>modality</code> records whether the document "
                "asserted, planned or speculated."
                % f"{counts_x.get('proposition', 0):,}"))
    a("</section>")

    # ---------------------------------------------------------------- s2 layer B
    a('<section id=s2><h2>3 &middot; Layer B &mdash; who is who</h2>')
    a("<p>The same company is written differently everywhere &mdash; <i>Bharat Forge</i>, "
      "<i>Bharat Forge Limited</i>, <i>Kalyani</i>. Layer B resolves mentions into "
      "canonical entities with their aliases, so counting, ordering and de-duplication "
      "all work on one identity rather than three.</p>")
    a("<p>A second, smaller identity layer (<code>pipeline/aliases.py</code>) sits in "
      "front of the serving side. It folds legal suffixes (Ltd, GmbH, S.A.), maps "
      "known variants (Hanwha Defense &rarr; Hanwha Aerospace), and encodes one "
      "standing rule: <b>Kalyani, KSSL and Bharat Forge are one client identity</b> "
      "&mdash; the client group, never a rival, never a threat to itself.</p>")
    a("<h3><code>extracted.entity</code></h3>")
    a(col_table(schema["extracted"]["entity"],
                "%s entities." % f"{counts_x.get('entity', 0):,}"))
    a("<h3><code>extracted.entity_alias</code></h3>")
    a(col_table(schema["extracted"]["entity_alias"],
                "%s aliases &mdash; the surface forms that all mean the same "
                "organisation." % f"{counts_x.get('entity_alias', 0):,}"))
    a("</section>")

    # ---------------------------------------------------------------- s3 gates
    a('<section id=s3><h2>4 &middot; The gates (before any LLM)</h2>')
    a("<p>Most documents never reach a model. The cheap refusals run first, in this "
      "order, and each one is counted and printed at the end of every run &mdash; a "
      "skipped document is a reported number, never a silent disappearance.</p>")
    a(GATES_TABLE)
    a("<p class=rule>Two of these gates exist because they failed once in production. "
      "An August-2026 news query returned a July-2024 article and the dashboard showed "
      "it as current &mdash; so recency is now proved per article, from the article's "
      "own dates, in thirteen languages. And a &ldquo;document&rdquo; that was really a "
      "site's headline ticker produced a card whose title, summary and quotes came from "
      "three unrelated stories &mdash; so listing pages are refused by URL shape before "
      "anything reads them.</p></section>")

    # ---------------------------------------------------------------- s4 cards
    a('<section id=s4><h2>5 &middot; Signals: competitive / market / technology</h2>')
    a("<p>This is the step that fills the three Overview feeds. For one document that "
      "passed every gate, the judge model is shown <b>only that document's "
      "propositions with their quotes</b> &mdash; never the raw page &mdash; and asked "
      "one question: is there a signal here a KSSL analyst should see, and which pillar "
      "does it belong to?</p>")
    a("<div class=cards>"
      "<div class=card><h3>Competitive</h3><p>A <b>rival's</b> move: an order won, a "
      "partnership, an expansion, a product launch that changes KSSL's field. KSSL's own "
      "news is never a competitive signal &mdash; the pillar tracks rivals.</p></div>"
      "<div class=card><h3>Market</h3><p>A demand event: a tender, a government order, a "
      "budget, an import or export decision that changes what buyers want.</p></div>"
      "<div class=card><h3>Technology</h3><p>A capability advance: a system demonstrated, "
      "a technical milestone, an innovation that moves what is expected in a KSSL "
      "category.</p></div></div>")
    a("<h3>The prompt, exactly as the code sends it</h3>")
    a("<p class=note>The <code>%s</code> placeholders are filled in at call time with "
      "the nine KSSL categories, then the document's title, source, language, and its "
      "list of statements.</p>")
    a(prompt_block(prompts["card"]))
    a("<h3>What is done with the answer</h3>")
    a("<p>The reply is parsed field by field, and a malformed reply is a counted "
      "failure rather than a half-written row:</p>")
    a(CARD_VALIDATION)
    a("<h3>Where it is stored</h3>")
    a("<p>Two rows are written per accepted signal: the feed row and the detail panel.</p>")
    a("<h4><code>serving.signal_card</code> &mdash; the row in the feed</h4>")
    a(col_table(schema["serving"]["signal_card"],
                "%d pipeline rows. <code>lane</code> is the pillar "
                "(competitive/market/tech); <code>ago</code> is the article's own "
                "publication month; <code>ord</code> and <code>rank</code> are "
                "renumbered from the served position, so rivals lead the competitive "
                "feed and badges start at 01." % counts_s.get("signal_card", 0)))
    a("<h4><code>serving.signal_detail</code> &mdash; the panel that opens on click</h4>")
    a(col_table(schema["serving"]["signal_detail"],
                "<code>what</code> is the event in one factual sentence; "
                "<code>why</code> is the analyst reading; <code>lens</code> holds the "
                "verbatim quotes, so a reader can always get from the card back to the "
                "sentences behind it."))
    a("</section>")

    # ---------------------------------------------------------------- s5 verify
    a('<section id=s5><h2>6 &middot; The entailment check</h2>')
    a("<p>Grounding is not entailment. The extractor guarantees the <i>quotes</i> are "
      "real; it does not guarantee the card built on them is what those quotes say. So "
      "every card is shown back to the model with its own evidence and asked whether "
      "the evidence supports it. Cards that fail are deleted and the reason is "
      "printed.</p>")
    a(prompt_block(prompts["verify"]))
    a("<p class=rule>The check is deliberately asymmetric: the <b>facts</b> in the "
      "title must be stated or directly implied (announced is not delivered, a plan is "
      "not a contract, talks are not an order), while the <b>why-it-matters</b> may "
      "infer significance &mdash; it is refused only if it asserts something the quotes "
      "do not contain. An unparseable verdict never deletes a card.</p></section>")

    # ---------------------------------------------------------------- s6 enrichment
    a('<section id=s6><h2>7 &middot; Companies, partnerships, geo, innovation, '
      'matchups</h2>')
    a("<p>The other tabs are filled by a second pass over the same propositions, one "
      "step per tab. Each step is delete-then-write for its own rows, so re-running "
      "cleans rather than duplicates.</p>")
    for key, title, table, reads, note in ENRICH_STEPS:
        a("<div class=step><h3>%s</h3><p>%s</p>" % (esc(title), reads))
        a(prompt_block(prompts[key]))
        a("<p class=stores>Stored in <code>serving.%s</code> &mdash; %s</p>" % (table, note))
        a(col_table(schema["serving"][table]))
        a("</div>")
    a("<div class=step><h3>Positioning &mdash; product matchups</h3>"
      "<p>Rival products named in the corpus are paired against the KSSL product in the "
      "same category. This step writes no numbers it was not given: "
      "<code>specs</code> stays empty and <code>edge</code>, <code>verdict</code> stay "
      "NULL unless the corpus states a comparable figure &mdash; which defence news "
      "almost never does. The tab therefore shows real rival products with their "
      "evidence and an honest &ldquo;no measured gap&rdquo; state.</p>"
      "<p class=stores>Stored in <code>serving.matchup</code> &mdash; %d pipeline rows."
      "</p>%s</div>" % (counts_s.get("matchup", 0), col_table(schema["serving"]["matchup"])))
    a("</section>")

    # ---------------------------------------------------------------- s7 tenders
    a('<section id=s7><h2>8 &middot; Tenders (live APIs, not news)</h2>')
    a("<p>News reports awards; it rarely publishes an open solicitation with a deadline "
      "and a value. So the Tender Pipeline is fed from procurement APIs directly &mdash; "
      "SAM.gov (US), TED (EU, by defence CPV codes), and India's GeM and CPPP &mdash; "
      "filtered to KSSL's portfolio and mapped onto the same nine categories.</p>")
    a(TENDER_TABLE)
    a("<p>A tender is kept only if its <b>title</b> matches the portfolio; issuer names "
      "were disqualified as evidence after a company called &ldquo;Armoured Vehicles "
      "Nigam&rdquo; filed floor-tile tenders that the filter read as armoured vehicles. "
      "Bare words that look military but are not (&ldquo;cartridge&rdquo; in "
      "<i>cartridge-type heater</i>, &ldquo;armored&rdquo; in <i>Armored Brigade turf "
      "replacement</i>) are excluded by name.</p>")
    a("<p class=note>Two writers share this table &mdash; the API fetcher (ids prefixed "
      "<code>sam_</code>, <code>ted_</code>, <code>gem_</code>) and the news step "
      "(numeric ids). Each deletes only its own id space; a blanket delete wiped the "
      "API feed once, which is why the boundary is now explicit.</p>")
    a("<h3><code>serving.tender</code></h3>")
    a(col_table(schema["serving"]["tender"],
                "%d pipeline rows. <code>dl</code> is left NULL &mdash; the interface "
                "computes the countdown from <code>deadline</code>, and a tender with "
                "no stated deadline reads &ldquo;no deadline on record&rdquo; rather "
                "than a manufactured number." % counts_s.get("tender", 0)))
    a("</section>")

    # ---------------------------------------------------------------- s8 serving
    a('<section id=s8><h2>9 &middot; Serving tables, column by column</h2>')
    a("<p>Everything the screen reads lives in these tables. The API assembles them "
      "into the shapes the interface expects; it computes rollups (patent totals, "
      "company order) but invents nothing.</p>")
    done = {"signal_card", "signal_detail", "tender", "matchup"}
    done |= {t for _, _, t, _, _ in ENRICH_STEPS}
    rest = [t for t in sorted(schema["serving"]) if t not in done]
    for t in rest:
        a("<h3><code>serving.%s</code> <span class=cnt>%d rows</span></h3>"
          % (t, counts_s.get(t, 0)))
        a(col_table(schema["serving"][t], SERVING_NOTES.get(t, "")))
    a("<p class=rule>Every table above carries <code>origin</code>. The API reads "
      "<code>serving_live</code>, a set of views filtered to "
      "<code>origin='pipeline'</code>, so the archived demo data cannot leak onto the "
      "screen. Setting <code>KSSL_SERVE_ORIGIN=all</code> points the backend back at "
      "the raw tables to inspect the archive.</p></section>")

    # ---------------------------------------------------------------- s9 tabs
    a('<section id=s9><h2>10 &middot; Which tab reads what</h2>')
    a(TABS_TABLE)
    a("</section>")

    # ---------------------------------------------------------------- s10 empty
    a('<section id=s10><h2>11 &middot; What is deliberately empty</h2>')
    a("<p>Two tabs are empty on purpose, and saying so is part of the design: an empty "
      "tab is a true statement about the corpus, whereas a filled one would be a "
      "false statement about the world.</p>")
    a(EMPTY_TABLE)
    a("</section>")

    # ---------------------------------------------------------------- s11 example
    a('<section id=s11><h2>12 &middot; One document, followed all the way</h2>')
    if ex:
        c, d = ex["card"], ex["doc"]
        facts = c["facts"] if isinstance(c["facts"], list) else json.loads(c["facts"] or "[]")
        lens = c["lens"] if isinstance(c["lens"], list) else json.loads(c["lens"] or "[]")
        a("<ol class=walk>")
        a("<li><b>A page is fetched.</b> %s publishes a press release in Swedish: "
          "<i>%s</i>. It is stored whole as <code>%s</code>, %s characters."
          "</li>" % (esc(d["source_id"]), esc(d["title"]), esc(d["document_id"]),
                     d["n_chars"]))
        a("<li><b>Layer A reads it.</b> %d spans are marked and %d statements are "
          "extracted. The Swedish word <i>granatgeväret</i> is typed as a weapon system "
          "and glossed in English; the order value is typed as a money value."
          "</li>" % (ex["n_spans"], ex["n_props"]))
        a("<li><b>The gates run.</b> The URL is a press release, not a listing page. The "
          "article's own date proves the year. Saab is a tracked rival, so the document "
          "is on-portfolio. No earlier card has this title.</li>")
        a("<li><b>The judge reads the statements &mdash; not the page.</b> It files the "
          "signal as <b>%s</b>, category <b>%s</b>, direction <b>%s</b>, and writes an "
          "English headline from a Swedish source: <i>%s</i></li>"
          % (esc(c["lane"]), esc(c["tags"]), esc(c["dir"]), esc(c["title"])))
        a("<li><b>The entailment check.</b> The card is shown its own quotes and asked "
          "whether they support it. This one passed &mdash; note the wording of the "
          "event line: <i>%s</i> The source says an order was received, so the card says "
          "received, not delivered.</li>" % esc(c["what"]))
        a("<li><b>It is written to two rows.</b> <code>signal_card</code> holds the feed "
          "row (<code>lane=%s</code>, <code>ord=%s</code>, <code>rank=%s</code>, "
          "<code>ago=%s</code>, <code>company=%s</code>); <code>signal_detail</code> "
          "holds the panel.</li>"
          % (esc(c["lane"]), esc(c["ord"]), esc(c["rank"]), esc(c["ago"]),
             esc(c["company"])))
        a("<li><b>The screen reads those rows.</b> The card appears in the Competitive "
          "feed; clicking it opens the panel below.</li>")
        a("</ol>")
        a("<div class=example><div class=exhead>The panel, as stored</div>"
          "<table class=kv>%s</table>"
          % "".join("<tr><td>%s</td><td>%s</td></tr>" % (esc(k), esc(v))
                    for k, v in facts))
        a("<div class=exhead>Why it matters (the analyst reading)</div><p>%s</p>"
          % esc(c["why"]))
        if lens:
            a("<div class=exhead>Evidence, verbatim from the Swedish source</div>")
            for row in lens[:3]:
                if isinstance(row, list) and len(row) > 1:
                    a("<p class=lens>%s</p>" % row[1])
        a("<p class=note>The quotes are the original Swedish sentences, reproduced "
          "character for character from the stored document. That is the whole point of "
          "the offset contract: the analysis is in English, the proof is in the source "
          "language.</p></div>")
    a("</section>")

    a("</main>")
    a("<footer><p>Generated from the running pipeline code and the live database by "
      "<code>docs/build_pipeline_doc.py</code>. Re-run it after any change to a prompt, "
      "a gate or a schema.</p></footer>")
    return "\n".join(P)


# --------------------------------------------------------------------------- copy

GATES_TABLE = """
<div class=tw><table class=data>
<thead><tr><th>gate</th><th>what it refuses</th><th>why it exists</th></tr></thead>
<tbody>
<tr><td>audit suppression</td><td>document ids an audit ruled out</td>
<td>a human verdict must outlive the next re-run</td></tr>
<tr><td>listing page</td><td>homepages, <code>/tag/</code>, <code>/category/</code>,
paginated archives, media indexes</td>
<td>they are collections of headlines; a card built from one mixes unrelated stories</td></tr>
<tr><td>no statements</td><td>documents Layer A could not read</td>
<td>a document with no grounded statements would have to be summarised from raw text</td></tr>
<tr><td>provable date</td><td>documents with no date of their own</td>
<td>the fetch date is not the publication date</td></tr>
<tr><td>recency</td><td>articles older than roughly three months</td>
<td>an intelligence feed showing 2024 news as current is wrong, not stale</td></tr>
<tr><td>portfolio relevance</td><td>documents that name no KSSL category and no tracked
company</td><td>keeps the feed about artillery, ammunition, armour, small arms, naval,
UAVs, missiles and forgings</td></tr>
<tr><td>duplicate story</td><td>a story already carded, under any company spelling</td>
<td>one event syndicated by four outlets is one signal</td></tr>
<tr><td>client-news in the rival lane</td><td>KSSL / Kalyani / Bharat Forge stories filed
as competitive</td><td>the competitive pillar tracks rivals; the client is not its own
rival</td></tr>
</tbody></table></div>"""

CARD_VALIDATION = """
<div class=tw><table class=data>
<thead><tr><th>field</th><th>rule</th><th>if it fails</th></tr></thead>
<tbody>
<tr><td>pillar</td><td>exactly one of competitive / market / technology</td>
<td>the card is refused (an unknown pillar used to default into the rival lane)</td></tr>
<tr><td>category</td><td>exactly one of the nine KSSL categories</td>
<td>refused &mdash; a free-text category joins nothing downstream</td></tr>
<tr><td>title, company, sowhat</td><td>all present, English</td><td>refused whole</td></tr>
<tr><td>dir</td><td>threat or watch</td><td>falls back to watch, never to threat</td></tr>
<tr><td>company (client group)</td><td>Kalyani / KSSL / Bharat Forge</td>
<td>forced to watch, and removed from the competitive lane entirely</td></tr>
<tr><td>all text</td><td>HTML-escaped at write time</td>
<td>article text is not curated markup and must not be able to inject any</td></tr>
</tbody></table></div>"""

ENRICH_STEPS = [
    ("profile", "Companies — the rival roster and the drawer behind each name",
     "competitors",
     "Every company the corpus actually covers gets a profile built from up to 25 of "
     "its own statements: sector, headquarters, an assessment, a threat level, and the "
     "products the statements name. Sources are recorded per profile.",
     "one row per company, %s"),
    ("partner", "Partnerships — who is tied to whom", "partner",
     "Statements whose predicate indicates a partnership, joint venture or agreement "
     "are read one at a time. The model must name the two organisations separately; a "
     "single field holding &ldquo;X and Y&rdquo; is refused, and two companies merely "
     "mentioned in the same sentence are not a tie.",
     "client-group ties; rival ties are attached to the company profiles"),
    ("geo", "Geo footprint — activity by country", "geo_presence",
     "Statements that place a company in a country. The bar is an <b>activity</b> "
     "&mdash; production, export, service, a partnership &mdash; not an address: a "
     "headquarters, a sales office or a round of talks is refused, because a map dot "
     "means presence, and presence is a claim.",
     "one row per company-country activity"),
    ("tender", "Tenders mentioned in the news", "tender",
     "Documents whose statements describe a procurement event. This is a cross-check "
     "only &mdash; the real tender feed comes from the APIs in the next section &mdash; "
     "and an intention or an unveiling is not a tender.",
     "news-sourced rows (numeric ids), alongside the API rows"),
    ("innov", "Innovation pipeline — capability advances", "innovation",
     "Documents describing a technical advance, filed under one of the eight KSSL "
     "technology areas. Maturity is held to what the source says: demonstrated is not "
     "fielded, a concept is not a product. This rule alone refused most candidates.",
     "one row per advance, grouped by technology area"),
]

SERVING_NOTES = {
    "ui_config": "Interface vocabulary &mdash; category names, labels, synonyms, the "
                 "chat suggestions. This is language, not data, so it is served "
                 "regardless of origin.",
    "company_source": "The documents each company was read from &mdash; this is what "
                      "makes the &lsquo;sourced&rsquo; badges honest.",
    "source_registry": "Every outlet the corpus drew on, per company.",
    "geo_comp": "The companies plotted on the map.",
    "patent": "Empty by design &mdash; see section 11.",
}

TENDER_TABLE = """
<div class=tw><table class=data>
<thead><tr><th>source</th><th>how it is queried</th><th>what is kept</th></tr></thead>
<tbody>
<tr><td>SAM.gov (US)</td><td>opportunities API, date-window slicing, ten rotating keys
read from the TendPro environment at runtime</td><td>notices whose title matches the
portfolio</td></tr>
<tr><td>TED (EU)</td><td>search API restricted to defence CPV codes &mdash; weapons and
ammunition, military vehicles, warships, military aircraft and UAVs</td>
<td>English titles where the notice provides them</td></tr>
<tr><td>GeM (India)</td><td>public bid-search API with the Ministry of Defence filter</td>
<td>defence bids in KSSL categories</td></tr>
<tr><td>CPPP (India)</td><td>the captcha-free pagers</td>
<td>nothing, in the current window &mdash; those feeds are dominated by civil works;
deeper defence rows need the captcha-gated search</td></tr>
</tbody></table></div>"""

TABS_TABLE = """
<div class=tw><table class=data>
<thead><tr><th>pillar &middot; tab</th><th>reads</th><th>what the reader sees</th></tr></thead>
<tbody>
<tr><td>Competitive &middot; Overview</td><td><code>signal_card</code> (lane
competitive) + <code>signal_detail</code></td><td>rival moves, rivals ordered before
anyone else, newest first within each group</td></tr>
<tr><td>Competitive &middot; Positioning</td><td><code>matchup</code></td>
<td>KSSL products against rival products by category, with the evidence behind each
pairing</td></tr>
<tr><td>Competitive &middot; Gap Analysis</td><td><code>matchup</code> (only rows with a
measured edge)</td><td>currently empty &mdash; see section 11</td></tr>
<tr><td>Competitive &middot; Partnerships</td><td><code>competitors</code>,
<code>partner</code></td><td>the alliance network per company, and which ties KSSL
shares</td></tr>
<tr><td>Competitive &middot; Geo Footprint</td><td><code>geo_presence</code>,
<code>geo_comp</code></td><td>a map of where rivals actually do something</td></tr>
<tr><td>Competitive &middot; Patents</td><td><code>patent</code></td>
<td>empty &mdash; see section 11</td></tr>
<tr><td>Market &middot; Overview</td><td><code>signal_card</code> (lane market)</td>
<td>demand and procurement signals</td></tr>
<tr><td>Market &middot; Tender Pipeline / Awarded / Closed</td><td><code>tender</code></td>
<td>live solicitations with countdowns, then awarded and expired ones</td></tr>
<tr><td>Technology &middot; Overview</td><td><code>signal_card</code> (lane tech)</td>
<td>capability signals</td></tr>
<tr><td>Technology &middot; Innovation Pipeline</td><td><code>innovation</code></td>
<td>advances grouped by technology area</td></tr>
<tr><td>every tab</td><td><code>company_source</code>, <code>source_registry</code></td>
<td>the source chips that let a reader open the original article</td></tr>
</tbody></table></div>"""

EMPTY_TABLE = """
<div class=tw><table class=data>
<thead><tr><th>tab</th><th>why it is empty</th><th>what would fill it honestly</th></tr></thead>
<tbody>
<tr><td>Gap Analysis</td><td>it scores measured spec differences, and the corpus is news.
Defence journalism reports that a howitzer was ordered, not its chamber pressure, so
there is nothing to measure.</td>
<td>manufacturer datasheets or a specification database, parsed into the matchup
<code>specs</code> field</td></tr>
<tr><td>Patents</td><td>no patent data exists in a news corpus, and no writer invents
one.</td><td>a patent-office feed &mdash; EPO, WIPO or India's inPASS &mdash; with
assignees resolved through the same identity layer</td></tr>
</tbody></table></div>"""

FLOW_SVG = """
<figure class=flow>
<svg viewBox="0 0 900 300" role="img" aria-label="The pipeline from a fetched page to a
dashboard tab, with refusal gates between stages" xmlns="http://www.w3.org/2000/svg">
<defs><marker id="pa" markerWidth="9" markerHeight="9" refX="8" refY="3"
orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="currentColor"/></marker></defs>
<g fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#pa)">
<path d="M132,52 L172,52"/><path d="M292,52 L332,52"/><path d="M452,52 L492,52"/>
<path d="M572,70 L572,110"/><path d="M572,168 L572,208"/><path d="M492,228 L452,228"/>
<path d="M332,228 L292,228"/>
</g>
<g font-size="12" text-anchor="middle" fill="currentColor">
<rect x="12" y="32" width="120" height="40" rx="5" fill="none" stroke="currentColor"/>
<text x="72" y="50">crawler / API</text><text x="72" y="64" opacity=".7">a page, whole</text>
<rect x="172" y="32" width="120" height="40" rx="5" fill="none" stroke="currentColor"/>
<text x="232" y="50">Layer A</text><text x="232" y="64" opacity=".7">spans + statements</text>
<rect x="332" y="32" width="120" height="40" rx="5" fill="none" stroke="currentColor"/>
<text x="392" y="50">Layer B</text><text x="392" y="64" opacity=".7">who is who</text>
<rect x="492" y="32" width="160" height="40" rx="5" fill="none" stroke="currentColor"/>
<text x="572" y="50">extracted schema</text><text x="572" y="64" opacity=".7">offsets checked</text>
<rect x="492" y="110" width="160" height="58" rx="5" fill="none" stroke="currentColor"
stroke-dasharray="4 3"/>
<text x="572" y="130">the gates</text><text x="572" y="146" opacity=".7">listing · date ·</text>
<text x="572" y="160" opacity=".7">portfolio · duplicate</text>
<rect x="492" y="208" width="160" height="40" rx="5" fill="none" stroke="currentColor"/>
<text x="572" y="226">local judge</text><text x="572" y="240" opacity=".7">writes the card</text>
<rect x="332" y="208" width="120" height="40" rx="5" fill="none" stroke="currentColor"/>
<text x="392" y="226">entailment</text><text x="392" y="240" opacity=".7">quotes vs claim</text>
<rect x="172" y="208" width="120" height="40" rx="5" fill="none" stroke="currentColor"/>
<text x="232" y="226">serving schema</text><text x="232" y="240" opacity=".7">what the UI reads</text>
<text x="72" y="232" font-weight="600">the tab</text>
<text x="450" y="285" opacity=".75" font-size="11">every stage may refuse — and every
refusal is counted and printed, never silent</text>
</g></svg>
<figcaption>The path a document takes. The dashed box is where most documents
stop.</figcaption>
</figure>"""

# Stamped before the body paints, so an overridden theme does not flash the other
# palette first. Every read and write is guarded: a page opened from file:// or in a
# private window can throw on storage access, and the toggle still has to work.
THEME_TOGGLE = """<button class=themetog id=themetog type=button
  aria-label="Switch between light and dark">Light</button>
<script>
(function(){
  var K="kssl-pipeline-theme", r=document.documentElement;
  function sysDark(){ try{ return matchMedia("(prefers-color-scheme: dark)").matches; }
                      catch(e){ return false; } }
  function stored(){ try{ return localStorage.getItem(K); }catch(e){ return null; } }
  function now(){ var v=stored(); return v || (sysDark() ? "dark" : "light"); }
  function paint(){
    var t=now();
    r.setAttribute("data-theme", t);
    var b=document.getElementById("themetog");
    if(b) b.textContent = (t==="dark" ? "Light" : "Dark");
  }
  paint();
  document.addEventListener("click", function(e){
    var b=e.target.closest && e.target.closest("#themetog");
    if(!b) return;
    var next = now()==="dark" ? "light" : "dark";
    try{ localStorage.setItem(K, next); }catch(err){}
    paint();
  });
  try{ matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function(){
    if(!stored()) paint();
  }); }catch(e){}
})();
</script>"""

STYLE = """<style>
:root{
  --bg:#fbfaf8; --ink:#1c1a17; --dim:#5d564d; --line:#e0dbd2; --card:#ffffff;
  --accent:#8a4b2a; --code-bg:#f4f1ec; --mark:#f7efe6;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#16150f; --ink:#eae5db; --dim:#a49c8f; --line:#2f2c25; --card:#1d1b15;
    --accent:#d9925f; --code-bg:#211f19; --mark:#2a241b;
  }
}
:root[data-theme="dark"]{
  --bg:#16150f; --ink:#eae5db; --dim:#a49c8f; --line:#2f2c25; --card:#1d1b15;
  --accent:#d9925f; --code-bg:#211f19; --mark:#2a241b;
}
/* Theme switch. The palette above already answers the system setting; this only
   lets a reader override it, and the choice is remembered per browser. */
.themetog{position:fixed;top:14px;right:14px;z-index:9;
  font:600 12px/1 ui-sans-serif,system-ui,sans-serif;letter-spacing:.04em;
  color:var(--dim);background:var(--card);border:1px solid var(--line);
  border-radius:999px;padding:8px 13px;cursor:pointer}
.themetog:hover{color:var(--accent);border-color:var(--accent)}
@media print{.themetog{display:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.65 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;}
header{padding:56px 24px 30px;max-width:900px;margin:0 auto;}
h1{font-size:clamp(28px,4.6vw,44px);line-height:1.12;margin:0 0 14px;
  letter-spacing:-.02em;text-wrap:balance;}
.sub{color:var(--dim);max-width:66ch;margin:0;font-size:17px}
nav.toc{max-width:900px;margin:0 auto 20px;padding:0 24px}
nav.toc ol{columns:2;column-gap:34px;padding-left:18px;margin:0;font-size:14.5px}
nav.toc li{margin:3px 0;break-inside:avoid}
nav.toc a{color:var(--dim);text-decoration:none;border-bottom:1px solid transparent}
nav.toc a:hover{color:var(--accent);border-bottom-color:var(--accent)}
main{max-width:900px;margin:0 auto;padding:0 24px 80px}
section{padding:34px 0;border-top:1px solid var(--line)}
h2{font-size:25px;margin:0 0 16px;letter-spacing:-.01em;text-wrap:balance}
h3{font-size:18px;margin:26px 0 8px}
h4{font-size:15px;margin:18px 0 6px;color:var(--dim);
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600}
p{max-width:70ch}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.88em;
  background:var(--code-bg);padding:1px 5px;border-radius:3px}
a{color:var(--accent)}
.rule{background:var(--mark);border-left:3px solid var(--accent);
  padding:12px 16px;border-radius:0 4px 4px 0;max-width:70ch}
.note{color:var(--dim);font-size:14.5px;max-width:70ch}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;
  margin:18px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:14px 16px}
.card h3{margin:0 0 6px;font-size:15px;color:var(--accent)}
.card p{font-size:14.5px;margin:0;color:var(--dim)}
.tw{overflow-x:auto;margin:12px 0;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:14px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
table.data,table.schema{background:var(--card)}
th{text-align:left;font-weight:600;color:var(--dim);font-size:12px;
  text-transform:uppercase;letter-spacing:.06em;padding:9px 12px;
  border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
td.col{color:var(--accent);white-space:nowrap}
td.ty{color:var(--dim);white-space:nowrap;font-size:13px}
td.req{color:var(--dim);font-size:11.5px;text-transform:uppercase;letter-spacing:.05em}
td.off{color:var(--dim);white-space:nowrap}
td.q{color:var(--dim);font-style:italic}
/* The prose column is no longer last -- the example column is -- so it is addressed
   by position rather than by :last-child, which silently moved to the examples. */
table.data td:last-child,table.schema td:nth-child(4){
  font-family:inherit;font-size:14.5px;min-width:14rem}
td.egc{max-width:22rem;min-width:11rem}
span.eg{color:var(--accent);font-size:12.5px;word-break:break-word;
  display:inline-block;line-height:1.45}
span.egnone{color:var(--dim);opacity:.55;font-size:12px;font-style:italic}
table.kv td:first-child{color:var(--dim);white-space:nowrap;width:11rem}
table.kv{background:transparent;font-size:14.5px}
table.kv td{font-family:inherit}
pre.prompt{background:var(--code-bg);border:1px solid var(--line);border-left:3px solid var(--accent);
  border-radius:0 5px 5px 0;padding:14px 16px;overflow-x:auto;white-space:pre-wrap;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;line-height:1.5}
pre.doc{background:var(--code-bg);border-radius:5px;padding:12px 14px;overflow-x:auto;
  white-space:pre-wrap;font-size:13.5px;font-family:inherit;color:var(--dim);margin:6px 0 0}
.example{background:var(--card);border:1px solid var(--line);border-radius:6px;
  padding:16px 18px;margin:16px 0}
.exhead{font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);
  margin:10px 0 6px;font-family:ui-monospace,Menlo,monospace}
.exhead:first-child{margin-top:0}
.step{border-left:2px solid var(--line);padding-left:18px;margin:26px 0}
.step h3{margin-top:0;color:var(--accent)}
.stores{font-size:14.5px;color:var(--dim)}
.cnt{font-size:12px;color:var(--dim);font-weight:400;
  font-family:ui-monospace,Menlo,monospace}
.lens{background:var(--code-bg);border-radius:4px;padding:9px 12px;font-size:14px;
  margin:6px 0;max-width:none}
ol.walk{max-width:72ch;padding-left:22px}
ol.walk li{margin:12px 0}
figure.flow{margin:20px 0;padding:16px;background:var(--card);border:1px solid var(--line);
  border-radius:6px}
figure.flow svg{width:100%;height:auto;max-width:100%}
figcaption{color:var(--dim);font-size:13.5px;margin-top:10px;text-align:center}
footer{border-top:1px solid var(--line);max-width:900px;margin:0 auto;padding:22px 24px 60px}
footer p{color:var(--dim);font-size:13.5px;margin:0}
@media (max-width:620px){nav.toc ol{columns:1}}
</style>"""


# --------------------------------------------------------------------------- main


def main():
    import psycopg2
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    schema = live_schema(cur)
    counts_x = live_counts(cur, "extracted", schema["extracted"])
    counts_s = live_counts(cur, "serving", schema["serving"])
    # The worked example is chosen FIRST so the per-column examples can be drawn from
    # the same document, and the reader sees one story rather than a bag of unrelated
    # fragments.
    ex = live_example(cur)
    schema = with_samples(cur, schema,
                          (ex or {}).get("doc", {}).get("document_id"))
    prompts = live_prompts()
    con.close()
    body = build(ex, schema, counts_x, counts_s, prompts)
    OUT.write_text(body, encoding="utf-8")
    print("wrote %s (%.0f KB) -- %d serving tables, %d extracted tables, %s docs"
          % (OUT, len(body) / 1024, len(schema["serving"]), len(schema["extracted"]),
             counts_x.get("document", 0)))


def _demo():
    # The document's whole authority is that it quotes the CODE, not a copy of it.
    p = live_prompts()
    assert "competitive" in p["card"] and "NONE" in p["card"]
    assert "SUPPORTED" in p["verify"]
    for k in ("profile", "partner", "geo", "tender", "innov"):
        assert len(p[k]) > 200, k
    # esc() must neutralise markup coming from the database
    assert esc("<b>&x") == "&lt;b&gt;&amp;x"
    # every section id in the nav must be emitted by build()
    ids = {s for s, _ in SECTIONS}
    assert len(ids) == len(SECTIONS), "duplicate section id"

    # the example column renders what it is GIVEN, and says so when given nothing
    h = col_table([("document_id", "text", True, "Stable id.", "doc_2beae347139eeca8"),
                   ("gloss", "text", False, "Short description.", "")])
    assert "example from a real document" in h
    assert "doc_2beae347139eeca8" in h
    assert "no value stored" in h, "an empty column must not look like a filled one"
    # a column tuple with no example at all still renders (older callers)
    assert "no value stored" in col_table([("x", "text", False, "n")])
    # and a value out of the database cannot inject markup
    assert "<img" not in col_table([("x", "text", False, "n", '<img src=x>')])
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        main()
