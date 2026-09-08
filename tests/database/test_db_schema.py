# -*- coding: utf-8 -*-
"""Module: DATABASE / schema presence and shape.

Every object asserted here is created by a file in db/ or by
extraction/engine/route.py (extract_queue). Nothing is invented.
"""
import sys, os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import env  # noqa: E402
from conftest import regclass  # noqa: E402

# db/00_documents.sql, db/01_extracted.sql, db/02_serving.sql, db/03_serving_live.sql,
# db/05_metrics.sql, db/06_bench.sql, db/07_provenance.sql, engine/route.py DDL
CORE_TABLES = [
    ("public.documents", "db/00_documents.sql"),
    ("public.extract_queue", "extraction/engine/route.py DDL"),
    ("extracted.extraction_run", "db/01_extracted.sql"),
    ("extracted.document", "db/01_extracted.sql"),
    ("extracted.span", "db/01_extracted.sql"),
    ("extracted.proposition", "db/01_extracted.sql"),
    ("extracted.span_value", "db/01_extracted.sql"),
    ("extracted.prop_arg", "db/01_extracted.sql"),
    ("extracted.entity", "db/01_extracted.sql"),
    ("extracted.entity_alias", "db/01_extracted.sql"),
    ("serving.ui_config", "db/02_serving.sql"),
    ("serving.competitors", "db/02_serving.sql"),
    ("serving.competitor_news", "db/02_serving.sql"),
    ("serving.competitor_structure", "db/02_serving.sql"),
    ("serving.competitor_metrics", "db/02_serving.sql"),
    ("serving.signal_card", "db/02_serving.sql"),
    ("serving.signal_detail", "db/02_serving.sql"),
    ("serving.matchup", "db/02_serving.sql"),
    ("serving.tender", "db/02_serving.sql"),
    ("serving.patent", "db/02_serving.sql"),
    ("serving.geo_presence", "db/02_serving.sql"),
    ("serving.geo_comp", "db/02_serving.sql"),
    ("serving.client_product", "db/02_serving.sql"),
    ("serving.competitor_product", "db/02_serving.sql"),
    ("serving.innovation", "db/02_serving.sql"),
    ("serving.partner", "db/02_serving.sql"),
    ("serving.source_registry", "db/02_serving.sql"),
    ("serving.company_source", "db/02_serving.sql"),
]

SERVING_LIVE_VIEWS = [
    "serving_live.company_source", "serving_live.competitors",
    "serving_live.competitor_news", "serving_live.competitor_metrics",
    "serving_live.competitor_structure", "serving_live.geo_comp",
    "serving_live.geo_presence", "serving_live.innovation", "serving_live.matchup",
    "serving_live.partner", "serving_live.patent", "serving_live.signal_card",
    "serving_live.signal_detail", "serving_live.source_registry",
    "serving_live.tender", "serving_live.ui_config",
]


@pytest.mark.parametrize("table,source", CORE_TABLES)
def test_db_001_core_table_exists(cur, table, source):
    """
    Test ID        : DB-001
    Module         : Database / Schema
    Precondition   : direct DB access to the kssl database
    Steps          : 1. SELECT to_regclass('<table>')
    Test Data      : every table db/*.sql and route.py's DDL create
    Expected Result: present. A missing serving table takes a whole panel off the
                     dashboard; a missing extracted table stops the worker committing.
    API Endpoint   : consumed by GET /api/dataset and /api/ops/*
    DB Validation  : to_regclass IS NOT NULL
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    assert regclass(cur, table), "%s is missing (created by %s)" % (table, source)


@pytest.mark.parametrize("view", SERVING_LIVE_VIEWS)
def test_db_002_serving_live_view_exists(cur, view):
    """
    Test ID        : DB-002
    Module         : Database / Schema - the served layer
    Precondition   : direct DB access
    Steps          : 1. SELECT to_regclass('<view>')
    Test Data      : the 16 views in db/03_serving_live.sql
    Expected Result: present. backend/app.py serves from serving_live by default
                     (SCHEMA = 'serving_live'); a missing view is an instant 500 on
                     /api/dataset.
    API Endpoint   : GET /api/dataset
    DB Validation  : to_regclass IS NOT NULL
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    assert regclass(cur, view), "%s is missing (db/03_serving_live.sql)" % view


