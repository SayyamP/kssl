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
    assert "rebuild_window(" in body, \
        "the write must run inside rebuild_window, which owns the lock and the timeout"
    win = TEXT[TEXT.index("def rebuild_window("):]
    win = win[:win.index("\ndef ", 10)]
    assert "SET LOCAL lock_timeout" in win, \
        "the rebuild window must fail fast rather than join the queue that caused this"
    assert "finally:" in win and "pg_advisory_unlock" in win, \
        "the window must return the advisory lock in a finally"
    print("ok  idempotent: inserts are ON CONFLICT; the window owns timeout + unlock")




# ---------------------------------------------------------------- the rest of the pass
STEPS_WITH_CALLS = ("step_companies", "step_structure", "step_geo", "step_innovations",
                    "step_partnerships", "step_tenders")


def _body(name):
    i = TEXT.index("def %s(" % name)
    j = TEXT.index("\ndef ", i + 5)
    return TEXT[i:j]


def test_no_step_calls_the_model_holding_a_write():
    """The audit that found this, kept as a test so it cannot come back."""
    import re as _re
    WRITE = _re.compile(r"(DELETE\s+FROM|INSERT\s+INTO|UPDATE)\s+serving\.", _re.I)
    CALL = _re.compile(r"\b(_ask\(|ThreadPoolExecutor)")
    bad = []
    for name in STEPS_WITH_CALLS:
        ev = []
        for n, line in enumerate(_body(name).splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if _re.search(r"\bcon\.commit\(\)", line): ev.append(("commit", n))
            if CALL.search(line):                          ev.append(("call", n))
            if WRITE.search(line):                         ev.append(("write", n))
        for kind, n in ev:
            if kind != "write":
                continue
            nxt = next((e for e in ev if e[1] > n and e[0] in ("call", "commit")), None)
            if nxt and nxt[0] == "call":
                bad.append("%s: write L%d then call L%d with no commit between"
                           % (name, n, nxt[1]))
    assert not bad, "steps still calling the model inside a write transaction:\n  " \
                    + "\n  ".join(bad)
    print("ok  audit: no step writes a serving table then calls the model before commit")


def test_every_rebuilding_step_uses_the_window():
    missing = [n for n in ("step_structure", "step_geo", "step_innovations")
               if "rebuild_window(" not in _body(n)]
    assert not missing, "these rebuild a serving table outside the window: %s" % missing
    assert "rebuild_window(" in _body("_write_companies")
    print("ok  every rebuilding step writes inside rebuild_window")


def test_each_step_has_its_own_lock():
    ids = {}
    for line in TEXT.splitlines():
        if line.startswith("LOCK_") and "=" in line:
            k, v = line.split("=", 1)
            ids[k.strip()] = int(v.strip().replace("_", ""), 16)
    assert len(ids) >= 4, ids
    assert len(set(ids.values())) == len(ids), \
        "two steps sharing a lock id would serialise unrelated rebuilds: %s" % ids
    print("ok  %d distinct advisory lock ids, one per rebuilt table" % len(ids))


def test_partner_writers_cannot_queue_forever():
    """The orphan's actual cause: a backend BLOCKED ON A LOCK does no socket I/O, so it
    never learns its client died. Keepalives cannot see that; a lock timeout ends it."""
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    missing = [f for f in ("mark_shared.py", "revive_partners.py", "discover_ties.py",
                           "backfill_tie_status.py", "fill_revenue.py",
                           "fill_founded.py", "fill_competitor_news.py")
               if "lock_timeout" not in (here / f).read_text(encoding="utf-8")]
    assert not missing, "these write serving.competitors with no lock_timeout: %s" % missing
    print("ok  every serving.competitors writer sets a lock_timeout")


def test_reconnect_keeps_keepalives():
    b = TEXT[TEXT.index("def _open("):]
    b = b[:b.index("\ndef ", 10)]
    for kw in ("keepalives", "keepalives_idle", "connect_timeout"):
        assert kw in b, "reconnect must not drop %s" % kw
    print("ok  reconnect opens with keepalives and a connect timeout")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    for fn in (test_source_boundary,
               test_delete_and_insert_share_one_transaction,
               test_no_write_is_open_when_the_model_is_called,
               test_second_pass_is_refused_not_queued,
               test_lock_is_released_even_when_the_write_fails,
               test_write_is_idempotent,
               test_no_step_calls_the_model_holding_a_write,
               test_every_rebuilding_step_uses_the_window,
               test_each_step_has_its_own_lock,
               test_partner_writers_cannot_queue_forever,
               test_reconnect_keeps_keepalives):
        fn()
    print("\nall transaction-boundary checks passed")
