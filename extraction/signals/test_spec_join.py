# -*- coding: utf-8 -*-
"""KSSL's own published specifications must reach the pairing that compares them.

    python test_spec_join.py

THE CASE THESE TESTS ARE BUILT FROM is the operator's, verbatim: "why we had no specs
for kssl cqb carbine its simply on kssl website directly?
https://www.kssl.in/small-arms".

They were never missing. serving.client_product holds 28 bullets for the CQB Carbine,
parsed off that page; matchup 20102 (CQB Carbine vs Kalashnikov's AK-203) carried ONE
of them and reported "1 value(s) sourced, none comparable on both sides". The tests
below drive the REAL build path -- revive_matchups.rebuild, with the real archive row
out of reference_dataset.json and the real workbook row out of
portfolio/kssl_portfolio.json -- so they fail if the join is removed, not merely if
spec_join's own vocabulary changes.

Hermetic: no database, no network, no model. The only synthetic input is a two-document
corpus stating what Kalashnikov and one independent outlet publish about the AK-203,
which is what the rival side of any pairing has to clear before it may be shown.
"""
import json
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import client_portfolio                                           # noqa: E402
import positioning_gate                                           # noqa: E402
import restamp_matchup_specs                                      # noqa: E402
import revive_matchups                                            # noqa: E402
import spec_join                                                  # noqa: E402

ARCHIVE = os.path.join(HERE, "..", "..", "reference_dataset.json")

# Two independent domains, which is the bar engine/source_tiers.publishable sets for a
# value with no official publisher behind it. Nothing here is about KSSL: the client's
# side comes from the workbook, and the corpus is only ever asked about the rival.
AK203_DOCS = [
    ("d1", "https://kalashnikovgroup.ru/ak-203",
     "The AK-203 assault rifle is chambered for the 7.62x39 mm cartridge. "
     "The AK-203 has a barrel of 415 mm and a weight of 3.8 kg."),
    ("d2", "https://www.armyrecognition.com/ak-203",
     "The AK-203 is chambered in 7.62x39 mm. The AK-203 weighs 3.8 kg and has a "
     "415 mm barrel."),
]


def _archive():
    return json.loads(io.open(ARCHIVE, encoding="utf-8").read())["matchups"]


def _row(bf, comp_contains):
    """One archive matchup as revive_matchups.rebuild's caller passes it."""
    for m in _archive().values():
        if m.get("bf") == bf and comp_contains in str(m.get("comp")):
            return (20102, m["cat"], m["comp"], m["compBy"], m["bf"], m["bfBy"],
                    m["specs"], m["advComp"], m["advBf"], m["country"], m["dir"],
                    m["catKey"], m["anchor"])
    raise AssertionError("archive row not found: %s vs %s" % (bf, comp_contains))


def _docs():
    return [(d, u, revive_matchups.norm(t)) for d, u, t in AK203_DOCS]


def _built():
    """The CQB Carbine / AK-203 pairing, built the way production builds it."""
    new, rep = revive_matchups.rebuild(_row("KSSL · CQB Carbine", "AK-203"),
                                       _docs(), client_portfolio.load())
    assert new, "the pairing was dropped entirely: %r" % (rep.get("drop"),)
    return new, rep


# ---------------------------------------------------------------------------
# 1. the operator's question
# ---------------------------------------------------------------------------
def test_more_than_one_kssl_spec_reaches_the_pairing():
    """RED WITHOUT THE FIX. The served row carried exactly one KSSL value.

    The ceiling was the ARCHIVE's label list -- revive_matchups walked `specs` and asked
    the workbook only about a label the archive had already named (five, for a small
    arm). Remove the spec_join call from rebuild and this comes back at 3."""
    new, _rep = _built()
    kssl = [s for s in new["specs"] if spec_join.stated(s.get("kv"))]
    assert len(kssl) > 1, "only %d KSSL value(s) reached the pairing" % len(kssl)
    assert len(kssl) >= 8, ("the client publishes 24 keyed bullets for this carbine; "
                            "only %d reached the panel" % len(kssl))


