"""KSSL_Deploy backend.

GET /api/dataset returns ALL 35 globals in exactly the contract shapes
(contract_shapes.json), assembled from the serving.* tables + serving.ui_config.
Derived rollups computed here:
  - compOrder            = key order of serving.competitors (ord)
  - PATENTS.byArea       = flat serving.patent rows grouped by area (ord order)
  - PATENTS.byAssignee   = same rows grouped by assignee (assignee_ord order)

Optional fields that the reference dataset OMITS (rather than nulls) are
omitted here too when NULL — presence is not shape, but an unexpected null
where the app expects absence has blanked the UI before. Fields that are
honestly null in the reference (matchup.edge, patent.granted) stay null.

Env: KSSL_DSN (default host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl)
"""

import json
import os
import sys
from datetime import datetime, timezone

# The threat grade is SHARED with the pipeline, not reimplemented here -- the same
# reason pipeline/stage_timer.py is copied into this image rather than rewritten. Two
# definitions of "how bad is this" is how the served number and the displayed number
# stopped agreeing the last time a figure in this codebase was derived twice.
for _p in (os.path.dirname(os.path.abspath(__file__)),
           os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "extraction", "signals")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import threat_gate  # noqa: E402

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

DEFAULT_DSN = "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl"
DSN = os.environ.get("KSSL_DSN", DEFAULT_DSN)
# Reference rows are ARCHIVED: kept in serving.* (and reference_dataset.json) but
# not served. serving_live.* are views filtered to origin='pipeline' (ui_config
# passes through -- it is interface vocabulary, not data). KSSL_SERVE_ORIGIN=all
# points the app back at the raw tables to see the archive.
SCHEMA = "serving" if os.environ.get("KSSL_SERVE_ORIGIN") == "all" else "serving_live"

def _q(cur, sql, params=None):
    cur.execute(sql.replace("serving.", SCHEMA + "."), params)


app = FastAPI(title="KSSL serving API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # localhost dev; front door added later
    allow_methods=["*"],
    allow_headers=["*"],
)

# Field lists follow contract_shapes.json; OPT = omit when NULL (absent in the
# reference dataset when missing, never null).
COMP_FIELDS = ["name", "dir", "sector", "hq", "threat", "assess", "updates",
               "center", "partners", "site", "srcs", "products", "threatNote",
               # harvested from each maker's own site, each value carrying the URL and
               # the verbatim line it was read from - see pipeline/harvest/promote.py
               "leadership", "facilities", "sales",
               # 2026-09-01 schema addition. These sat in the table AND in the
               # serving_live view but not here, so they could never reach the
               # browser however well the pipeline filled them -- and the Profile
               # page invented founded / headcount / revenue in their place.
               "starting_year", "global_locations", "company_size",
               "strategic_positioning",
               # 2026-09-06. Origin country, one word. The Competitor filter reads
               # THIS and not the geo footprint, so "France" means from France.
               "country"]
COMP_OPT = frozenset(["starting_year", "global_locations", "company_size",
                      "strategic_positioning", "country"])
NEWS_FIELDS = ["id", "comp_id", "title", "description", "source",
               "published_date", "category", "is_trending", "url", "image",
               # 2026-09-06. The running story an article belongs to, and how it
               # relates to the one before it. Written by news_chain.py from spans
               # the extraction layer typed; null on an article that stands alone.
               "story_key", "continues_url", "duplicate_of_url"]
NEWS_OPT = frozenset(["description", "category", "is_trending",
                      "story_key", "continues_url", "duplicate_of_url"])
# Ownership. source_url is NOT optional here for the same reason it is NOT NULL in the
# table: the Profile graph draws a claim, and a claim on this dashboard shows its source.
STRUCT_FIELDS = ["comp_id", "entity_id", "entity_name", "relationship_type",
                 "ownership_pct", "description", "source_url", "source_note"]
STRUCT_OPT = frozenset(["entity_id", "ownership_pct", "description", "source_note"])
# Corpus mention volume. window_days travels WITH the counts, so the UI cannot label a
# 7-day figure as 24h: the number carries its own units.
METRIC_FIELDS = ["comp_id", "mentions_window", "mentions_previous",
                 "corpus_window", "corpus_previous",
                 "mentions_change_pct", "window_days", "window_end", "as_of"]
METRIC_OPT = frozenset(["mentions_change_pct"])
CARD_FIELDS = ["id", "dir", "rank", "title", "meta", "company", "lens",
               "sowhat", "sec", "url", "ago", "tags", "image"]
CARD_OPT = frozenset(["company", "lens", "sec", "url", "image"])
DETAIL_FIELDS = ["rank", "dir", "title", "facts", "what", "why", "lens",
                 "actions", "url", "suggest", "kind", "match", "pursue",
                 # the same picture the card carries; absent when the article had none
                 "image"]
DETAIL_OPT = frozenset(["lens", "url", "kind", "match", "pursue", "image"])
MATCHUP_FIELDS = ["cat", "anchor", "global", "dir", "country", "comp", "compBy",
                  "bf", "bfBy", "ks_thin", "reason", "edge", "specs", "advComp",
                  "advBf", "det", "verdictH", "verdict", "catKey", "srcs", "gen",
                  "revenue_filter", "news_image", "product_news"]
MATCHUP_OPT = frozenset(["srcs", "gen",  # edge stays, null is honest
                         "revenue_filter", "news_image"])
TENDER_FIELDS = ["id", "title", "issuer", "country", "cat", "value", "qty",
                 "deadline", "dl", "reqNote", "req", "matches", "lean",
                 "leanTxt", "status", "url", "urlKind", "srcs", "stage"]
TENDER_OPT = frozenset(["stage"])
PATENT_FIELDS = ["no", "title", "assignee", "status", "filed", "granted",
                 "country", "ipc", "abstract", "area", "threat", "relev",
                 "url", "p",  # granted stays, null is honest
                 # 2026-09-06. Which competitor this filing belongs to, resolved by
                 # the harvester against its own applicant allow-list. The frontend
                 # used to re-derive it by matching Latin word tokens, which cannot
                 # see a Korean or a German legal name.
                 "comp_id",
                 # 2026-09-06, THE HALF OF THAT MIGRATION NOBODY WIRED UP.
                 # _patent_grant_status.sql added published/grant_no/pub_kind/doc_id to
                 # serving.patent AND re-created serving_live.patent to expose them, and
                 # the harvester writes them -- but this list is the SELECT, so the four
                 # columns could not reach the browser whatever was in them. The card
                 # already reads r.published ("Published <date>" for a record whose
                 # application date is unknown) and it was reading a key the API never
                 # sent: dead code that looked live. A column nothing selects is a column
                 # nothing can ever show, so measuring it harder would not have helped.
                 "published", "grant_no", "pub_kind", "doc_id",
                 # 2026-09-06. English rendering of `title`, written by the translation
                 # step (extraction/signals/patent_titles.py). NULL means "not looked at
                 # yet" and the UI falls back to the source-language title -- which it
                 # keeps showing either way, as the subline.
                 "title_en"]
# OPTIONAL IN BOTH SENSES, and both matter here.
#   NULL  -- comp_id is null on the 26 curated reference rows; published/grant_no/
#            pub_kind/doc_id are null on every row harvested before the detail pass, and
#            title_en on every row the translation step has not reached. Omitting the
#            key is how the frontend tells "not measured" from a value.
#   ABSENT -- a database that has not run 2026-09-06_patent_comp_id.sql /
#            _patent_grant_status.sql / _patent_title_en.sql has not got the column at
#            all, and deploy.sh runs no migrations. _reconcile_optional drops those,
#            which is why adding a field here cannot 500 the whole dataset.
PATENT_OPT = frozenset(["comp_id", "published", "grant_no", "pub_kind", "doc_id",
                        "title_en"])
GEO_FIELDS = ["name", "c", "val", "since", "qty", "stage", "note", "src", "srcnote",
              "geo_news"]
GEOCOMP_FIELDS = ["id", "name", "dir", "hq", "isBf"]
INNOV_FIELDS = ["t", "mat", "gap", "driver", "horizon", "body", "impact",
                "whatsNew", "compNote", "action", "sources", "url"]
INNOV_OPT = frozenset(["url"])
PARTNER_FIELDS = ["id", "label", "kind", "rel", "sig", "ptype", "note", "date",
                  "country", "deal", "insight", "mean", "src", "srcnote", "cid",
                  "image"]
PARTNER_OPT = frozenset(["image"])
SRCREG_FIELDS = ["company", "label", "url", "kind"]


def _cols(fields):
    return ", ".join('"%s"' % f for f in fields)


ARRAY_FIELDS = frozenset([
    "partners", "products", "srcs", "updates", "advComp", "advBf", "specs",
    "ipc", "sec", "facts", "lens", "actions", "suggest", "matches", "req",
    "leadership", "facilities", "sales",
    "global_locations", "product_news", "geo_news",
])


def _emit(row, fields, optional=frozenset()):
    out = {}
    for f in fields:
        v = row[f]
        if v is None and f in optional:
            continue
        if v is None and f in ARRAY_FIELDS:
            v = []
        out[f] = v
    return out



# The stage timer lives with the pipeline. The API must still serve if it is not
# importable here, so this degrades to a context manager that does nothing.
try:
    _here = os.path.dirname(os.path.abspath(__file__))
    # two layouts: alongside the app in the image (/app/pipeline), and one level
    # up in the source tree (../pipeline). Trying only the second is how this
    # silently ran as a no-op in the container.
    for _cand in (os.path.join(_here, "pipeline"),
                  os.path.join(_here, "..", "pipeline")):
        if os.path.isfile(os.path.join(_cand, "stage_timer.py")):
            sys.path.insert(0, _cand)
            break
    from stage_timer import stage as _stage           # noqa: E402
except Exception:                                     # noqa: BLE001
    import contextlib

    class _Noop(object):
        def items(self, _n):
            return self

        def tokens(self, _n):
            return self

    @contextlib.contextmanager
    def _stage(*_a, **_k):
        yield _Noop()


@app.get("/healthz")
def healthz():
    try:
        conn = psycopg2.connect(DSN, connect_timeout=3)
        with conn.cursor() as cur:
            _q(cur, "SELECT count(*) FROM serving.ui_config")
            n_cfg = cur.fetchone()[0]
        conn.close()
        return {"ok": True, "db": True, "ui_config_keys": n_cfg,
                "schema": SCHEMA}
    except Exception as exc:  # pragma: no cover - db down
        return JSONResponse(status_code=503,
                            content={"ok": False, "db": False, "error": str(exc)})


@app.get("/api/dataset")
def dataset():
    # The last stage of the journey: how long the dashboard waits for its data.
    # Without this the metrics table can say how long the pipeline took to build
    # a card and nothing about how long a reader waits to see it.
    with _stage("frontend", note="GET /api/dataset") as _st:
        return _dataset(_st)


# AN OPTIONAL FIELD MUST SURVIVE ITS MIGRATION NOT HAVING RUN YET.
#
# deploy.sh does not apply migrations. On any environment. The only thing that
# does is sync_from_prod.sh, and it says so in its own comment. So the moment a
# commit adds a column to one of the lists above AND ships db/migrations/*.sql
# for it, the next deploy puts a backend that selects that column in front of a
# database that has not got it -- and because the competitors query is the FIRST
# one in _dataset, psycopg2's UndefinedColumn took down the entire dashboard, not
# the one field. That is what "Could not load the KSSL dataset - 500" was on
# staging on 2026-09-06, from `country`.
#
# OPT already means "omit this key when the value is NULL". It now also means
# "omit it when the column is not there yet", which is the same promise to the
# browser -- the field is absent -- made about a schema that is a step behind
# instead of a row that is empty.
#
# A NON-optional column that is missing still raises. That is not a pending
# migration, it is a deploy badly out of step with its database, and it should be
# loud.
_SERVED = [
    ("competitors", COMP_FIELDS, COMP_OPT),
    ("competitor_news", NEWS_FIELDS, NEWS_OPT),
    ("competitor_structure", STRUCT_FIELDS, STRUCT_OPT),
    ("competitor_metrics", METRIC_FIELDS, METRIC_OPT),
    ("signal_card", CARD_FIELDS, CARD_OPT),
    ("signal_detail", DETAIL_FIELDS, DETAIL_OPT),
    ("matchup", MATCHUP_FIELDS, MATCHUP_OPT),
    ("tender", TENDER_FIELDS, TENDER_OPT),
    ("innovation", INNOV_FIELDS, INNOV_OPT),
    ("partner", PARTNER_FIELDS, PARTNER_OPT),
    ("patent", PATENT_FIELDS, PATENT_OPT),
]
_reconciled = False


