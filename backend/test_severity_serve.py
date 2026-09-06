# -*- coding: utf-8 -*-
"""The API grades every signal card before it leaves the building.

    python backend/test_severity_serve.py

Severity is DERIVED HERE and served, rather than stored on serving.signal_card. The two
inputs -- the competitor's rated threat level and the card's impact on a KSSL line --
live in two tables that are rebuilt on different schedules, so a stored copy is stale for
exactly as long as the gap between those passes. Derived on the response it cannot
disagree with the rating it came from, and it needs no migration to work.

What must hold for the browser to be able to trust it:

  * every card gets a rank, including the ones that could not be graded -- a MISSING key
    is indistinguishable from an ungraded card once it reaches JSON, and this repo has
    logged that exact confusion ("presence is not shape");
  * `severity` null and `severity` "low" are different answers with different ranks;
  * the alias resolution is the same one the writer uses, so a card written under a
    division still grades against its parent's rating;
  * an empty roster does not silently grade everything as fine.
"""
import os
import sys

os.environ.setdefault("KSSL_CORPUS_DSN", "postgresql://unused/unused")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extraction", "signals"))
import app                                                            # noqa: E402
import threat_gate                                                    # noqa: E402

bad = 0


def check(what, got, want):
    global bad
    if got != want:
        bad += 1
        print("  FAIL %s\n    got  %r\n    want %r" % (what, got, want))


def payload():
    """The shape _dataset has built by the time _grade_cards runs."""
    return {
        "competitors": {
            "rheinmetall": {"name": "Rheinmetall", "threat": "high",
                            "products": [{"name": "PzH 2000", "category": "Artillery"}]},
            "saab": {"name": "Saab", "threat": "medium",
                     "products": [{"name": "Carl-Gustaf M4", "category": "Small Arms"}]},
            # A rated rival whose products were never categorised. Its cards are
            # gradeable to 'adjacent' -- unknown catalogue is not an empty one.
            "otokar": {"name": "Otokar", "threat": "low", "products": ["Cobra II"]},
            # No rating at all. NULL is the honest state for a company nothing
            # measurable placed in a KSSL category, and it must not become 'low'.
            "nexter": {"name": "Nexter", "threat": None, "products": []},
            "kssl": {"name": "Kalyani Strategic Systems", "threat": None, "products": []},
        },
        "competitiveCards": [
            {"id": "a", "dir": "threat", "company": "Rheinmetall MAN",
             "tags": "Artillery", "sec": [1, 2]},
            {"id": "b", "dir": "threat", "company": "Saab", "tags": "Artillery",
             "sec": [1]},
            {"id": "c", "dir": "watch", "company": "Otokar", "tags": "Small Arms",
             "sec": [1]},
            {"id": "d", "dir": "watch", "company": "Nexter", "tags": "Artillery",
             "sec": [1]},
            {"id": "e", "dir": "watch", "company": "Northrop Grumman",
             "tags": "Artillery", "sec": [1]},
            {"id": "f", "dir": "watch", "company": "Saab", "tags": "", "meta": "",
             "sec": []},
        ],
        "marketCards": [],
        "techCards": [],
    }


# THE CALL SITE. Grading that is never invoked is grading that never happened, and a
# unit test that calls the function itself cannot tell the two apart -- it passes
# happily against a _dataset that assembles the payload and ships it ungraded. The one
# line between those two worlds is read here.
import inspect                                                        # noqa: E402
_src = inspect.getsource(app._dataset)
check("_dataset grades the cards it assembled", "_grade_cards(out)" in _src, True)
if "_grade_cards(out)" in _src:
    check("...after the three lanes are loaded",
          _src.index("_grade_cards(out)") > _src.index("out[gname] ="), True)

out = app._grade_cards(payload())
cards = {c["id"]: c for c in out["competitiveCards"]}

# EVERY card carries the four keys. An absent key is not "not assessed" -- it is a card
# the grader never saw, and once it is JSON nobody downstream can tell the two apart.
for cid, c in cards.items():
    for k in ("severity", "severityRank", "impact", "competitor"):
        if k not in c:
            bad += 1
            print("  FAIL card %s is missing %r" % (cid, k))

# a: a division of a high-rated rival, in a line they both sell. The worst case there is.
check("division resolves to its parent", cards["a"].get("competitor"), "Rheinmetall")
check("...and is graded against the parent's rating", cards["a"].get("severity"), "high")
check("...on a direct catalogue overlap", cards["a"].get("impact"), "direct")
check("...with the grounds attached", len(cards["a"].get("impactBasis") or []) > 0, True)

# b: Saab is rated medium and sells small arms, not artillery -> adjacent, one step down.
check("a KSSL line the rival does not sell is adjacent", cards["b"].get("impact"), "adjacent")
check("...and grades one band below", cards["b"].get("severity"), "low")

# c: rated low, catalogue unknown. Unknown is not empty.
check("an uncategorised catalogue still grades", cards["c"].get("impact"), "adjacent")
check("...at the rival's own level", cards["c"].get("severity"), "low")

# d: a rival with NO rating. Not assessed, and not 'low'.
check("no rating -> severity null", cards["d"].get("severity"), None)
check("...ranked last, not with 'low'",
      (cards["d"].get("severityRank") or -1) > threat_gate.severity_rank("low"), True)
check("...but the impact itself was still graded", cards["d"].get("impact"), "adjacent")

# e: not on the roster at all.
check("an untracked company resolves to nobody", cards["e"].get("competitor"), None)
check("...and carries no severity", cards["e"].get("severity"), None)

# f: nothing to grade.
check("an ungradeable card says so", cards["f"].get("impact"), "not_assessed")
check("...in words a reader sees", cards["f"].get("impactLabel"), "impact not assessed")
check("...and is not dropped", "f" in cards, True)

# The label a card shows when there is no rating must not be a rating.
check("the unassessed label is not one of the levels",
      cards["f"].get("severityLabel") not in threat_gate.LEVELS, True)

# THE ROSTER IS THE ONE THE DASHBOARD SERVES. An empty competitors dict is a broken read,
# and the failure mode being fixed is exactly "no roster, so everything passes".
blind = app._grade_cards({"competitors": {}, "competitiveCards": [
    {"id": "z", "dir": "threat", "company": "Rheinmetall", "tags": "Artillery",
     "sec": [1]}]})
z = blind["competitiveCards"][0]
check("an empty roster resolves nobody", z.get("competitor"), None)
check("...and grades nothing", z.get("severity"), None)

# The client is on serving.competitors and is never a rival to itself.
solo = app._grade_cards({
    "competitors": {"kssl": {"name": "Kalyani Strategic Systems", "threat": "high",
                             "products": [{"category": "Artillery"}]}},
    "competitiveCards": [{"id": "y", "dir": "watch",
                          "company": "Kalyani Strategic Systems",
                          "tags": "Artillery", "sec": [1]}]})
check("the client does not grade as its own threat",
      solo["competitiveCards"][0].get("competitor"), None)

if bad:
    print("\n%d failure(s)" % bad)
    sys.exit(1)
print("ok - served severity: every card graded or honestly marked ungraded, "
      "aliases resolved to the parent, null is not low, empty roster grades nothing")
