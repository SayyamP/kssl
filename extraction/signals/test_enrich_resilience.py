"""Checks that one dying step no longer takes the whole enrich pass down.

    python extraction/signals/test_enrich_resilience.py     # inside the image

This is the failure that actually happened in production: step 1 of 7 lost its
Postgres connection to an unrelated `pg_terminate_backend`, raised, and the six
later steps -- partnerships, geo, tenders, innovations, sources, matchups -- were
never reached. Six empty tables from one dropped socket.

Runs no SQL and calls no model: `run()` is driven with fake steps and a fake
connection, so what is under test is the control flow and nothing else.
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import enrich_serving as E                                           # noqa: E402

fails = []


def check(name, ok, detail=""):
    print("  %s %-56s %s" % ("ok  " if ok else "FAIL", name, detail))
    if not ok:
        fails.append(name)


class FakeCur:
    def __init__(self, con):
        self.con = con

    def execute(self, *a, **k):
        if self.con.dead:
            raise RuntimeError("server closed the connection unexpectedly")

    def fetchone(self):
        return (1,)


class FakeCon:
    def __init__(self):
        self.dead = False
        self.closed_n = 0

    def cursor(self):
        return FakeCur(self)

    def commit(self):
        if self.dead:
            raise RuntimeError("server closed the connection unexpectedly")

    def rollback(self):
        pass

    def close(self):
        self.closed_n += 1


opened = []


def fake_open(dsn):
    con = FakeCon()
    opened.append(con)
    return con, con.cursor()


# --- harness -------------------------------------------------------------
_real = (E._open, E.load_docs, E.load_props, E.suppressed_ids, E.STEPS)
E._open = fake_open
E.load_docs = lambda cur: {"d1": {"url": "u", "source": "s"}}
E.load_props = lambda cur: {"d1": []}
E.suppressed_ids = lambda: set()

ran = []


def ok_step(name):
    def f(cur, con, docs, props, limit=None):
        ran.append(name)
        return {"written": 1}
    return f


def raising_step(cur, con, docs, props, limit=None):
    ran.append("boom")
    raise RuntimeError("step blew up")


def killing_step(cur, con, docs, props, limit=None):
    """Behaves like the real failure: the shared connection goes away mid-step."""
    ran.append("kill")
    opened[-1].dead = True
    raise Exception("server closed the connection unexpectedly")


try:
    # 1. a step that raises must not stop the steps after it
    ran.clear(); opened.clear()
    E.STEPS = [("a", ok_step("a")), ("b", raising_step), ("c", ok_step("c"))]
    res = E.run(dsn="fake")
    check("later steps still run after a raise", ran == ["a", "boom", "boom", "c"],
          "ran=%s" % ran)
    check("the failed step is recorded, not silently absent",
          "error" in res.get("b", {}), "b=%r" % res.get("b"))
    check("the good steps kept their results",
          res.get("a") == {"written": 1} and res.get("c") == {"written": 1})

    # 2. the production failure: connection killed mid-step -> reconnect, continue
    ran.clear(); opened.clear()
    E.STEPS = [("a", killing_step), ("b", ok_step("b")), ("c", ok_step("c"))]
    res = E.run(dsn="fake")
    check("a dead connection is reconnected, not fatal", ran[-2:] == ["b", "c"],
          "ran=%s" % ran)
    check("reconnect actually opened a new connection", len(opened) >= 2,
          "%d opened" % len(opened))
    check("six later steps are no longer lost to step 1",
          res.get("b") == {"written": 1} and res.get("c") == {"written": 1})

    # 3. a clean pass reports clean
    ran.clear(); opened.clear()
    E.STEPS = [("a", ok_step("a")), ("b", ok_step("b"))]
    res = E.run(dsn="fake")
    check("clean pass returns every step", sorted(res) == ["a", "b"])
    check("no error key on a clean pass",
          not any("error" in v for v in res.values()))

    # 4. --only still selects a single step
    ran.clear(); opened.clear()
    E.STEPS = [("a", ok_step("a")), ("b", ok_step("b"))]
    res = E.run(only="b", dsn="fake")
    check("--only runs just that step", ran == ["b"] and list(res) == ["b"])

    # 5. _live is a predicate, never a raise
    c = FakeCon()
    check("_live true on a healthy connection", E._live(c) is True)
    c.dead = True
    check("_live false on a dead one, no exception", E._live(c) is False)
finally:
    E._open, E.load_docs, E.load_props, E.suppressed_ids, E.STEPS = _real

print()
print("all enrich-resilience checks passed" if not fails
      else "FAILED: %s" % ", ".join(fails))
sys.exit(1 if fails else 0)
