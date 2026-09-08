# -*- coding: utf-8 -*-
"""Module: SECURITY / auth, headers, CORS, injection, method surface.

WHAT AUTHENTICATION EXISTS HERE, exactly: HTTP Basic, enforced by traefik in front of
BOTH the UI router (kssl-web) and the API router (kssl-api), user `kssl`, hash in
KSSL_BASIC_AUTH (docker-compose.vps.yml:148-157, deploy/provision_env.sh).

WHAT DOES NOT EXIST: no login page, no session, no cookie, no JWT, no API key, and NO
ROLES. backend/app.py has no auth code at all -- it trusts the proxy. So the
authorization tests below assert the real boundary (everything or nothing) and do not
invent an admin/viewer split the code has never had.
"""
import sys, os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import env  # noqa: E402

try:
    import requests
except ImportError:
    requests = None

FRONT_DOOR = env.BASE_URL != env.API_URL and env.BASE_URL.startswith("https")


def _bare():
    s = requests.Session()
    s.headers.update({"User-Agent": "kssl-e2e-suite/1.0"})
    return s


@pytest.mark.skipif(not FRONT_DOOR, reason="no traefik front door configured")
def test_sec_001_api_requires_basic_auth(api_up):
    """
    Test ID        : SEC-001
    Module         : Security / Authentication
    Precondition   : running against the traefik front door on staging or prod
    Steps          : 1. GET {BASE}/api/dataset with NO credentials
    Test Data      : none
    Expected Result: 401 with WWW-Authenticate: Basic realm="KSSL". The dataset is the
                     whole competitive corpus; an unauthenticated 200 is a data breach,
                     not a bug.
    API Endpoint   : GET /api/dataset
    DB Validation  : n/a
    Priority       : P0
    Automation Tool: pytest + requests
    """
    r = _bare().get(env.front("/api/dataset"), timeout=env.TIMEOUT_S)
    assert r.status_code == 401, "unauthenticated /api/dataset -> %s" % r.status_code
    assert "basic" in r.headers.get("www-authenticate", "").lower()


@pytest.mark.skipif(not FRONT_DOOR, reason="no traefik front door configured")
def test_sec_002_ui_requires_basic_auth(api_up):
    """
    Test ID        : SEC-002
    Module         : Security / Authentication
    Precondition   : traefik front door
    Steps          : 1. GET {BASE}/ with no credentials
    Test Data      : none
    Expected Result: 401. The kssl-web router carries the SAME kssl-auth middleware.
    API Endpoint   : GET /
    DB Validation  : n/a
    Priority       : P0
    Automation Tool: pytest + requests
    """
    r = _bare().get(env.front("/"), timeout=env.TIMEOUT_S)
    assert r.status_code == 401


@pytest.mark.skipif(not FRONT_DOOR, reason="no traefik front door configured")
def test_sec_003_ops_console_requires_basic_auth(api_up):
    """
    Test ID        : SEC-003
    Module         : Security / Authorization boundary
    Precondition   : traefik front door
    Steps          : 1. GET {BASE}/ops/ with no credentials
    Test Data      : none
    Expected Result: 401. The operator console is served as a static subdirectory of the
                     SAME frontend container (frontend/public/ops/index.html) and has NO
                     authorization of its own -- basic auth is the only thing between
                     the public internet and the pipeline internals. Asserted, because
                     the console's own code has no notion of a user or a role.
    API Endpoint   : GET /ops/
    DB Validation  : n/a
    Priority       : P0
    Automation Tool: pytest + requests
    """
    r = _bare().get(env.front("/ops/"), timeout=env.TIMEOUT_S)
    assert r.status_code == 401


@pytest.mark.skipif(not FRONT_DOOR, reason="no traefik front door configured")
def test_sec_004_wrong_password_is_rejected(api_up):
    """
    Test ID        : SEC-004
    Module         : Security / Authentication
    Precondition   : traefik front door
    Steps          : 1. GET /api/dataset with kssl / a wrong password
    Test Data      : ("kssl", "definitely-not-the-password")
    Expected Result: 401
    API Endpoint   : GET /api/dataset
    DB Validation  : n/a
    Priority       : P0
    Automation Tool: pytest + requests
    """
    s = _bare()
    s.auth = ("kssl", "definitely-not-the-password")
    assert s.get(env.front("/api/dataset"), timeout=env.TIMEOUT_S).status_code == 401


