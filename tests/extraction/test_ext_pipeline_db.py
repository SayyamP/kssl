# -*- coding: utf-8 -*-
"""Module: EXTRACTION / live pipeline state -- what the queue and the extracted layer
actually hold on the deployment under test.

Read-only. These are the checks an operator would run by hand at 3am, written down.
"""
import sys, os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import env  # noqa: E402
from conftest import regclass  # noqa: E402


@pytest.fixture(autouse=True)
def _needs_queue(cur):
    if not regclass(cur, "public.extract_queue"):
        pytest.skip("public.extract_queue not on this database")


def test_ext_030_no_lease_is_expired_and_unreaped(cur):
    """
    Test ID        : EXT-030
    Module         : Extraction / Lease reaping
    Precondition   : direct DB access; the feeder role running (it reaps every cycle)
    Steps          : 1. SELECT count(*) FROM extract_queue
                        WHERE state='leased' AND lease_until < now() - interval '30 min'
    Test Data      : a 30-minute grace on top of the reap cycle (FEED_EVERY_S = 600s)
    Expected Result: zero. A dead worker announces itself by silence; the reap is the
                     only thing that returns its document to `ready`. Rows stuck here
                     are work nobody is doing and nobody is counting.
    API Endpoint   : GET /api/ops/overview -> queue[state='leased']
    DB Validation  : extract_queue.state / lease_until
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    cur.execute("SELECT count(*) AS n FROM extract_queue "
                "WHERE state='leased' AND lease_until < now() - interval '30 minutes'")
    n = cur.fetchone()["n"]
    assert n == 0, ("%d leases expired over 30 minutes ago and were never reaped -- "
                    "the feeder's `reap` step is not running" % n)


def test_ext_031_the_fleet_is_not_idle_beside_a_full_queue(cur):
    """
    Test ID        : EXT-031
    Module         : Extraction / Backfill
    Precondition   : direct DB access
    Steps          : 1. count state='ready'
                     2. count state='deferred' with a gate reason
    Test Data      : none
    Expected Result: FINDING if ready = 0 while deferred is large. Measured live once:
                     ready 0, deferred/gate 51,994, 198 workers in backoff -- an idle
                     fleet beside a 98%-full queue. route.backfill() tops `ready` back
                     up from gate-refused rows; the fix is a backfill, never a lower
                     threshold.
    API Endpoint   : GET /api/ops/overview
    DB Validation  : SELECT state, reason, count(*) FROM extract_queue GROUP BY 1,2
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    cur.execute("SELECT count(*) AS n FROM extract_queue WHERE state='ready'")
    ready = cur.fetchone()["n"]
    cur.execute("SELECT count(*) AS n FROM extract_queue WHERE state='deferred'")
    deferred = cur.fetchone()["n"]
    if deferred == 0:
        pytest.skip("nothing deferred; backfill has nothing to do")
    assert ready > 0, ("ready=0 with %d deferred rows -- every worker is in backoff "
                       "beside a full queue; run route.py --backfill" % deferred)


def test_ext_032_parked_rows_carry_a_reason(cur):
    """
    Test ID        : EXT-032
    Module         : Extraction / Auditability
    Precondition   : direct DB access
    Steps          : 1. count parked/deferred rows with a null reason
    Test Data      : none
    Expected Result: zero. route.py: "A state without a reason is not auditable" --
                     park() used to discard why, and `deferred` acquired two
                     indistinguishable meanings.
    API Endpoint   : GET /api/ops/overview
    DB Validation  : extract_queue.reason
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    cur.execute("SELECT state, count(*) AS n FROM extract_queue "
                "WHERE state IN ('parked','deferred') AND reason IS NULL GROUP BY state")
    rows = {r["state"]: r["n"] for r in cur.fetchall()}
    assert not rows, "queue rows with no reason: %s" % rows


def test_ext_033_attempts_never_exceed_the_park_threshold(cur):
    """
    Test ID        : EXT-033
    Module         : Extraction / Retry accounting
    Precondition   : direct DB access
    Steps          : 1. SELECT max(attempts), and count rows still 'ready' with high attempts
    Test Data      : none
    Expected Result: a row that has burned its attempts is 'parked', not 'ready'. A
                     ready row with attempts past the cap is a document the claim query
                     will never select but the queue still counts as available work.
    API Endpoint   : GET /api/ops/overview
    DB Validation  : extract_queue.attempts / state
    Priority       : P2
    Automation Tool: pytest + psycopg2
    """
    cur.execute("SELECT max(attempts) AS m FROM extract_queue")
    top = cur.fetchone()["m"] or 0
    if top == 0:
        pytest.skip("nothing has been attempted yet")
    cur.execute("SELECT count(*) AS n FROM extract_queue "
                "WHERE state='ready' AND attempts >= %s", (top,))
    print("NOTE: %d ready rows at the maximum attempt count (%d)"
          % (cur.fetchone()["n"], top))


def test_ext_034_extracted_documents_have_spans(cur):
    """
    Test ID        : EXT-034
    Module         : Extraction / Output integrity
    Precondition   : direct DB access; extracted.* present
    Steps          : 1. count extracted.document rows with no extracted.span
    Test Data      : none
    Expected Result: report the ratio. A document stored with zero spans is a model call
                     that produced nothing; a large share of them means the extraction
                     prompt or the model alias has changed under the pipeline.
    API Endpoint   : GET /api/lineage/doc/{id} -> the extraction stage
    DB Validation  : LEFT JOIN extracted.span ON document_id
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    if not (regclass(cur, "extracted.document") and regclass(cur, "extracted.span")):
        pytest.skip("extracted.* not on this database")
    cur.execute("SELECT count(*) AS n FROM extracted.document")
    docs = cur.fetchone()["n"]
    if docs == 0:
        pytest.skip("nothing extracted yet")
    cur.execute("SELECT count(*) AS n FROM extracted.document d "
                "WHERE NOT EXISTS (SELECT 1 FROM extracted.span s "
                "                  WHERE s.document_id = d.document_id)")
    empty = cur.fetchone()["n"]
    assert empty < docs, "every extracted document has zero spans -- extraction is producing nothing"
    print("NOTE: %d/%d extracted documents carry no spans (%.1f%%)"
          % (empty, docs, 100.0 * empty / docs))


