"""THE ROSTER GATE MUST READ THE CLIENT'S OWN CATALOGUE.

Reported from the dashboard: northropgrumman.com is in the corpus (38 pages), Northrop
Grumman is on the curated allowlist, it carries 13 signal cards -- and it is not on the
Competitor tab.

It was refused by competes_with_kssl for having nothing in KSSL's nine categories. That
verdict was reached from the products the model read out of the CORPUS, which for a
company the corpus covers heavily is the worst evidence available -- the SPREAD_STATEMENTS
comment measured it: "Northrop 475 docs, 1,113 statements -> a torpedo and a mine
detector". Meanwhile serving.competitor_product, the client's own audited workbook, lists
Northrop with four ammunition lines, and ammunition is one of the nine.

The gate had the answer and no way to look at it. These checks are about that lookup, and
about it staying a piece of EVIDENCE rather than becoming a bypass.

    python test_workbook_bands.py
"""
import re
import sys

sys.path.insert(0, ".")

import enrich_serving as es

FAILS = []


def ck(name, ok, detail=""):
    print("  %-70s %s%s" % (name, "ok" if ok else "FAIL", "" if ok else "  " + str(detail)))
    if not ok:
        FAILS.append(name)


class FakeCur:
    """Just enough cursor: the regclass probe, then the workbook rows."""

    def __init__(self, rows, exists=True):
        self.rows, self.exists, self._out = rows, exists, []

    def execute(self, sql, args=None):
        self._out = [(self.exists and "serving.competitor_product" or None,)] \
            if "to_regclass" in sql else list(self.rows)

    def fetchone(self):
        return self._out[0]

    def fetchall(self):
        return self._out


ROWS = [
    ("Northrop Grumman", "Ammunition"),
    ("Northrop Grumman", "UAVs/Drones"),
    ("Huta Stalowa Wola (HSW)", "Artillery"),
    ("Huntington Ingalls Industries", "Marine/Naval"),
    ("Kalyani Strategic Systems", "Artillery"),
]

es._WORKBOOK_BANDS = es._workbook_band_map(FakeCur(ROWS))

ck("the workbook's ammunition credit reaches the gate",
   "ammo" in es.workbook_bands("Northrop Grumman"), es.workbook_bands("Northrop Grumman"))

# The workbook writes "Huta Stalowa Wola (HSW)"; the roster and corpus write it without
# the expansion. A parenthetical is not a different company.
ck("a parenthetical expansion still matches the plain name",
   "art" in es.workbook_bands("Huta Stalowa Wola"), es.workbook_bands("Huta Stalowa Wola"))
ck("...and the workbook's own spelling matches too",
   "art" in es.workbook_bands("Huta Stalowa Wola (HSW)"))

# THE CHECK THAT THIS IS EVIDENCE AND NOT A BYPASS. A shipyard is in the workbook and is
# still not in KSSL's business; if this ever returns a band, the gate has stopped gating.
ck("a shipyard gains NO band, because Marine/Naval is not one of the nine",
   es.workbook_bands("Huntington Ingalls Industries") == set(),
   es.workbook_bands("Huntington Ingalls Industries"))

ck("the client is never credited as its own rival",
   es.workbook_bands("Kalyani Strategic Systems") == set())

ck("a company absent from the workbook gains nothing",
   es.workbook_bands("Some Company Nobody Catalogued") == set())

# NEVER FATAL. The archive lookup beside this one is wrapped for the same reason: a gate
# is a refinement, and must not be the reason a pass dies.
es._WORKBOOK_BANDS = es._workbook_band_map(FakeCur([], exists=False))
ck("no workbook table means no opinion, not a crash", es.workbook_bands("Northrop Grumman") == set())


class Boom:
    def execute(self, *a, **k):
        raise RuntimeError("db is down")

    def fetchone(self):
        raise RuntimeError("db is down")


es._WORKBOOK_BANDS = es._workbook_band_map(Boom())
ck("an unreachable database means no opinion, not a crash",
   es.workbook_bands("Northrop Grumman") == set())

print("")
print("%d FAILED" % len(FAILS) if FAILS
      else "ok - the gate reads the client's catalogue, and shipyards still do not pass")
sys.exit(1 if FAILS else 0)