def test_db_003_observability_tables(cur):
    """
    Test ID        : DB-003
    Module         : Database / Observability schema
    Precondition   : direct DB access
    Steps          : 1. check metrics.stage_run, metrics.stage_summary,
                        metrics.doc_journey, metrics.adhoc_job, metrics.adhoc_summary,
                        provenance.event
    Test Data      : db/05_metrics.sql, db/06_bench.sql, db/07_provenance.sql
    Expected Result: report which are present. provenance.event is allowed to be absent
                     (migration 2026-09-07_provenance_events.sql may not have run) --
                     the ops endpoints degrade to "unavailable" for it, which BE-030
                     already covers. metrics.stage_run must be present: it is the only
                     record of how long anything took.
    API Endpoint   : GET /api/ops/overview, /api/ops/runs, /api/bench/runs
    DB Validation  : to_regclass on each
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    assert regclass(cur, "metrics.stage_run"), "metrics.stage_run missing (db/05_metrics.sql)"
    for t in ("metrics.stage_summary", "metrics.doc_journey", "metrics.adhoc_job",
              "metrics.adhoc_summary", "provenance.event"):
        if not regclass(cur, t):
            print("NOTE: %s is not on this database (degrades to 'unavailable')" % t)


def test_db_004_schema_version_ledger(cur):
    """
    Test ID        : DB-004
    Module         : Database / Migrations
    Precondition   : direct DB access
    Steps          : 1. SELECT filename FROM schema_version
                     2. compare against the files in db/ and db/migrations/
    Test Data      : the repository's own db/*.sql and db/migrations/*.sql
    Expected Result: every migration file on disk has a ledger row. extraction/
                     entrypoint.sh `migrate` records each file once; a migration on
                     disk with no row is one that has never been applied -- which is
                     exactly what put a backend selecting `country` in front of a
                     database without it on 2026-09-06.
    API Endpoint   : n/a
    DB Validation  : SELECT filename FROM schema_version
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "public.schema_version"):
        pytest.skip("schema_version ledger not on this database (pre-migrate)")
    cur.execute("SELECT filename FROM schema_version")
    applied = {r["filename"] for r in cur.fetchall()}
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    mig_dir = os.path.join(repo, "db", "migrations")
    if not os.path.isdir(mig_dir):
        pytest.skip("db/migrations not present next to the test suite")
    on_disk = {f for f in os.listdir(mig_dir) if f.endswith(".sql")}
    missing = sorted(on_disk - applied)
    assert not missing, ("migrations on disk with no schema_version row (never applied "
                         "to this database): %s" % missing)


def test_db_005_signal_card_columns_the_api_selects(cur):
    """
    Test ID        : DB-005
    Module         : Database / Backend contract
    Precondition   : direct DB access
    Steps          : 1. read information_schema.columns for serving.signal_card
                     2. assert every NON-optional field in app.py CARD_FIELDS exists
    Test Data      : CARD_FIELDS minus CARD_OPT (backend/app.py)
    Expected Result: present. app.py's _reconcile_optional drops only OPTIONAL columns
                     that are missing; a missing NON-optional column raises
                     UndefinedColumn and takes the entire dashboard down, not one field.
    API Endpoint   : GET /api/dataset
    DB Validation  : information_schema.columns
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    required = ["id", "dir", "rank", "title", "meta", "sowhat", "ago", "tags"]
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='serving' AND table_name='signal_card'")
    have = {r["column_name"] for r in cur.fetchall()}
    missing = [c for c in required if c not in have]
    assert not missing, "serving.signal_card is missing non-optional columns: %s" % missing


def test_db_006_extract_queue_columns(cur):
    """
    Test ID        : DB-006
    Module         : Database / Extraction queue schema
    Precondition   : direct DB access
    Steps          : 1. read the columns of public.extract_queue
    Test Data      : the DDL in extraction/engine/route.py
    Expected Result: document_id, class, chars, est_out, crawl_ts, text_hash, state,
                     leased_by, lease_epoch, lease_until, attempts, reason all present.
                     `reason` in particular: without it park() discards why a document
                     was parked and `deferred` has two indistinguishable meanings.
    API Endpoint   : GET /api/ops/overview (queue tiles)
    DB Validation  : information_schema.columns
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "public.extract_queue"):
        pytest.skip("public.extract_queue not on this database")
    want = {"document_id", "class", "chars", "est_out", "crawl_ts", "text_hash",
            "state", "leased_by", "lease_epoch", "lease_until", "attempts", "reason"}
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='extract_queue'")
    have = {r["column_name"] for r in cur.fetchall()}
    assert want <= have, "extract_queue is missing: %s" % sorted(want - have)
