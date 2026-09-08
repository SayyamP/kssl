# -*- coding: utf-8 -*-
"""Module: BACKEND / article bench (/api/bench*) -- the only WRITE path on the HTTP surface.

POST /api/bench/submit INSERTs into metrics.adhoc_job, so every write case here is
gated behind KSSL_TEST_ALLOW_WRITES=1. The validation cases below send NO valid job and
are therefore always safe to run: app.py rejects them before it opens a connection.
"""
import sys, os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import env  # noqa: E402


def test_be_060_bench_page_is_html_or_a_named_failure(http, api_up):
    """
    Test ID        : BE-060
    Module         : Backend / Bench
    Precondition   : API up
    Steps          : 1. GET /api/bench
    Test Data      : none
    Expected Result: 200 text/html, OR 500 with {"error": "bench/dashboard.html is not
                     in the image"} -- a named, actionable failure, not a stack trace.
    API Endpoint   : GET /api/bench
    DB Validation  : n/a
    Priority       : P2
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/bench"), timeout=env.TIMEOUT_S)
    assert r.status_code in (200, 500)
    if r.status_code == 500:
        assert "dashboard.html" in r.json().get("error", "")
    else:
        assert "text/html" in r.headers.get("content-type", "")


@pytest.mark.parametrize("body,why", [
    ({}, "neither url nor text"),
    ({"url": "", "text": ""}, "both blank"),
    ({"url": "   "}, "whitespace-only url"),
    ({"url": "ftp://example.com/a"}, "scheme is not http(s)"),
    ({"url": "javascript:alert(1)"}, "javascript: scheme"),
    ({"url": "file:///etc/passwd"}, "file: scheme"),
])
def test_be_061_bench_submit_rejects_bad_input(http, api_up, body, why):
    """
    Test ID        : BE-061
    Module         : Backend / Bench - input validation
    Precondition   : API up
    Steps          : 1. POST /api/bench/submit with each invalid body
    Test Data      : {}, blank url+text, whitespace url, ftp://, javascript:, file://
    Expected Result: 400 with an `error` string, and NO row inserted into
                     metrics.adhoc_job -- app.py validates before it connects.
    API Endpoint   : POST /api/bench/submit
    DB Validation  : count(metrics.adhoc_job) unchanged (see BE-062)
    Priority       : P0
    Automation Tool: pytest + requests
    """
    r = http.post(env.api("/api/bench/submit"), json=body, timeout=env.TIMEOUT_S)
    assert r.status_code == 400, "%s (%s) -> %s" % (body, why, r.status_code)
    assert "error" in r.json()


def test_be_062_bench_rejection_writes_no_row(http, api_up, cur):
    """
    Test ID        : BE-062
    Module         : Backend / Bench - validation <-> database
    Precondition   : API up AND direct DB access AND metrics.adhoc_job present
    Steps          : 1. count metrics.adhoc_job
                     2. POST an invalid submit (no url, no text)
                     3. recount
    Test Data      : {}
    Expected Result: unchanged -- a rejected request must not reach the table.
    API Endpoint   : POST /api/bench/submit
    DB Validation  : SELECT count(*) FROM metrics.adhoc_job
    Priority       : P0
    Automation Tool: pytest + requests + psycopg2
    """
    from conftest import regclass
    if not regclass(cur, "metrics.adhoc_job"):
        pytest.skip("metrics.adhoc_job not on this database")
    cur.execute("SELECT count(*) AS n FROM metrics.adhoc_job")
    before = cur.fetchone()["n"]
    http.post(env.api("/api/bench/submit"), json={}, timeout=env.TIMEOUT_S)
    cur.execute("SELECT count(*) AS n FROM metrics.adhoc_job")
    assert cur.fetchone()["n"] == before


def test_be_063_bench_runs_limit_is_capped(http, api_up):
    """
    Test ID        : BE-063
    Module         : Backend / Bench - pagination guard
    Precondition   : API up
    Steps          : 1. GET /api/bench/runs?limit=99999
    Test Data      : limit=99999
    Expected Result: 200 and at most 60 rows -- app.py caps with min(int(limit), 60).
    API Endpoint   : GET /api/bench/runs?limit=
    DB Validation  : metrics.adhoc_summary
    Priority       : P1
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/bench/runs"), params={"limit": 99999}, timeout=env.TIMEOUT_S)
    if r.status_code != 200:
        pytest.skip("bench tables not on this database (%s)" % r.status_code)
    assert len(r.json()["runs"]) <= 60


def test_be_064_bench_run_404_on_unknown_id(http, api_up):
    """
    Test ID        : BE-064
    Module         : Backend / Bench - error handling
    Precondition   : API up
    Steps          : 1. GET /api/bench/run/nosuchrunid00
    Test Data      : run_id = "nosuchrunid00"
    Expected Result: 404 {"error": "no such run"}
    API Endpoint   : GET /api/bench/run/{run_id}
    DB Validation  : metrics.adhoc_summary has no such run_id
    Priority       : P2
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/bench/run/nosuchrunid00"), timeout=env.TIMEOUT_S)
    if r.status_code == 500:
        pytest.skip("bench tables not on this database")
    assert r.status_code == 404
    assert r.json()["error"] == "no such run"


@pytest.mark.skipif(not env.ALLOW_WRITES, reason="write test; set KSSL_TEST_ALLOW_WRITES=1")
def test_be_065_bench_submit_queues_a_job(http, api_up, cur):
    """
    Test ID        : BE-065
    Module         : Backend / Bench - the write path (Frontend -> API -> DB)
    Precondition   : API up, DB access, KSSL_TEST_ALLOW_WRITES=1
    Steps          : 1. POST /api/bench/submit {"text": "<marker>", "title": "e2e"}
                     2. read run_id from the response
                     3. SELECT the row from metrics.adhoc_job by run_id
                     4. GET /api/bench/run/{run_id}
    Test Data      : text = "KSSL E2E suite probe -- not a real article."
    Expected Result: 200 {"run_id": <12 hex>, "status": "queued"}; a matching row
                     exists in metrics.adhoc_job with that raw_text; the run endpoint
                     answers 200 for it. Full chain: API -> DB -> API.
    API Endpoint   : POST /api/bench/submit ; GET /api/bench/run/{run_id}
    DB Validation  : SELECT run_id, raw_text FROM metrics.adhoc_job WHERE run_id = %s
    Priority       : P1
    Automation Tool: pytest + requests + psycopg2
    """
    from conftest import regclass
    if not regclass(cur, "metrics.adhoc_job"):
        pytest.skip("metrics.adhoc_job not on this database")
    marker = "KSSL E2E suite probe -- not a real article."
    r = http.post(env.api("/api/bench/submit"),
                  json={"text": marker, "title": "e2e"}, timeout=env.TIMEOUT_S)
    assert r.status_code == 200, r.text[:300]
    b = r.json()
    assert b["status"] == "queued" and len(b["run_id"]) == 12
    cur.execute("SELECT run_id, raw_text FROM metrics.adhoc_job WHERE run_id = %s",
                (b["run_id"],))
    row = cur.fetchone()
    assert row is not None, "submit returned a run_id with no row behind it"
    assert row["raw_text"] == marker
    assert http.get(env.api("/api/bench/run/" + b["run_id"]),
                    timeout=env.TIMEOUT_S).status_code == 200
