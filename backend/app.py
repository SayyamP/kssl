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

import os
import sys

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
                 "comp_id"]
# comp_id is null on the 26 curated reference rows and absent entirely on a database
# that has not run 2026-09-06_patent_comp_id.sql, so it is optional in both senses.
PATENT_OPT = frozenset(["comp_id"])
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


# ============================================================================
# ROLLBACK DRILL FIXTURE -- TEMPORARY. Reverted in the commit immediately after.
#
# The health gate's rollback has only ever been proven against stubs
# (deploy/test_healthgate.sh). This makes one real deploy unhealthy so the gate
# on VPS-A has something genuine to catch and revert.
#
# A 503 rather than a crash, deliberately. Crashing at import would put the
# container into a restart loop, which the gate also catches -- but a loop
# churns RestartCount, leaves a dead container behind if anything goes wrong,
# and is harder to reason about. This keeps the process up and healthy and
# fails only the one thing the gate actually measures: _be_answers(), which
# has no /api/health route to fall back to and so lands on /api/dataset.
# Blast radius is one endpoint, for the ~60s the gate takes to give up.
@app.middleware("http")
async def _rollback_drill_503(request: Request, call_next):
    if request.url.path in ("/api/health", "/api/dataset"):
        return JSONResponse(status_code=503,
                            content={"drill": "deliberate health-gate failure"})
    return await call_next(request)