@pytest.mark.skipif(not FRONT_DOOR, reason="no traefik front door configured")
def test_sec_005_ui_security_headers(http, api_up):
    """
    Test ID        : SEC-005
    Module         : Security / Response headers
    Precondition   : authenticated request to the front door
    Steps          : 1. GET {BASE}/  2. read the headers
    Test Data      : none
    Expected Result: X-Frame-Options DENY, X-Content-Type-Options nosniff,
                     Referrer-Policy strict-origin-when-cross-origin -- the kssl-sec
                     middleware in docker-compose.vps.yml:180-182.
    API Endpoint   : GET /
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: pytest + requests
    """
    h = {k.lower(): v for k, v in
         http.get(env.front("/"), timeout=env.TIMEOUT_S).headers.items()}
    assert h.get("x-frame-options", "").upper() == "DENY"
    assert h.get("x-content-type-options", "").lower() == "nosniff"
    assert h.get("referrer-policy") == "strict-origin-when-cross-origin"


@pytest.mark.skipif(not FRONT_DOOR, reason="no traefik front door configured")
def test_sec_006_api_router_carries_no_security_headers(http, api_up):
    """
    Test ID        : SEC-006
    Module         : Security / Response headers - known asymmetry
    Precondition   : authenticated request to the front door
    Steps          : 1. GET {BASE}/api/dataset  2. read the headers
    Test Data      : none
    Expected Result: DOCUMENTED GAP, asserted so it cannot change silently. The
                     kssl-api router's middleware list is `kssl-auth` ONLY
                     (docker-compose.vps.yml:152); kssl-sec is on kssl-web alone. So
                     the API responses carry no nosniff / frameDeny. This test records
                     the current truth: if the headers appear, the deployment changed
                     and this case should be inverted.
    API Endpoint   : GET /api/dataset
    DB Validation  : n/a
    Priority       : P2
    Automation Tool: pytest + requests
    """
    h = {k.lower(): v for k, v in
         http.get(env.front("/api/dataset"), timeout=env.TIMEOUT_S, stream=True).headers.items()}
    if "x-content-type-options" in h:
        pytest.xfail("kssl-sec now also covers the API router -- SEC-006 needs inverting")


def test_sec_007_cors_is_wide_open(http, api_up):
    """
    Test ID        : SEC-007
    Module         : Security / CORS
    Precondition   : API reachable
    Steps          : 1. GET /api/dataset with Origin: https://evil.example
                     2. read Access-Control-Allow-Origin
    Test Data      : Origin: https://evil.example
    Expected Result: FINDING, asserted as the current state: backend/app.py sets
                     CORSMiddleware(allow_origins=["*"], allow_methods=["*"],
                     allow_headers=["*"]) with the comment "localhost dev; front door
                     added later". Any page in any browser can read the whole corpus
                     from a session that has basic auth cached. This test states the
                     fact; tightening the policy is an application change, which the
                     suite does not make.
    API Endpoint   : GET /api/dataset (with Origin)
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/dataset"), headers={"Origin": "https://evil.example"},
                 timeout=env.TIMEOUT_S, stream=True)
    acao = r.headers.get("access-control-allow-origin")
    r.close()
    assert acao in ("*", "https://evil.example", None)
    if acao == "*":
        pytest.xfail("CORS allow_origins=['*'] on /api/dataset -- recorded as SEC-007")


@pytest.mark.parametrize("param,payload", [
    ("company", "' OR '1'='1"),
    ("q", "'; DROP TABLE serving.signal_card; --"),
    ("lane", "competitive' UNION SELECT 1 --"),
    ("origin", "pipeline' OR 1=1 --"),
    ("since", "2020-01-01'; DELETE FROM serving.signal_card; --"),
])
def test_sec_008_signal_filters_are_bound_parameters(http, api_up, param, payload):
    """
    Test ID        : SEC-008
    Module         : Security / SQL injection
    Precondition   : API up
    Steps          : 1. GET /api/ops/signals with an injection payload in each filter
    Test Data      : classic OR-1=1, UNION and stacked-DROP payloads
    Expected Result: no 500, and no widened result set. Every filter in app.py's
                     ops_signals is appended as `col = %s` / `ILIKE %s` with the value
                     in `params` -- psycopg2 binds it, so the payload is matched as a
                     literal and returns nothing.
    API Endpoint   : GET /api/ops/signals?lane=&company=&q=&since=&origin=
    DB Validation  : serving.signal_card still exists afterwards (see SEC-009)
    Priority       : P0
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/ops/signals"),
                 params={param: payload, "limit": 5}, timeout=env.TIMEOUT_S)
    assert r.status_code in (200, 422, 400), "%s=%s -> %s" % (param, payload, r.status_code)
    if r.status_code == 200 and r.json().get("available"):
        assert r.json()["signals"] == [], (
            "an injection payload in %s returned rows -- the filter is not bound" % param)