def _reconcile_optional(cur, schema=None):
    """Drop optional fields whose column does not exist in the served schema.

    One query, once per process. The lists are mutated in place so that _emit,
    which closes over the same objects, cannot disagree with the SELECT that
    fetched the row. Returns what it dropped, so a caller can log or assert.
    """
    schema = schema or SCHEMA
    cur.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = %s", (schema,))
    have = {}
    for r in cur.fetchall():
        # RealDictCursor here, plain tuples in the self-check -- accept both
        t, c = (r["table_name"], r["column_name"]) if isinstance(r, dict) else r
        have.setdefault(t, set()).add(c)
    dropped = {}
    for table, fields, optional in _SERVED:
        cols = have.get(table)
        if cols is None:
            # The relation itself is absent. Not this function's business: the
            # query against it will say so, and say which one.
            continue
        gone = [f for f in fields if f in optional and f not in cols]
        if gone:
            fields[:] = [f for f in fields if f not in gone]
            dropped[table] = gone
    return dropped


def _grade_cards(out):
    """Stamp severity and impact onto every signal card, in one place.

    THE OPERATOR ASKED FOR TWO THINGS and neither had anywhere to come from.
    A threat card had to be about a company that can actually hurt KSSL, and the cards
    had to be sequenced by how bad they are and how fresh. serving.signal_card has no
    severity column; the two inputs to one -- the competitor's rated threat level and
    the card's own impact on a KSSL line -- are both already on this response.

    DERIVED AT SERVE TIME rather than stored, deliberately. A stored severity is a third
    copy of a number computed from two tables that are rebuilt on different schedules,
    and it is stale for as long as the gap between those schedules. Derived here it
    cannot disagree with the rating it came from, and it needs no migration to work.

    THE BROWSER DOES NOT RECOMPUTE IT. `severityRank` is the sort position and it is
    computed once, here, from threat_gate.SEVERITY_RANK. lib/overview.js reads that
    integer and never derives one -- the failure this repo has already logged is a
    number computed in two places where the frontend silently overwrote the served one.

    NULL SEVERITY IS A STATE, NOT A ZERO. A card whose company is not a tracked
    competitor, or whose event carries no KSSL category, gets severity null, impact
    "not_assessed" and the WORST rank -- it sorts below every graded card and says so on
    the card, instead of being dropped or quietly scored low.
    """
    comps = out.get("competitors") or {}
    by_name = {}
    for c in comps.values():
        name = (c.get("name") or "").strip()
        if name:
            by_name.setdefault(name, c)
    try:
        gate = threat_gate.RosterGate(list(by_name))
    except threat_gate.EmptyRosterError as exc:
        # Loud, and closed. Nothing is graded rather than everything being graded from
        # an empty roster, which is the shape of the fail-open bug this replaced.
        print("severity: %s" % exc, file=sys.stderr, flush=True)
        gate = threat_gate.refusing_gate("roster-unavailable")
    for key in ("competitiveCards", "marketCards", "techCards"):
        for card in out.get(key) or []:
            name = gate.resolve(card.get("company"))
            comp = by_name.get(name) if name else None
            imp = threat_gate.impact_of(card, comp)
            sev = threat_gate.severity_of((comp or {}).get("threat"), imp)
            card["severity"] = sev                      # null == not assessed
            card["severityRank"] = threat_gate.severity_rank(sev)
            card["severityLabel"] = (sev or threat_gate.SEVERITY_UNASSESSED_LABEL)
            card["impact"] = imp.state
            card["impactLabel"] = imp.label
            card["impactBasis"] = imp.basis
            card["competitor"] = name                   # null == not a tracked rival
    return out


def _dataset(_st=None):
    # connect_timeout so a wedged database returns an error instead of hanging
    # the request until the client gives up
    conn = psycopg2.connect(DSN, connect_timeout=5)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Before the first query that names a column: reconcile the optional
        # fields against the schema this database actually has.
        global _reconciled
        if not _reconciled:
            gone = _reconcile_optional(cur)
            _reconciled = True
            for _t, _f in sorted(gone.items()):
                print("serving %s: %s not in %s yet, omitting"
                      % (_t, ", ".join(_f), SCHEMA), file=sys.stderr, flush=True)

        # Interface vocabulary + PATENTS aux pieces.
        _q(cur, "SELECT key, value FROM serving.ui_config")
        cfg = {r["key"]: r["value"] for r in cur.fetchall()}
        out = {k: v for k, v in cfg.items() if not k.startswith("PATENTS.")}

        # competitors (dict, key order = ord) + derived compOrder.
        _q(cur, "SELECT comp_id, %s FROM serving.competitors ORDER BY ord"
                    % _cols(COMP_FIELDS))
        comps = cur.fetchall()
        out["competitors"] = {r["comp_id"]: _emit(r, COMP_FIELDS, COMP_OPT)
                              for r in comps}
        out["compOrder"] = [r["comp_id"] for r in comps]

        # competitorNews (dict comp_id -> list, newest first). The table and its
        # serving_live view existed with no reader at all; until this query the
        # Profile / Products / Geo news panels had nowhere real to read from and
        # rendered a hard-coded template with the company name substituted in.
        _q(cur, "SELECT %s FROM serving.competitor_news "
                "ORDER BY comp_id, published_date DESC NULLS LAST, id"
                    % _cols(NEWS_FIELDS))
        news = {}
        for r in cur.fetchall():
            item = _emit(r, NEWS_FIELDS, NEWS_OPT)
            d = item.pop("published_date", None)
            # ISO date only: the UI formats it, and a timestamp implies a precision
            # the publisher's markup rarely states.
            item["date"] = d.date().isoformat() if d is not None else None
            news.setdefault(item.pop("comp_id"), []).append(item)
        out["competitorNews"] = news

        # competitorStructure (dict comp_id -> list). Ownership edges, the parent first:
        # on a company's own page its parent is the fact that orders the rest.
        _q(cur, "SELECT %s FROM serving.competitor_structure "
                "ORDER BY comp_id, relationship_type, entity_name"
                    % _cols(STRUCT_FIELDS))
        struct = {}
        for r in cur.fetchall():
            item = _emit(r, STRUCT_FIELDS, STRUCT_OPT)
            # NUMERIC comes back as Decimal, which json cannot serialise.
            if item.get("ownership_pct") is not None:
                item["ownership_pct"] = float(item["ownership_pct"])
            struct.setdefault(item.pop("comp_id"), []).append(item)
        out["competitorStructure"] = struct

        # competitorMetrics (dict comp_id -> one object). Counts over THIS corpus, which
        # is why the payload carries window_days rather than a name that implies a window.
        _q(cur, "SELECT %s FROM serving.competitor_metrics" % _cols(METRIC_FIELDS))
        metrics = {}
        for r in cur.fetchall():
            item = _emit(r, METRIC_FIELDS, METRIC_OPT)
            if item.get("mentions_change_pct") is not None:
                item["mentions_change_pct"] = float(item["mentions_change_pct"])
            item["as_of"] = item["as_of"].isoformat() if item["as_of"] else None
            # window_end is a date; the UI prints which days the count covers, because
            # they are not the last seven -- the crawl runs behind publication.
            item["window_end"] = (item["window_end"].isoformat()
                                  if item["window_end"] else None)
            metrics[item.pop("comp_id")] = item
        out["competitorMetrics"] = metrics

        # signal cards, three lanes.
        for lane, gname in (("competitive", "competitiveCards"),
                            ("market", "marketCards"),
                            ("tech", "techCards")):
            _q(cur, "SELECT %s FROM serving.signal_card WHERE lane = %%s "
                        "ORDER BY ord" % _cols(CARD_FIELDS), (lane,))
            out[gname] = [_emit(r, CARD_FIELDS, CARD_OPT) for r in cur.fetchall()]

        # SEVERITY AND IMPACT, derived here and served -- not stored, and not derived
        # again in the browser. See _grade_cards.
        _grade_cards(out)

        # details (dict keyed by card id).
        _q(cur, "SELECT id, %s FROM serving.signal_detail ORDER BY ord"
                    % _cols(DETAIL_FIELDS))
        out["details"] = {r["id"]: _emit(r, DETAIL_FIELDS, DETAIL_OPT)
                          for r in cur.fetchall()}

        # matchups (dict keyed by numeric-string id, id order).
        _q(cur, "SELECT matchup_id, %s FROM serving.matchup ORDER BY matchup_id"
                    % _cols(MATCHUP_FIELDS))
        out["matchups"] = {str(r["matchup_id"]): _emit(r, MATCHUP_FIELDS, MATCHUP_OPT)
                           for r in cur.fetchall()}

        # tenders (list).
        _q(cur, "SELECT %s FROM serving.tender ORDER BY ord" % _cols(TENDER_FIELDS))
        out["tenders"] = [_emit(r, TENDER_FIELDS, TENDER_OPT) for r in cur.fetchall()]

        # PATENTS: flat rows -> byArea (ord order) and byAssignee (assignee_ord).
        _q(cur, "SELECT %s FROM serving.patent ORDER BY ord" % _cols(PATENT_FIELDS))
        by_area = {}
        for r in cur.fetchall():
            by_area.setdefault(r["area"], []).append(
                _emit(r, PATENT_FIELDS, PATENT_OPT))
        _q(cur, "SELECT %s FROM serving.patent ORDER BY assignee_ord"
                    % _cols(PATENT_FIELDS))
        by_assignee = {}
        for r in cur.fetchall():
            by_assignee.setdefault(r["assignee"], []).append(
                _emit(r, PATENT_FIELDS, PATENT_OPT))
        # _meta.total/lastSync are computed from the served rows -- the config copy
        # described the reference sync and kept asserting 26 filings on an empty store.
        _q(cur, "SELECT count(*), max(updated_at) FROM serving.patent")
        n_pat, last_pat = list(cur.fetchone().values())
        meta = {k: v for k, v in (cfg.get("PATENTS._meta") or {}).items()
                if k not in ("total", "lastSync", "status")}
        meta["total"] = n_pat
        meta["status"] = "ok"
        if last_pat is not None:
            meta["lastSync"] = last_pat.strftime("%Y-%m-%d")
        out["PATENTS"] = {
            "techAreas": cfg.get("PATENTS.techAreas", []),
            "byArea": by_area,
            "byAssignee": by_assignee,
            "_meta": meta,
        }

        # geoData (dict comp -> dict country -> list).
        _q(cur, "SELECT comp_id, country, %s FROM serving.geo_presence "
                    "ORDER BY comp_ord, country_ord, ord" % _cols(GEO_FIELDS))
        geo = {}
        for r in cur.fetchall():
            geo.setdefault(r["comp_id"], {}).setdefault(r["country"], []) \
               .append(_emit(r, GEO_FIELDS))
        out["geoData"] = geo

        # geoComps (list).
        _q(cur, "SELECT %s FROM serving.geo_comp ORDER BY ord" % _cols(GEOCOMP_FIELDS))
        out["geoComps"] = [_emit(r, GEOCOMP_FIELDS) for r in cur.fetchall()]

        # innovations (dict area -> list).
        _q(cur, "SELECT area, %s FROM serving.innovation ORDER BY area_ord, ord"
                    % _cols(INNOV_FIELDS))
        innov = {}
        for r in cur.fetchall():
            innov.setdefault(r["area"], []).append(_emit(r, INNOV_FIELDS, INNOV_OPT))
        out["innovations"] = innov

        # KSSL_PARTNERS (list).
        _q(cur, "SELECT %s FROM serving.partner ORDER BY ord" % _cols(PARTNER_FIELDS))
        out["KSSL_PARTNERS"] = [_emit(r, PARTNER_FIELDS, PARTNER_OPT)
                                for r in cur.fetchall()]

        # sourceRegistry (list).
        _q(cur, "SELECT %s FROM serving.source_registry ORDER BY ord"
                    % _cols(SRCREG_FIELDS))
        out["sourceRegistry"] = [_emit(r, SRCREG_FIELDS) for r in cur.fetchall()]

        # companySources (dict company -> list of urls).
        _q(cur, "SELECT company, url FROM serving.company_source "
                    "ORDER BY comp_ord, ord")
        srcs = {}
        for r in cur.fetchall():
            srcs.setdefault(r["company"], []).append(r["url"])
        out["companySources"] = srcs

        cur.close()
        if _st is not None:
            # how much the dashboard actually got, so an empty
            # dataset is visible in the metrics, not just on screen
            _st.items(len(out.get('compOrder') or []))
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------- article bench
# "Give it an article and watch every stage." The work happens at the data
# centre; this side only queues it and reports. See bench/worker.py for why the
# direction is data-centre-polls-VPS rather than VPS-calls-data-centre.

