# -*- coding: utf-8 -*-
"""Module: BACKEND / Health & reachability.  Tool: pytest + requests.

Every case below carries the full record required by the test protocol. The endpoint
paths are exactly the ones declared in backend/app.py.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import env  # noqa: E402
from conftest import regclass  # noqa: E402,F401


def test_be_001_healthz_reports_db(http, api_up):
    """
    Test ID        : BE-001
    Module         : Backend / Health
    Precondition   : backend container up; postgres reachable on KSSL_DSN
    Steps          : 1. GET {API}/healthz
                     2. Read ok / db / ui_config_keys / schema
    Test Data      : none
    Expected Result: 200 with ok=true, db=true, schema in {serving, serving_live},
                     ui_config_keys > 0. 503 with ok=false only when the DB is down.
    API Endpoint   : GET /healthz            (NOT under /api -- see BE-002)
    DB Validation  : ui_config_keys equals SELECT count(*) FROM <schema>.ui_config
    Priority       : P0
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/healthz"), timeout=env.TIMEOUT_S)
    assert r.status_code in (200, 503), r.text[:300]
    body = r.json()
    if r.status_code == 503:
        assert body["ok"] is False and body["db"] is False
        return
    assert body["ok"] is True and body["db"] is True
    assert body["schema"] in ("serving", "serving_live")
    assert isinstance(body["ui_config_keys"], int) and body["ui_config_keys"] > 0


def test_be_002_healthz_is_not_reachable_through_the_front_door(http):
    """
    Test ID        : BE-002
    Module         : Backend / Health, routing
    Precondition   : running against the traefik front door (KSSL_TEST_BASE_URL is https)
    Steps          : 1. GET {BASE}/healthz through the front door
    Test Data      : none
    Expected Result: NOT 200 JSON from the API. traefik router `kssl-api` matches
                     PathPrefix(`/api`) only (docker-compose.vps.yml:148), so /healthz
                     falls through to the SPA router `kssl-web` and returns index.html.
                     This is a documented routing consequence, asserted so a future
                     change to it is visible.
    API Endpoint   : GET /healthz (front door)
    DB Validation  : n/a
    Priority       : P2
    Automation Tool: pytest + requests
    """
    if env.BASE_URL == env.API_URL:
        import pytest
        pytest.skip("BASE_URL == API_URL: no front door in front of the API here")
    r = http.get(env.front("/healthz"), timeout=env.TIMEOUT_S)
    ctype = r.headers.get("content-type", "")
    assert not (r.status_code == 200 and "application/json" in ctype), (
        "/healthz answered JSON through the front door -- the traefik /api PathPrefix "
        "rule has changed; update BE-002 and the deployment notes")


def test_be_003_healthz_ui_config_count_matches_db(http, api_up, cur):
    """
    Test ID        : BE-003
    Module         : Backend / Health <-> Database
    Precondition   : API up AND direct DB access (tunnel to KSSL_DB_PORT)
    Steps          : 1. GET /healthz  2. SELECT count(*) FROM <schema>.ui_config
    Test Data      : none
    Expected Result: the two counts are equal -- the health endpoint reports the
                     database it actually serves from, not a cached number.
    API Endpoint   : GET /healthz
    DB Validation  : SELECT count(*) FROM serving_live.ui_config
    Priority       : P1
    Automation Tool: pytest + requests + psycopg2
    """
    r = http.get(env.api("/healthz"), timeout=env.TIMEOUT_S)
    if r.status_code != 200:
        import pytest
        pytest.skip("healthz not ok (%s)" % r.status_code)
    schema = r.json()["schema"]
    cur.execute("SELECT count(*) AS n FROM " + schema + ".ui_config")
    assert cur.fetchone()["n"] == r.json()["ui_config_keys"]
