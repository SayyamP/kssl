#!/usr/bin/env python3
"""The summary backfill must ADVANCE. Driven with a stubbed cursor -- no database.

THE BUG THIS EXISTS TO PREVENT has already happened once in this file, to the
translation pass: `retranslate` selected `ORDER BY d.id LIMIT 200` with nothing
recording what it had done, so the same first 200 of 949 cards were re-asked every
signals cycle -- roughly 17 minutes of farm time per replica, for no change -- and cards
201..949 were never reached at all (9dee205).

`--resummarise` is one model call over up to 7000 characters of article for EVERY card
it scans, run by six replicas every 120 seconds. If it does not advance, it is the most
expensive loop in the system.

Advancing rests on one rule that is easy to write backwards: a REFUSAL MUST BE MARKED.
summarize() returns None for a real reason -- an article under 200 characters, or a
summary that came back in the source language after a retry -- and if the row is only
marked when a summary was produced, every refusal is retried for ever. Writing
`if summary:` around the UPDATE is a one-word change that reintroduces the whole defect
and breaks no other test.

A transport failure is NOT a refusal and must leave the row unmarked, so the next cycle
retries it. That is the other half, and it fails the same way in reverse.

Run: python3 test_resummarise.py       (picked up by selfcheck's test_*.py loop)
"""
import sys
import types
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

fails = 0


def ck(name, expected, actual):
    global fails
    if expected == actual:
        print("  %-62s ok" % name)
    else:
        print("  %-62s FAIL (want %r, got %r)" % (name, expected, actual))
        fails += 1


# ---- the stub -------------------------------------------------------------------
# Answers by query shape, and records every write so the assertions can read them back.
class Cur:
    def __init__(self, rows):
        self.rows = rows
        self.writes = []          # (sql, params) for every UPDATE
        self._last = None

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self._last = flat
        if "information_schema.columns" in flat:
            self._result = [(1,)]                       # the column exists
        elif flat.startswith("SELECT d.id"):
            self._result = list(self.rows)
            self.select = flat
            self.select_params = params
        elif flat.startswith("UPDATE"):
            self.writes.append((flat, params))
            self._result = []
        else:
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


class Con:
    def __init__(self, cur):
        self.cur = cur
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def run(rows, answers):
    """answers: id -> a summary string, None (refusal), or an Exception to raise."""
    cur = Cur(rows)
    fake = types.ModuleType("psycopg2")
    fake.connect = lambda dsn: Con(cur)
    sys.modules["psycopg2"] = fake

    import serving_fill
    import summarize

    def fake_summarize(text, title=None, language=None, ask=None, stats=None):
        a = answers[fake_summarize.i]
        fake_summarize.i += 1
        if isinstance(a, Exception):
            raise a
        if a is None and stats is not None:            # a refusal states its reason
            stats["summary_thin"] = stats.get("summary_thin", 0) + 1
        return a
    fake_summarize.i = 0

    real = summarize.summarize
    serving_fill.ask = lambda *a, **k: "unused -- summarize is stubbed"
    summarize.summarize = fake_summarize
    try:
        stats = serving_fill.resummarise(dsn="stub", limit=10, apply=True, verbose=False)
    finally:
        summarize.summarize = real
    return cur, stats


D = "the article body, long enough to be worth summarising " * 8
ROWS = [("pl_doc_a", "en", "A", D), ("pl_doc_b", "ru", "B", D), ("pl_doc_c", "it", "C", D)]

print("resummarise:")

# ---- the window advances over all three outcomes ---------------------------------
cur, stats = run(ROWS, ["<p>a real summary</p>", None, RuntimeError("farm unreachable")])

ck("a summary is stored", 1, sum(1 for _s, p in cur.writes if p[0]))
ck("...and the row is marked with the prompt version", 1,
   sum(1 for _s, p in cur.writes if p[0] and p[1] == "s1"))

# THE ONE THAT MATTERS.
ck("A REFUSAL IS ALSO MARKED, or it is re-asked for ever", 1,
   sum(1 for _s, p in cur.writes if p[0] is None and p[1] == "s1"))

# ...and the other half of the same rule.
ck("a transport failure is NOT marked, so it retries", 3,
   len(cur.writes) + 1)          # 2 writes for 3 cards: the raiser wrote nothing
ck("...so exactly two of three cards were written", 2, len(cur.writes))

# A refused row must not lose the summary it already had.
ck("the UPDATE coalesces, so None cannot wipe a good summary", True,
   all("coalesce(%s, summary)" in s for s, _p in cur.writes))

# ---- the cursor is the version column, not the summary itself --------------------
ck("the window filters on `summarised`, not `summary IS NULL`", True,
   "d.summarised IS DISTINCT FROM" in cur.select and "summary IS NULL" not in cur.select)
ck("...oldest first, so a re-run continues rather than restarts", True,
   "ORDER BY d.summarised NULLS FIRST, d.updated_at" in cur.select)
ck("...and it is the prompt version that is compared", True, "s1" in cur.select_params)

# ---- concurrency + progress ------------------------------------------------------
ck("six replicas cannot pick the same rows", True, "FOR UPDATE OF d SKIP LOCKED" in cur.select)
ck("a pruned document is never a candidate (JOIN, not LEFT JOIN)", True,
   "JOIN extracted.document" in cur.select and "LEFT JOIN extracted.document" not in cur.select)
ck("only pipeline rows, never reference data", True, "d.origin='pipeline'" in cur.select)

# ---- an outage is reported, not reported as success ------------------------------
_cur2, stats2 = run(ROWS, [None, None, None])
ck("every card refused for a stated reason is NOT an alert", 3, stats2["cards"])
_cur3, stats3 = run(ROWS, [RuntimeError("x"), RuntimeError("x"), RuntimeError("x")])
ck("scanned some, wrote none, refused none -> outage (returns None)", None, stats3)

print("ok - the summary window advances, marks refusals, and retries transport failures"
      if not fails else "%d FAILED" % fails)
sys.exit(1 if fails else 0)