_BENCH_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "bench", "dashboard.html")


@app.get("/api/bench")
def bench_page():
    from fastapi.responses import HTMLResponse, JSONResponse as _J
    try:
        with open(_BENCH_HTML, encoding="utf-8") as fh:
            return HTMLResponse(fh.read())
    except FileNotFoundError:
        return _J(status_code=500,
                  content={"error": "bench/dashboard.html is not in the image"})


@app.post("/api/bench/submit")
async def bench_submit(request: Request):
    """Queue one article. Returns immediately -- the worker does the work."""
    import uuid
    body = await request.json()
    url = (body.get("url") or "").strip() or None
    text = (body.get("text") or "").strip() or None
    title = (body.get("title") or "").strip() or None
    if not url and not text:
        return JSONResponse(status_code=400,
                            content={"error": "give it a url or some text"})
    if url and not url.startswith(("http://", "https://")):
        return JSONResponse(status_code=400,
                            content={"error": "url must start with http:// or https://"})

    run_id = uuid.uuid4().hex[:12]
    conn = psycopg2.connect(DSN, connect_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO metrics.adhoc_job "
                "  (run_id, url, raw_text, title, layer_b) "
                "VALUES (%s,%s,%s,%s,%s)",
                (run_id, url, text, title, bool(body.get("layer_b"))))
        conn.commit()
    finally:
        conn.close()
    return {"run_id": run_id, "status": "queued"}


