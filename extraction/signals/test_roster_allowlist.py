"""The allowlist decides the roster -- and must not drop a company it means to keep.

    docker run ... python3 /w/test_roster_allowlist.py

The failure this guards against is not a filter that is too loose. It is the opposite:
the roster names a company one way and the corpus writes it another, so an exact-name
allowlist silently archives the company it was written to protect. The corpus really
does write "Raytheon" for the row curated as "RTX" (20 cards) and "American Rheinmetall"
for "Rheinmetall" (4), and aliases.same() returns False for both pairs.

No database -- apply_roster_allowlist makes exactly two queries, so a stub cursor is
the whole fixture.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roster                                                         # noqa: E402
from enrich_serving import apply_roster_allowlist                     # noqa: E402


def _with_allowlist(allow):
    """roster.keys() caches for the life of the process -- deliberately, since the
    roster changes when a human edits it, not mid-run. That makes the cache the thing
    a stub cursor cannot override, so reset it explicitly per case rather than letting
    the first real read decide every later assertion."""
    roster._KEYS = None
    return Cur(True, allow)


class Cur:
    """Answers the two queries the function makes."""

    def __init__(self, table_exists, allow):
        self.exists, self.allow = table_exists, allow

    def execute(self, sql, args=None):
        pass

    def fetchone(self):
        return (("serving.competitor_roster_allow" if self.exists else None),)

    def fetchall(self):
        return [(n,) for n in self.allow]


FIFTY = ["RTX", "Kalashnikov", "Huntington Ingalls Industries", "Rheinmetall",
         "Larsen & Toubro", "Bharat Dynamics"]

bad = 0


def check(what, got, want):
    global bad
    if got != want:
        bad += 1
        print("  FAIL %s\n    got  %r\n    want %r" % (what, got, want))


# merge_candidates hands us {survivor: {every spelling folded into it}}
merged = {
    "Raytheon": {"Raytheon", "RTX"},            # roster says RTX, corpus says Raytheon
    "Kalashnikov Concern": {"Kalashnikov Concern"},
    "Rheinmetall": {"Rheinmetall", "American Rheinmetall"},
    "Terma": {"Terma"},                          # genuinely not on the list
    "Saildrone": {"Saildrone"},                  # genuinely not on the list
}
kept = apply_roster_allowlist(_with_allowlist(FIFTY), merged)
check("an alias of a kept company survives", "Raytheon" in kept, True)
check("a legal-suffix variant survives", "Kalashnikov Concern" in kept, True)
check("the plain name survives", "Rheinmetall" in kept, True)
check("a company not on the list goes", "Terma" in kept, False)
check("...and so does the other one", "Saildrone" in kept, False)
check("nothing else crept in", len(kept), 3)

# advisory: absent or empty means no opinion -- never an empty roster
roster._KEYS = None
check("no table -> unchanged", apply_roster_allowlist(Cur(False, []), merged), merged)
check("empty table -> unchanged", apply_roster_allowlist(_with_allowlist([]), merged), merged)

# the alias sets are carried through untouched, not rebuilt
check("alias set preserved", kept["Rheinmetall"], {"Rheinmetall", "American Rheinmetall"})

if bad:
    print("\n%d failure(s)" % bad)
    sys.exit(1)
print("ok - roster allowlist, 9 checks, alias-aware and advisory")