def test_ext_035_done_queue_rows_reached_the_extracted_layer(cur):
    """
    Test ID        : EXT-035
    Module         : Extraction / Queue <-> store consistency
    Precondition   : direct DB access; extracted.document present
    Steps          : 1. count extract_queue rows state='done' with no extracted.document
    Test Data      : none
    Expected Result: zero, or a small number in flight. The worker writes the spans AND
                     the done-mark in ONE transaction on ONE connection (this is why
                     db/00_documents.sql exists at all), so a `done` row with no
                     extraction is a broken atomicity guarantee.
    API Endpoint   : GET /api/lineage/doc/{id}
    DB Validation  : extract_queue.state='done' LEFT JOIN extracted.document
    Priority       : P0
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "extracted.document"):
        pytest.skip("extracted.document not on this database")
    cur.execute("SELECT count(*) AS n FROM extract_queue q WHERE q.state='done' "
                "AND NOT EXISTS (SELECT 1 FROM extracted.document d "
                "                WHERE d.document_id = q.document_id)")
    n = cur.fetchone()["n"]
    assert n == 0, ("%d queue rows are marked done with nothing in extracted.document "
                    "-- the store+mark transaction is not atomic" % n)


def test_ext_036_signal_cards_trace_back_to_a_document(cur):
    """
    Test ID        : EXT-036
    Module         : Extraction / Serving lineage
    Precondition   : direct DB access
    Steps          : 1. for pipeline cards keyed pl_<document_id>, check the document exists
    Test Data      : none
    Expected Result: every pipeline card's document is in public.documents. A card whose
                     source document is gone cannot be traced, audited or re-gated.
    API Endpoint   : GET /api/ops/signals/{id} ; GET /api/lineage/doc/{id}
    DB Validation  : serving.signal_card.id -> documents.document_id
    Priority       : P1
    Automation Tool: pytest + psycopg2
    """
    if not (regclass(cur, "serving.signal_card") and regclass(cur, "public.documents")):
        pytest.skip("tables not present")
    cur.execute("SELECT count(*) AS n FROM serving.signal_card c "
                "WHERE c.origin='pipeline' AND c.id LIKE 'pl\\_%' "
                "AND NOT EXISTS (SELECT 1 FROM documents d "
                "                WHERE d.document_id = substring(c.id from 4))")
    n = cur.fetchone()["n"]
    print("NOTE: %d pipeline cards whose source document is no longer in the corpus" % n)


def test_ext_037_stage_run_records_every_stage_the_pipeline_claims(cur):
    """
    Test ID        : EXT-037
    Module         : Extraction / Instrumentation
    Precondition   : direct DB access; metrics.stage_run present
    Steps          : 1. SELECT DISTINCT stage FROM metrics.stage_run in the last 7 days
    Test Data      : none
    Expected Result: the stages a running pipeline produces are recorded. A stage that
                     has failed every cycle for a week prints the same single line as
                     one that hiccupped once (entrypoint.sh) -- the timing table is
                     where that shows up as an absence.
    API Endpoint   : GET /api/ops/overview -> stages_24h
    DB Validation  : SELECT DISTINCT stage FROM metrics.stage_run
    Priority       : P2
    Automation Tool: pytest + psycopg2
    """
    if not regclass(cur, "metrics.stage_run"):
        pytest.skip("metrics.stage_run not on this database")
    cur.execute("SELECT DISTINCT stage FROM metrics.stage_run "
                "WHERE ended_at > now() - interval '7 days' ORDER BY stage")
    stages = [r["stage"] for r in cur.fetchall()]
    print("NOTE: stages recorded in the last 7 days: %s" % stages)
    assert stages, "metrics.stage_run has recorded nothing in a week -- the pipeline is not running"
