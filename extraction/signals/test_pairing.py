# -*- coding: utf-8 -*-
"""Whether two products may be compared at all -- the gate, under test.

    python test_pairing.py

pairing.py decides which of the 507 archived matchups reach the Positioning tab, and
it had NO test and was in no check. deploy/selfcheck.sh runs `for t in test_*.py`, so
this file is the whole wiring: it exists, therefore it gates a pull request and a push
to main. Its demo() already carried good assertions ("Cleaver is not Kalyani M4") and
nothing ever ran them.

Hermetic: no database, no network, no model.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pairing  # noqa: E402


def test_demo():
    """The module's own checks, which nothing was running."""
    assert pairing.demo() == 0, "pairing.demo() reported failures"


def test_initialism_cannot_collide():
    """norm("MaRG 45") -> ['marg','45'] -> 'm' + '4' -> "m4".

    same_product("M4", "MaRG 45") therefore returned True and an armoured vehicle was
    validated as a client product by a wheeled howitzer. An initialism is built from
    WORDS, and from at least three of them."""
    assert pairing.initialism("MaRG 45") == ""
    assert pairing.initialism("PzH 2000") == ""
    assert pairing.initialism("Kalyani M4") == ""
    assert not pairing.same_product("M4", "MaRG 45")
    assert not pairing.same_product("ATC", "AT 4")
    # ...and every abbreviation the client actually uses still resolves
    for short, long in (("MPV", "Mine Protected Vehicle"),
                        ("LTV", "Light Tactical Vehicle"),
                        ("ULSV", "Ultra Light Specialist Vehicle"),
                        ("LBPV", "Light Bullet Proof Vehicle")):
        assert pairing.same_product(short, long), (short, long)
    # a single token that IS one of the product's own words is a different rule and
    # is untouched
    assert pairing.same_product("M4", "Kalyani M4")
    assert pairing.same_product("MArG 155", "MaRG 155-BR")


def test_empty_list_is_a_refusal():
    """A gate that cannot fail closed is not a gate.

    `if roster_names:` and `if client_products:` skipped the check when the list was
    empty -- the state of a database whose serving.competitors or
    serving.client_product has not been loaded, which is precisely when an unchecked
    pairing gets published."""
    row = {"comp": "HESA · Shahed-136", "compBy": "HESA",
           "bf": "KSSL · Bayonet", "bfBy": "KSSL",
           "specs": [{"l": "Range", "cn": 2500, "kn": 200, "hi": True}]}
    os.environ.pop(pairing.ALLOW_EMPTY, None)
    assert pairing.refuse(row, [], [])[0] is not None
    assert pairing.refuse(row, [], ["Bharat 150 UAV"])[0] == \
        "no tracked-competitor roster to check the maker against"
    assert pairing.refuse(row, ["Adani Defence"], [])[0] == \
        "no client portfolio to check the KSSL side against"
    # a list of empty strings is an empty list
    assert pairing.refuse(row, ["", None], ["", None])[0] is not None
    # the override is named, opt-in, and restores the old behaviour exactly
    os.environ[pairing.ALLOW_EMPTY] = "1"
    pairing._warned[0] = True                # the warning text is not under test here
    try:
        assert pairing.refuse(row, [], [])[0] is None
    finally:
        os.environ.pop(pairing.ALLOW_EMPTY, None)
        pairing._warned[0] = False


def test_direction_is_a_property_of_the_field():
    """The archive typed `hi` per ROW and disagreed with itself.

    Rate of fire is directional on 1 of the 35 live rows that carry it, so this gate
    called the same field comparable on one pairing and not on the next."""
    for hi in (True, False, None):
        assert pairing.shared_measurables(
            [{"l": "Rate of fire", "cn": 6, "kn": 5, "hi": hi}])[0] == 1
        assert pairing.shared_measurables(
            [{"l": "Calibre", "cn": 155, "kn": 105, "hi": hi}])[0] == 0
    # "2 + 10" against "8-14 personnel" is a crew count plus a troop count
    assert pairing.shared_measurables(
        [{"l": "Crew / pax", "cn": 3, "kn": 8, "hi": True}])[0] == 0
    # a label the table has never seen still falls back to the row, then to the regex
    assert pairing.shared_measurables(
        [{"l": "Widget index", "cn": 1, "kn": 2, "hi": True}])[0] == 1
    assert pairing.shared_measurables(
        [{"l": "Widget index", "cn": 1, "kn": 2, "hi": None}])[0] == 0
    assert pairing.shared_measurables(
        [{"l": "Widget type", "cv": "1", "kv": "2"}])[0] == 0, "AXIS_FIELDS fallback"
    # A blanked cn is a DECISION, not a missing value: rebuild() nulls both sides when
    # their units resolve to different quantities. Reading the numbers back out of the
    # display text would undo that and put "47 t vs 18000 kg" back on the screen.
    assert pairing.shared_measurables(
        [{"l": "Weight", "cn": None, "kn": None, "cv": "47", "kv": "18000 kg"}])[0] == 0
    # ...while a row that carries no cn/kn at all is still read from its text
    assert pairing.shared_measurables(
        [{"l": "Weight", "cv": "47 t", "kv": "18 t"}])[0] == 1


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
