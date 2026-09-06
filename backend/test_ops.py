# -*- coding: utf-8 -*-
"""The operator endpoints must be read-only and degrade, never 500, on a missing table.

Hermetic: a fake connection answers each query by substring and records that the
connection was opened read-only. No database.

Run: python backend/test_ops.py
"""
import json
import os
import sys

os.environ.setdefault("KSSL_CORPUS_DSN", "postgresql://unused/unused")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402


class FakeCur:
    def __init__(self, rows, present):
        self.rows, self.present, self._last = rows, present, None

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        if "to_regclass(" in flat:
            # which table? from the param (ops_events/_regclass pass %s) or the literal
            name = params[0] if params else next((t for t in self.present.keys() if t in flat), None)
            self._last = {"t": name if self.present.get(name) else None}
            return
        if "count(*) AS n FROM " in flat and "GROUP BY" not in flat:  # pipeline row count
            self._last = {"n": 123}
            return
        for key, val in self.rows.items():
            if key in flat:
                self._last = val
                return
        self._last = None

    def fetchone(self):
        r = self._last
        return (r[0] if r else None) if isinstance(r, list) else r

    def fetchall(self):
        r = self._last
        return r if isinstance(r, list) else ([r] if r else [])

    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeConn:
    last_session = None

    def __init__(self, rows, present):
        self.rows, self.present, self.closed = rows, present, False

    def set_session(self, **kw):
        FakeConn.last_session = kw

    def cursor(self, cursor_factory=None):
        return FakeCur(self.rows, self.present)

    def close(self):
        self.closed = True


def wire(rows, present):
    app.psycopg2.connect = lambda dsn, connect_timeout=None: FakeConn(rows, present)


def body(resp):
    return json.loads(resp.body)


def test_overview_readonly_and_shaped():
    rows = {
        "FROM public.extract_queue GROUP BY state": [
            {"state": "done", "n": 100}, {"state": "ready", "n": 5}],
        "FROM metrics.stage_run WHERE ended_at": [
            {"stage": "llm", "runs": 10, "avg_ms": 700, "max_ms": 900, "failures": 1,
             "last_at": "2026-09-06 22:00:00+00"}],
        "FROM metrics.stage_run ORDER BY": [
            {"run_id": "r1", "stage": "llm", "doc_id": None, "ms": 700, "ok": True,
             "ended_at": "2026-09-06 22:00:00+00"}],
    }
    present = {"public.extract_queue": True, "metrics.stage_run": True, "provenance.event": False}
    wire(rows, present)
    d = body(app.ops_overview())
    assert d["read_only"] is True
    assert FakeConn.last_session.get("readonly") is True, "connection must be read-only"
    assert d["queue"][0]["state"] == "done"
    assert d["stages_24h"][0]["stage"] == "llm"
    assert d["events_available"] is False and "events_note" in d
    print("  ok  overview: read-only, queue+stages shaped, events gracefully unavailable")


def test_overview_survives_all_tables_missing():
    wire({}, {"public.extract_queue": False, "metrics.stage_run": False, "provenance.event": False})
    d = body(app.ops_overview())
    assert d["queue"] is None and d["stages_24h"] is None and d["events_available"] is False
    print("  ok  overview: every source missing -> nulls, not a 500")


def test_events_unavailable_and_available():
    wire({}, {"provenance.event": False})
    d = body(app.ops_events())
    assert d["available"] is False and d["events"] == [] and "note" in d
    wire({"FROM provenance.event": [
            {"event_id": 9, "ts": "2026-09-06 22:00:00+00", "stage": "signals",
             "component": "serving_fill.py", "document_id": "doc_x", "run_id": "run-1",
             "ref_table": "serving.signal_card", "ref_id": "pl_doc_x",
             "action": "record_rejected", "reason": "stale", "evidence": None}]},
         {"provenance.event": True})
    d = body(app.ops_events(limit=10, document_id="doc_x"))
    assert d["available"] is True and d["events"][0]["reason"] == "stale"
    assert d["max_event_id"] == 9
    print("  ok  events: unavailable is explicit; available returns rows + max_event_id")


def test_pipeline_map_is_grounded():
    wire({}, {"provenance.event": False, "public.documents": True, "serving.signal_card": True})
    d = body(app.ops_pipeline())
    assert len(d["stages"]) == len(app._PIPELINE)
    ids = [s["id"] for s in d["stages"]]
    assert ids == ["ingestion", "gate", "extraction", "signals", "enrich", "serving", "api", "ui"]
    ing = next(s for s in d["stages"] if s["id"] == "ingestion")
    assert ing["live_output_counts"].get("public.documents") == 123, "grounded with a live count"
    assert d["events_available"] is False
    print("  ok  pipeline: real stage order, files/functions, grounded live counts")


def test_no_writes_issued():
    seen = []
    class RecCur(FakeCur):
        def execute(self, sql, params=None):
            seen.append(sql); return super().execute(sql, params)
    class RecConn(FakeConn):
        def cursor(self, cursor_factory=None): return RecCur({}, {"public.extract_queue": False,
            "metrics.stage_run": False, "provenance.event": False})
    app.psycopg2.connect = lambda dsn, connect_timeout=None: RecConn({}, {})
    body(app.ops_overview()); body(app.ops_pipeline()); body(app.ops_events())
    for s in seen:
        assert s.strip().split(None, 1)[0].upper() in ("SELECT", "SET"), "non-read statement: " + s[:40]
    print("  ok  ops endpoints issue only SELECT/SET -- no writes")