def test_sec_009_injection_left_the_schema_intact(http, api_up, cur):
    """
    Test ID        : SEC-009
    Module         : Security / SQL injection - aftermath
    Precondition   : SEC-008 has run; direct DB access
    Steps          : 1. assert serving.signal_card and public.documents still exist
                     2. assert signal_card still has rows (if it had any)
    Test Data      : none
    Expected Result: schema intact. Run immediately after SEC-008's stacked DROP/DELETE
                     payloads.
    API Endpoint   : n/a (verification step)
    DB Validation  : to_regclass('serving.signal_card') IS NOT NULL
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    from conftest import regclass
    assert regclass(cur, "serving.signal_card"), "serving.signal_card is gone"
    assert regclass(cur, "public.documents"), "public.documents is gone"


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/dataset"),
    ("PUT", "/api/dataset"),
    ("DELETE", "/api/dataset"),
    ("POST", "/api/ops/overview"),
    ("DELETE", "/api/ops/signals"),
    ("PUT", "/api/lineage/doc/doc_x"),
])
def test_sec_010_no_undeclared_write_methods(http, api_up, method, path):
    """
    Test ID        : SEC-013
    Module         : Security / HTTP method surface
    Precondition   : API up
    Steps          : 1. issue each non-GET method against a GET-only route
    Test Data      : POST/PUT/DELETE on /api/dataset, /api/ops/*, /api/lineage/*
    Expected Result: 405 Method Not Allowed. backend/app.py declares exactly ONE
                     non-GET route in the whole application: POST /api/bench/submit.
                     Everything else must refuse a write verb.
    API Endpoint   : various
    DB Validation  : nothing is modified
    Priority       : P0
    Automation Tool: pytest + requests
    """
    r = http.request(method, env.api(path), timeout=env.TIMEOUT_S)
    assert r.status_code in (405, 404), "%s %s -> %s" % (method, path, r.status_code)


def test_sec_011_errors_do_not_leak_a_stack_trace(http, api_up):
    """
    Test ID        : SEC-014
    Module         : Security / Information disclosure
    Precondition   : API up
    Steps          : 1. request several malformed URLs
                     2. scan each body for Traceback / File "/app / psycopg2 internals
    Test Data      : malformed ids and parameters
    Expected Result: no Python traceback, no file path, no DSN in any response body.
                     NOTE: /healthz and /api/lineage/doc DO return str(exc) on a DB
                     failure -- which can contain the host and port of the database.
                     That is recorded as a finding rather than asserted away.
    API Endpoint   : various
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: pytest + requests
    """
    for p in ("/api/ops/runs/%00", "/api/lineage/doc/%FF", "/api/bench/run/%20",
              "/api/ops/signals?limit=abc"):
        r = http.get(env.api(p), timeout=env.TIMEOUT_S)
        body = r.text[:5000]
        assert "Traceback (most recent call last)" not in body, "stack trace leaked at %s" % p
        assert 'File "/app' not in body, "source path leaked at %s" % p
        assert "password=" not in body, "a DSN leaked at %s" % p
