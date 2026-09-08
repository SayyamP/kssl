# -*- coding: utf-8 -*-
"""Module: DATABASE / data integrity, constraints and referential health.

These are the invariants the application depends on and the ones this repository has
already been bitten by: a threat column holding prose, cascaded-away news, ties with no
`cid`, tender rows whose `det` is not a jsonb array.
"""
import sys, os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import env  # noqa: E402
from conftest import regclass  # noqa: E402


def test_db_010_origin_vocabulary(cur):
    """
    Test ID        : DB-010
    Module         : Database / Constraints
    Precondition   : direct DB access
    Steps          : 1. for each serving table with an `origin` column, read DISTINCT origin
    Test Data      : the CHECK (origin IN ('reference','pipeline')) in db/02_serving.sql
    Expected Result: only 'reference' and 'pipeline'. A third value is invisible to BOTH
                     serving_live (which filters to 'pipeline') and the archive.
    API Endpoint   : GET /api/dataset
    DB Validation  : SELECT DISTINCT origin FROM serving.X
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    bad = {}
    for t in ("competitors", "signal_card", "signal_detail", "matchup", "tender",
              "patent", "partner", "innovation"):
        q = "serving." + t
        if not regclass(cur, q):
            continue
        cur.execute("SELECT DISTINCT origin FROM " + q)
        vals = {r["origin"] for r in cur.fetchall()}
        extra = vals - {"reference", "pipeline"}
        if extra:
            bad[t] = extra
    assert not bad, "origin values outside the CHECK constraint: %s" % bad


def test_db_011_threat_column_holds_levels_not_prose(cur):
    """
    Test ID        : DB-011
    Module         : Database / Data quality (regression)
    Precondition   : direct DB access
    Steps          : 1. SELECT comp_id, threat FROM serving.competitors WHERE threat IS NOT NULL
                     2. assert each value is one of the levels the gate recognises
    Test Data      : the LEVELS vocabulary in extraction/signals/threat_gate.py
    Expected Result: every non-null threat is high | medium | low (case-insensitive).
                     serving.competitors.threat has NO check constraint, and this
                     repository records rows where a threatNote paragraph was written
                     into it -- which then renders as a rating on the Profile dot, the
                     Products dot, the patent leader sort AND the severity grade.
    API Endpoint   : GET /api/dataset -> competitors[].threat
    DB Validation  : SELECT threat FROM serving.competitors
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "serving.competitors"):
        pytest.skip("serving.competitors not on this database")
    cur.execute("SELECT comp_id, threat FROM serving.competitors WHERE threat IS NOT NULL")
    prose = [(r["comp_id"], str(r["threat"])[:60]) for r in cur.fetchall()
             if str(r["threat"]).strip().lower() not in ("high", "medium", "low")]
    assert not prose, ("serving.competitors.threat holds non-level values (prose in a "
                       "level column): %s" % prose[:10])