@app.get("/api/bench/runs")
def bench_runs(limit: int = 15):
    conn = psycopg2.connect(DSN, connect_timeout=5)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM metrics.adhoc_summary "
                    "ORDER BY submitted DESC LIMIT %s", (min(int(limit), 60),))
        return {"runs": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()


@app.get("/api/bench/run/{run_id}")
def bench_run(run_id: str):
    conn = psycopg2.connect(DSN, connect_timeout=5)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM metrics.adhoc_summary WHERE run_id=%s", (run_id,))
        job = cur.fetchone()
        if not job:
            return JSONResponse(status_code=404, content={"error": "no such run"})
        # The stage timings are read from metrics.stage_run, the same table the
        # production pipeline writes -- the dashboard cannot show a number the
        # pipeline did not record.
        cur.execute("SELECT stage, ms, n_items, n_tokens, ok, note, host, "
                    "       started_at, ended_at "
                    "  FROM metrics.stage_run WHERE run_id=%s ORDER BY id",
                    (run_id,))
        return {"job": dict(job), "runs": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()


@app.get("/api/production")
def production_doc():
    """The production write-up, served rather than emailed around.

    docs/build_production_doc.py regenerates it from docs/metrics/*.json and the
    live metrics.stage_run, so what is on screen is what the database holds. If
    the file is missing, say so -- do not serve a stale copy from somewhere else
    and let it be read as current.
    """
    from fastapi.responses import HTMLResponse, JSONResponse as _J
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "PRODUCTION.html")
    if not os.path.exists(p):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PRODUCTION.html")
    try:
        with open(p, encoding="utf-8") as fh:
            return HTMLResponse(fh.read())
    except FileNotFoundError:
        return _J(status_code=404,
                  content={"error": "PRODUCTION.html has not been generated yet",
                           "how": "python docs/build_production_doc.py"})


# ----------------------------------------------------------------------------------------
# GET /api/lineage/doc/{document_id}  -- read-only provenance trace (POC)
#
# Reconstructs ONLY lineage the pipeline actually records, one stage at a time, and labels
# every stage recorded | reconstructed | provenance_unavailable. It invents nothing: a
# stage with no stored row says so. The known gaps (prop->card not stored; serving rows
# carry no document_id; crawler discovery off-box; reference rows have no lineage) are
# surfaced IN the response, not hidden.
#
# All stages live in the one `kssl` database the backend already connects to, so this uses
# the same DSN and psycopg2 as /api/dataset -- not a parallel system. Every statement is a
# SELECT and the connection is opened read-only, so the endpoint cannot write.
# ----------------------------------------------------------------------------------------

# Deterministic code-path facts (no stored row asserts them; they follow from origin + code).
_LANE_TO_UI = {
    "competitive": "Overview signal feed + competitive pages (src/pages/competitive/*)",
    "market":      "Market Overview (src/pages/market/MarketOverview.jsx)",
    "tech":        "Technology / Innovation (src/pages/technology/Innovation.jsx)",
}

# The four gaps the investigation confirmed. Returned on every response so a consumer of
# this endpoint sees the boundaries of what is knowable, not just what is known.
_KNOWN_GAPS = [
    "proposition -> signal_card is NOT stored; the link can only be reconstructed by "
    "matching evidence quotes, and fails when the card text was translated from a "
    "source-language proposition.",
    "serving/enrichment rows (competitors, partner, matchup, geo_*, innovation, patent, "
    "news) carry no document_id or run_id; only a src/url STRING links them to a source, "
    "and rows are often aggregated from several documents.",
    "crawler discovery history (how a URL was found, the crawl path before fetch) is "
    "off-box; public.documents keeps only url/source_id/published_at/fetched_at.",
    "reference-origin serving rows are a curated archive and have no document lineage.",
]


def _lstep(stage, status, component, **kw):
    """One lineage step. status is recorded | reconstructed | provenance_unavailable."""
    out = {"stage": stage, "status": status, "component": component}
    out.update({k: v for k, v in kw.items() if v is not None})
    return out


def _has_column(cur, schema, table, col):
    """True if the column exists -- lineage columns are optional until their migration runs."""
    cur.execute("SELECT 1 AS t FROM information_schema.columns WHERE table_schema=%s "
                "AND table_name=%s AND column_name=%s", (schema, table, col))
    return bool(cur.fetchone())


def _finish(did, stages):
    """The 200 body. Extracted so an early recorded-enrichment return builds the same shape."""
    return 200, {
        "document_id": did,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "read_only": True,
        "stage_order": ["raw_corpus", "gate", "extracted_document", "propositions",
                        "extraction_run", "signal_card", "signal_detail",
                        "prop_to_card_link", "api_destination", "ui_destination",
                        "enrichment"],
        "stages": stages,
        "known_gaps": _KNOWN_GAPS,
    }


def build_lineage(cur, document_id):
    """-> (http_status, body). Pure over a DB cursor so it is testable with a fake one.

    cur must yield dict rows (RealDictCursor in production, a stub in tests). Only SELECTs
    are issued; nothing here writes.
    """
    did = document_id

    def one(sql, params=None):
        cur.execute(sql, params)
        return cur.fetchone()

    def many(sql, params=None):
        cur.execute(sql, params)
        return list(cur.fetchall())

    def rec_of(row):
        return row.get("rec") if row else None

    stages = []
    found_any = False

    # 1. RAW CORPUS -----------------------------------------------------------------------
    raw = rec_of(one("SELECT to_jsonb(d) AS rec FROM public.documents d "
                     "WHERE d.document_id = %s", (did,)))
    doc_url = raw.get("url") if raw else None
    if raw:
        found_any = True
        stages.append(_lstep(
            "raw_corpus", "recorded",
            "public.documents (crawler sync: select_worklist.py / sync_documents.py)",
            identifier=did, timestamp=raw.get("fetched_at"),
            reason="present in the corpus; published_at is the crawler's proven publication date",
            record=raw, downstream_ref="extract_queue.document_id=%s" % did,
            note="Crawler discovery history is OFF-BOX; only url/source_id/published_at/"
                 "fetched_at survive here."))
    else:
        stages.append(_lstep("raw_corpus", "provenance_unavailable",
                             "public.documents", identifier=did,
                             note="No public.documents row for this id on this database."))

    # 2. GATE -----------------------------------------------------------------------------
    q_tbl = one("SELECT to_regclass('public.extract_queue') AS t")
    if q_tbl and q_tbl.get("t"):
        q = rec_of(one("SELECT to_jsonb(q) AS rec FROM public.extract_queue q "
                       "WHERE q.document_id = %s", (did,)))
        if q:
            stages.append(_lstep(
                "gate", "recorded", "extraction/engine/route.py (presignal gate)",
                identifier=did, timestamp=q.get("crawl_ts"),
                reason="class=%s state=%s reason=%s attempts=%s" % (
                    q.get("class"), q.get("state"),
                    q.get("reason") if q.get("reason") is not None else "(none: passed)",
                    q.get("attempts")),
                record=q, downstream_ref="extracted.document.document_id=%s" % did))
        else:
            stages.append(_lstep("gate", "provenance_unavailable",
                                 "extraction/engine/route.py", identifier=did,
                                 note="No extract_queue row: document never entered the queue."))
    else:
        stages.append(_lstep("gate", "provenance_unavailable",
                             "extraction/engine/route.py", identifier=did,
                             note="extract_queue is created by route.py and is absent on "
                                  "this database (e.g. a serving-only replica)."))

    # 3. EXTRACTED DOCUMENT ---------------------------------------------------------------
    xdoc = rec_of(one("SELECT to_jsonb(d) AS rec FROM extracted.document d "
                      "WHERE d.document_id = %s", (did,)))
    if xdoc:
        found_any = True
        stages.append(_lstep(
            "extracted_document", "recorded", "extraction/engine/store_pg.py",
            identifier=did, timestamp=xdoc.get("first_seen"),
            reason="passed the gate and was extracted (Layer A)",
            record=xdoc, downstream_ref="extracted.proposition.document_id=%s" % did))
    else:
        stages.append(_lstep("extracted_document", "provenance_unavailable",
                             "extraction/engine/store_pg.py", identifier=did,
                             note="No extracted.document row: not yet extracted, or purged."))

    # 4. PROPOSITIONS + SPANS + 5. RUN LINEAGE --------------------------------------------
    props = [rec_of({"rec": r["rec"]}) for r in many(
        "SELECT to_jsonb(p) AS rec FROM extracted.proposition p "
        "WHERE p.document_id = %s ORDER BY p.i", (did,))]
    span_row = one("SELECT count(*) AS n FROM extracted.span WHERE document_id = %s", (did,))
    n_spans = (span_row or {}).get("n")

    run_ids = sorted({p.get("run_id") for p in props if p and p.get("run_id")})
    if props:
        found_any = True
        stages.append(_lstep(
            "propositions", "recorded",
            "extraction/engine/comprehend.py -> extracted.proposition",
            identifier="%d proposition(s), %s span(s)" % (
                len(props), n_spans if n_spans is not None else "?"),
            reason="claims extracted with verbatim evidence quotes and byte offsets",
            evidence=[{"i": p.get("i"),
                       "spo": "%s / %s / %s" % (p.get("subject"), p.get("predicate"),
                                                p.get("object")),
                       "modality": p.get("modality"), "polarity": p.get("polarity"),
                       "ev_quote": p.get("ev_quote"),
                       "ev_span": [p.get("ev_start"), p.get("ev_end")]}
                      for p in props],
            downstream_ref="signal_card.id=pl_%s (link NOT stored; see gaps)" % did))
    else:
        stages.append(_lstep("propositions", "provenance_unavailable",
                             "extraction/engine/comprehend.py", identifier=did,
                             note="No propositions recorded for this document."))

    for rid in run_ids:
        run = rec_of(one("SELECT to_jsonb(r) AS rec FROM extracted.extraction_run r "
                         "WHERE r.run_id = %s", (rid,)))
        if run:
            stages.append(_lstep(
                "extraction_run", "recorded",
                "extraction/engine/lineage.py -> extracted.extraction_run",
                identifier=rid, timestamp=run.get("started_at"),
                reason="run version/model/config that produced the propositions above",
                model={"model": run.get("model"),
                       "pipeline_version": run.get("pipeline_version"),
                       "lexicon_version": run.get("lexicon_version"),
                       "config": run.get("config")},
                record=run))
    if props and not run_ids:
        stages.append(_lstep("extraction_run", "provenance_unavailable",
                             "extracted.extraction_run",
                             note="Propositions carry no run_id (pre-lineage extraction)."))

    # 6. SIGNAL CARD + 7. SIGNAL DETAIL ---------------------------------------------------
    card_id = "pl_" + did
    card = rec_of(one("SELECT to_jsonb(c) AS rec FROM serving.signal_card c "
                      "WHERE c.id = %s", (card_id,)))
    detail = rec_of(one("SELECT to_jsonb(d) AS rec FROM serving.signal_detail d "
                        "WHERE d.id = %s", (card_id,)))
    lane = card.get("lane") if card else None
    if card:
        found_any = True
        origin = card.get("origin")
        stages.append(_lstep(
            "signal_card", "recorded",
            "extraction/signals/serving_fill.py -> serving.signal_card",
            identifier=card_id, timestamp=card.get("updated_at"),
            reason="card written for this document (id convention pl_<document_id>); "
                   "origin=%s" % origin,
            record=card, downstream_ref="/api/dataset signal_card[%s]" % (lane or "?"),
            note=("reference-origin row: no document lineage" if origin == "reference"
                  else None)))
    else:
        stages.append(_lstep("signal_card", "provenance_unavailable",
                             "serving.signal_card", identifier=card_id,
                             note="No signal_card for pl_%s: the document produced no card "
                                  "(gated out at the card stage, undated, off-topic, or "
                                  "stale). NOTE: card-stage rejection reasons are printed to "
                                  "stdout only and are not stored." % did))
    if detail:
        stages.append(_lstep(
            "signal_detail", "recorded",
            "extraction/signals/serving_fill.py -> serving.signal_detail",
            identifier=card_id, timestamp=detail.get("updated_at"),
            reason="detail written for the card; translated=%s (translation prompt version)"
                   % detail.get("translated"),
            record=detail, downstream_ref="/api/dataset signal_detail[%s]" % card_id))

    # prop -> card link. RECORDED when serving.signal_card.source_prop_ids is populated
    # (2026-09-07 lineage columns); otherwise the old quote-overlap RECONSTRUCTION, which
    # is honest about being a guess and empty for translated cards.
    stored_props = (card or {}).get("source_prop_ids")
    if card is not None and stored_props is not None:
        stages.append(_lstep(
            "prop_to_card_link", "recorded",
            "serving.signal_card.source_prop_ids (written by serving_fill.py)",
            identifier=card_id,
            source_prop_ids=stored_props,
            source_run_id=(card or {}).get("source_run_id"),
            source_doc_ids=(card or {}).get("source_doc_ids"),
            note="Authoritative: these are the proposition indices fed to the card, "
                 "recorded at write time -- not a quote-match guess."))
    elif props and (card or detail):
        hay = " ".join(str(v) for v in [
            card.get("title") if card else "", card.get("lens") if card else "",
            card.get("sowhat") if card else "",
            (detail or {}).get("what"), (detail or {}).get("why"),
            json.dumps((detail or {}).get("facts")) if (detail or {}).get("facts") else "",
        ]).lower()
        matched = [p.get("i") for p in props
                   if p.get("ev_quote") and len(p["ev_quote"]) >= 12
                   and p["ev_quote"][:24].lower() in hay]
        stages.append(_lstep(
            "prop_to_card_link", "reconstructed",
            "quote-overlap heuristic (NOT a stored link)",
            identifier=card_id, method="ev_quote substring match against card/detail text",
            matched_proposition_indices=matched,
            note=("No overlap found: the card text is translated from source-language "
                  "propositions, so quotes do not match literally. The link is genuinely "
                  "not recoverable from stored data. (Recorded provenance is available "
                  "once the row is rewritten under the 2026-09-07 lineage columns.)"
                  if not matched else
                  "Overlap is a heuristic guess, not a recorded fact.")))

    # 8. API DESTINATION + 9. UI DESTINATION (deterministic code paths) -------------------
    if card:
        stages.append(_lstep(
            "api_destination", "reconstructed", "backend/app.py (/api/dataset)",
            identifier="signal_card[%s] + signal_detail[%s]" % (lane or "?", card_id),
            method="deterministic: origin='pipeline' rows flow through serving_live into "
                   "/api/dataset; no stored row records the serve event",
            note=None if card.get("origin") == "pipeline" else
                 "origin!=pipeline: serving_live filters this row OUT; it is NOT served."))
        stages.append(_lstep(
            "ui_destination", "reconstructed", "frontend/src/pages",
            identifier=_LANE_TO_UI.get(lane, "(unknown lane -> no mapped page)"),
            method="lane->page mapping lives in frontend code, not in data"))

    # ENRICHMENT. RECORDED when serving.partner.source_doc_ids lists this document
    # (2026-09-07 lineage columns); otherwise fall back to the URL-string reconstruction.
    partner_lineage = rec_of(one(
        "SELECT to_jsonb(p) AS rec FROM serving.partner p "
        "WHERE p.source_doc_ids IS NOT NULL AND %s = ANY(p.source_doc_ids)", (did,))) \
        if _has_column(cur, "serving", "partner", "source_doc_ids") else None
    if partner_lineage:
        stages.append(_lstep(
            "enrichment", "recorded",
            "serving.partner.source_doc_ids (written by enrich_serving.py)",
            identifier=did, record=partner_lineage,
            downstream_ref="/api/dataset partner[]",
            note="Authoritative: this document is listed in this partner row's "
                 "source_doc_ids (multi-document ties keep every contributing id)."))
        return _finish(did, stages)

    # URL-string reconstruction (no recorded link for this document's enrichment).
    enrich_hits = []
    if doc_url:
        for tbl, col in (("serving.competitor_news", "url"), ("serving.partner", "src"),
                         ("serving.partner", "srcnote"), ("serving.innovation", "url")):
            reg = one("SELECT to_regclass(%s) AS t", (tbl,))
            if not (reg and reg.get("t")):
                continue
            hit = one("SELECT count(*) AS n FROM %s WHERE %s = %%s" % (tbl, col), (doc_url,))
            if hit and hit.get("n"):
                enrich_hits.append({"table": tbl, "column": col, "rows": hit["n"]})
    stages.append(_lstep(
        "enrichment", "reconstructed" if enrich_hits else "provenance_unavailable",
        "extraction/signals/enrich_serving.py + fill_competitor_news.py",
        identifier=did,
        matched_by_url=enrich_hits or None,
        note="Enrichment rows carry no document_id/run_id. "
             + ("This document's URL was found in the rows above by STRING match only."
                if enrich_hits else
                "This document's URL appears in no enrichment row; even the URL-string "
                "reconstruction finds nothing. The link is not recoverable.")))

    if not found_any:
        return 404, {"error": "no lineage recorded for this document_id",
                     "document_id": did,
                     "checked": ["public.documents", "extracted.document",
                                 "extracted.proposition", "serving.signal_card"]}
    return _finish(did, stages)


@app.get("/api/lineage/doc/{document_id}")
def lineage_doc(document_id: str):
    """Read-only provenance trace for one document. Writes nothing (RO connection)."""
    try:
        conn = psycopg2.connect(DSN, connect_timeout=5)
    except Exception as exc:  # pragma: no cover - db down
        return JSONResponse(status_code=503, content={"error": "db unavailable",
                                                      "detail": str(exc)})
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        code, body = build_lineage(cur, document_id)
        return JSONResponse(status_code=code, content=body)
    finally:
        conn.close()


# ============================================================================================
# OPERATOR DASHBOARD -- read-only aggregations for the Backend Intelligence dashboard.
#
# Small endpoints over data the pipeline already records: public.extract_queue (gate),
# metrics.stage_run (timings), provenance.event (lifecycle), and the serving.* tables. The
# frontend never touches the database directly -- it calls these. Every one opens a
# READ-ONLY connection and guards each source table's existence, so an environment missing
# a table (a replica, or before a migration) degrades to "unavailable", never a 500.
# /api/lineage/doc/{id} (above) is the source of truth for the Document Lineage view.
# ============================================================================================

def _ops_conn():
    conn = psycopg2.connect(DSN, connect_timeout=5)
    conn.set_session(readonly=True, autocommit=True)      # cannot write, by construction
    return conn


def _regclass(cur, qualified):
    cur.execute("SELECT to_regclass(%s) IS NOT NULL AS t", (qualified,))
    r = cur.fetchone()
    return bool(r and (r["t"] if isinstance(r, dict) else r[0]))


# The real pipeline, traced from the repository (files/functions/tables all exist today).
# It is GROUNDED at request time with live table row-counts and event counts, so the map
# is structure and the numbers beside it are real. Not invented architecture.
_PIPELINE = [
    {"id": "ingestion", "title": "Ingestion / crawl sync", "role": "feeder",
     "files": ["extraction/select_worklist.py", "extraction/sync_documents.py"],
     "functions": ["select_worklist", "sync_documents"],
     "inputs": ["(data-centre corpus, off-box)"], "outputs": ["public.documents"],
     "model": None, "events": []},
    {"id": "gate", "title": "Presignal gate + queue", "role": "feeder",
     "files": ["extraction/engine/route.py", "extraction/engine/presignal.py"],
     "functions": ["enqueue", "dispatchable", "klass", "presignal.score"],
     "inputs": ["public.documents"], "outputs": ["public.extract_queue"],
     "model": None, "events": ["gated"]},
    {"id": "extraction", "title": "Extraction (Layer A)", "role": "worker",
     "files": ["extraction/engine/run_node.py", "extraction/engine/comprehend.py",
               "extraction/engine/store_pg.py", "extraction/engine/lineage.py"],
     "functions": ["run_node", "comprehend", "store_pg.save_and_commit"],
     "inputs": ["public.extract_queue", "public.documents"],
     "outputs": ["extracted.extraction_run", "extracted.span", "extracted.proposition",
                 "extracted.prop_arg", "extracted.span_value"],
     "model": "extraction LLM + GLiNER (per extraction_run.model)", "events": ["extracted"]},
    {"id": "signals", "title": "Signals / cards", "role": "signals",
     "files": ["extraction/signals/serving_fill.py", "extraction/signals/glance.py",
               "extraction/signals/translate.py"],
     "functions": ["fill", "glance_rows", "card_lineage"],
     "inputs": ["extracted.proposition", "extracted.span", "extracted.document"],
     "outputs": ["serving.signal_card", "serving.signal_detail"],
     "model": "14B serving model (farm)",
     "events": ["card_written", "record_rejected", "error"]},
    {"id": "enrich", "title": "Enrichment", "role": "enrich",
     "files": ["extraction/signals/enrich_serving.py", "extraction/signals/mark_shared.py",
               "extraction/signals/fill_competitor_news.py",
               "extraction/signals/backfill_tie_status.py"],
     "functions": ["step_companies", "step_partnerships", "tie_doc_ids"],
     "inputs": ["extracted.proposition", "serving.signal_card"],
     "outputs": ["serving.competitors", "serving.partner", "serving.matchup",
                 "serving.competitor_news", "serving.geo_presence", "serving.innovation"],
     "model": "14B serving model (farm)", "events": ["enriched"]},
    {"id": "serving", "title": "Serving views", "role": "db",
     "files": ["db/03_serving_live.sql"], "functions": ["serving_live.* views"],
     "inputs": ["serving.*"], "outputs": ["serving_live.* (origin='pipeline')"],
     "model": None, "events": []},
    {"id": "api", "title": "API", "role": "backend",
     "files": ["backend/app.py"], "functions": ["dataset", "lineage_doc", "ops_*"],
     "inputs": ["serving_live.*", "provenance.event"], "outputs": ["/api/dataset", "/api/lineage/*"],
     "model": None, "events": ["served (reconstructed; not yet an event)"]},
    {"id": "ui", "title": "Frontend", "role": "frontend",
     "files": ["frontend/src/pages/*", "frontend/public/ops/index.html"],
     "functions": ["pages + services", "operator dashboard"],
     "inputs": ["/api/dataset", "/api/ops/*", "/api/lineage/*"], "outputs": ["rendered UI"],
     "model": None, "events": []},
]


@app.get("/api/ops/overview")
def ops_overview():
    """System Overview: queue state, recent run timings, error/retry and event activity."""
    conn = _ops_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "read_only": True}

        if _regclass(cur, "public.extract_queue"):
            cur.execute("SELECT state, count(*) AS n FROM public.extract_queue "
                        "GROUP BY state ORDER BY n DESC")
            out["queue"] = [dict(r) for r in cur.fetchall()]
        else:
            out["queue"] = None

        if _regclass(cur, "metrics.stage_run"):
            cur.execute("SELECT stage, count(*) AS runs, round(avg(ms))::int AS avg_ms, "
                        "max(ms) AS max_ms, sum((NOT ok)::int) AS failures, "
                        "max(ended_at)::text AS last_at FROM metrics.stage_run "
                        "WHERE ended_at > now() - interval '24 hours' "
                        "GROUP BY stage ORDER BY last_at DESC NULLS LAST")
            out["stages_24h"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT run_id, stage, doc_id, ms, ok, ended_at::text AS ended_at "
                        "FROM metrics.stage_run ORDER BY ended_at DESC NULLS LAST LIMIT 15")
            out["recent_runs"] = [dict(r) for r in cur.fetchall()]
        else:
            out["stages_24h"] = None
            out["recent_runs"] = None

        if _regclass(cur, "provenance.event"):
            cur.execute("SELECT action, count(*) AS n FROM provenance.event "
                        "WHERE ts > now() - interval '24 hours' GROUP BY action ORDER BY n DESC")
            out["events_24h"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT count(*) AS n, max(ts)::text AS last_at FROM provenance.event")
            r = cur.fetchone()
            out["events_total"] = r["n"]
            out["events_last_at"] = r["last_at"]
            cur.execute("SELECT count(*) AS n FROM provenance.event "
                        "WHERE action IN ('error','retry') AND ts > now() - interval '24 hours'")
            out["events_errors_24h"] = cur.fetchone()["n"]
            out["events_available"] = True
        else:
            out["events_24h"] = None
            out["events_total"] = None
            out["events_available"] = False
            out["events_note"] = ("provenance.event does not exist on this database yet "
                                  "(migration 2026-09-07_provenance_events.sql not applied).")
        return JSONResponse(out)
    finally:
        conn.close()


@app.get("/api/ops/events")
def ops_events(limit: int = 50, action: str = None, document_id: str = None,
               since_id: int = None):
    """Live Event Stream: recent provenance.event rows, newest first. `since_id` returns
    only events after a prior max, for cheap polling."""
    limit = max(1, min(int(limit), 500))
    conn = _ops_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if not _regclass(cur, "provenance.event"):
            return JSONResponse({"available": False, "events": [],
                                 "note": "provenance.event does not exist on this database "
                                         "yet (migration not applied). It fills once the "
                                         "instrumented pipeline runs; there is no backfill."})
        where, params = [], []
        if action:
            where.append("action = %s"); params.append(action)
        if document_id:
            where.append("document_id = %s"); params.append(document_id)
        if since_id:
            where.append("event_id > %s"); params.append(int(since_id))
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        cur.execute("SELECT event_id, ts::text AS ts, stage, component, document_id, run_id, "
                    "ref_table, ref_id, action, reason, evidence FROM provenance.event"
                    + clause + " ORDER BY event_id DESC LIMIT %s", params + [limit])
        rows = [dict(r) for r in cur.fetchall()]
        return JSONResponse({"available": True, "events": rows,
                             "max_event_id": rows[0]["event_id"] if rows else since_id})
    finally:
        conn.close()


@app.get("/api/ops/pipeline")
def ops_pipeline():
    """Pipeline Explorer: the real stage map, grounded with live table/event counts."""
    conn = _ops_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        has_events = _regclass(cur, "provenance.event")
        stages = []
        for st in _PIPELINE:
            live = {}
            for tbl in st["outputs"]:
                if "." in tbl and not tbl.endswith("*)") and _regclass(cur, tbl.split(" ")[0]):
                    name = tbl.split(" ")[0]
                    try:
                        cur.execute("SELECT count(*) AS n FROM " + name)  # names from our own map
                        live[name] = cur.fetchone()["n"]
                    except Exception:                       # noqa: BLE001
                        pass
            ev = {}
            if has_events and st["events"]:
                acts = [e.split(" ")[0] for e in st["events"]]
                cur.execute("SELECT action, count(*) AS n FROM provenance.event "
                            "WHERE action = ANY(%s) GROUP BY action", (acts,))
                ev = {r["action"]: r["n"] for r in cur.fetchall()}
            stages.append(dict(st, live_output_counts=live, live_event_counts=ev))
        return JSONResponse({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "events_available": has_events, "stages": stages})
    finally:
        conn.close()


# ============================================================================================
# RUN TIMELINE -- what one run_id did, over time. READ-ONLY.
#
# IMPORTANT SCOPE, established by investigation (do not misread it): a run_id is a
# COMPONENT/PROCESS scope, NOT one end-to-end pipeline run. stage_timer.RUN_ID is a
# per-process uuid, so a container's while-loop keeps one run_id across many passes, and
# most llm run_ids are a single call. Extraction uses a SEPARATE namespace
# (extracted.extraction_run.run_id = 'run-YYYYMMDD-...'), which provenance 'extracted'
# events carry. So a run_id groups one component's work, and this view says so. A single
# document's journey ACROSS components is the Document Lineage view, not this one.
#
# Two recorded sources, joined on run_id: metrics.stage_run (timings) and provenance.event
# (lifecycle, after #47). Roll-ups are marked aggregated; a missing provenance.event is
# marked unavailable. No start/end is ever manufactured.
# ============================================================================================

def _run_status(open_rows, last_at):
    """in_progress if any stage_run row has no ended_at; else completed. Never guessed
    beyond what is recorded."""
    if open_rows and open_rows > 0:
        return "in_progress"
    return "completed"


@app.get("/api/ops/runs")
def ops_runs(limit: int = 40):
    """List recent runs (component/process scope) from stage_run and provenance.event."""
    limit = max(1, min(int(limit), 200))
    conn = _ops_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        runs = {}
        has_sr = _regclass(cur, "metrics.stage_run")
        has_ev = _regclass(cur, "provenance.event")
        if has_sr:
            cur.execute(
                "SELECT run_id, min(started_at)::text AS first_at, "
                "max(coalesce(ended_at, started_at))::text AS last_at, count(*) AS stage_rows, "
                "count(*) FILTER (WHERE ok IS FALSE) AS failures, "
                "count(*) FILTER (WHERE ended_at IS NULL) AS open_rows, "
                "count(DISTINCT doc_id) AS docs, string_agg(DISTINCT stage, ',') AS stages, "
                "coalesce(sum(n_tokens),0)::bigint AS tokens "
                "FROM metrics.stage_run GROUP BY run_id "
                "ORDER BY max(coalesce(ended_at, started_at)) DESC NULLS LAST LIMIT %s", (limit,))
            for r in cur.fetchall():
                d = dict(r)
                runs[d["run_id"]] = {
                    "run_id": d["run_id"], "sources": ["stage_run"],
                    "first_at": d["first_at"], "last_at": d["last_at"],
                    "stage_rows": d["stage_rows"], "failures": d["failures"],
                    "docs": d["docs"], "stages": (d["stages"] or "").split(",") if d["stages"] else [],
                    "tokens": d["tokens"],
                    "status": _run_status(d["open_rows"], d["last_at"]),
                    "events": None, "event_actions": None}
        if has_ev:
            cur.execute(
                "SELECT run_id, min(ts)::text AS first_at, max(ts)::text AS last_at, "
                "count(*) AS events, string_agg(DISTINCT action, ',') AS actions, "
                "string_agg(DISTINCT component, ',') AS components "
                "FROM provenance.event WHERE run_id IS NOT NULL GROUP BY run_id "
                "ORDER BY max(ts) DESC LIMIT %s", (limit,))
            for r in cur.fetchall():
                d = dict(r)
                cur2 = runs.get(d["run_id"])
                if cur2:
                    cur2["sources"].append("provenance.event")
                    cur2["events"] = d["events"]
                    cur2["event_actions"] = (d["actions"] or "").split(",")
                    cur2["components"] = (d["components"] or "").split(",")
                    # widen the window to whichever source saw activity first/last
                    cur2["first_at"] = min(cur2["first_at"], d["first_at"])
                    cur2["last_at"] = max(cur2["last_at"], d["last_at"])
                else:
                    runs[d["run_id"]] = {
                        "run_id": d["run_id"], "sources": ["provenance.event"],
                        "first_at": d["first_at"], "last_at": d["last_at"],
                        "stage_rows": None, "failures": None, "docs": None, "stages": None,
                        "tokens": None, "status": "completed",
                        "events": d["events"],
                        "event_actions": (d["actions"] or "").split(","),
                        "components": (d["components"] or "").split(",")}
        out = sorted(runs.values(), key=lambda x: x["last_at"] or "", reverse=True)[:limit]
        return JSONResponse({
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "read_only": True, "events_available": has_ev,
            "scope_note": "A run_id is a component/process scope, not one end-to-end "
                          "pipeline run. Extraction runs use the 'run-YYYYMMDD-...' namespace.",
            "runs": out,
            "events_note": None if has_ev else
                "provenance.event not present; runs are shown from metrics.stage_run only "
                "until the migration is applied."})
    finally:
        conn.close()


@app.get("/api/ops/runs/{run_id}")
def ops_run_detail(run_id: str):
    """One run's timeline: stage_run timings + provenance events, chronological, plus
    aggregated roll-ups. Recorded rows vs aggregated roll-ups vs unavailable are marked."""
    conn = _ops_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        has_sr = _regclass(cur, "metrics.stage_run")
        has_ev = _regclass(cur, "provenance.event")
        timeline, stage_rollup, action_rollup, reject_reasons = [], [], [], []
        found = False

        if has_sr:
            cur.execute(
                "SELECT stage, doc_id, started_at::text AS started_at, ended_at::text AS ended_at, "
                "ms, n_items, n_tokens, ok, host, note FROM metrics.stage_run "
                "WHERE run_id = %s ORDER BY started_at, id", (run_id,))
            for r in cur.fetchall():
                found = True
                d = dict(r)
                timeline.append({"kind": "timing", "at": d["started_at"], "stage": d["stage"],
                                 "doc_id": d["doc_id"], "ended_at": d["ended_at"], "ms": d["ms"],
                                 "n_items": d["n_items"], "n_tokens": d["n_tokens"],
                                 "ok": d["ok"], "host": d["host"], "note": d["note"]})
            cur.execute(
                "SELECT stage, count(*) AS runs, coalesce(sum(ms),0)::bigint AS total_ms, "
                "round(avg(ms))::int AS avg_ms, count(*) FILTER (WHERE ok IS FALSE) AS failures, "
                "coalesce(sum(n_items),0)::bigint AS items, coalesce(sum(n_tokens),0)::bigint AS tokens "
                "FROM metrics.stage_run WHERE run_id = %s GROUP BY stage ORDER BY min(started_at)",
                (run_id,))
            stage_rollup = [dict(r) for r in cur.fetchall()]

        if has_ev:
            cur.execute(
                "SELECT ts::text AS ts, stage, component, document_id, ref_table, ref_id, "
                "action, reason, evidence FROM provenance.event WHERE run_id = %s "
                "ORDER BY event_id", (run_id,))
            for r in cur.fetchall():
                found = True
                d = dict(r)
                timeline.append({"kind": "event", "at": d["ts"], "stage": d["stage"],
                                 "component": d["component"], "doc_id": d["document_id"],
                                 "ref_table": d["ref_table"], "ref_id": d["ref_id"],
                                 "action": d["action"], "reason": d["reason"],
                                 "evidence": d["evidence"]})
            cur.execute("SELECT action, count(*) AS n FROM provenance.event WHERE run_id = %s "
                        "GROUP BY action ORDER BY n DESC", (run_id,))
            action_rollup = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT reason, count(*) AS n FROM provenance.event "
                        "WHERE run_id = %s AND action = 'record_rejected' "
                        "GROUP BY reason ORDER BY n DESC", (run_id,))
            reject_reasons = [dict(r) for r in cur.fetchall()]

        if not found:
            return JSONResponse(status_code=404, content={
                "error": "no run with this run_id in metrics.stage_run or provenance.event",
                "run_id": run_id})

        timeline.sort(key=lambda e: (e["at"] or ""))
        starts = [e["at"] for e in timeline if e["at"]]
        ends = [e.get("ended_at") or e.get("at") for e in timeline if (e.get("ended_at") or e.get("at"))]
        open_rows = sum(1 for e in timeline if e["kind"] == "timing" and e.get("ended_at") is None)
        return JSONResponse({
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "read_only": True,
            "events_available": has_ev,
            "status": _run_status(open_rows, None),
            "first_at": min(starts) if starts else None,
            "last_at": max(ends) if ends else None,
            "timeline": timeline,                        # recorded rows
            "stage_rollup": stage_rollup,                # aggregated
            "action_rollup": action_rollup,              # aggregated
            "reject_reasons": reject_reasons,            # aggregated
            "events_note": None if has_ev else
                "provenance.event not present; this run shows metrics.stage_run timings "
                "only. Actions, rejection reasons and model events are unavailable until "
                "the migration is applied."})
    finally:
        conn.close()


