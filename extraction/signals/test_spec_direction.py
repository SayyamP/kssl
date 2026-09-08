# -*- coding: utf-8 -*-
"""One direction per FIELD, on every row, measured over the real archive.

    python test_spec_direction.py

The blocker behind 97 of the 117 published "none comparable on both sides" verdicts
was `hi` being decided per ROW. This file proves the table gives one answer per field,
and -- where reference_dataset.json is present -- replays it over all 507 archive rows
so the claim is measured rather than asserted on three fixtures.

Hermetic: no database, no network, no model.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import revive_matchups  # noqa: E402
import spec_direction as sd  # noqa: E402

ARCHIVE = os.path.join(HERE, "..", "..", "reference_dataset.json")


def test_demo():
    sd.demo()


def test_the_fields_the_live_rows_disagreed_on():
    """Live counts of hi True/False/None, per field, before this table existed."""
    #                       field            live T/F/N        the one answer
    for label, was, want in (("Rate of fire", "1/0/34", True),
                             ("Max range", "30/0/20", True),
                             ("Power / speed", "6/0/26", True),
                             ("Range", "1/0/8", True),
                             ("Crew / pax", "23/0/4", None),
                             ("Calibre", "0/0/67", None),
                             ("Weight", "0/51/2", False),
                             ("Combat weight", "0/16/0", False)):
        got = sd.direction_of(label)
        assert got is want, "%s was %s live, table says %r" % (label, was, got)
        assert sd.known(label), "%s must be a decision, not a fall-through" % label


def test_one_answer_per_field_over_the_whole_archive():
    """Replay the 507 hand-built rows: no field may come out two ways.

    That is exactly what the archive does today -- "Crew / pax" is True on 205 rows
    and None on 5, "Max range" True on 61 and None on 46."""
    if not os.path.exists(ARCHIVE):
        print("      (reference_dataset.json absent -- archive replay skipped)")
        return
    rows = json.load(open(ARCHIVE, encoding="utf-8")).get("matchups") or {}
    before = collections.defaultdict(set)
    after = collections.defaultdict(set)
    for m in rows.values():
        specs = m.get("specs") or []
        for s in specs:
            before[sd.key(s.get("l"))].add(s.get("hi"))
        sd.stamp(specs)
        for s in specs:
            after[sd.key(s.get("l"))].add(s.get("hi"))
    inconsistent_before = sorted(k for k, v in before.items() if len(v) > 1)
    inconsistent_after = sorted(k for k, v in after.items() if len(v) > 1)
    assert inconsistent_before, "the archive is supposed to be inconsistent; fixture?"
    assert not inconsistent_after, inconsistent_after
    print("      archive replay: %d field(s) had two directions, now %d; %d fields seen"
          % (len(inconsistent_before), len(inconsistent_after), len(after)))
    # every label the archive uses is a decision, not a gap
    unknown = sorted(k for k in after if k and not sd.known(k))
    assert not unknown, "archive labels with no entry in the table: %s" % unknown


def test_no_field_reverses_direction():
    """The safety property, measured over all 507 archive rows: 565 spec entries GAIN
    a direction and 220 lose one (205 of them "Crew / pax"), and NOT ONE flips from
    higher-is-better to lower-is-better or back.

    That matters because a flip is the only change that can turn a published lead into
    a published deficit without anyone noticing. A gain or a loss changes whether a
    field counts; a flip changes who wins."""
    if not os.path.exists(ARCHIVE):
        print("      (reference_dataset.json absent -- flip check skipped)")
        return
    rows = json.load(open(ARCHIVE, encoding="utf-8")).get("matchups") or {}
    flips, gained, lost = [], 0, 0
    for m in rows.values():
        for s in m.get("specs") or []:
            was, want = s.get("hi"), sd.direction_of(s.get("l"))
            if was == want:
                continue
            if was is None:
                gained += 1
            elif want is None:
                lost += 1
            else:
                flips.append((s.get("l"), was, want))
    assert not flips, "a field reverses direction: %s" % sorted(set(flips))
    assert gained > lost, (gained, lost)
    print("      %d spec(s) gain a direction, %d lose one, 0 reverse" % (gained, lost))


def test_an_unknown_label_asserts_nothing_and_is_counted():
    sd.UNKNOWN.clear()
    assert sd.direction_of("Sprocket tension") is None
    assert not sd.known("Sprocket tension")
    assert sd.UNKNOWN["sprocket tension"] == 1
    sd.UNKNOWN.clear()


def test_the_reviver_stamps_from_the_table():
    """A source check: the failure to guard against is nobody asking, not a wrong
    answer. `e = dict(s)` carried the archive's hand-typed flag straight through."""
    src = open(revive_matchups.__file__, encoding="utf-8").read()
    assert "import spec_direction" in src
    assert 'e["hi"] = spec_direction.direction_of(' in src, \
        "the rebuilt spec does not take its direction from the field table"


def test_edge_and_verdict_have_one_definition():
    """spec_direction --apply recomputes both THROUGH revive_matchups.

    A stored edge left beside a changed direction is the "one number, two definitions"
    fault this repo has already paid for."""
    assert hasattr(revive_matchups, "edge_of")
    assert hasattr(revive_matchups, "verdict_of")
    src = open(sd.__file__, encoding="utf-8").read()
    assert "rm.edge_of(" in src and "rm.verdict_of(" in src


def test_the_restamp_stays_in_its_own_id_range():
    """serving.matchup has two writers. enrich_serving owns everything below 20000 and
    revive_matchups owns 20000+, and verdict_of is REVIVE'S sentence -- writing it over
    a card-derived row is the two-writers-one-id-space fault that has already cost this
    project serving.tender once and 453 revived rows once."""
    src = open(sd.__file__, encoding="utf-8").read()
    assert "rm.MATCHUP_ID0" in src, "the re-stamp is not scoped to one writer's range"
    assert src.count("matchup_id >= %s") >= 2, "both the read and the write must scope"
    assert revive_matchups.MATCHUP_ID0 == 20000


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