def test_db_012_news_rows_survive_the_enrich_rebuild(cur):
    """
    Test ID        : DB-012
    Module         : Database / Referential integrity (regression)
    Precondition   : direct DB access; the enrich role has run at least once
    Steps          : 1. count serving.competitors with origin='pipeline'
                     2. count serving.competitor_news
    Test Data      : none
    Expected Result: news is not empty while competitors is populated.
                     serving.competitor_news.comp_id REFERENCES serving.competitors
                     ON DELETE CASCADE, and the enrich pass deletes and rebuilds every
                     origin='pipeline' competitor -- so each pass takes the whole news
                     table with it. fill_competitor_news.py is its only writer and was
                     once wired to nothing; measured on production 2026-09-04:
                     123 rows before a pass, 0 after.
    API Endpoint   : GET /api/dataset -> competitorNews
    DB Validation  : count(serving.competitor_news) vs count(serving.competitors)
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    if not (regclass(cur, "serving.competitors") and regclass(cur, "serving.competitor_news")):
        pytest.skip("competitors/news tables not on this database")
    cur.execute("SELECT count(*) AS n FROM serving.competitors WHERE origin='pipeline'")
    comps = cur.fetchone()["n"]
    cur.execute("SELECT count(*) AS n FROM serving.competitor_news")
    news = cur.fetchone()["n"]
    if comps == 0:
        pytest.skip("no pipeline competitors yet")
    assert news > 0, ("%d pipeline competitors and 0 news rows -- the enrich rebuild "
                      "cascaded the news away and fill_competitor_news.py did not run"
                      % comps)


def test_db_013_no_orphan_news(cur):
    """
    Test ID        : DB-013
    Module         : Database / Referential integrity
    Precondition   : direct DB access
    Steps          : 1. LEFT JOIN serving.competitor_news to serving.competitors
    Test Data      : none
    Expected Result: zero orphans (the FK guarantees it; asserted because a restored
                     replica can carry data whose constraints were dropped by the dump).
    API Endpoint   : GET /api/dataset -> competitorNews
    DB Validation  : SELECT count(*) ... WHERE c.comp_id IS NULL
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    if not (regclass(cur, "serving.competitors") and regclass(cur, "serving.competitor_news")):
        pytest.skip("tables not present")
    cur.execute("SELECT count(*) AS n FROM serving.competitor_news n "
                "LEFT JOIN serving.competitors c ON c.comp_id = n.comp_id "
                "WHERE c.comp_id IS NULL")
    assert cur.fetchone()["n"] == 0


def test_db_014_signal_detail_has_a_card(cur):
    """
    Test ID        : DB-014
    Module         : Database / Referential integrity
    Precondition   : direct DB access
    Steps          : 1. count serving.signal_detail rows with no matching signal_card id
    Test Data      : none
    Expected Result: zero. A detail with no card is a drawer that can never be opened;
                     the frontend keys details by card id.
    API Endpoint   : GET /api/dataset -> details
    DB Validation  : LEFT JOIN serving.signal_card ON id
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    if not (regclass(cur, "serving.signal_card") and regclass(cur, "serving.signal_detail")):
        pytest.skip("tables not present")
    cur.execute("SELECT count(*) AS n FROM serving.signal_detail d "
                "LEFT JOIN serving.signal_card c ON c.id = d.id WHERE c.id IS NULL")
    n = cur.fetchone()["n"]
    assert n == 0, "%d signal_detail rows have no signal_card" % n


def test_db_015_card_ids_follow_the_pl_document_convention(cur):
    """
    Test ID        : DB-015
    Module         : Database / Key convention
    Precondition   : direct DB access
    Steps          : 1. count pipeline-origin signal_card rows whose id does not start pl_
    Test Data      : none
    Expected Result: zero. serving_fill.py keys a card pl_<document_id>, and
                     app.py::_sig_ids and the Signal Explorer both depend on it. A card
                     that breaks the convention cannot be traced back to its document.
    API Endpoint   : GET /api/ops/signals/{signal_id}
    DB Validation  : SELECT id FROM serving.signal_card WHERE origin='pipeline'
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "serving.signal_card"):
        pytest.skip("serving.signal_card not present")
    cur.execute("SELECT count(*) AS n FROM serving.signal_card "
                "WHERE origin='pipeline' AND id NOT LIKE 'pl\\_%'")
    n = cur.fetchone()["n"]
    assert n == 0, "%d pipeline cards do not use the pl_<document_id> key" % n


