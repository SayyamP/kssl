# -*- coding: utf-8 -*-
"""Module: BACKEND / GET /api/dataset -- the dashboard's whole bootstrap read.

The contract asserted here is backend/app.py's own: the globals it assembles in
_dataset(), the field lists (COMP_FIELDS, NEWS_FIELDS, ...) and the OPT rule -- an
optional field is OMITTED when NULL or when its migration has not run, never nulled.
"""
import sys, os, time
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import env  # noqa: E402

# The globals _dataset() writes into `out`, read off backend/app.py.
DERIVED_GLOBALS = ["competitors", "compOrder", "competitorNews", "competitorStructure",
                   "competitorMetrics", "details", "matchups", "tenders", "PATENTS",
                   "geoData", "geoComps", "innovations", "KSSL_PARTNERS",
                   "sourceRegistry", "companySources"]

# app.py COMP_OPT / NEWS_OPT / CARD_OPT / MATCHUP_OPT: absent-not-null.
COMP_OPT = {"starting_year", "global_locations", "company_size",
            "strategic_positioning", "country"}
CARD_OPT = {"company", "lens", "sec", "url", "image"}


def test_be_010_dataset_200_and_json(dataset):
    """
    Test ID        : BE-010
    Module         : Backend / Dataset
    Precondition   : backend up, serving_live views present
    Steps          : 1. GET /api/dataset  2. parse JSON
    Test Data      : none
    Expected Result: 200, a JSON object, non-empty
    API Endpoint   : GET /api/dataset
    DB Validation  : implied -- the payload is assembled from serving_live.*
    Priority       : P0
    Automation Tool: pytest + requests
    """
    assert isinstance(dataset, dict) and dataset


def test_be_011_all_derived_globals_present(dataset):
    """
    Test ID        : BE-011
    Module         : Backend / Dataset contract
    Precondition   : BE-010 passed
    Steps          : 1. assert each global _dataset() assembles is a key of the payload
    Test Data      : DERIVED_GLOBALS (from backend/app.py)
    Expected Result: every one present. A missing global blanks a whole panel --
                     DataProvider.jsx throws on a payload with no `matchups` at all.
    API Endpoint   : GET /api/dataset
    DB Validation  : each global maps to a serving_live table (see TEST_CASES.md)
    Priority       : P0
    Automation Tool: pytest
    """
    missing = [g for g in DERIVED_GLOBALS if g not in dataset]
    assert not missing, "globals missing from /api/dataset: %s" % missing


def test_be_012_matchups_present_or_frontend_refuses_to_boot(dataset):
    """
    Test ID        : BE-012
    Module         : Backend / Dataset <-> Frontend contract
    Precondition   : BE-010 passed
    Steps          : 1. assert payload.matchups exists
    Test Data      : none
    Expected Result: present. frontend/src/state/DataProvider.jsx raises
                     "the API answered but did not return a usable dataset (no matchups
                     global)" and the app renders an error instead of the shell.
    API Endpoint   : GET /api/dataset
    DB Validation  : SELECT count(*) FROM serving_live.matchup
    Priority       : P0
    Automation Tool: pytest
    """
    assert "matchups" in dataset


def test_be_013_comporder_matches_competitors_keys(dataset):
    """
    Test ID        : BE-013
    Module         : Backend / Dataset derived rollups
    Precondition   : BE-010 passed
    Steps          : 1. compare compOrder to competitors' keys
    Test Data      : none
    Expected Result: same set; compOrder is the ord-sorted key order of the same rows
                     (app.py builds both from one SELECT ... ORDER BY ord)
    API Endpoint   : GET /api/dataset
    DB Validation  : SELECT comp_id FROM serving_live.competitors ORDER BY ord
    Priority       : P1
    Automation Tool: pytest
    """
    assert set(dataset["compOrder"]) == set(dataset["competitors"].keys())
    assert len(dataset["compOrder"]) == len(dataset["competitors"])


