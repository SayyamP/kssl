"""Append-only provenance events: a queryable record of what happened to a document as
it moved through the pipeline, so the future dashboard (and an engineer today) can answer
"why didn't this document appear?" from data instead of from stdout.

    import provenance
    provenance.emit("signals", "serving_fill.py", "record_rejected",
                    document_id=did, reason="stale", ref_table="serving.signal_card")

DESIGN, and it matches stage_timer.py deliberately -- this is NOT a second run-tracking
system:
  * RUN_ID, HOST, the DSN and the timeouts are stage_timer's, imported, not reinvented.
  * emit() NEVER raises and NEVER blocks: a bad DSN, an unreachable database or a write
    error degrades to a no-op with one warning, and CONSECUTIVE_FAILURES in a row disable
    recording for the rest of the process. Observability must never be why production stops.
  * Append-only: emit() only ever INSERTs. Nothing here updates or deletes.
  * No secrets: model_evidence() keeps only identity/telemetry keys -- never a prompt, a
    response, a key or a full payload.
  * No backfill: the table starts empty and fills only from live calls, so every row is a
    real observed event. Historical documents predating instrumentation simply have none;
    that absence is honest, not a gap to be invented.
"""
import json
import os
import sys

try:
    import psycopg2
    _connect = psycopg2.connect
except ImportError:                                     # pragma: no cover
    try:
        import psycopg
        _connect = psycopg.connect
    except ImportError:
        _connect = None

import stage_timer  # RUN_ID, HOST, _dsn, timeouts -- ONE run identity, shared

ENABLED = os.environ.get("KSSL_PROVENANCE", "1") not in ("0", "false", "no")
CONNECT_TIMEOUT_S = stage_timer.CONNECT_TIMEOUT_S
STATEMENT_TIMEOUT_S = stage_timer.STATEMENT_TIMEOUT_S
CONSECUTIVE_FAILURES = 3

# The lifecycle. A typo must not become a silent action, so emit() checks membership.
ACTIONS = ("selected", "gated", "extracted", "record_rejected", "transformed",
           "card_written", "enriched", "served", "error", "retry")

# Only these keys ever leave a model-call meta dict. NEVER a prompt, response, or key.
SAFE_MODEL_KEYS = ("model", "via", "run_id", "pipeline_version", "model_digest",
                   "lexicon_version", "eval_count", "npredict", "lane", "gliner")

_INSERT = ("INSERT INTO provenance.event "
           "(stage, component, document_id, run_id, ref_table, ref_id, action, "
           " reason, evidence, input_hash, output_hash) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)")

_con = [None]
_failures = [0]
_dead = [False]
_warned = [False]


def _dsn():
    return stage_timer._dsn()


def _warn(msg):
    if not _warned[0]:
        print("provenance: %s (events will not be recorded)" % msg, file=sys.stderr)
        _warned[0] = True


def _reset_con():
    try:
        if _con[0] is not None:
            _con[0].close()
    except Exception:                                   # noqa: BLE001
        pass
    _con[0] = None


def _get_con():
    if _con[0] is not None:
        return _con[0]
    dsn = _dsn()
    if not dsn or _connect is None:
        return None
    c = _connect(dsn, connect_timeout=CONNECT_TIMEOUT_S)
    c.autocommit = True                                 # each event stands alone
    with c.cursor() as cur:
        cur.execute("SET statement_timeout = %d" % (STATEMENT_TIMEOUT_S * 1000))
    _con[0] = c
    return c


def _fail(exc):
    _reset_con()
    _failures[0] += 1
    if _failures[0] >= CONSECUTIVE_FAILURES:
        _dead[0] = True
        print("provenance: %d consecutive failures (%s) -- recording disabled for this "
              "process" % (_failures[0], exc), file=sys.stderr)
    else:
        _warn("could not record: %s" % exc)