def test_db_016_tender_det_is_a_json_array(cur):
    """
    Test ID        : DB-016
    Module         : Database / Data shape (regression)
    Precondition   : direct DB access
    Steps          : 1. for every serving.tender row with a non-null det,
                        assert jsonb_typeof(det) = 'array'
    Test Data      : none
    Expected Result: 'array' everywhere. The UI iterates det; an object or a string
                     there is a render crash on the Tender Pipeline page.
    API Endpoint   : GET /api/dataset -> tenders[].det
    DB Validation  : SELECT jsonb_typeof(det) FROM serving.tender WHERE det IS NOT NULL
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "serving.tender"):
        pytest.skip("serving.tender not present")
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='serving' AND table_name='tender' AND column_name='det'")
    if not cur.fetchone():
        pytest.skip("serving.tender has no det column")
    cur.execute("SELECT id, jsonb_typeof(det) AS t FROM serving.tender "
                "WHERE det IS NOT NULL AND jsonb_typeof(det) <> 'array'")
    bad = [(r["id"], r["t"]) for r in cur.fetchall()]
    assert not bad, "tender.det is not a jsonb array on: %s" % bad[:10]


def test_db_017_competitor_metrics_carry_their_window(cur):
    """
    Test ID        : DB-017
    Module         : Database / Units integrity
    Precondition   : direct DB access
    Steps          : 1. count competitor_metrics rows with a mentions_window but no window_days
    Test Data      : none
    Expected Result: zero. app.py's comment states the reason: window_days travels WITH
                     the counts so the UI cannot label a 7-day figure as 24h. A count
                     without its units is a number the dashboard will describe wrongly.
    API Endpoint   : GET /api/dataset -> competitorMetrics
    DB Validation  : SELECT ... WHERE mentions_window IS NOT NULL AND window_days IS NULL
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "serving.competitor_metrics"):
        pytest.skip("serving.competitor_metrics not present")
    cur.execute("SELECT count(*) AS n FROM serving.competitor_metrics "
                "WHERE mentions_window IS NOT NULL AND window_days IS NULL")
    assert cur.fetchone()["n"] == 0


def test_db_018_ownership_claims_carry_a_source(cur):
    """
    Test ID        : DB-018
    Module         : Database / Provenance integrity
    Precondition   : direct DB access
    Steps          : 1. count serving.competitor_structure rows with a null/blank source_url
    Test Data      : none
    Expected Result: zero. app.py: source_url is NOT optional "for the same reason it is
                     NOT NULL in the table: the Profile graph draws a claim, and a claim
                     on this dashboard shows its source".
    API Endpoint   : GET /api/dataset -> competitorStructure
    DB Validation  : SELECT count(*) WHERE source_url IS NULL OR source_url = ''
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "serving.competitor_structure"):
        pytest.skip("serving.competitor_structure not present")
    cur.execute("SELECT count(*) AS n FROM serving.competitor_structure "
                "WHERE source_url IS NULL OR btrim(source_url) = ''")
    assert cur.fetchone()["n"] == 0


def test_db_019_kssl_own_pages_are_not_in_the_competitive_corpus(cur):
    """
    Test ID        : DB-019
    Module         : Database / Corpus scoping
    Precondition   : direct DB access
    Steps          : 1. count public.documents whose url is a kssl.in / bharatforge host
    Test Data      : the client's own domains
    Expected Result: zero on VPS-B. The client's own pages are deliberately kept off
                     this box; a competitor dashboard that reads the client's own site
                     back to them as intelligence is the failure this filter prevents.
    API Endpoint   : n/a (upstream of every endpoint)
    DB Validation  : SELECT count(*) FROM documents WHERE url ILIKE '%kssl.in%' ...
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "public.documents"):
        pytest.skip("public.documents not present")
    cur.execute("SELECT count(*) AS n FROM documents "
                "WHERE url ILIKE '%//kssl.in%' OR url ILIKE '%.kssl.in%' "
                "   OR url ILIKE '%//bharatforge.com%' OR url ILIKE '%.bharatforge.com%'")
    n = cur.fetchone()["n"]
    assert n == 0, ("%d client-owned pages are in the VPS-B corpus -- the four filters "
                    "that keep them out have a hole" % n)


def test_db_020_the_read_only_test_connection_really_is(db):
    """
    Test ID        : DB-020
    Module         : Database / Test-harness safety
    Precondition   : direct DB access
    Steps          : 1. attempt CREATE TEMP TABLE on the suite's own connection
    Test Data      : none
    Expected Result: it raises. The suite must be incapable of mutating production data
                     -- this is the guard on the guard.
    API Endpoint   : n/a
    DB Validation  : the connection is set readonly=True in conftest
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    import psycopg2
    with pytest.raises(psycopg2.Error):
        with db.cursor() as c:
            c.execute("CREATE TEMP TABLE kssl_e2e_should_not_exist (x int)")