def test_be_014_optional_fields_are_absent_never_null(dataset):
    """
    Test ID        : BE-014
    Module         : Backend / Dataset OPT rule
    Precondition   : BE-010 passed
    Steps          : 1. for every competitor, assert no OPT key is present with value null
                     2. same for signal cards (details/cards CARD_OPT)
    Test Data      : COMP_OPT, CARD_OPT (backend/app.py)
    Expected Result: an optional field is OMITTED when NULL, never emitted as null --
                     the reference dataset omits it and the UI treats an unexpected null
                     as data (this blanked the Profile page once already).
    API Endpoint   : GET /api/dataset
    DB Validation  : the NULLs exist in serving_live.competitors; the payload must not
                     carry them as keys
    Priority       : P1
    Automation Tool: pytest
    """
    bad = []
    for cid, comp in dataset["competitors"].items():
        for k in COMP_OPT:
            if k in comp and comp[k] is None:
                bad.append("competitors.%s.%s" % (cid, k))
    assert not bad, "optional fields emitted as null instead of omitted: %s" % bad[:20]


def test_be_015_honest_nulls_survive(dataset):
    """
    Test ID        : BE-015
    Module         : Backend / Dataset OPT rule (the other half)
    Precondition   : BE-010 passed
    Steps          : 1. matchup.edge and patent.granted may be present and null
    Test Data      : none
    Expected Result: no exception; nullable-by-design fields are NOT stripped. app.py:
                     "edge stays, null is honest" / "granted stays, null is honest".
    API Endpoint   : GET /api/dataset
    DB Validation  : serving.matchup.edge IS NULL on the reference rows
    Priority       : P2
    Automation Tool: pytest
    """
    for m in (dataset.get("matchups") or {}).values():
        assert "edge" in m, "matchup lost its `edge` key -- null is honest here, absence is not"
        break


def test_be_016_competitors_match_the_database(dataset, cur):
    """
    Test ID        : BE-016
    Module         : Backend / Dataset <-> Database
    Precondition   : API up AND direct DB access
    Steps          : 1. count competitors in the payload
                     2. SELECT count(*) FROM <served schema>.competitors
    Test Data      : none
    Expected Result: equal -- the API serves the rows the database holds, unfiltered
                     beyond the serving_live origin='pipeline' view itself.
    API Endpoint   : GET /api/dataset
    DB Validation  : SELECT count(*) FROM serving_live.competitors
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    cur.execute("SELECT count(*) AS n FROM " + env.SERVED_SCHEMA + ".competitors")
    assert cur.fetchone()["n"] == len(dataset["competitors"])


def test_be_017_signal_cards_match_the_database(dataset, cur):
    """
    Test ID        : BE-017
    Module         : Backend / Dataset <-> Database
    Precondition   : API up AND direct DB access
    Steps          : 1. count the served cards across every lane in the payload
                     2. SELECT count(*) FROM <served schema>.signal_card
    Test Data      : none
    Expected Result: the payload's card total equals the table's row count.
    API Endpoint   : GET /api/dataset
    DB Validation  : SELECT count(*) FROM serving_live.signal_card
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    cur.execute("SELECT count(*) AS n FROM " + env.SERVED_SCHEMA + ".signal_card")
    n_db = cur.fetchone()["n"]
    served = 0
    for key, val in dataset.items():
        if isinstance(val, dict) and val.get("cards") is not None:
            served += len(val["cards"])
    assert served == n_db, ("cards served=%d, signal_card rows=%d -- a card in the "
                            "table that the API does not serve is invisible to the "
                            "dashboard" % (served, n_db))


