# -*- coding: utf-8 -*-
"""The event layer must record faithfully AND never take the pipeline down with it.

Hermetic: a fake connection captures the SQL/params, or raises to prove failure is
swallowed. No database.

Run: python extraction/signals/test_provenance.py
"""
import os
import sys

os.environ["KSSL_DSN"] = "host=x port=5432 dbname=x user=x password=x"  # non-empty -> _ready()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provenance  # noqa: E402


class FakeCur:
    def __init__(self, sink, fail=False):
        self.sink, self.fail = sink, fail

    def execute(self, sql, params=None):
        if self.fail:
            raise RuntimeError("db down")
        self.sink.append((sql, params))

    def executemany(self, sql, seq):
        if self.fail:
            raise RuntimeError("db down")
        for p in seq:
            self.sink.append((sql, p))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, sink, fail=False):
        self.sink, self.fail, self.autocommit, self.closed = sink, fail, False, False

    def cursor(self):
        return FakeCur(self.sink, self.fail)

    def close(self):
        self.closed = True


def _wire(sink, fail=False):
    provenance._reset_for_tests()
    provenance._connect = lambda dsn, connect_timeout=None: FakeConn(sink, fail)


def _inserts(sink):
    return [(s, p) for (s, p) in sink if s.startswith("INSERT INTO provenance.event")]


def test_insert_shape_and_values():
    sink = []
    _wire(sink)
    ok = provenance.emit("signals", "serving_fill.py", "card_written",
                         document_id="doc_x", run_id="run-1",
                         ref_table="serving.signal_card", ref_id="pl_doc_x",
                         evidence={"lane": "competitive"})
    assert ok is True
    ins = _inserts(sink)
    assert len(ins) == 1, ins
    _sql, params = ins[0]
    # order: stage, component, document_id, run_id, ref_table, ref_id, action, reason, evidence, in, out
    assert params[0] == "signals" and params[1] == "serving_fill.py"
    assert params[2] == "doc_x" and params[3] == "run-1"
    assert params[4] == "serving.signal_card" and params[5] == "pl_doc_x"
    assert params[6] == "card_written"
    assert params[8] == '{"lane": "competitive"}'      # evidence json
    print("  ok  emit writes one row with correct columns/values")


def test_nullable_fields_default():
    sink = []
    _wire(sink)
    assert provenance.emit("gate", "route.py", "gated") is True
    _sql, params = _inserts(sink)[0]
    assert params[2] is None and params[4] is None and params[7] is None  # doc, ref_table, reason
    assert params[3] == provenance.stage_timer.RUN_ID                     # run_id defaults, never NULL-by-accident
    print("  ok  nullable fields insert as NULL; run_id defaults to the process RUN_ID")


def test_gate_rejection_reason_is_recorded():
    sink = []
    _wire(sink)
    provenance.emit("signals", "serving_fill.py", "record_rejected",
                    document_id="doc_stale", reason="stale")
    _sql, params = _inserts(sink)[0]
    assert params[6] == "record_rejected" and params[7] == "stale"
    print("  ok  a rejection reason is stored and queryable (not stdout-only)")


def test_failure_never_raises_and_returns_false():
    sink = []
    _wire(sink, fail=True)
    for _ in range(provenance.CONSECUTIVE_FAILURES + 2):
        assert provenance.emit("signals", "x.py", "error", document_id="d") is False
    assert provenance._dead[0] is True, "breaker must trip so a dead DB stops costing time"
    print("  ok  a broken database never raises; breaker disables recording")


def test_unknown_action_rejected():
    sink = []
    _wire(sink)
    assert provenance.emit("signals", "x.py", "not_a_real_action") is False
    assert _inserts(sink) == []
    print("  ok  an unknown action is refused, never a silent typo row")


def test_no_secrets_in_model_evidence():
    ev = provenance.model_evidence({"model": "qwen", "via": "farm", "eval_count": 42,
                                    "prompt": "SECRET PROMPT", "response": "SECRET",
                                    "api_key": "sk-live-xxx", "OLLAMA_API_KEY": "y"})
    assert ev == {"model": "qwen", "via": "farm", "eval_count": 42}, ev
    for bad in ("prompt", "response", "api_key", "OLLAMA_API_KEY"):
        assert bad not in ev
    assert provenance.model_evidence({"api_key": "sk"}) is None
    print("  ok  model_evidence keeps identity/telemetry only, drops prompts/keys")


def test_emit_many_batches():
    sink = []
    _wire(sink)
    n = provenance.emit_many([
        {"stage": "gate", "component": "route.py", "action": "gated", "document_id": "d1",
         "reason": "ready"},
        {"stage": "gate", "component": "route.py", "action": "gated", "document_id": "d2",
         "reason": "deferred:no-live-node"},
        {"stage": "gate", "component": "route.py", "action": "bogus", "document_id": "d3"},
    ])
    assert n == 2, "the bogus action is skipped, the two valid ones batched"
    ins = _inserts(sink)
    assert len(ins) == 2 and {p[2] for _s, p in ins} == {"d1", "d2"}
    print("  ok  emit_many batches valid rows and skips bad actions")


if __name__ == "__main__":
    test_insert_shape_and_values()
    test_nullable_fields_default()
    test_gate_rejection_reason_is_recorded()
    test_failure_never_raises_and_returns_false()
    test_unknown_action_rejected()
    test_no_secrets_in_model_evidence()
    test_emit_many_batches()
    print("ok - provenance events: faithful, nullable-safe, secret-free, never fatal")
