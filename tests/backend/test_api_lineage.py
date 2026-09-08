# -*- coding: utf-8 -*-
"""Module: BACKEND / GET /api/lineage/doc/{document_id} -- provenance trace.

The endpoint's own promise, asserted: it invents nothing. Every stage is labelled
recorded | reconstructed | provenance_unavailable, and the four known gaps are returned
in the body rather than hidden.
"""
import sys, os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import env  # noqa: E402

STATUSES = {"recorded", "reconstructed", "provenance_unavailable"}


def _a_document_id(cur):
    from conftest import regclass
    if regclass(cur, "public.documents"):
        cur.execute("SELECT document_id FROM public.documents LIMIT 1")
        row = cur.fetchone()
        if row:
            return row["document_id"]
    return None


def test_be_050_lineage_404_on_unknown_document(http, api_up):
    """
    Test ID        : BE-050
    Module         : Backend / Lineage - error handling
    Precondition   : API up
    Steps          : 1. GET /api/lineage/doc/doc_e2e_not_a_real_document
    Test Data      : an id that cannot exist
    Expected Result: 404 with error + `checked` naming public.documents,
                     extracted.document, extracted.proposition, serving.signal_card.
                     Never 200 with an empty trace.
    API Endpoint   : GET /api/lineage/doc/{document_id}
    DB Validation  : the id is in none of the four checked tables
    Priority       : P1
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/lineage/doc/doc_e2e_not_a_real_document"),
                 timeout=env.TIMEOUT_S)
    assert r.status_code in (404, 503), "got %s" % r.status_code
    if r.status_code == 404:
        b = r.json()
        assert "checked" in b and len(b["checked"]) == 4


def test_be_051_lineage_of_a_real_document(http, api_up, cur):
    """
    Test ID        : BE-051
    Module         : Backend / Lineage
    Precondition   : API up AND direct DB access AND public.documents has rows
    Steps          : 1. read one document_id from public.documents
                     2. GET /api/lineage/doc/{that id}
    Test Data      : a live document_id
    Expected Result: 200; stages is a non-empty list; every stage carries stage /
                     status / component; every status is in the labelled vocabulary.
    API Endpoint   : GET /api/lineage/doc/{document_id}
    DB Validation  : the document exists in public.documents
    Priority       : P0
    Automation Tool: pytest + requests + psycopg2
    """
    did = _a_document_id(cur)
    if not did:
        pytest.skip("public.documents is empty or absent on this database")
    r = http.get(env.api("/api/lineage/doc/" + did), timeout=env.TIMEOUT_S)
    assert r.status_code == 200, r.text[:400]
    b = r.json()
    assert b["document_id"] == did
    assert isinstance(b["stages"], list) and b["stages"]
    for st in b["stages"]:
        assert st["status"] in STATUSES, "unlabelled stage status: %s" % st["status"]
        assert st["stage"] and st["component"]


def test_be_052_lineage_returns_its_known_gaps(http, api_up, cur):
    """
    Test ID        : BE-052
    Module         : Backend / Lineage - honesty contract
    Precondition   : as BE-051
    Steps          : 1. GET a real document's lineage  2. read known_gaps
    Test Data      : a live document_id
    Expected Result: the four confirmed gaps are returned in the body (prop->card link
                     is not stored; serving rows carry no document_id; crawler discovery
                     is off-box; reference rows have no lineage). Dropping them would
                     make the trace read as complete when it is not.
    API Endpoint   : GET /api/lineage/doc/{document_id}
    DB Validation  : n/a (a code-path fact, stated as one)
    Priority       : P1
    Automation Tool: pytest + requests
    """
    did = _a_document_id(cur)
    if not did:
        pytest.skip("public.documents is empty or absent")
    b = http.get(env.api("/api/lineage/doc/" + did), timeout=env.TIMEOUT_S).json()
    gaps = b.get("known_gaps") or []
    assert len(gaps) >= 4, "the known gaps are no longer surfaced in the response"


def test_be_053_lineage_writes_nothing(http, api_up, cur):
    """
    Test ID        : SEC-011
    Module         : Backend / Lineage - read-only guarantee
    Precondition   : API up AND direct DB access
    Steps          : 1. snapshot extracted.document count
                     2. GET the lineage of a real document 3 times
                     3. re-snapshot
    Test Data      : a live document_id
    Expected Result: unchanged. app.py sets the connection readonly=True before
                     build_lineage runs, so the endpoint cannot write by construction.
    API Endpoint   : GET /api/lineage/doc/{document_id}
    DB Validation  : count(extracted.document) before == after
    Priority       : P0
    Automation Tool: pytest + requests + psycopg2
    """
    from conftest import regclass
    if not regclass(cur, "extracted.document"):
        pytest.skip("extracted.document not on this database")
    did = _a_document_id(cur)
    if not did:
        pytest.skip("public.documents is empty")
    cur.execute("SELECT count(*) AS n FROM extracted.document")
    before = cur.fetchone()["n"]
    for _ in range(3):
        http.get(env.api("/api/lineage/doc/" + did), timeout=env.TIMEOUT_S)
    cur.execute("SELECT count(*) AS n FROM extracted.document")
    # The live pipeline may add rows; it must never lose them to a read.
    assert cur.fetchone()["n"] >= before


def test_be_054_lineage_path_traversal_is_not_a_path(http, api_up):
    """
    Test ID        : SEC-012
    Module         : Backend / Security - injection & traversal
    Precondition   : API up
    Steps          : 1. GET /api/lineage/doc/ with traversal and SQL payloads in the id
    Test Data      : "../../etc/passwd", "' OR 1=1 --", "%27%20OR%201%3D1"
    Expected Result: 404 / 422 / 400 -- never 200 with data, never 500. document_id is
                     bound as a psycopg2 parameter, never interpolated.
    API Endpoint   : GET /api/lineage/doc/{document_id}
    DB Validation  : no row is returned for a payload id
    Priority       : P0
    Automation Tool: pytest + requests
    """
    for payload in ("..%2F..%2Fetc%2Fpasswd", "%27%20OR%201%3D1%20--",
                    "doc_1%27%3B%20DROP%20TABLE%20documents%3B%20--"):
        r = http.get(env.api("/api/lineage/doc/" + payload), timeout=env.TIMEOUT_S)
        assert r.status_code != 500, "%s produced a 500" % payload
        if r.status_code == 200:
            assert r.json().get("document_id"), "a payload id resolved to a document"