def test_the_published_values_the_operator_named_are_all_there():
    """Named one by one, off https://www.kssl.in/small-arms, so a silent narrowing of
    the field table is a failure and not a smaller number nobody reads."""
    new, _rep = _built()
    by = {}
    for s in new["specs"]:
        if spec_join.stated(s.get("kv")):
            by[s.get("k")] = str(s["kv"])
    for field, needle in (("Weight", "3.15"), ("Loaded weight", "3.65"),
                          ("Barrel length", "508"), ("Overall length", "802"),
                          ("Magazine capacity", "30"), ("Fire mode", "automatic"),
                          ("Cartridge", "45"), ("Action", "bullpup"),
                          ("MRBS", "2000"), ("MRBF", "6000")):
        assert field in by, "%s never reached the pairing (have: %s)" % (field, sorted(by))
        assert needle in by[field], "%s reached it as %r" % (field, by[field])


def test_every_spec_entry_carries_its_field_key():
    """RED WITHOUT THE FIX. `k` was NULL on every entry in serving.matchup.

    client_portfolio computes the workbook's key with the figure (its `_value`) and
    revive_matchups stored only the value, so nothing downstream could join a KSSL
    value to a rival's field to field -- which is the whole reason 27 published
    specifications had nowhere to land."""
    new, _rep = _built()
    missing = [s.get("l") for s in new["specs"] if not s.get("k")]
    assert not missing, "spec entries with no field key: %r" % missing


# ---------------------------------------------------------------------------
# 2. shown, and not scored
# ---------------------------------------------------------------------------
def test_a_kssl_value_with_no_counterpart_is_shown_not_dropped():
    """RED WITHOUT THE FIX: the magazine capacity was simply absent from the row."""
    new, _rep = _built()
    mag = [s for s in new["specs"] if s.get("k") == "Magazine capacity"]
    assert mag, "a published KSSL value with no rival counterpart was dropped"
    m = mag[0]
    assert "30" in str(m["kv"])
    assert m.get("noCounterpart") is True, "shown, but not marked as uncompared: %r" % m


def test_a_value_with_no_counterpart_is_never_scored_as_a_win():
    """It must reach the panel and it must reach neither the edge nor the verdict.

    revive_matchups.comparable() is the one definition of "can decide a lead", so it is
    what is asked -- not a second opinion written here."""
    new, _rep = _built()
    lonely = [s for s in new["specs"] if s.get("noCounterpart")]
    assert lonely, "the case under test did not arise"
    for s in lonely:
        assert s["cv"] is None and s["cn"] is None, "a rival value was invented: %r" % s
        assert not revive_matchups.comparable([s]), "a one-sided value can decide a lead"
    # ...and removing every one of them changes neither number on screen.
    without = [s for s in new["specs"] if not s.get("noCounterpart")]
    assert revive_matchups.edge_of(new["specs"]) == revive_matchups.edge_of(without)
    who = (new["compBy"], new["bfBy"])
    assert (revive_matchups.verdict_of(spec_join.scored(new["specs"]), *who)
            == revive_matchups.verdict_of(without, *who) == new["verdict"])


def test_no_rival_value_is_ever_invented():
    """Absence stays absence. Every rival value on the row must be one the archive
    stated for THIS pairing; nothing may appear beside a KSSL figure to make a pair."""
    row = _row("KSSL · CQB Carbine", "AK-203")
    stated = set()
    for s in row[6]:
        if s.get("cv") is not None:
            stated.add(str(s["cv"]))
    new, _rep = _built()
    for s in new["specs"]:
        if s.get("cv") is not None:
            assert str(s["cv"]) in stated, "invented rival value %r" % (s["cv"],)


# ---------------------------------------------------------------------------
# 3. the honesty machinery this must not break
# ---------------------------------------------------------------------------
def test_the_bore_rule_still_refuses_to_score_a_class_difference():
    """A 105 mm gun weighs a third of a 155 mm gun and `Weight` is hi=False, so a bore
    difference must never turn into a KSSL lead. The figure is SHOWN -- refusing to
    compare two values is not a reason to hide one -- and it carries no number."""
    prows = client_portfolio.load()
    fit = client_portfolio.match("KSSL · Garuda 105", "art",
                                 [{"l": "Calibre", "cv": "155/52", "kv": "105mm / 37 Cal"}],
                                 prows)
    assert isinstance(fit, client_portfolio.Fit) and fit.bore, "bore mismatch not recorded"
    assert isinstance(client_portfolio.kssl_side(fit, "Weight", "kg"),
                      client_portfolio.Refusal), "the scoring rule was weakened"
    got, _rep = spec_join.join(
        [{"l": "Weight", "cv": "13.7 t", "cn": 13700.0, "kv": None, "kn": None,
          "u": "kg", "hi": False}], fit.rows[0], bore_differs=True)
    w = [s for s in got if s.get("k") == "Weight"][0]
    assert w["kn"] is None and not revive_matchups.comparable([w]), \
        "a class difference became a scoreable field: %r" % w


