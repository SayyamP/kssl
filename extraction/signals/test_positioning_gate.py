# -*- coding: utf-8 -*-
"""The like-for-like gate, and proof that it is in the tree that runs.

    python test_positioning_gate.py

positioning_gate.py and class_axis.py existed ONLY under pipeline/. The containers run
extraction/signals (pipeline/_superseded.py says so; deploy/selfcheck.sh does
`cd extraction/signals`), and `grep -rn "positioning_gate\\|class_axis" extraction/`
returned nothing -- so a gate written to stop "Shell forgings vs Excalibur" and
"CQB Carbine vs a tank machine gun" had never been asked about a published row. The
last test here is the one that matters: it fails if the gate is ever unwired again.

Hermetic: no database, no network, no model.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import class_axis  # noqa: E402
import positioning_gate as pg  # noqa: E402
import revive_matchups  # noqa: E402


def test_demo():
    pg.demo()


def test_class_axis_demo():
    class_axis._demo()


def test_the_two_rows_the_operator_caught():
    v, _k, why = pg.gate("KSSL · Shell forgings", "Raytheon · Excalibur (precision)")
    assert v == "refuse", (v, why)
    v, _k, why = pg.gate("KSSL · CQB Carbine", "AWEIL · MTMG tank machine gun")
    assert v == "refuse", (v, why)


def test_three_states_not_two():
    """A REFUSE is a finding; an UNRESOLVED is a gap in our sourcing.

    Collapsing them reported "200 of 219 refused", which reads as "the pairings are
    wrong" when 165 of them were only "this name means nothing to a keyword table"."""
    assert pg.gate("KSSL · ATAGS", "BAE Systems · M777")[0] == "pass"
    assert pg.gate("KSSL · ATAGS", "Some Co · Kestrel")[0] == "unresolved"
    assert pg.gate("KSSL · CQB Carbine", "Nammo · 155 HE-ER")[0] == "refuse"


def test_the_gate_is_actually_called():
    """The whole point. rebuild() may produce a row; main() must refuse it.

    Written as a source check on purpose: a behavioural test would need a database and
    a corpus, and the failure this guards against is not a wrong answer -- it is
    nobody asking the question."""
    src = open(revive_matchups.__file__, encoding="utf-8").read()
    assert "import positioning_gate" in src, "the live tree does not import the gate"
    assert "positioning_gate.gate(" in src, "the gate is imported but never called"
    assert "positioning_gate.strict()" in src, \
        "the unresolved-pairing policy is not read from the gate"
    # ...and the advantage-bullet path asks the same table which domain a row is in
    assert "positioning_gate.domain_for_row" in src


def test_a_component_is_not_another_business():
    """"Indigenous IP + forged barrel" is a legitimate thing to say about a howitzer.

    Putting gun-barrel in its own DOMAIN refused it, and a domain check built on the
    raw KINDS table refused 146 of the 2,320 archive bullets -- 58 of them on the
    single word "precision"."""
    assert pg.DOMAIN["gun-barrel"] == pg.DOMAIN["howitzer-towed"]
    for phrase in ("Indigenous IP + forged barrel; lower unit cost",
                   "155/52 with ALAS; long-range precision; Saudi export interest",
                   "Ultra-light strike; speed & rapid response, air-portable"):
        assert pg.kind_in_text(phrase) is None, phrase
    # ...while the maker-credential lines that name another domain's product still read
    assert pg.domain_of(pg.kind_in_text(
        "ATAGS co-producer; WhAP 8x8 exported (Morocco); ALS-50 UAV")) == "artillery"
    assert pg.domain_of(pg.kind_in_text(
        "Drone supplier to Belgium-Netherlands MCM; naval robotics leader")) == "uav"


def test_a_domain_we_cannot_read_refuses_nothing():
    assert pg.domain_for_row(catkey="msl") is None
    assert pg.domain_for_row(catkey="pc") is None
    assert pg.domain_for_row(catkey="mro") is None
    assert pg.domain_for_row() is None
    assert pg.domain_of(None) is None


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