# ============================================================================================
# SIGNAL EXPLORER -- investigate one signal end to end. READ-ONLY.
#
# A "signal" is a serving.signal_card row, keyed pl_<document_id> (serving_fill.py). This
# view answers "why does this card exist, from which document, on what evidence, where is it
# served?" by joining the signal-centric RECORDED fields (card/detail, the 2026-09-07
# lineage columns, provenance.event lifecycle) to the FULL document trace -- which it gets
# by calling build_lineage(), the same source of truth the Document Lineage view uses. No
# lineage logic is duplicated here, and nothing manufactures a proposition->signal link:
# the recorded input set is signal_card.source_prop_ids; the quote-overlap guess stays
# labelled 'reconstructed' inside build_lineage. Every section is tagged recorded /
# reconstructed / aggregated / provenance_unavailable.
# ============================================================================================

def _sig_ids(signal_id):
    """A card id is pl_<document_id>. Accept either form; return (card_id, document_id)."""
    sid = (signal_id or "").strip()
    if sid.startswith("pl_"):
        return sid, sid[3:]
    return "pl_" + sid, sid


@app.get("/api/ops/signals")
def ops_signals(lane: str = None, company: str = None, q: str = None,
                since: str = None, until: str = None, origin: str = None,
                limit: int = 50):
    """Signal list with filters (lane, company, free-text q over id/title/company, a
    since/until window on updated_at, origin). Source: serving.signal_card, read-only."""
    limit = max(1, min(int(limit), 500))
    conn = _ops_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if not _regclass(cur, "serving.signal_card"):
            return JSONResponse({"available": False, "signals": [],
                                 "note": "serving.signal_card does not exist on this "
                                         "database."})
        has_lin = _has_column(cur, "serving", "signal_card", "source_prop_ids")
        where, params = [], []
        if lane:
            where.append("lane = %s"); params.append(lane)
        if company:
            where.append("company ILIKE %s"); params.append("%" + company + "%")
        if origin:
            where.append("origin = %s"); params.append(origin)
        if q:
            where.append("(id ILIKE %s OR title ILIKE %s OR company ILIKE %s)")
            params += ["%" + q + "%"] * 3
        if since:
            where.append("updated_at >= %s"); params.append(since)
        if until:
            where.append("updated_at <= %s"); params.append(until)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        lin_cols = ", source_doc_ids, source_run_id, source_prop_ids" if has_lin else ""
        cur.execute(
            "SELECT id, lane, ord, dir, rank, title, company, tags, url, ago, origin, "
            "updated_at::text AS updated_at" + lin_cols +
            " FROM serving.signal_card" + clause +
            " ORDER BY updated_at DESC, ord LIMIT %s", params + [limit])
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["has_lineage"] = ({
                "source_doc_ids": bool(d.get("source_doc_ids")),
                "source_run_id": bool(d.get("source_run_id")),
                "source_prop_ids": bool(d.get("source_prop_ids"))} if has_lin else None)
            rows.append(d)
        return JSONResponse({
            "available": True, "read_only": True,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(rows),
            "filters": {"lane": lane, "company": company, "q": q, "since": since,
                        "until": until, "origin": origin, "limit": limit},
            "lineage_columns_present": has_lin,
            "signals": rows})
    finally:
        conn.close()