def test_the_pairings_the_gate_refuses_are_still_refused():
    """20107/20108 pair KSSL's bolt-action Sniper against the AK-203 and are withheld
    as not_like_for_like. Nothing here may resurrect them: the gate reads the two NAMES
    and knows nothing about how many specs the row carries."""
    verdict, _caveat, why = positioning_gate.gate("KSSL · Sniper",
                                                  "Kalashnikov Concern · AK-203")
    assert verdict == "refuse", "the gate stopped refusing sniper-vs-carbine: %s" % why
    assert "sniper-rifle" in why or "precision" in why, why
    # ...and the two carbine rows the gate also refuses stay refused
    assert positioning_gate.gate("KSSL · CQB Carbine",
                                 "AWEIL · MTMG tank machine gun")[0] == "refuse"


def test_the_restamp_pass_never_shrinks_a_row():
    """The loader's third refusal, checked on the join itself rather than on a mock:
    every pairing it can touch must come out at least as long as it went in."""
    prows = {r["product_id"]: r for r in client_portfolio.load()}
    grew = 0
    for m in _archive().values():
        name = str(m.get("bf", "")).split("·")[-1].strip()
        ids = client_portfolio.ALIASES.get(name) or []
        if len(ids) != 1 or ids[0] not in prows:
            continue
        before = m["specs"]
        after, rep = spec_join.join(before, prows[ids[0]])
        assert len(after) >= len(before), "%s lost a spec" % name
        for i, s in enumerate(before):
            assert after[i].get("cv") == s.get("cv"), "a rival value was rewritten"
        grew += 1 if rep["added"] else 0
    assert grew > 50, "only %d archive rows gained a KSSL value" % grew


def test_a_product_the_workbook_does_not_hold_gains_nothing():
    """Bayonet, Cleaver and Omega are not KSSL products -- they are in no workbook row
    and their pairings are withheld as nothing_published. The join must not invent a
    portfolio for them."""
    for name in ("Bayonet", "Cleaver", "Omega", "MRAUV"):
        assert name not in client_portfolio.ALIASES, \
            "%s acquired a workbook alias; the withholding rests on it having none" % name


def test_module_demos():
    assert spec_join._demo() == 0
    assert restamp_matchup_specs._demo() == 0


# ---------------------------------------------------------------------------
# 4. the label and unit variation the brief names
# ---------------------------------------------------------------------------
def test_label_variation_resolves_to_one_field():
    f = spec_join.field_of
    assert f("Muzzle velocity") == f("Muzzle Velocity, m/s") == f("Velocity")
    assert f("Weight") == f("Mass") == f("Weight, carbine only") == "Weight"
    assert f("Weight with full magazine") == "Loaded weight", "two weights, two fields"
    assert f("Barrel") == f("Barrel options") == f("Barrel length options")
    assert f("Operating principle") == f("Action")
    # ...and a label the table has never seen keeps its value rather than losing it
    assert f("Bolt locking lugs") == "Bolt locking lugs"


def test_unit_variation_reaches_one_quantity():
    mm = spec_join.figure("508 mm")
    inch = spec_join.figure("20 in")
    assert mm[3] == inch[3] == "length"
    assert abs(mm[2] - inch[2]) < 1e-9, "20 inches is 508 mm: %r %r" % (mm, inch)
    kg = spec_join.figure("3.63 kg")
    lb = spec_join.figure("8 lb")
    assert kg[3] == lb[3] == "mass" and abs(kg[2] - lb[2]) < 0.01
    # a variant set, a range and prose all state no single figure, so the front end
    # draws chips instead of bars -- the existing rule, not a new one
    for v in ("508 / 407 / 360 mm", "640-840 rounds/min", "Gas-operated bullpup"):
        assert spec_join.figure(v)[0] is None, v


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
        except Exception as e:                                    # noqa: BLE001
            # A missing key is a failure of the thing under test, not a reason to
            # abandon the run: without the join, `k` is absent from every entry and
            # the harness must SAY so on each test rather than stop at the first.
            fails += 1
            print("  FAIL  %s: %s: %s" % (name, type(e).__name__, e))
    print("%s" % ("all checks passed" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
