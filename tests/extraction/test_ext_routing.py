# -*- coding: utf-8 -*-
"""Module: EXTRACTION / dispatch rules -- pure functions, no database, no network.

These import extraction/engine/route.py directly and pin the decisions it makes:
klass(), eligible(), route(), dispatchable(), lease_ttl(). They are the cheapest tests
in the suite and the ones that catch a queue that lies about itself.

Run: pytest tests/extraction/test_ext_routing.py
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(REPO, "extraction", "engine")

if not os.path.isdir(ENGINE):
    pytest.skip("extraction/engine is not next to the test suite", allow_module_level=True)
sys.path.insert(0, ENGINE)
os.environ.setdefault("C_DS_JSON", os.path.join(ENGINE, "ds.json"))
os.environ.setdefault("C_TIERS_PATH", os.path.join(ENGINE, "source_tiers.py"))

try:
    import route  # noqa: E402
except Exception as exc:                                    # noqa: BLE001
    pytest.skip("cannot import extraction/engine/route.py (%s)" % exc,
                allow_module_level=True)


def test_ext_001_freshness_dominates_priority():
    """
    Test ID        : EXT-001
    Module         : Extraction / Class assignment
    Precondition   : extraction/engine/route.py importable
    Steps          : 1. klass(presignal_pct=0.99, age_hours=FRESH_HOURS)  -> P3
                     2. klass(0.01, 0)                                    -> P2
    Test Data      : a perfect-score stale document; a zero-score fresh one
    Expected Result: age wins. route.py: "Freshness dominates, as the product requires:
                     today's crawl before any historical document." A stale document
                     scoring 0.99 must NOT outrank a fresh one.
    API Endpoint   : n/a (upstream of GET /api/ops/overview queue tiles)
    DB Validation  : the class written to extract_queue.class
    Priority       : P0
    Automation Tool: pytest
    """
    assert route.klass(0.99, route.FRESH_HOURS) == route.P3
    assert route.klass(0.99, route.FRESH_HOURS + 1000) == route.P3
    assert route.klass(0.01, 0) != route.P3


def test_ext_002_percentile_bands():
    """
    Test ID        : EXT-002
    Module         : Extraction / Class assignment
    Precondition   : as EXT-001
    Steps          : 1. klass at the band edges 0.75 and 0.40, fresh
    Test Data      : pct = 0.75, 0.7499, 0.40, 0.3999 with age_hours = 0
    Expected Result: >=0.75 -> P0, >=0.40 -> P1, else P2. The boundaries are inclusive
                     at the bottom of each band exactly as written.
    API Endpoint   : n/a
    DB Validation  : extract_queue.class
    Priority       : P1
    Automation Tool: pytest
    """
    assert route.klass(0.75, 0) == route.P0
    assert route.klass(0.7499, 0) == route.P1
    assert route.klass(0.40, 0) == route.P1
    assert route.klass(0.3999, 0) == route.P2


def test_ext_003_a_cohort_that_ties_lands_at_no_information():
    """
    Test ID        : EXT-003
    Module         : Extraction / Presignal percentile
    Precondition   : as EXT-001
    Steps          : 1. percentile_within(score, [same score] * n)
    Test Data      : a cohort where every document ties
    Expected Result: 0.5 -- "no information" -- not 1.0. Ranking on the raw score would
                     rank the SCORER'S VOCABULARY (62% of Polish pages match against 8%
                     of Hebrew), quietly starving every non-English source.
    API Endpoint   : n/a
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: pytest
    """
    assert route.percentile_within(0.5, [0.5] * 20) == pytest.approx(0.5, abs=0.05)


def test_ext_004_node_eligibility_is_a_pure_predicate():
    """
    Test ID        : EXT-004
    Module         : Extraction / Node eligibility
    Precondition   : as EXT-001
    Steps          : 1. eligible(node, cls, chars) for each configured node
    Test Data      : chars = 1 and chars = node cap + 1
    Expected Result: a document within cap and class range is eligible; one char over
                     the cap is not. No I/O in the call (it is called per-document in
                     the enqueue loop).
    API Endpoint   : n/a
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: pytest
    """
    for name, spec in route.NODES.items():
        cls = spec.get("min_class", route.P0)
        assert route.eligible(name, cls, 1) is True
        assert route.eligible(name, cls, spec["cap"] + 1) is False


def test_ext_005_an_oversized_document_is_parked_not_queued():
    """
    Test ID        : EXT-005
    Module         : Extraction / Dispatch
    Precondition   : as EXT-001
    Steps          : 1. route(chars = PARK_CHARS + 1, ...)
    Test Data      : a document larger than every node's cap
    Expected Result: (None, []) -- parking means IMPOSSIBLE. Nothing un-parks, so it
                     must never mean "nobody is up right now".
    API Endpoint   : GET /api/ops/overview (the `parked` tile)
    DB Validation  : extract_queue.state = 'parked'
    Priority       : P0
    Automation Tool: pytest
    """
    cls, nodes = route.route(route.PARK_CHARS + 1, 0.9, 0)
    assert cls is None and nodes == []


def test_ext_006_a_p0_no_always_on_node_can_serve_is_demoted():
    """
    Test ID        : EXT-006
    Module         : Extraction / Dispatch - the promise rule
    Precondition   : as EXT-001
    Steps          : 1. route() a fresh, high-scoring document too large for every
                        always-on node but within PARK_CHARS
    Test Data      : chars = max always-on cap + 1, pct = 0.9, age = 0
    Expected Result: class is NOT P0. A class is a PROMISE; left as P0 the document is
                     eligible NOWHERE, sits in `ready` forever, and is the
                     highest-priority thing in the system. "Later than promised is
                     honest, never is a silent hole."
    API Endpoint   : GET /api/ops/overview
    DB Validation  : extract_queue.class
    Priority       : P0
    Automation Tool: pytest
    """
    on_caps = [route.NODES[n]["cap"] for n in route.ALWAYS_ON if n in route.NODES]
    if not on_caps:
        pytest.skip("no always-on nodes configured")
    big = max(on_caps) + 1
    if big > route.PARK_CHARS:
        pytest.skip("an always-on node already has the largest cap on this config")
    cls, _ = route.route(big, 0.9, 0)
    assert cls != route.P0


def test_ext_007_dispatchable_never_writes_ready_for_a_dead_node():
    """
    Test ID        : EXT-007
    Module         : Extraction / Queue honesty
    Precondition   : as EXT-001
    Steps          : 1. dispatchable() a document no LIVE node can take
    Test Data      : chars just above LIVE_CAP but at or below PARK_CHARS
    Expected Result: state is 'deferred', never 'ready' (a lie the queue tells about
                     itself) and never 'parked' (terminal, with no code path out).
    API Endpoint   : GET /api/ops/overview -> queue[state='deferred']
    DB Validation  : extract_queue.state / reason
    Priority       : P0
    Automation Tool: pytest
    """
    if route.LIVE_CAP >= route.PARK_CHARS:
        pytest.skip("every live node already carries the largest cap on this config")
    out = route.dispatchable(route.LIVE_CAP + 1, 0.9, 0)
    state = out[2] if isinstance(out, (tuple, list)) and len(out) >= 3 else None
    assert state == "deferred", "expected deferred, got %r" % (out,)


def test_ext_008_lease_ttl_is_sized_from_the_document_not_the_cap():
    """
    Test ID        : EXT-008
    Module         : Extraction / Lease sizing
    Precondition   : as EXT-001
    Steps          : 1. lease_ttl(small doc, tok_s) vs lease_ttl(large doc, tok_s)
    Test Data      : chars = 1,089 and chars = 200,000, same tok/s
    Expected Result: the small document's TTL is smaller, and never below TTL_FLOOR_S.
                     Sized from the CAP instead, the DC's lease was 172 minutes for
                     every document: a 1,089-char row it finishes in ~9 minutes stayed
                     "in progress" for nearly three hours after its worker died,
                     invisible to the reap that whole time.
    API Endpoint   : GET /api/ops/overview -> queue[state='leased']
    DB Validation  : extract_queue.lease_until
    Priority       : P1
    Automation Tool: pytest
    """
    small = route.lease_ttl(1089, 12.0)
    large = route.lease_ttl(200000, 12.0)
    assert small >= route.TTL_FLOOR_S
    assert large > small


def test_ext_009_claim_sql_uses_skip_locked_and_is_class_ordered():
    """
    Test ID        : EXT-009
    Module         : Extraction / Concurrency
    Precondition   : as EXT-001
    Steps          : 1. read route.CLAIM
    Test Data      : none
    Expected Result: the claim contains FOR UPDATE SKIP LOCKED and ORDER BY class ASC.
                     SKIP LOCKED is what lets N workers claim concurrently with no
                     broker; the class ordering is what makes P1 drain before P2.
    API Endpoint   : n/a
    DB Validation  : the SQL the worker issues against extract_queue
    Priority       : P0
    Automation Tool: pytest (static assertion on the shipped SQL)
    """
    flat = " ".join(route.CLAIM.split())
    assert "FOR UPDATE SKIP LOCKED" in flat
    assert "ORDER BY class ASC" in flat


def test_ext_010_commit_is_fenced_on_the_lease_epoch():
    """
    Test ID        : EXT-010
    Module         : Extraction / At-least-once correctness
    Precondition   : as EXT-001
    Steps          : 1. read route.COMMIT and route.REAP
    Test Data      : none
    Expected Result: COMMIT filters on lease_epoch; REAP bumps lease_epoch. Without the
                     fence a worker whose lease expired while still alive commits on
                     top of a re-run's result -- at-least-once becomes
                     last-writer-wins, and a reaped worker could flip a `parked` row to
                     `done`, undoing the park that evicted it.
    API Endpoint   : n/a
    DB Validation  : extract_queue.lease_epoch
    Priority       : P0
    Automation Tool: pytest (static assertion on the shipped SQL)
    """
    assert "lease_epoch=%(epoch)s" in " ".join(route.COMMIT.split())
    assert "lease_epoch=lease_epoch+1" in " ".join(route.REAP.split())


def test_ext_011_trust_tier_does_not_decide_dispatch():
    """
    Test ID        : EXT-011
    Module         : Extraction / Selection policy
    Precondition   : as EXT-001
    Steps          : 1. inspect route.route's signature
    Test Data      : none
    Expected Result: the trust tier is NOT an argument. route.py: an earlier router had
                     P0 = tier 1, which "would have starved the most productive source
                     in the catalogue while looking principled". Trust rides along as
                     metadata for the downstream card gate and decides nothing here.
    API Endpoint   : n/a
    DB Validation  : n/a
    Priority       : P2
    Automation Tool: pytest
    """
    import inspect
    args = inspect.signature(route.route).parameters
    assert not any("tier" in a for a in args), "tier leaked into the dispatch decision"