@app.get("/api/ops/signals/{signal_id}")
def ops_signal_detail(signal_id: str):
    """One signal, end to end. Signal-centric recorded fields + provenance lifecycle +
    translation, plus the full document trace from build_lineage() (reused, not
    duplicated). 404 only when neither a card, a detail, provenance events, nor any
    document lineage exists for the id."""
    card_id, did = _sig_ids(signal_id)
    conn = _ops_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if not _regclass(cur, "serving.signal_card"):
            return JSONResponse(status_code=503,
                                content={"error": "serving.signal_card not on this database"})

        def rec_of(row):
            return row.get("rec") if row else None

        cur.execute("SELECT to_jsonb(c) AS rec FROM serving.signal_card c WHERE c.id = %s",
                    (card_id,))
        card = rec_of(cur.fetchone())
        cur.execute("SELECT to_jsonb(d) AS rec FROM serving.signal_detail d WHERE d.id = %s",
                    (card_id,))
        detail = rec_of(cur.fetchone())

        # -- signal-centric recorded fields --
        if card:
            signal = {"status": "recorded", "card": card, "detail": detail,
                      "lane": card.get("lane"), "company": card.get("company"),
                      "category_tags": card.get("tags"), "rank": card.get("rank"),
                      "dir": card.get("dir"), "title": card.get("title"),
                      "origin": card.get("origin")}
        else:
            signal = {"status": "provenance_unavailable", "card": None, "detail": detail,
                      "note": "No serving.signal_card with id %s: the document produced no "
                              "card. See provenance_events / lineage for why." % card_id}

        # -- lineage columns (recorded 2026-09-07) --
        if card and card.get("source_prop_ids") is not None:
            lineage_columns = {
                "status": "recorded",
                "source_doc_ids": card.get("source_doc_ids"),
                "source_run_id": card.get("source_run_id"),
                "source_prop_ids": card.get("source_prop_ids"),
                "note": "The INPUT SET of proposition indices fed to this card, recorded at "
                        "write time -- not sentence-level causal attribution."}
        else:
            lineage_columns = {
                "status": "provenance_unavailable",
                "note": "This card predates the lineage columns (no backfill) or is a "
                        "reference row; the prop->card link is only reconstructable "
                        "(see lineage.stages prop_to_card_link)."}

        # -- provenance lifecycle events for this signal (recorded) --
        if _regclass(cur, "provenance.event"):
            cur.execute(
                "SELECT event_id, ts::text AS ts, stage, component, document_id, run_id, "
                "action, reason, evidence FROM provenance.event "
                "WHERE ref_id = %s OR document_id = %s ORDER BY event_id", (card_id, did))
            evs = [dict(r) for r in cur.fetchall()]
            rejects = [e for e in evs if e.get("action") in ("record_rejected", "error")]
            provenance_events = {
                "status": "recorded", "events": evs,
                "rejection_or_error": rejects or None,
                "note": ("record_rejected/error rows are the recorded gate/selection "
                         "decision for this document." if rejects else None)}
        else:
            provenance_events = {
                "status": "provenance_unavailable", "events": [],
                "note": "provenance.event is not present on this database."}

        # -- translation (RECONSTRUCTED from source language; there is no stored flag) --
        lang = None
        if _regclass(cur, "public.documents"):
            cur.execute("SELECT language FROM public.documents WHERE document_id = %s", (did,))
            lr = cur.fetchone()
            lang = (lr or {}).get("language") if lr else None
        if lang is not None:
            translation = {
                "status": "reconstructed", "source_language": lang,
                "translated": (lang or "").lower() not in ("", "en", "eng"),
                "note": "Derived from the source document language. serving_fill translates "
                        "non-English lead-ins to English at write time (translate.py); there "
                        "is no stored translation flag, so this is a reconstruction."}
        else:
            translation = {"status": "provenance_unavailable",
                           "note": "Source language not recorded on this database."}

        # -- FULL document trace: REUSE build_lineage (source of truth; own labels) --
        lineage_code, lineage = build_lineage(cur, did)

        found = bool(card or detail or provenance_events.get("events") or lineage_code != 404)
        if not found:
            return JSONResponse(status_code=404,
                                content={"error": "no signal or lineage for this id",
                                         "signal_id": signal_id, "card_id": card_id,
                                         "document_id": did})
        return JSONResponse({
            "signal_id": signal_id, "card_id": card_id, "document_id": did,
            "read_only": True,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "signal": signal,
            "lineage_columns": lineage_columns,
            "provenance_events": provenance_events,
            "translation": translation,
            "lineage": lineage,            # full doc trace, reused build_lineage (own labels)
            "lineage_status": lineage_code,
            "label_key": {"recorded": "a stored fact",
                          "reconstructed": "derived or guessed, not stored",
                          "aggregated": "a computed roll-up",
                          "provenance_unavailable": "an honest gap"}})
    finally:
        conn.close()


