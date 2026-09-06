# -*- coding: utf-8 -*-
"""The matchup reviver: its own demo, plus the advantage-bullet grounder.

    python test_revive_matchups.py

revive_matchups.py writes every served Positioning row and `--demo` was in no check.
The bullet grounder had three faults at once: it never asked what the row was about,
its "near the product" was a whole-document scan, and its word test was `t in text`.

Hermetic: no database, no network, no model.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import revive_matchups as rm  # noqa: E402


def _doc(text):
    return [("d1", "https://example.gov/1", rm.norm(text))]


def test_demo():
    rm._demo()


def test_words_must_be_words():
    """`t in text` is a substring test: "base" is inside "database", "arms" inside
    "disarmament", "range" inside "arrangement"."""
    d = _doc("the atags database lists disarmament records and many arrangements")
    assert rm.ground_phrase(d, ["atags"], "wide base for arms exports", "ATAGS") is None
    ok = _doc("the atags has a wide base and arms exports follow")
    assert rm.ground_phrase(ok, ["atags"], "wide base for arms exports", "ATAGS")


def test_near_the_product_must_mean_near():
    """The docstring said "stated near the product". `spans` was computed and then
    only tested for truthiness; the words were looked for in the whole document."""
    near = _doc("the atags gun offers indigenous barrels and forged components")
    assert rm.ground_phrase(near, ["atags"], "indigenous forged components", "ATAGS")
    far = _doc("atags. " + ("filler word " * 200) + " indigenous forged components")
    assert rm.ground_phrase(far, ["atags"], "indigenous forged components",
                            "ATAGS") is None


def test_the_row_says_what_it_is_about():
    """An artillery blurb was published on a UAV matchup because `cat`/`catKey` was
    never consulted."""
    d = _doc("the bharat 150 uses athos atmos 52-cal guns with longer barrels")
    blurb = "ATHOS/ATMOS 52-cal guns, longer barrels"
    assert rm.ground_phrase(d, ["bharat"], blurb, "Bharat 150", catkey="uav") is None
    assert rm.ground_phrase(d, ["bharat"], blurb, "Bharat 150", cat="UAVs & Drones") is None
    # the same words on a row they belong to are not refused
    assert rm.ground_phrase(d, ["bharat"], blurb, "Bharat 150", catkey="art")
    # ...and a category with no kind bucket refuses nothing
    assert rm.ground_phrase(d, ["bharat"], blurb, "Bharat 150", catkey="msl")


def test_a_copied_verdict_is_not_republished():
    """The module recomputes edge and verdict precisely so a verdict written about ten
    specs is not printed over the two that could be grounded. 468 bullets reading
    "Leads on Weight (3.15 kg)" were exempted from that rule."""
    d = _doc("the atags weight is 3.15 kg per the maker and it leads the field")
    assert rm.ground_phrase(d, ["atags"], "Leads on Weight (3.15 kg)", "ATAGS") is None
    assert rm.ground_phrase(d, ["atags"], "ahead of every rival on weight",
                            "ATAGS") is None
    # "leading" is NOT a verdict word: a credential is not a claim about this pairing
    cred = _doc("kalyani is the leading indigenous forging house in the country")
    assert rm.ground_phrase(cred, ["kalyani"], "leading indigenous forging house",
                            "Kalyani")


def test_a_number_in_a_bullet_is_a_claim_too():
    """The token filter drops anything of three characters or fewer, so "3.15" split
    to "3" and "15" and was never looked for at all."""
    d = _doc("the atags gun holds 40 percent of the indigenous artillery orders")
    assert rm.ground_phrase(d, ["atags"], "40 percent of indigenous orders", "ATAGS")
    assert rm.ground_phrase(d, ["atags"], "70 percent of indigenous orders",
                            "ATAGS") is None
    # and the guard that stops "41" matching inside "341" applies here too
    big = _doc("the atags gun covered 341 percent growth in indigenous orders")
    assert rm.ground_phrase(big, ["atags"], "41 percent of indigenous orders",
                            "ATAGS") is None
    # ...but a drive configuration is part of a NAME. "on 4x4" asserts no magnitude,
    # and demanding a bare "4" beside the product refused the list for nothing.
    assert rm.bullet_numbers("155/39 on 4x4; shoot-and-scoot") == ["155", "39"]
    assert rm.bullet_numbers("Boxer 8x8, fires on move") == []


def test_every_refusal_is_counted():
    """A bullet is a published claim like any other, and it was the only one with no
    refusal count behind it."""
    rm.ADV_REFUSED.clear()
    d = _doc("nothing relevant here at all")
    rm.ground_phrase(d, ["atags"], "Leads on Weight (3.15 kg)", "ATAGS")
    rm.ground_phrase(d, ["atags"], "one", "ATAGS")
    rm.ground_phrase(d, ["atags"], "indigenous forged components", "ATAGS")
    assert sum(rm.ADV_REFUSED.values()) == 3, dict(rm.ADV_REFUSED)
    assert len(rm.ADV_REFUSED) == 3, "three different faults, three different reasons"
    rm.ADV_REFUSED.clear()


def test_edge_and_verdict_are_one_definition_each():
    lead = [{"l": "Max range", "cn": 30000, "kn": 41000, "hi": True}]
    assert rm.edge_of(lead) == 75
    assert "KSSL leads on 1 of 1" in rm.verdict_of(lead, "KNDS", "KSSL")
    # a dimension class_axis has marked is shown but decides nothing
    marked = [dict(lead[0], classAxis="towed vs self-propelled")]
    assert rm.comparable(marked) == [] and rm.edge_of(marked) is None
    assert "none comparable on both sides" in rm.verdict_of(marked, "KNDS", "KSSL")
    # nothing sourced is not the same statement as "level"
    assert rm.edge_of([]) is None


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("  PASS  %s" % name)
        except AssertionError as e:
            fails += 1
            print("  FAIL  %s: %s" % (name, e))
    print("%s" % ("all checks passed" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