def _row(action, stage, component, document_id, run_id, ref_table, ref_id, reason,
         evidence, input_hash, output_hash):
    ev = json.dumps(evidence, default=str) if evidence is not None else None
    return (stage, component, document_id, run_id or stage_timer.RUN_ID, ref_table,
            ref_id, action, reason, ev, input_hash, output_hash)


def _ready():
    if not ENABLED or _dead[0] or _connect is None:
        return False
    if not _dsn():
        _warn("KSSL_DSN is not set")
        return False
    return True


def emit(stage, component, action, document_id=None, run_id=None, ref_table=None,
         ref_id=None, reason=None, evidence=None, input_hash=None, output_hash=None):
    """Append one event. Returns True if written, else False. NEVER raises."""
    try:
        if not _ready():
            return False
        if action not in ACTIONS:
            _warn("unknown action %r -- not recorded" % (action,))
            return False
        con = _get_con()
        if con is None:
            return False
        with con.cursor() as cur:
            cur.execute(_INSERT, _row(action, stage, component, document_id, run_id,
                                      ref_table, ref_id, reason, evidence, input_hash,
                                      output_hash))
        _failures[0] = 0
        return True
    except Exception as exc:                            # noqa: BLE001
        _fail(exc)
        return False


def emit_many(rows):
    """Append many events in one round-trip (executemany). `rows` is an iterable of dicts
    with the same keys emit() takes. Returns the count written (0 on any failure). NEVER
    raises. For high-volume points like the gate, where one INSERT per document is wasteful.
    """
    try:
        if not _ready():
            return 0
        params = []
        for r in rows:
            a = r.get("action")
            if a not in ACTIONS:
                _warn("unknown action %r -- batch skipped that row" % (a,))
                continue
            params.append(_row(a, r.get("stage"), r.get("component"),
                               r.get("document_id"), r.get("run_id"), r.get("ref_table"),
                               r.get("ref_id"), r.get("reason"), r.get("evidence"),
                               r.get("input_hash"), r.get("output_hash")))
        if not params:
            return 0
        con = _get_con()
        if con is None:
            return 0
        with con.cursor() as cur:
            cur.executemany(_INSERT, params)
        _failures[0] = 0
        return len(params)
    except Exception as exc:                            # noqa: BLE001
        _fail(exc)
        return 0


def model_evidence(meta):
    """Only non-secret identity/telemetry keys from a model-call meta dict. NEVER prompts,
    responses, credentials or full payloads."""
    if not isinstance(meta, dict):
        return None
    out = {k: meta[k] for k in SAFE_MODEL_KEYS if k in meta}
    return out or None


def _reset_for_tests():
    """Clear module state between tests."""
    _reset_con()
    _failures[0] = 0
    _dead[0] = False
    _warned[0] = False


def _selfcheck():
    """Runs without a database: emit must measure nothing and never raise."""
    global _connect
    os.environ.pop("KSSL_METRICS_DSN", None)
    os.environ.pop("KSSL_DSN", None)
    _reset_for_tests()
    assert emit("signals", "x.py", "card_written", document_id="d") is False, "no DSN -> no write, no raise"
    assert emit("signals", "x.py", "not_an_action", document_id="d") is False, "bad action rejected"
    assert model_evidence({"model": "m", "via": "farm", "prompt": "SECRET"}) == {"model": "m", "via": "farm"}
    assert model_evidence({"api_key": "sk-xxx"}) is None, "no safe keys -> None, secret dropped"
    # an unreachable database must cost nothing and never raise
    _reset_for_tests()
    os.environ["KSSL_DSN"] = "host=203.0.113.1 port=5432 dbname=x user=x password=x"
    for _ in range(CONSECUTIVE_FAILURES + 1):
        assert emit("signals", "x.py", "error", document_id="d") is False
    assert _dead[0] is True, "circuit breaker must trip"
    print("ok")


if __name__ == "__main__":
    _selfcheck()