# ============================================================================================
# FEATURE / TAB EXPLORER -- the implementation path of each product feature. READ-ONLY.
#
# For every major tab the dashboard renders, this maps the real end-to-end path:
# source -> gate -> extraction -> propositions -> (signals|enrich|external harvest) ->
# serving table -> serving_live view -> /api/dataset[key] -> frontend component. The
# registry below is TRACED from the actual code (files/functions/tables/prompts all exist),
# and each entry is GROUNDED at request time with live row counts and real column presence,
# exactly like _PIPELINE. Provenance is labelled per feature; only signal_card/detail and
# (partially) partner record document lineage -- everything else is UNAVAILABLE / a per-row
# source URL / an aggregate, and is labelled so, never invented. No pipeline logic is
# duplicated: row-level lineage still comes from /api/lineage/doc/{id} and /api/ops/signals.
# ============================================================================================

_FEATURES = [
    {"id": "signals", "title": "Signal feed (Overview)",
     "purpose": "The competitive/market/tech signal cards and their detail panels -- the "
                "headline feed on every pillar's Overview.",
     "source_kind": "corpus", "pipeline_step": "signals",
     "serving_table": "serving.signal_card", "serving_view": "serving_live.signal_card",
     "extra_tables": ["serving.signal_detail"],
     "api": {"endpoint": "/api/dataset", "keys": ["competitiveCards", "marketCards",
             "techCards", "details"], "fields": CARD_FIELDS},
     "ui": {"view": "overview", "component": "frontend/src/pages/overview/Overview.jsx",
            "renders": "components/signalCard/SignalCard.jsx + detailPanel/DetailPanel.jsx"},
     "writers": [{"file": "extraction/signals/serving_fill.py", "function": "fill / CARD_INSERT_SQL",
                  "kind": "LLM", "model": "serving 14B (farm) via llmapi.client; parse_card classifies in code"}],
     "inputs": ["extracted.proposition", "extracted.document"],
     "provenance": {"class": "RECORDED",
                    "recorded_cols": ["source_doc_ids", "source_run_id", "source_prop_ids"],
                    "row_trace": "/api/ops/signals/{id} and /api/lineage/doc/{id}"},
     "gaps": ["prop->card link is an input set, not sentence-level attribution",
              "pre-2026-09-07 cards have null lineage (no backfill)"]},

    {"id": "partnerships", "title": "Partnerships",
     "purpose": "KSSL's own partners plus each rival's partnership network and the overlap "
                "with KSSL (the red-line ties).",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.partner", "serving_view": "serving_live.partner",
     "api": {"endpoint": "/api/dataset", "keys": ["KSSL_PARTNERS", "competitors[].partners"],
             "fields": PARTNER_FIELDS},
     "ui": {"view": "partnerships", "component": "frontend/src/pages/competitive/Partnerships.jsx",
            "renders": "lib/partners.js SVG graph + per-tie drawer"},
     "writers": [{"file": "extraction/signals/enrich_serving.py", "function": "step_partnerships",
                  "kind": "LLM", "model": "serving 14B (farm), PART_PROMPT", "scope": "client rows plp_*, ord<REV_ORD0"},
                 {"file": "pipeline/revive_partners.py", "function": "main",
                  "kind": "rule/DB", "scope": "rvp_*, ord>=REV_ORD0"}],
     "inputs": ["extracted.proposition", "extracted.document"],
     "provenance": {"class": "RECORDED_PARTIAL", "recorded_cols": ["source_doc_ids"],
                    "per_row_source": ["src", "srcnote"],
                    "note": "enrich_serving rows record source_doc_ids; revive_partners rows "
                            "do not. source_run_id/source_prop_ids are not on this table.",
                    "row_trace": "/api/lineage/doc/{id} (enrichment stage)"},
     "gaps": ["revive_partners rows carry no source_doc_ids"]},

    {"id": "competitors", "title": "Competitors / Profile",
     "purpose": "The per-competitor dossier: sector, HQ, threat, assessment, and the nested "
                "leadership/revenue/facilities/products sub-panels.",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.competitors", "serving_view": "serving_live.competitors",
     "api": {"endpoint": "/api/dataset", "keys": ["competitors", "compOrder"], "fields": COMP_FIELDS},
     "ui": {"view": "profile", "component": "frontend/src/pages/competitive/Profile.jsx",
            "renders": "lib/profile.js buildProfile"},
     "writers": [{"file": "extraction/signals/enrich_serving.py", "function": "step_companies / _rebuild_companies",
                  "kind": "LLM", "model": "serving 14B (farm), PROFILE_PROMPT", "scope": "ord<REV_ORD0"},
                 {"file": "pipeline/revive_partners.py", "function": "main", "kind": "rule/DB", "scope": "ord>=REV_ORD0"},
                 {"file": "pipeline/harvest/promote.py", "function": "(harvest)", "kind": "harvest",
                  "note": "fills leadership/facilities/sales from each maker's own site, each value carrying its URL + verbatim line"}],
     "inputs": ["extracted.proposition", "extracted.document", "maker websites (harvest)"],
     "provenance": {"class": "UNAVAILABLE",
                    "note": "No source_doc_ids on serving.competitors. Harvested sub-fields "
                            "(leadership/sales/facilities) carry a per-value source URL + quote; "
                            "the LLM profile fields carry none. Some profiles are interim agent data.",
                    "per_row_source": ["srcs"]},
     "gaps": ["profile/threat/assess have no recorded document lineage",
              "leadership column is ~0% filled on live data"]},

    {"id": "leadership", "title": "Leadership (Profile sub-panel)",
     "purpose": "Board/executive cards inside a competitor's profile.",
     "source_kind": "harvest", "pipeline_step": "enrich",
     "serving_table": "serving.competitors", "serving_view": "serving_live.competitors",
     "column": "leadership",
     "api": {"endpoint": "/api/dataset", "keys": ["competitors[].leadership"]},
     "ui": {"view": "profile", "component": "frontend/src/pages/competitive/Profile.jsx (Leadership section)"},
     "writers": [{"file": "pipeline/harvest/promote.py", "function": "(harvest)", "kind": "harvest",
                  "note": "each value carries the URL and the verbatim line it was read from"}],
     "inputs": ["maker websites"],
     "provenance": {"class": "RECONSTRUCTED", "per_row_source": ["per-value URL + quote"],
                    "note": "Recorded as a per-value source URL, not document lineage."},
     "gaps": ["column is ~0% filled on live data -- empty state, not fabricated"]},

    {"id": "revenue", "title": "Revenue / Sales (Profile row)",
     "purpose": "Annual revenue / sales figure in a competitor's Company Details panel.",
     "source_kind": "harvest", "pipeline_step": "enrich",
     "serving_table": "serving.competitors", "serving_view": "serving_live.competitors",
     "column": "sales",
     "api": {"endpoint": "/api/dataset", "keys": ["competitors[].sales"]},
     "ui": {"view": "profile", "component": "frontend/src/pages/competitive/Profile.jsx (firstFigure)"},
     "writers": [{"file": "pipeline/harvest/promote.py", "function": "(harvest)", "kind": "harvest"}],
     "inputs": ["maker websites"],
     "provenance": {"class": "RECONSTRUCTED", "per_row_source": ["per-value URL + quote"]},
     "gaps": ["revenue_filter facet tier is unwritten (frontend Products.jsx)"]},

    {"id": "products", "title": "Products",
     "purpose": "A competitor's product catalogue with specs and product news.",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.competitors", "serving_view": "serving_live.competitors",
     "column": "products", "extra_tables": ["serving.matchup"],
     "api": {"endpoint": "/api/dataset", "keys": ["competitors[].products", "matchups[].specs"]},
     "ui": {"view": "products", "component": "frontend/src/pages/competitive/Products.jsx"},
     "writers": [{"file": "extraction/signals/enrich_serving.py", "function": "step_companies (products) / step_matchups (specs)",
                  "kind": "mixed", "model": "PROFILE_PROMPT for products; specs are rule/DB from propositions"}],
     "inputs": ["extracted.proposition", "extracted.document"],
     "provenance": {"class": "UNAVAILABLE", "note": "products embedded in serving.competitors; no doc lineage."},
     "gaps": []},

    {"id": "matchups", "title": "Matchups / Positioning",
     "purpose": "Every rating-matched KSSL-vs-rival pair with the spec dossier and edge verdict.",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.matchup", "serving_view": "serving_live.matchup",
     "api": {"endpoint": "/api/dataset", "keys": ["matchups"], "fields": MATCHUP_FIELDS},
     "ui": {"view": "positioning", "component": "frontend/src/pages/competitive/Positioning.jsx",
            "renders": "matchupList + matchupDossier; also GapAnalysis.jsx"},
     "writers": [{"file": "extraction/signals/enrich_serving.py", "function": "step_matchups",
                  "kind": "rule/DB", "model": "extract_specs / categorise_product over propositions (no self-narration)", "scope": "matchup_id<20000"},
                 {"file": "pipeline/revive_matchups.py", "function": "main", "kind": "rule/DB", "scope": "matchup_id>=20000"}],
     "inputs": ["extracted.proposition", "extracted.document", "serving.competitors"],
     "provenance": {"class": "UNAVAILABLE", "per_row_source": ["srcs", "det"],
                    "note": "Per-row srcs/det carry the spec sources; no source_doc_ids column."},
     "gaps": ["spec->document link not stored as lineage"]},

    {"id": "structure", "title": "Structure / Ownership",
     "purpose": "Ownership and corporate-structure ties between a competitor and other entities.",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.competitor_structure", "serving_view": "serving_live.competitor_structure",
     "api": {"endpoint": "/api/dataset", "keys": ["competitorStructure"], "fields": STRUCT_FIELDS},
     "ui": {"view": None, "component": None,
            "note": "NO frontend surface: /api/dataset emits competitorStructure but no RAIL "
                    "tab or component renders it (verified against the router + Layout switch)."},
     "writers": [{"file": "extraction/signals/enrich_serving.py", "function": "step_structure",
                  "kind": "rule/DB", "line": 2702}],
     "inputs": ["extracted.proposition", "extracted.document"],
     "provenance": {"class": "RECONSTRUCTED", "per_row_source": ["source_url (NOT NULL)", "source_note"],
                    "note": "Every ownership claim stores its evidence source_url; no source_doc_ids."},
     "gaps": ["built and served but not rendered anywhere in the UI"]},

    {"id": "metrics", "title": "Mention metrics (KPI strip)",
     "purpose": "Corpus mention volume per competitor over a rolling window vs the previous "
                "one -- the KPI tiles and the trend numbers.",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.competitor_metrics", "serving_view": "serving_live.competitor_metrics",
     "api": {"endpoint": "/api/dataset", "keys": ["competitorMetrics"], "fields": METRIC_FIELDS},
     "ui": {"view": "(cross-cutting)", "component": "frontend/src/components/metricsStrip/MetricsStrip.jsx"},
     "writers": [{"file": "extraction/signals/enrich_serving.py", "function": "step_metrics",
                  "kind": "rule/DB", "line": 2809, "note": "counts corpus mentions over window_days"}],
     "inputs": ["extracted.document", "extracted.proposition (mention counts)"],
     "provenance": {"class": "AGGREGATED",
                    "note": "Window counts computed over the corpus; window_days travels with "
                            "the counts so the UI cannot mislabel the units. No per-row source."},
     "gaps": ["individual mentions are aggregated away; not drillable to documents"]},

    {"id": "news", "title": "Competitor / market news",
     "purpose": "The sourced news feed shown inside Profile, Products and Geo.",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.competitor_news", "serving_view": "serving_live.competitor_news",
     "api": {"endpoint": "/api/dataset", "keys": ["competitorNews"], "fields": NEWS_FIELDS},
     "ui": {"view": "(cross-cutting)", "component": "lib/news.js (companyNews/productNews/marketNews)"},
     "writers": [{"file": "extraction/signals/fill_competitor_news.py", "function": "main",
                  "kind": "rule/DB", "note": "rows copied from existing serving.signal_card; cascaded away and refilled every enrich pass"}],
     "inputs": ["serving.signal_card", "serving.competitors"],
     "provenance": {"class": "RECONSTRUCTED", "per_row_source": ["url", "story_key", "continues_url"],
                    "note": "Each article carries its own url; the underlying card has full "
                            "lineage (trace via Signal Explorer on pl_<doc>)."},
     "gaps": ["news_chain story_key/continues_url null on standalone articles"]},

    {"id": "geo", "title": "Geo / HQ footprint",
     "purpose": "Country <-> competitor <-> product footprint with overlap-vs-KSSL badges.",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.geo_presence", "serving_view": "serving_live.geo_presence",
     "extra_tables": ["serving.geo_comp"],
     "api": {"endpoint": "/api/dataset", "keys": ["geoData", "geoComps"],
             "fields": GEO_FIELDS},
     "ui": {"view": "geo", "component": "frontend/src/pages/competitive/Geo.jsx",
            "renders": "components/geoMap/GeoMap.jsx"},
     "writers": [{"file": "extraction/signals/enrich_serving.py", "function": "step_geo",
                  "kind": "LLM", "model": "serving 14B (farm), GEO_PROMPT", "scope": "ord<2000"},
                 {"file": "pipeline/discover_geo.py", "function": "main", "kind": "LLM", "scope": "ord>=GEO_ORD0"}],
     "inputs": ["extracted.proposition", "extracted.document"],
     "provenance": {"class": "UNAVAILABLE", "per_row_source": ["src", "srcnote"],
                    "note": "Per-row src URL only; no source_doc_ids."},
     "gaps": []},

    {"id": "innovation", "title": "Innovation / tech pipeline",
     "purpose": "Innovation pipeline by technology domain with maturity, KSSL gap and sources.",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.innovation", "serving_view": "serving_live.innovation",
     "api": {"endpoint": "/api/dataset", "keys": ["innovations"], "fields": INNOV_FIELDS},
     "ui": {"view": "innovation", "component": "frontend/src/pages/technology/Innovation.jsx"},
     "writers": [{"file": "extraction/signals/enrich_serving.py", "function": "step_innovations",
                  "kind": "LLM", "model": "serving 14B (farm), INNOV_PROMPT"}],
     "inputs": ["extracted.proposition", "extracted.document"],
     "provenance": {"class": "RECONSTRUCTED", "per_row_source": ["sources", "url"],
                    "note": "Per-row source URLs; no source_doc_ids."},
     "gaps": []},

    {"id": "tenders", "title": "Tenders / market",
     "purpose": "Open/awarded/closed procurement tenders with per-tender assessment and the "
                "market-report roll-ups.",
     "source_kind": "external_api", "pipeline_step": None,
     "serving_table": "serving.tender", "serving_view": "serving_live.tender",
     "api": {"endpoint": "/api/dataset", "keys": ["tenders"], "fields": TENDER_FIELDS},
     "ui": {"view": "tender", "component": "frontend/src/pages/market/Tenders.jsx + MarketOverview.jsx"},
     "writers": [{"file": "pipeline/fetch_tenders.py", "function": "write_db",
                  "kind": "rule/API", "note": "SAM/TED/GeM/CPPP procurement APIs; CPV_MAP classification; id-prefixed sam_/ted_/gem_/cppp_. NOT corpus-derived."}],
     "inputs": ["government procurement APIs (SAM/TED/GeM/CPPP)"],
     "provenance": {"class": "UNAVAILABLE", "per_row_source": ["srcs", "url"],
                    "note": "Sourced from government APIs, not the document corpus; each row "
                            "carries its portal URL. enrich_serving.step_tenders is dead code."},
     "gaps": ["not part of the corpus->extraction pipeline; no document lineage applies"]},

    {"id": "patents", "title": "Patents",
     "purpose": "Competitor patent filings by rival and by technology field.",
     "source_kind": "external_api", "pipeline_step": None,
     "serving_table": "serving.patent", "serving_view": "serving_live.patent",
     "api": {"endpoint": "/api/dataset", "keys": ["PATENTS", "patentAssignees"], "fields": PATENT_FIELDS},
     "ui": {"view": "patents-comp", "component": "frontend/src/pages/competitive/Patents.jsx"},
     "writers": [{"file": "pipeline/fetch_patents_wipo.py", "function": "write_db",
                  "kind": "rule/API", "note": "WIPO feed; area/relev/threat from IPC/CPC classification, not keywords"},
                 {"file": "extraction/signals/patent_titles.py", "function": "translate_titles",
                  "kind": "LLM", "model": "title translation only (title_en)"}],
     "inputs": ["WIPO patent API"],
     "provenance": {"class": "RECONSTRUCTED", "per_row_source": ["doc_id", "url"],
                    "note": "Harvested rows carry a doc_id + url; the three signal-lineage "
                            "columns do not apply (external source)."},
     "gaps": ["comp_id/published/grant_no null on pre-detail-pass rows; title_en null until translated"]},

    {"id": "sources", "title": "Source registry",
     "purpose": "The registry of sources behind the dashboard -- the source-link chips shown "
                "across every view.",
     "source_kind": "corpus", "pipeline_step": "enrich",
     "serving_table": "serving.source_registry", "serving_view": "serving_live.source_registry",
     "extra_tables": ["serving.company_source"],
     "api": {"endpoint": "/api/dataset", "keys": ["sourceRegistry", "companySources"], "fields": SRCREG_FIELDS},
     "ui": {"view": "(cross-cutting)", "component": "components/sourceLink/SourceLink.jsx + lib/html.js srcChips"},
     "writers": [{"file": "extraction/signals/enrich_serving.py", "function": "step_sources",
                  "kind": "rule/DB", "note": "company_mentions + article_date; no model"}],
     "inputs": ["extracted.document", "extracted.proposition", "serving.competitors"],
     "provenance": {"class": "UNAVAILABLE", "per_row_source": ["url"],
                    "note": "Each entry IS a source URL; there is no upstream lineage column."},
     "gaps": []},
]

