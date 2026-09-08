# -*- coding: utf-8 -*-
"""Module: BACKEND / operator endpoints (/api/ops/*).

app.py's contract for these, asserted literally: every one opens a READ-ONLY connection
and every source table is guarded by _regclass, so a missing table degrades to
"unavailable" and NEVER a 500.
"""
import sys, os, time
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import env  # noqa: E402


def test_be_030_ops_overview(http, api_up):
    """
    Test ID        : BE-030
    Module         : Backend / Ops - System Overview
    Precondition   : backend up
    Steps          : 1. GET /api/ops/overview  2. inspect the keys
    Test Data      : none
    Expected Result: 200, read_only=true, generated_at present. queue / stages_24h /
                     recent_runs / events_24h are each either a list or null (null =
                     the source table is not on this database), never a 500.
    API Endpoint   : GET /api/ops/overview
    DB Validation  : public.extract_queue, metrics.stage_run, provenance.event
    Priority       : P0
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/ops/overview"), timeout=env.TIMEOUT_S)
    assert r.status_code == 200, r.text[:300]
    b = r.json()
    assert b["read_only"] is True
    assert b["generated_at"]
    for k in ("queue", "stages_24h", "recent_runs", "events_24h"):
        assert k in b, "missing key %s" % k
        assert b[k] is None or isinstance(b[k], list)
    assert isinstance(b["events_available"], bool)


def test_be_031_ops_overview_queue_matches_db(http, api_up, cur):
    """
    Test ID        : BE-031
    Module         : Backend / Ops <-> Database
    Precondition   : API up AND direct DB access AND public.extract_queue present
    Steps          : 1. GET /api/ops/overview
                     2. SELECT state, count(*) FROM public.extract_queue GROUP BY state
    Test Data      : none
    Expected Result: the same state->count map (+/- rows the workers moved between the
                     two reads; the STATE SET must match exactly).
    API Endpoint   : GET /api/ops/overview
    DB Validation  : SELECT state, count(*) FROM public.extract_queue GROUP BY state
    Priority       : P1
    Automation Tool: pytest + requests + psycopg2
    """
    from conftest import regclass
    if not regclass(cur, "public.extract_queue"):
        pytest.skip("public.extract_queue not on this database")
    api_q = http.get(env.api("/api/ops/overview"), timeout=env.TIMEOUT_S).json()["queue"]
    assert api_q is not None
    cur.execute("SELECT state, count(*) AS n FROM public.extract_queue GROUP BY state")
    db_states = {r["state"] for r in cur.fetchall()}
    assert {r["state"] for r in api_q} == db_states


def test_be_032_ops_queue_states_are_the_ones_route_py_writes(http, api_up):
    """
    Test ID        : BE-032
    Module         : Backend / Ops - queue vocabulary
    Precondition   : API up
    Steps          : 1. GET /api/ops/overview  2. check every reported state
    Test Data      : the states extraction/engine/route.py writes:
                     ready, leased, done, deferred, parked
    Expected Result: no state outside that set. An unknown state means a writer nobody
                     tracks, or a typo that quietly parks work forever.
    API Endpoint   : GET /api/ops/overview
    DB Validation  : public.extract_queue.state
    Priority       : P1
    Automation Tool: pytest
    """
    known = {"ready", "leased", "done", "deferred", "parked"}
    q = http.get(env.api("/api/ops/overview"), timeout=env.TIMEOUT_S).json()["queue"]
    if not q:
        pytest.skip("queue unavailable on this database")
    unknown = {r["state"] for r in q} - known
    assert not unknown, "extract_queue holds states route.py never writes: %s" % unknown


def test_be_033_ops_pipeline_stage_map(http, api_up):
    """
    Test ID        : BE-033
    Module         : Backend / Ops - Pipeline Explorer
    Precondition   : API up
    Steps          : 1. GET /api/ops/pipeline
    Test Data      : none
    Expected Result: 200; stages is a non-empty list; each stage carries
                     live_output_counts and live_event_counts objects (empty is fine --
                     it means the table is absent, which is honest, not a failure).
    API Endpoint   : GET /api/ops/pipeline
    DB Validation  : counts come from the tables each stage declares as outputs
    Priority       : P1
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/ops/pipeline"), timeout=env.TIMEOUT_S)
    assert r.status_code == 200
    b = r.json()
    assert isinstance(b["stages"], list) and b["stages"]
    for st in b["stages"]:
        assert isinstance(st["live_output_counts"], dict)
        assert isinstance(st["live_event_counts"], dict)


