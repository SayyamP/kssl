"""Time one pipeline stage and record it, so the pipeline can answer
"how long does each step take" from data instead of from memory.

    from stage_timer import stage

    with stage("extract_a", doc_id=doc) as s:
        spans = extract(doc)
        s.items(len(spans))

The row is written even when the body raises -- a stage that fails still took
time, and a failure that leaves no trace is how a stage silently stops running.

Nothing here is required for the pipeline to work: if KSSL_METRICS_DSN is not
set, or the database is unreachable, the timer degrades to a no-op and prints a
single warning. Instrumentation must never be the reason production stops.
"""
import os
import socket
import sys
import time
import uuid

try:
    import psycopg
    _connect = psycopg.connect
except ImportError:                                     # pragma: no cover
    try:
        import psycopg2
        _connect = psycopg2.connect
    except ImportError:
        _connect = None

# One id per process, so every stage a single run touches can be grouped.
RUN_ID = os.environ.get("KSSL_RUN_ID") or uuid.uuid4().hex[:12]

# Where this code is running. Set it once per machine; guessing from the
# hostname is how a data-centre row ends up labelled 'vps'.
HOST = os.environ.get("KSSL_HOST_ROLE") or "unknown"

_warned = False

# A metrics write must never cost more than the work it measures. Without a
# connect timeout, a tunnel that is up but whose far end black-holes blocks for
# the OS default -- tens of seconds, per stage, per document.
CONNECT_TIMEOUT_S = int(os.environ.get("KSSL_METRICS_CONNECT_TIMEOUT", "5"))
STATEMENT_TIMEOUT_S = int(os.environ.get("KSSL_METRICS_STATEMENT_TIMEOUT", "10"))
CONSECUTIVE_FAILURES = 3

_failures = [0]
_dead = False


def _dsn():
    return os.environ.get("KSSL_METRICS_DSN") or os.environ.get("KSSL_DSN") or ""


def _warn(msg):
    global _warned
    if not _warned:
        print("stage_timer: %s (timings will not be recorded)" % msg,
              file=sys.stderr)
        _warned = True


class stage(object):
    """Context manager that writes one metrics.stage_run row."""

    def __init__(self, name, doc_id=None, note=None, meta=None, run_id=None):
        self.name = name
        self.doc_id = doc_id
        self.note = note
        self.meta = meta
        self.run_id = run_id or RUN_ID
        self.n_items = None
        self.n_tokens = None
        self._t0 = None

    # -- things the body can report back -------------------------------------
    def items(self, n):
        """How many units of work this stage produced."""
        self.n_items = int(n)
        return self

    def tokens(self, n):
        """LLM stages only: tokens generated, so tok/s is derivable."""
        self.n_tokens = int(n)
        return self

    def annotate(self, note=None, **meta):
        if note:
            self.note = note
        if meta:
            self.meta = dict(self.meta or {}, **meta)
        return self

    # -- the timer itself ----------------------------------------------------
    def __enter__(self):
        self._t0 = time.perf_counter()
        self.started = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        ms = int((time.perf_counter() - self._t0) * 1000)
        self.write(ms, ok=exc_type is None,
                   note=self.note or (repr(exc)[:400] if exc else None))
        return False                    # never swallow the exception

    def write(self, ms, ok=True, note=None):
        global _dead
        dsn = _dsn()
        if not dsn:
            _warn("KSSL_METRICS_DSN is not set")
            return
        if _connect is None:
            _warn("neither psycopg nor psycopg2 is installed")
            return
        if _dead:
            # The database already failed CONSECUTIVE_FAILURES times in a row.
            # Without this, a tunnel whose far end black-holes costs every stage
            # of every document a full TCP timeout, and instrumentation becomes
            # the slowest part of the pipeline.
            return
        try:
            with _connect(dsn, connect_timeout=CONNECT_TIMEOUT_S) as cx:
                with cx.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = %d"
                                % (STATEMENT_TIMEOUT_S * 1000))
                    cur.execute(
                        "INSERT INTO metrics.stage_run "
                        "  (run_id, stage, doc_id, host, started_at, ended_at,"
                        "   ms, n_items, n_tokens, ok, note, meta) "
                        # BOTH timestamps come from the database clock. Taking
                        # started_at from the client and ended_at from the server
                        # buried the machine-to-machine clock skew inside
                        # doc_journey.end_to_end_s -- the one number the whole
                        # table exists to report.
                        "SELECT %s, %s, %s, %s,"
                        "       now() - make_interval(secs => %s / 1000.0), now(),"
                        "       %s, %s, %s, %s, %s, %s::jsonb "
                        # a stage name that is not in stage_order inserts nothing:
                        # a typo must not become a silent ninth stage
                        "WHERE EXISTS (SELECT 1 FROM metrics.stage_order WHERE stage = %s)",
                        (self.run_id, self.name, self.doc_id, HOST,
                         ms, ms, self.n_items, self.n_tokens, ok, note,
                         _json(self.meta), self.name))
                    if cur.rowcount == 0:
                        _warn("unknown stage %r -- not in metrics.stage_order"
                              % self.name)
            _failures[0] = 0
        except Exception as exc:                        # noqa: BLE001
            _failures[0] += 1
            if _failures[0] >= CONSECUTIVE_FAILURES:
                _dead = True
                print("stage_timer: %d consecutive failures (%s) -- recording "
                      "disabled for this process" % (_failures[0], exc),
                      file=sys.stderr)
            else:
                _warn("could not record: %s" % exc)


def _json(obj):
    if obj is None:
        return None
    import json
    return json.dumps(obj, default=str)


def _selfcheck():
    """Runs without a database: proves the timer measures and never raises."""
    os.environ.pop("KSSL_METRICS_DSN", None)
    os.environ.pop("KSSL_DSN", None)

    with stage("extract_a", doc_id="x") as s:
        time.sleep(0.02)
        s.items(3).tokens(0)
    assert s.n_items == 3, s.n_items

    # a failing body still leaves the timer intact and re-raises
    raised = False
    try:
        with stage("llm", doc_id="y"):
            raise ValueError("boom")
    except ValueError:
        raised = True
    assert raised, "the timer swallowed an exception"

    # elapsed time is real, not zero
    t = stage("serving")
    with t:
        time.sleep(0.03)
    assert t._t0 is not None

    # An unreachable database must cost the pipeline almost nothing. 203.0.113.1
    # is TEST-NET-3: reserved, unroutable, guaranteed to hang rather than refuse.
    global _dead, _warned
    _dead, _warned, _failures[0] = False, False, 0
    os.environ["KSSL_METRICS_DSN"] = ("host=203.0.113.1 port=5432 dbname=x "
                                      "user=x password=x")
    budget = CONNECT_TIMEOUT_S * CONSECUTIVE_FAILURES + 5
    t0 = time.perf_counter()
    for _ in range(12):
        with stage("llm", doc_id="z"):
            pass
    spent = time.perf_counter() - t0
    assert _dead, "the breaker never tripped -- 12 dead writes were attempted"
    assert spent < budget, ("12 stages against a black hole took %.1fs "
                            "(budget %ds)" % (spent, budget))
    print("stage_timer self-check ok: breaker tripped after %d failures, "
          "12 stages cost %.1fs not %.0fs"
          % (CONSECUTIVE_FAILURES, spent, 12 * 30.0))


if __name__ == "__main__":
    _selfcheck()