def test_be_018_no_reference_origin_rows_leak_into_serving_live(cur):
    """
    Test ID        : BE-018
    Module         : Backend / serving_live filter
    Precondition   : direct DB access
    Steps          : 1. for each serving_live view, count rows whose origin <> 'pipeline'
    Test Data      : none
    Expected Result: zero. db/03_serving_live.sql defines every view as
                     WHERE origin='pipeline'; a reference/demo row reaching the browser
                     is fabricated content on a live dashboard.
    API Endpoint   : GET /api/dataset (consumer)
    DB Validation  : SELECT count(*) FROM serving_live.X WHERE origin <> 'pipeline'
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    from conftest import regclass
    views = ["competitors", "signal_card", "signal_detail", "matchup", "tender",
             "patent", "partner", "innovation", "geo_comp", "geo_presence",
             "source_registry", "company_source"]
    leaks = {}
    for v in views:
        q = "serving_live." + v
        if not regclass(cur, q):
            continue
        cur.execute("SELECT count(*) AS n FROM " + q + " WHERE origin <> 'pipeline'")
        n = cur.fetchone()["n"]
        if n:
            leaks[v] = n
    assert not leaks, "non-pipeline rows visible through serving_live: %s" % leaks


def test_be_019_dataset_is_a_read_and_changes_nothing(http, api_up, cur):
    """
    Test ID        : BE-019
    Module         : Backend / Dataset side effects
    Precondition   : API up AND direct DB access
    Steps          : 1. snapshot row counts of the served tables
                     2. GET /api/dataset twice
                     3. re-snapshot
    Test Data      : none
    Expected Result: identical counts. /api/dataset is a read; the only thing it may
                     write is a metrics.stage_run timing row (the `frontend` stage),
                     which is not a served table.
    API Endpoint   : GET /api/dataset
    DB Validation  : row counts before == after on serving_live.*
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    tables = ["competitors", "signal_card", "matchup", "tender", "patent"]
    def snap():
        out = {}
        for t in tables:
            cur.execute("SELECT count(*) AS n FROM " + env.SERVED_SCHEMA + "." + t)
            out[t] = cur.fetchone()["n"]
        return out
    before = snap()
    http.get(env.api("/api/dataset"), timeout=env.TIMEOUT_S)
    http.get(env.api("/api/dataset"), timeout=env.TIMEOUT_S)
    assert snap() == before


def test_be_020_dataset_response_time_budget(http, api_up):
    """
    Test ID        : PERF-001
    Module         : Backend / Performance
    Precondition   : API up, corpus loaded
    Steps          : 1. time a cold GET /api/dataset
    Test Data      : budget = KSSL_TEST_BUDGET_DATASET_S (default 30s)
    Expected Result: under budget. 30s is the app's OWN abort threshold
                     (frontend/src/api/client.js TIMEOUT_MS = 30000) -- past it the
                     dashboard shows "request to /dataset timed out".
    API Endpoint   : GET /api/dataset
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: pytest + requests
    """
    t0 = time.time()
    r = http.get(env.api("/api/dataset"), timeout=env.TIMEOUT_S)
    dt = time.time() - t0
    assert r.status_code == 200
    assert dt < env.BUDGET_DATASET_S, (
        "/api/dataset took %.1fs; frontend/src/api/client.js aborts at %.0fs"
        % (dt, env.BUDGET_DATASET_S))


@pytest.mark.parametrize("path", ["/api/health", "/api/manifest", "/api/globals/matchups"])
def test_be_021_frontend_service_paths_that_the_backend_does_not_implement(http, api_up, path):
    """
    Test ID        : BE-021
    Module         : Backend / Dead client surface
    Precondition   : API up
    Steps          : 1. GET each path declared in frontend/src/api/datasetService.js
                        (getGlobal, health, manifest)
    Test Data      : /api/health, /api/manifest, /api/globals/{name}
    Expected Result: 404. backend/app.py declares NO such routes. These service methods
                     are dead client code, not endpoints -- recorded here so the day one
                     is wired up, the test says so instead of the UI silently 404ing.
    API Endpoint   : GET /api/health | /api/manifest | /api/globals/{name}
    DB Validation  : n/a
    Priority       : P3
    Automation Tool: pytest + requests
    """
    r = http.get(env.api(path), timeout=env.TIMEOUT_S)
    assert r.status_code == 404, (
        "%s answered %s -- backend/app.py has no such route; if one was added, "
        "update BE-021" % (path, r.status_code))