_FEATURES_BY_ID = {f["id"]: f for f in _FEATURES}


def _feature_ground(cur, feat):
    """Live facts for one feature: serving_live row count and recorded-lineage presence.
    Names come from our own registry, so the interpolation is safe; every read is a SELECT."""
    g = {"serving_view_present": False, "live_rows": None,
         "has_source_doc_ids": False, "rows_with_doc_lineage": None}
    view = feat.get("serving_view")
    if view and _regclass(cur, view):
        g["serving_view_present"] = True
        try:
            cur.execute("SELECT count(*) AS n FROM " + view)
            g["live_rows"] = cur.fetchone()["n"]
        except Exception:                                   # noqa: BLE001
            pass
    tbl = feat.get("serving_table") or ""
    schema, _, table = tbl.partition(".")
    if table and _has_column(cur, schema, table, "source_doc_ids"):
        g["has_source_doc_ids"] = True
        try:
            cur.execute("SELECT count(*) AS n FROM %s WHERE source_doc_ids IS NOT NULL" % tbl)
            g["rows_with_doc_lineage"] = cur.fetchone()["n"]
        except Exception:                                   # noqa: BLE001
            pass
    return g


@app.get("/api/ops/features")
def ops_features(q: str = None):
    """List every product feature with its provenance class, grounded with live row counts.
    Optional q filters over id / title / purpose / serving table."""
    conn = _ops_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        ql = (q or "").strip().lower()
        rows = []
        for f in _FEATURES:
            if ql and ql not in " ".join([
                    f["id"], f["title"], f["purpose"], f.get("serving_table") or ""]).lower():
                continue
            g = _feature_ground(cur, f)
            rows.append({
                "id": f["id"], "title": f["title"], "purpose": f["purpose"],
                "pipeline_step": f.get("pipeline_step"), "source_kind": f.get("source_kind"),
                "serving_table": f.get("serving_table"),
                "api_keys": f["api"].get("keys"),
                "ui_view": f["ui"].get("view"),
                "provenance_class": f["provenance"]["class"],
                "live_rows": g["live_rows"],
                "has_recorded_lineage": g["has_source_doc_ids"],
                "rows_with_doc_lineage": g["rows_with_doc_lineage"]})
        return JSONResponse({
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "read_only": True, "count": len(rows),
            "provenance_legend": {
                "RECORDED": "document lineage stored on the row (source_doc_ids/run/prop)",
                "RECORDED_PARTIAL": "some rows record source_doc_ids, others do not",
                "RECONSTRUCTED": "a per-row source URL is stored, but not full pipeline lineage",
                "AGGREGATED": "a computed roll-up; individual sources aggregated away",
                "UNAVAILABLE": "no source lineage recorded on the row"},
            "features": rows})
    finally:
        conn.close()


@app.get("/api/ops/features/{feature_id}")
def ops_feature_detail(feature_id: str):
    """One feature, end to end: purpose, the pipeline path (reusing _PIPELINE), the real
    writer files/functions/models, input/output tables, provenance (labelled, grounded),
    API + UI destinations, and known gaps. 404 for an unknown feature id."""
    feat = _FEATURES_BY_ID.get(feature_id)
    if not feat:
        return JSONResponse(status_code=404,
                            content={"error": "no such feature", "feature_id": feature_id,
                                     "known": list(_FEATURES_BY_ID.keys())})
    conn = _ops_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        g = _feature_ground(cur, feat)

        # The end-to-end path, reusing _PIPELINE stage metadata. Corpus features flow through
        # ingestion->gate->extraction->(writer step); external-API features skip the corpus.
        pipe = {p["id"]: p for p in _PIPELINE}
        if feat.get("source_kind") in ("external_api",):
            step_ids = [feat.get("pipeline_step") or "api"]
            path = [{"stage": "external source", "role": "feeder",
                     "detail": feat["inputs"][0] if feat.get("inputs") else None}]
        elif feat.get("source_kind") == "harvest":
            path = [{"stage": "maker-site harvest", "role": "feeder",
                     "detail": "pipeline/harvest/promote.py; per-value URL + verbatim line"}]
            step_ids = ["serving"]
        else:
            step_ids = ["ingestion", "gate", "extraction", feat.get("pipeline_step") or "signals"]
            path = []
        for sid in step_ids:
            p = pipe.get(sid)
            if p:
                path.append({"stage": p["id"], "title": p["title"], "role": p["role"],
                             "files": p["files"], "functions": p["functions"],
                             "model": p.get("model")})
        # then serving -> serving_live -> api -> ui, grounded
        path.append({"stage": "serving_table", "table": feat.get("serving_table"),
                     "also": feat.get("extra_tables")})
        path.append({"stage": "serving_live_view", "view": feat.get("serving_view"),
                     "present": g["serving_view_present"], "live_rows": g["live_rows"],
                     "filter": "origin='pipeline'"})
        path.append({"stage": "api", "endpoint": feat["api"]["endpoint"],
                     "keys": feat["api"].get("keys")})
        path.append({"stage": "ui", "view": feat["ui"].get("view"),
                     "component": feat["ui"].get("component"),
                     "note": feat["ui"].get("note")})

        prov = dict(feat["provenance"])
        prov["grounded"] = {"has_source_doc_ids_column": g["has_source_doc_ids"],
                            "rows_with_doc_lineage": g["rows_with_doc_lineage"],
                            "live_rows": g["live_rows"]}
        return JSONResponse({
            "id": feat["id"], "title": feat["title"], "purpose": feat["purpose"],
            "read_only": True,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_kind": feat.get("source_kind"),
            "pipeline_path": path,
            "writers": feat["writers"],
            "inputs": feat.get("inputs"),
            "output_tables": [feat.get("serving_table")] + (feat.get("extra_tables") or []),
            "serving_view": feat.get("serving_view"),
            "api": feat["api"], "ui": feat["ui"],
            "provenance": prov,
            "gaps": feat.get("gaps"),
            "row_level_trace": feat["provenance"].get("row_trace")
                or "row-level document lineage is not recorded for this feature"})
    finally:
        conn.close()