def test_runs_list_stage_run_only():
    rows = {"FROM metrics.stage_run GROUP BY run_id": [
        {"run_id": "r1", "first_at": "2026-09-06 20:00:00+00", "last_at": "2026-09-06 21:00:00+00",
         "stage_rows": 186, "failures": 0, "open_rows": 0, "docs": 0, "stages": "llm",
         "tokens": 19961}]}
    wire(rows, {"metrics.stage_run": True, "provenance.event": False})
    d = body(app.ops_runs())
    assert d["events_available"] is False and "scope_note" in d
    r = d["runs"][0]
    assert r["run_id"] == "r1" and r["status"] == "completed" and r["stages"] == ["llm"]
    assert r["events"] is None
    print("  ok  runs list: stage_run only, events flagged unavailable, scope noted")


def test_runs_list_marks_in_progress():
    rows = {"FROM metrics.stage_run GROUP BY run_id": [
        {"run_id": "r2", "first_at": "2026-09-06 20:00:00+00", "last_at": "2026-09-06 20:05:00+00",
         "stage_rows": 3, "failures": 0, "open_rows": 1, "docs": 0, "stages": "llm", "tokens": 0}]}
    wire(rows, {"metrics.stage_run": True, "provenance.event": False})
    assert body(app.ops_runs())["runs"][0]["status"] == "in_progress", "open stage_run row -> in_progress"
    print("  ok  runs list: an unfinished stage_run row marks the run in_progress")


def test_run_detail_timeline_rollup_and_rejects():
    rows = {
        "FROM metrics.stage_run WHERE run_id = %s ORDER BY started_at": [
            {"stage": "llm", "doc_id": "doc_a", "started_at": "2026-09-06 20:00:00+00",
             "ended_at": "2026-09-06 20:00:15+00", "ms": 15000, "n_items": 1, "n_tokens": 200,
             "ok": True, "host": "vps", "note": None},
            {"stage": "llm", "doc_id": "doc_b", "started_at": "2026-09-06 20:01:00+00",
             "ended_at": "2026-09-06 20:01:05+00", "ms": 5000, "n_items": 1, "n_tokens": 90,
             "ok": False, "host": "vps", "note": "boom"}],
        "FROM metrics.stage_run WHERE run_id = %s GROUP BY stage": [
            {"stage": "llm", "runs": 2, "total_ms": 20000, "avg_ms": 10000, "failures": 1,
             "items": 2, "tokens": 290}],
        "FROM provenance.event WHERE run_id = %s ORDER BY event_id": [
            {"ts": "2026-09-06 20:00:30+00", "stage": "signals", "component": "serving_fill.py",
             "document_id": "doc_c", "ref_table": "serving.signal_card", "ref_id": "pl_doc_c",
             "action": "record_rejected", "reason": "stale", "evidence": None}],
        "WHERE run_id = %s AND action = 'record_rejected'": [{"reason": "stale", "n": 1}],
        "WHERE run_id = %s GROUP BY action": [{"action": "record_rejected", "n": 1}],
    }
    wire(rows, {"metrics.stage_run": True, "provenance.event": True})
    d = body(app.ops_run_detail("r1"))
    kinds = [e["kind"] for e in d["timeline"]]
    assert "timing" in kinds and "event" in kinds, "both sources present in the timeline"
    ats = [e["at"] for e in d["timeline"]]
    assert ats == sorted(ats), "timeline is chronological"
    assert d["stage_rollup"][0]["failures"] == 1
    assert d["reject_reasons"][0]["reason"] == "stale"
    assert any(e["kind"] == "timing" and e["ok"] is False for e in d["timeline"]), "a failure is preserved"
    print("  ok  run detail: timing+event timeline sorted; rollup + reject reasons; failure kept")


def test_run_detail_events_unavailable():
    rows = {"FROM metrics.stage_run WHERE run_id = %s ORDER BY started_at": [
        {"stage": "llm", "doc_id": None, "started_at": "2026-09-06 20:00:00+00",
         "ended_at": "2026-09-06 20:00:15+00", "ms": 15000, "n_items": 1, "n_tokens": 200,
         "ok": True, "host": "vps", "note": None}],
        "FROM metrics.stage_run WHERE run_id = %s GROUP BY stage": [
            {"stage": "llm", "runs": 1, "total_ms": 15000, "avg_ms": 15000, "failures": 0,
             "items": 1, "tokens": 200}]}
    wire(rows, {"metrics.stage_run": True, "provenance.event": False})
    d = body(app.ops_run_detail("r1"))
    assert d["events_note"] and all(e["kind"] == "timing" for e in d["timeline"])
    assert d["action_rollup"] == [] and d["reject_reasons"] == []
    print("  ok  run detail: without provenance.event, timings show and events are unavailable")


def test_run_detail_404():
    wire({}, {"metrics.stage_run": True, "provenance.event": True})
    r = app.ops_run_detail("nope")
    assert r.status_code == 404
    print("  ok  unknown run_id -> clean 404")


if __name__ == "__main__":
    test_overview_readonly_and_shaped()
    test_overview_survives_all_tables_missing()
    test_events_unavailable_and_available()
    test_pipeline_map_is_grounded()
    test_no_writes_issued()
    test_runs_list_stage_run_only()
    test_runs_list_marks_in_progress()
    test_run_detail_timeline_rollup_and_rejects()
    test_run_detail_events_unavailable()
    test_run_detail_404()
    print("ok - ops endpoints: read-only, resilient, grounded")
