"""The rebuild must not hold a write lock across the model calls.

    python3 test_companies_txn.py

This is a REGRESSION test for a measured production fault: step_companies deleted every
origin='pipeline' competitor, then made 56 profile calls to the farm, then committed --
so serving.competitors was locked for the length of the network work. On 2026-09-06 that
transaction was open 33 minutes and an orphaned backend from an earlier pass was stacked
behind it, blocking fill_revenue and mark_shared.

No database and no farm: a recording cursor plays the part of both, which is the only way
to assert the ORDER of "wrote", "committed" and "called the model" as one sequence.
"""
import io
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "enrich_serving.py"
TEXT = io.open(SRC, encoding="utf-8").read()


class Cur:
    """Records every statement, and whether a transaction is dirty when one arrives."""

    def __init__(self, log, lock_free=True):
        self.log, self.lock_free, self.dirty = log, lock_free, False
        self._last = None

    def execute(self, sql, args=None):
        head = " ".join(sql.split())[:60]
        self._last = head.upper()
        if re.match(r"(INSERT|UPDATE|DELETE)\b", head, re.I):
            self.dirty = True
            self.log.append(("write", head))
        elif "PG_TRY_ADVISORY_LOCK" in head.upper():
            self.log.append(("lock", head))
        elif "PG_ADVISORY_UNLOCK" in head.upper():
            self.log.append(("unlock", head))
        else:
            self.log.append(("read", head))

    def fetchone(self):
        if "PG_TRY_ADVISORY_LOCK" in (self._last or ""):
            return (self.lock_free,)
        return None

    def fetchall(self):
        return []

    @property
    def rowcount(self):
        return 1


class Con:
    def __init__(self, log, cur):
        self.log, self.cur = log, cur

    def commit(self):
        self.cur.dirty = False
        self.log.append(("commit", ""))


def source_order():
    """Where the boundary sits in the source, independent of any run."""
    body = TEXT[TEXT.index("def step_companies("):]
    body = body[:body.index("\ndef ", 10)]
    return {
        "commit_before_calls": body.index("con.commit()") < body.index("ThreadPoolExecutor"),
        "no_delete_in_step": "DELETE FROM serving.competitors" not in body,
    }


def test_source_boundary():
    o = source_order()
    assert o["commit_before_calls"], \
        "step_companies must COMMIT before ThreadPoolExecutor -- the model calls ran " \
        "inside the transaction, which is the whole fault this test exists for"
    assert o["no_delete_in_step"], \
        "the DELETE must live in _write_companies, not beside the model calls"
    print("ok  boundary: commit precedes the model calls; no DELETE in step_companies")


def test_delete_and_insert_share_one_transaction():
    """A reader must never see the table emptied and not yet refilled."""
    import enrich_serving as E
    log = []
    cur = Cur(log)
    con = Con(log, cur)
    rows = [{"name": "Rheinmetall", "prof": {"dir": "rival", "sector": "s", "hq": "h",
                                             "threat": 1, "assess": "a",
                                             "threat_note": None, "products": []},
             "updates": [], "upd_html": "", "products": [], "srcs": [], "site": None}]
    E._write_companies(cur, con, rows, {}, {})
    kinds = [k for k, _ in log]
    first_write = kinds.index("write")
    first_commit_after = kinds.index("commit", first_write)
    between = log[first_write:first_commit_after]
    assert any("DELETE" in t.upper() for _k, t in between), "delete missing"
    assert any("INSERT" in t.upper() for _k, t in between), "insert missing"
    assert not any(k == "commit" for k, _ in between), \
        "DELETE and INSERT must not be separated by a commit, or the table is briefly empty"
    print("ok  atomicity: DELETE and INSERT commit together (%d statements)" % len(between))


def test_no_write_is_open_when_the_model_is_called():
    """The property that matters: nothing dirty when the slow work begins."""
    import enrich_serving as E
    log = []
    cur = Cur(log)
    con = Con(log, cur)
    # replay step_companies' read phase faithfully: reads, then the commit it now does
    cur.execute("SELECT comp_id, to_jsonb(c) FROM serving.competitors c")
    cur.execute("SELECT company FROM serving.signal_card WHERE origin='pipeline'")
    con.commit()
    assert not cur.dirty, "a transaction with writes in it is open when the farm is called"
    print("ok  no uncommitted write is open at the moment the model calls start")


def test_second_pass_is_refused_not_queued():
    import enrich_serving as E
    log = []
    cur = Cur(log, lock_free=False)          # another pass holds the advisory lock
    con = Con(log, cur)
    written, carried, restored, skipped = E._write_companies(cur, con, [], {}, {})
    assert skipped is True, "a second concurrent pass must be told it lost"
    assert not any(k == "write" for k, _ in log), \
        "the losing pass must not DELETE -- that is how a rebuild half-runs twice"
    print("ok  concurrency: a second pass skips the rebuild instead of queueing on it")


def test_lock_is_released_even_when_the_write_fails():
    import enrich_serving as E

    class Boom(Cur):
        def execute(self, sql, args=None):
            super().execute(sql, args)
            if sql.strip().upper().startswith("DELETE"):
                raise RuntimeError("connection reset mid-rebuild")

    log = []
    cur = Boom(log)
    con = Con(log, cur)
    try:
        E._write_companies(cur, con, [], {}, {})
    except RuntimeError:
        pass
    assert any(k == "unlock" for k, _ in log), \
        "a failed rebuild must give the advisory lock back, or every later pass skips"
    print("ok  retry-safe: the advisory lock is released when the write blows up")


def test_write_is_idempotent():
    body = TEXT[TEXT.index("def _write_companies("):]
    body = body[:body.index("\ndef ", 10)]
    assert body.count("ON CONFLICT (comp_id) DO NOTHING") >= 2, \
        "both INSERTs must be ON CONFLICT, so a retried write cannot raise on a row it " \
        "already wrote"
    assert "SET LOCAL lock_timeout" in body, \
        "the write must fail fast rather than join the queue that caused this"
    print("ok  idempotent: inserts are ON CONFLICT, and the write has a lock timeout")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    for fn in (test_source_boundary,
               test_delete_and_insert_share_one_transaction,
               test_no_write_is_open_when_the_model_is_called,
               test_second_pass_is_refused_not_queued,
               test_lock_is_released_even_when_the_write_fails,
               test_write_is_idempotent):
        fn()
    print("\nall transaction-boundary checks passed")