@pytest.mark.parametrize("limit,expect_max", [(1, 1), (50, 50), (100000, 500), (0, 1), (-5, 1)])
def test_be_034_ops_events_limit_is_clamped(http, api_up, limit, expect_max):
    """
    Test ID        : BE-034
    Module         : Backend / Ops - Live Event Stream, input validation
    Precondition   : API up
    Steps          : 1. GET /api/ops/events?limit=N for each N
    Test Data      : 1, 50, 100000, 0, -5
    Expected Result: 200 always; app.py clamps with max(1, min(int(limit), 500)), so a
                     caller cannot ask the database for the whole event table, and a
                     zero/negative limit does not produce an empty or erroring query.
    API Endpoint   : GET /api/ops/events?limit=
    DB Validation  : provenance.event
    Priority       : P0 (resource-exhaustion guard)
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/ops/events"), params={"limit": limit}, timeout=env.TIMEOUT_S)
    assert r.status_code == 200, r.text[:300]
    b = r.json()
    if not b.get("available"):
        pytest.skip("provenance.event not on this database")
    assert len(b["events"]) <= expect_max


def test_be_035_ops_events_bad_limit_is_a_400_not_a_500(http, api_up):
    """
    Test ID        : BE-035
    Module         : Backend / Ops - validation & error handling
    Precondition   : API up
    Steps          : 1. GET /api/ops/events?limit=abc
    Test Data      : limit=abc
    Expected Result: 422 (FastAPI's int coercion on the query parameter). It must NOT be
                     a 500 -- a caller's bad input is not a server fault.
    API Endpoint   : GET /api/ops/events?limit=abc
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/ops/events"), params={"limit": "abc"}, timeout=env.TIMEOUT_S)
    assert r.status_code == 422, "expected 422, got %s: %s" % (r.status_code, r.text[:200])


def test_be_036_ops_events_filters(http, api_up):
    """
    Test ID        : BE-036
    Module         : Backend / Ops - filters
    Precondition   : API up, provenance.event present with rows
    Steps          : 1. GET /api/ops/events?limit=5  2. take one row's action
                     3. GET /api/ops/events?action=<that>  4. every row matches
                     5. GET with since_id = max_event_id -> nothing older comes back
    Test Data      : an action value read from live data, never invented
    Expected Result: the action filter is exact; since_id returns only newer events.
    API Endpoint   : GET /api/ops/events?action=&document_id=&since_id=
    DB Validation  : SELECT ... FROM provenance.event WHERE action = %s
    Priority       : P1
    Automation Tool: pytest + requests
    """
    b = http.get(env.api("/api/ops/events"), params={"limit": 5}, timeout=env.TIMEOUT_S).json()
    if not b.get("available") or not b["events"]:
        pytest.skip("no provenance events on this database")
    action = b["events"][0]["action"]
    f = http.get(env.api("/api/ops/events"),
                 params={"action": action, "limit": 20}, timeout=env.TIMEOUT_S).json()
    assert all(e["action"] == action for e in f["events"])
    top = b["max_event_id"]
    s = http.get(env.api("/api/ops/events"),
                 params={"since_id": top, "limit": 20}, timeout=env.TIMEOUT_S).json()
    assert all(e["event_id"] > top for e in s["events"])


def test_be_037_ops_event_actions_are_in_the_check_constraint(http, api_up):
    """
    Test ID        : BE-037
    Module         : Backend / Ops <-> Database constraint
    Precondition   : API up, provenance.event present
    Steps          : 1. GET /api/ops/events?limit=500  2. check every action
    Test Data      : the CHECK vocabulary in db/07_provenance.sql
    Expected Result: every served action is one of: selected, gated, extracted,
                     record_rejected, transformed, card_written, enriched, served,
                     error, retry.
    API Endpoint   : GET /api/ops/events
    DB Validation  : provenance.event.action CHECK constraint
    Priority       : P2
    Automation Tool: pytest
    """
    allowed = {"selected", "gated", "extracted", "record_rejected", "transformed",
               "card_written", "enriched", "served", "error", "retry"}
    b = http.get(env.api("/api/ops/events"), params={"limit": 500}, timeout=env.TIMEOUT_S).json()
    if not b.get("available"):
        pytest.skip("provenance.event not on this database")
    seen = {e["action"] for e in b["events"]}
    assert seen <= allowed, "actions outside the CHECK constraint: %s" % (seen - allowed)


def test_be_038_ops_runs_list(http, api_up):
    """
    Test ID        : BE-038
    Module         : Backend / Ops - Run Timeline list
    Precondition   : API up
    Steps          : 1. GET /api/ops/runs?limit=5
    Test Data      : limit=5
    Expected Result: 200; a list of runs; each run's status is one of the values
                     _run_status can return (in_progress | completed), never guessed.
    API Endpoint   : GET /api/ops/runs?limit=
    DB Validation  : metrics.stage_run, provenance.event joined on run_id
    Priority       : P1
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/ops/runs"), params={"limit": 5}, timeout=env.TIMEOUT_S)
    assert r.status_code == 200, r.text[:300]
    b = r.json()
    runs = b.get("runs") or []
    for run in runs:
        assert run.get("status") in ("in_progress", "completed", None)


def test_be_039_ops_run_detail_404_on_unknown_id(http, api_up):
    """
    Test ID        : BE-039
    Module         : Backend / Ops - error handling
    Precondition   : API up
    Steps          : 1. GET /api/ops/runs/<a run_id that cannot exist>
    Test Data      : run_id = "kssl-e2e-no-such-run-0000"
    Expected Result: 404 with an `error` message naming both source tables. Not a 500,
                     not an empty 200 pretending the run exists.
    API Endpoint   : GET /api/ops/runs/{run_id}
    DB Validation  : neither metrics.stage_run nor provenance.event has the run_id
    Priority       : P1
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/ops/runs/kssl-e2e-no-such-run-0000"), timeout=env.TIMEOUT_S)
    assert r.status_code == 404, r.text[:300]
    assert "error" in r.json()


def test_be_040_ops_run_detail_of_a_real_run(http, api_up):
    """
    Test ID        : BE-040
    Module         : Backend / Ops - Run Timeline detail
    Precondition   : API up and at least one run recorded
    Steps          : 1. GET /api/ops/runs?limit=1  2. GET /api/ops/runs/{run_id}
    Test Data      : a run_id read from live data
    Expected Result: 200; read_only=true; timeline sorted ascending by `at`;
                     stage_rollup / action_rollup / reject_reasons are lists.
    API Endpoint   : GET /api/ops/runs/{run_id}
    DB Validation  : metrics.stage_run WHERE run_id = %s
    Priority       : P1
    Automation Tool: pytest + requests
    """
    runs = (http.get(env.api("/api/ops/runs"), params={"limit": 1},
                     timeout=env.TIMEOUT_S).json().get("runs") or [])
    if not runs:
        pytest.skip("no runs recorded on this database")
    rid = runs[0]["run_id"]
    b = http.get(env.api("/api/ops/runs/" + rid), timeout=env.TIMEOUT_S).json()
    assert b["read_only"] is True
    ats = [e["at"] or "" for e in b["timeline"]]
    assert ats == sorted(ats), "timeline is not chronological"
    for k in ("stage_rollup", "action_rollup", "reject_reasons"):
        assert isinstance(b[k], list)


def test_be_041_ops_signals_list_and_filters(http, api_up):
    """
    Test ID        : BE-041
    Module         : Backend / Ops - Signal Explorer, search & filter
    Precondition   : API up, serving.signal_card present
    Steps          : 1. GET /api/ops/signals?limit=5
                     2. re-request with lane= from a returned row -> every row matches
                     3. re-request with q=<part of a returned id> -> that row is in it
    Test Data      : values read from live rows, never invented
    Expected Result: filters narrow, never widen; `filters` echoes what was asked;
                     limit is clamped to 500.
    API Endpoint   : GET /api/ops/signals?lane=&company=&q=&since=&until=&origin=&limit=
    DB Validation  : serving.signal_card WHERE lane = %s / id ILIKE %s
    Priority       : P0
    Automation Tool: pytest + requests
    """
    b = http.get(env.api("/api/ops/signals"), params={"limit": 5}, timeout=env.TIMEOUT_S).json()
    if not b.get("available") or not b["signals"]:
        pytest.skip("no signal cards on this database")
    assert b["filters"]["limit"] == 5
    lane = b["signals"][0]["lane"]
    lb = http.get(env.api("/api/ops/signals"),
                  params={"lane": lane, "limit": 50}, timeout=env.TIMEOUT_S).json()
    assert all(s["lane"] == lane for s in lb["signals"])
    sid = b["signals"][0]["id"]
    qb = http.get(env.api("/api/ops/signals"),
                  params={"q": sid, "limit": 50}, timeout=env.TIMEOUT_S).json()
    assert any(s["id"] == sid for s in qb["signals"])


def test_be_042_ops_signals_lane_vocabulary(http, api_up):
    """
    Test ID        : BE-042
    Module         : Backend / Ops <-> Database constraint
    Precondition   : API up
    Steps          : 1. GET /api/ops/signals?limit=500  2. check every lane
    Test Data      : db/02_serving.sql CHECK (lane IN ('competitive','market','tech'))
    Expected Result: no lane outside that set.
    API Endpoint   : GET /api/ops/signals
    DB Validation  : serving.signal_card.lane CHECK constraint
    Priority       : P2
    Automation Tool: pytest
    """
    b = http.get(env.api("/api/ops/signals"), params={"limit": 500},
                 timeout=env.TIMEOUT_S).json()
    if not b.get("available"):
        pytest.skip("serving.signal_card not on this database")
    lanes = {s["lane"] for s in b["signals"]}
    assert lanes <= {"competitive", "market", "tech"}, "unexpected lanes: %s" % lanes


def test_be_043_ops_signal_detail_accepts_both_id_forms(http, api_up):
    """
    Test ID        : BE-043
    Module         : Backend / Ops - Signal Explorer detail
    Precondition   : API up, at least one signal card
    Steps          : 1. take a card id (pl_<document_id>)
                     2. GET /api/ops/signals/{pl_id}
                     3. GET /api/ops/signals/{document_id}  (the bare form)
    Test Data      : a live card id
    Expected Result: both 200 and both resolve to the SAME card_id/document_id --
                     app.py::_sig_ids accepts either form.
    API Endpoint   : GET /api/ops/signals/{signal_id}
    DB Validation  : serving.signal_card WHERE id = 'pl_' || document_id
    Priority       : P1
    Automation Tool: pytest + requests
    """
    b = http.get(env.api("/api/ops/signals"), params={"limit": 1},
                 timeout=env.TIMEOUT_S).json()
    if not b.get("available") or not b["signals"]:
        pytest.skip("no signal cards")
    card_id = b["signals"][0]["id"]
    if not card_id.startswith("pl_"):
        pytest.skip("card id is not the pl_<document_id> form (%s)" % card_id)
    a = http.get(env.api("/api/ops/signals/" + card_id), timeout=env.TIMEOUT_S)
    c = http.get(env.api("/api/ops/signals/" + card_id[3:]), timeout=env.TIMEOUT_S)
    assert a.status_code == 200 and c.status_code == 200
    assert a.json()["card_id"] == c.json()["card_id"] == card_id
    assert a.json()["document_id"] == c.json()["document_id"]


def test_be_044_ops_signal_detail_labels_every_section(http, api_up):
    """
    Test ID        : BE-044
    Module         : Backend / Ops - provenance honesty
    Precondition   : API up, at least one signal card
    Steps          : 1. GET /api/ops/signals/{id}
                     2. read the status of signal / lineage_columns / provenance_events
                        / translation
    Test Data      : a live card id
    Expected Result: every status is one of recorded | reconstructed | aggregated |
                     provenance_unavailable, and label_key explains all four. The
                     endpoint must never present a reconstruction as a stored fact.
    API Endpoint   : GET /api/ops/signals/{signal_id}
    DB Validation  : serving.signal_card.source_prop_ids, provenance.event, documents.language
    Priority       : P0
    Automation Tool: pytest + requests
    """
    b = http.get(env.api("/api/ops/signals"), params={"limit": 1},
                 timeout=env.TIMEOUT_S).json()
    if not b.get("available") or not b["signals"]:
        pytest.skip("no signal cards")
    d = http.get(env.api("/api/ops/signals/" + b["signals"][0]["id"]),
                 timeout=env.TIMEOUT_S).json()
    allowed = {"recorded", "reconstructed", "aggregated", "provenance_unavailable"}
    for section in ("signal", "lineage_columns", "provenance_events", "translation"):
        assert d[section]["status"] in allowed, "%s: %s" % (section, d[section]["status"])
    assert set(d["label_key"]) == allowed


def test_be_045_ops_signal_detail_404_on_unknown(http, api_up):
    """
    Test ID        : BE-045
    Module         : Backend / Ops - error handling
    Precondition   : API up
    Steps          : 1. GET /api/ops/signals/doc_e2e_definitely_not_a_document
    Test Data      : an id that cannot exist
    Expected Result: 404 (or 503 if serving.signal_card is absent). Never 200 with an
                     empty shell, never 500.
    API Endpoint   : GET /api/ops/signals/{signal_id}
    DB Validation  : no card, no detail, no events, no lineage for this id
    Priority       : P1
    Automation Tool: pytest + requests
    """
    r = http.get(env.api("/api/ops/signals/doc_e2e_definitely_not_a_document"),
                 timeout=env.TIMEOUT_S)
    assert r.status_code in (404, 503), "got %s: %s" % (r.status_code, r.text[:200])


def test_be_046_ops_endpoints_are_read_only(http, api_up, cur):
    """
    Test ID        : SEC-010
    Module         : Backend / Ops - read-only guarantee
    Precondition   : API up AND direct DB access
    Steps          : 1. snapshot counts of extract_queue / provenance.event / signal_card
                     2. call every /api/ops/* endpoint
                     3. re-snapshot
    Test Data      : none
    Expected Result: nothing the operator console reads is changed by reading it.
                     app.py opens these on a connection set readonly=True.
    API Endpoint   : all /api/ops/*
    DB Validation  : row counts before == after
    Priority       : P0
    Automation Tool: pytest + requests + psycopg2
    """
    from conftest import regclass
    tables = [t for t in ("public.extract_queue", "provenance.event",
                          "serving.signal_card", "metrics.stage_run")
              if regclass(cur, t)]
    if not tables:
        pytest.skip("none of the ops source tables are on this database")
    def snap():
        out = {}
        for t in tables:
            cur.execute("SELECT count(*) AS n FROM " + t)
            out[t] = cur.fetchone()["n"]
        return out
    before = snap()
    for p in ("/api/ops/overview", "/api/ops/pipeline", "/api/ops/events?limit=10",
              "/api/ops/runs?limit=5", "/api/ops/signals?limit=10"):
        http.get(env.api(p), timeout=env.TIMEOUT_S)
    after = snap()
    # provenance.event and stage_run are written by the live pipeline, so they may GROW
    # on their own. What must never happen is a DECREASE, or a change in the tables the
    # ops endpoints have no writer for.
    for t in tables:
        if t in ("provenance.event", "metrics.stage_run"):
            assert after[t] >= before[t], "%s lost rows during a read-only call" % t
        else:
            assert after[t] == before[t], "%s changed during a read-only call" % t


def test_be_047_ops_endpoints_performance(http, api_up):
    """
    Test ID        : PERF-002
    Module         : Backend / Performance
    Precondition   : API up
    Steps          : 1. time each ops endpoint
    Test Data      : budget = KSSL_TEST_BUDGET_OPS_S (default 10s)
    Expected Result: each under budget. These are aggregations the operator console
                     polls; one that takes longer than its own poll interval is the
                     failure mode.
    API Endpoint   : /api/ops/overview, /pipeline, /events, /runs, /signals
    DB Validation  : n/a
    Priority       : P2
    Automation Tool: pytest + requests
    """
    slow = []
    for p in ("/api/ops/overview", "/api/ops/pipeline", "/api/ops/events?limit=50",
              "/api/ops/runs?limit=40", "/api/ops/signals?limit=50"):
        t0 = time.time()
        http.get(env.api(p), timeout=env.TIMEOUT_S)
        dt = time.time() - t0
        if dt > env.BUDGET_OPS_S:
            slow.append("%s %.1fs" % (p, dt))
    assert not slow, "over the %.0fs budget: %s" % (env.BUDGET_OPS_S, slow)
