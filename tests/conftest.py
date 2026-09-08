# -*- coding: utf-8 -*-
"""Shared fixtures. Read-only by default -- see tests/README.md.

The suite tests a RUNNING deployment. Nothing here starts, seeds or migrates anything:
a test that provisions its own fixtures would be testing the fixture, not the system
that serves the dashboard.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import env  # noqa: E402

try:
    import requests
except ImportError:                                  # pragma: no cover
    requests = None

try:
    import psycopg2
    import psycopg2.extras
except ImportError:                                  # pragma: no cover
    psycopg2 = None


@pytest.fixture(scope="session")
def http():
    """A session that carries the basic-auth credential when one is configured."""
    if requests is None:
        pytest.skip("requests is not installed (pip install -r tests/requirements.txt)")
    s = requests.Session()
    if env.AUTH:
        s.auth = env.AUTH
    s.headers.update({"Accept": "application/json",
                      "User-Agent": "kssl-e2e-suite/1.0"})
    return s


@pytest.fixture(scope="session")
def api_up(http):
    """Skip the whole API module rather than fail 40 tests on one unreachable host."""
    try:
        r = http.get(env.api("/api/dataset"), timeout=env.TIMEOUT_S, stream=True)
        r.close()
    except Exception as exc:                          # noqa: BLE001
        pytest.skip("API not reachable at %s (%s)" % (env.API_URL, exc))
    return True


@pytest.fixture(scope="session")
def db():
    """A READ-ONLY connection. Set read-only at the session level so a test that tries
    to write fails on the connection, not on the data."""
    if psycopg2 is None:
        pytest.skip("psycopg2 is not installed (pip install -r tests/requirements.txt)")
    try:
        conn = psycopg2.connect(env.DSN, connect_timeout=8)
    except Exception as exc:                          # noqa: BLE001
        pytest.skip("database not reachable (%s)" % exc)
    conn.set_session(readonly=True, autocommit=True)
    yield conn
    conn.close()


@pytest.fixture()
def cur(db):
    c = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    yield c
    c.close()


@pytest.fixture(scope="session")
def dataset(http, api_up):
    """GET /api/dataset once. Every dataset-shape test reads this one payload: fetching
    the whole corpus per test would make the suite the load test."""
    r = http.get(env.api("/api/dataset"), timeout=env.TIMEOUT_S)
    assert r.status_code == 200, "GET /api/dataset -> %s %s" % (r.status_code, r.text[:400])
    return r.json()


def regclass(cur, qualified):
    """Does this table/view exist? Same guard backend/app.py::_regclass uses, so a test
    reports 'not on this database' the way the application does."""
    cur.execute("SELECT to_regclass(%s) AS t", (qualified,))
    return cur.fetchone()["t"] is not None
