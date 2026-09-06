# -*- coding: utf-8 -*-
"""Which way is better, for a FIELD -- not for a row.

    python spec_direction.py --demo     # hermetic self-check, no DB
    python spec_direction.py --dry      # what re-stamping the served rows would change
    python spec_direction.py --apply

DIRECTION IS A PROPERTY OF THE MEASUREMENT, NOT OF THE ROW THAT CARRIES IT.
`hi` (True = higher is better, False = lower is, None = the field has no better and
worse at all) was never computed. It was hand-typed into each of the 507 archive rows
and then copied forward verbatim by revive_matchups (`e = dict(s)`), so the SAME field
came out directional on one row and directionless on the next. Measured on the live
serving.matchup, per field, True/False/None:

    Rate of fire      1 / 0 / 34      unambiguously higher-is-better, blank in 34 of 35
    Max range        30 / 0 / 20
    Power / speed     6 / 0 / 26
    Range             1 / 0 /  8
    Crew / pax       23 / 0 /  4      and this one is directional where it must NOT be
    Calibre           0 / 0 / 67      correct: 155 mm is not better than 105 mm
    Weight            0 / 51 / 2
    Combat weight     0 / 16 / 0      correct

A spec with hi=None cannot decide a lead (revive_matchups._wins, pairing.shared_
measurables and class_axis.re_edge all require it), so 97 of the 117 published rows
printed "N value(s) sourced, none comparable on both sides" while 88 of them held the
same field valued on BOTH sides. The evidence was there. The direction flag threw it away.

WHAT IS IN THE TABLE, AND WHAT DELIBERATELY IS NOT
--------------------------------------------------
Only where a direction is objectively true of the measurement itself:

  * A longer range, a faster rate of fire and a longer endurance are better; a
    heavier vehicle and a larger crew to serve it are worse. Those are not opinions.
  * Calibre, configuration, protection, mobility, type and class are NOT axes. They
    are what the product IS. Counting calibre as a win is most of what the old edge
    measured, and 155 mm against 105 mm is a class of gun, not a lead.
  * MTOW is refused for the same reason the matchup reviver already refuses it: a
    heavier airframe is neither better nor worse, it is a different aircraft.
  * "Crew / pax" is refused even though the archive marks it True on 205 rows. Its
    values read "2 + 10" against "8-14 personnel": a crew count (fewer is better)
    added to a troop count (more is better), and the grounded number may be either
    half on either side. One flag cannot be right for both, so no flag is asserted.
  * "Power / speed" IS directional -- "220hp / 85km/h" is two figures that both point
    the same way -- and revive_matchups will not draw a bar across two quantities
    anyway (it blanks cn/kn unless both sides resolve to the same quantity).

AN UNRECOGNISED LABEL GETS NO DIRECTION, AND IS COUNTED. Guessing from a substring
was the tempting shortcut and it is wrong in both directions: "weight" would make
"Munition weight" lower-is-better (a bigger warhead is not a worse warhead) and
"Maximum take-off weight" a deficiency. A label this table has never seen is a gap in
the table, and UNKNOWN records it so it can be closed on purpose rather than guessed.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter

UNKNOWN = Counter()     # normalised labels this table has never seen, with a count

# Higher is better.
_HI = (
    # reach
    "max range", "maximum range", "range", "effective range", "operational range",
    "engagement range", "firing range", "cruising range", "flight range",
    "intercept range", "interception range",
    # rate and time on task
    "rate of fire", "endurance", "loiter time", "operating time",
    "submerged endurance",
    # motion. Both halves of "power / speed" point the same way, which is why this
    # compound is allowed where "crew / pax" is not.
    "power speed", "power", "engine power", "max power", "maximum power",
    "speed", "max speed", "maximum speed", "top speed", "cruise speed",
    "cruising speed", "sprint speed", "loiter speed", "max road speed",
    "maximum road speed", "top speed road", "submerged speed",
    # what it can carry and how high. Same reasoning as power / speed.
    "payload", "payload capacity", "payload ceiling", "service ceiling", "ceiling",
    "cruising altitude", "interception altitude", "intercept altitude",
    # industrial
    "annual capacity",
)

# Lower is better.
_LO = (
    "weight", "combat weight", "combat mass", "mass", "gross weight",
    "gross vehicle weight", "maximum gross vehicle weight", "kerb weight",
    "curb weight",
    "crew",
)

# No better and no worse. Stated explicitly rather than left to fall through, so the
# UNKNOWN report stays a list of real gaps.
_NONE = (
    "calibre", "caliber", "configuration", "type", "class", "variant", "family",
    "role", "mobility", "protection", "loading", "action", "barrel", "chassis",
    "guidance", "engine", "engines", "main armament", "secondary armament",
    "hardpoints", "warhead", "munition weight", "bullet weight", "bullet type",
    "all up round weight", "mtow", "maximum takeoff weight",
    "maximum take off weight", "max takeoff weight", "autonomy ew",
    "launch recovery", "crew pax", "weight dia", "depth speed", "length", "width",
    "height", "diameter", "wingspan", "missile length", "displacement",
    "muzzle velocity", "muzzle energy", "angular accuracy", "range accuracy",
    "ingress protection", "fording depth", "gradient", "ready to fire rounds",
)

DIRECTION = {}
for _l in _HI:
    DIRECTION[_l] = True
for _l in _LO:
    DIRECTION[_l] = False
for _l in _NONE:
    DIRECTION[_l] = None


def key(label):
    """The one spelling every caller compares. "Crew / pax" -> "crew pax"."""
    s = unicodedata.normalize("NFKD", str(label or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def known(label):
    """Has the table been asked about this field on purpose?"""
    return key(label) in DIRECTION


def direction_of(label):
    """-> True (higher is better) / False (lower is) / None (no direction).

    None is returned BOTH for a field with no direction and for a label the table has
    never seen, because the consequence is the same and it is the safe one: the field
    decides no lead. The two are told apart by `known()` and by UNKNOWN, which is what
    the report prints -- an unrecognised label is a gap to close, not a fact."""
    k = key(label)
    if k in DIRECTION:
        return DIRECTION[k]
    if k:
        UNKNOWN[k] += 1
    return None


def stamp(specs):
    """Set `hi` on every spec from the field table. Returns (specs, n_changed).

    The archive's own value is not consulted. It is the thing being replaced."""
    n = 0
    for s in specs or []:
        want = direction_of(s.get("l") or s.get("label") or "")
        if s.get("hi") != want or "hi" not in s:
            n += 1
        s["hi"] = want
    return specs, n


# ---------------------------------------------------------------------------
# Re-stamping what is already served
# ---------------------------------------------------------------------------
# revive_matchups.py fixes this at build time, but a full rebuild needs the corpus and
# takes hours; the rows on screen carry the archive's flags until it runs. This pass
# corrects only `hi`, and then recomputes `edge` and `verdict` THROUGH revive_matchups'
# own functions -- never a second copy of the formula. A stored edge left beside a
# changed direction is the "one number, two definitions" fault this repo has already
# paid for once.
DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")


def main(apply=False):
    import psycopg2
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import revive_matchups as rm

    con = psycopg2.connect(DSN)
    cur = con.cursor()
    # SCOPED TO ONE WRITER'S ID RANGE. serving.matchup has two writers:
    # enrich_serving.py owns everything below 20000 and revive_matchups.py owns 20000+.
    # verdict_of is REVIVE'S definition of the sentence, so applying it to a card-
    # derived row would overwrite another writer's text with a text that was never
    # about it -- the two-writers-one-id-space fault that has already cost this project
    # serving.tender once and 453 revived rows once.
    cur.execute("""SELECT matchup_id, comp, "compBy", bf, "bfBy", specs, edge, verdict
                     FROM serving.matchup
                    WHERE origin='pipeline' AND matchup_id >= %s
                    ORDER BY matchup_id""", (rm.MATCHUP_ID0,))
    rows = cur.fetchall()
    print("%d served matchup(s) in the revived range (>= %d)"
          % (len(rows), rm.MATCHUP_ID0))
    changes, gained, lost = [], 0, 0
    for mid, comp, compby, bf, bfby, specs, edge, verdict in rows:
        sl = specs if isinstance(specs, list) else json.loads(specs or "[]")
        before = [s.get("hi") for s in sl]
        sl, n = stamp(sl)
        if not n:
            continue
        after = [s.get("hi") for s in sl]
        gained += sum(1 for a, b in zip(before, after) if a is None and b is not None)
        lost += sum(1 for a, b in zip(before, after) if a is not None and b is None)
        new_edge = rm.edge_of(sl)
        new_verdict = rm.verdict_of(sl, compby or comp, bfby or bf)
        changes.append((mid, n, edge, new_edge, sl, new_verdict,
                        verdict != new_verdict))
    print("  %d row(s) change; %d spec(s) GAIN a direction, %d lose one"
          % (len(changes), gained, lost))
    print("  %d row(s) whose verdict text changes"
          % sum(1 for c in changes if c[6]))
    print("  %d row(s) whose edge changes"
          % sum(1 for c in changes if c[2] != c[3]))
    if UNKNOWN:
        print("\n  labels this table has never seen (no direction asserted, %d):"
              % sum(UNKNOWN.values()))
        for lab, n in UNKNOWN.most_common(30):
            print("    %4d  %s" % (n, lab))
    if apply and changes:
        for mid, _n, _oe, new_edge, sl, new_verdict, _vc in changes:
            cur.execute("UPDATE serving.matchup SET specs=%s, edge=%s, verdict=%s, "
                        "updated_at=now() WHERE matchup_id=%s AND origin='pipeline' "
                        "AND matchup_id >= %s",
                        (json.dumps(sl), new_edge, new_verdict, mid, rm.MATCHUP_ID0))
        con.commit()
        print("\napplied to %d matchup(s)." % len(changes))
    elif not apply:
        print("\n(dry run -- nothing written)")
    con.close()
    return changes


def demo():
    # The field that started this: unambiguously higher-is-better, and directionless
    # on 34 of the 35 published rows that carry it.
    assert direction_of("Rate of fire") is True
    assert direction_of("Max range") is direction_of("Maximum range") is True
    assert direction_of("Range") is direction_of("Effective range") is True
    assert direction_of("Endurance") is True
    assert direction_of("Power / speed") is True
    # ...and the ones where lower is the better figure
    assert direction_of("Weight") is False
    assert direction_of("Combat weight") is False
    assert direction_of("Crew") is False
    # ...and the ones that are a class, not a lead
    assert direction_of("Calibre") is None and direction_of("Caliber") is None
    assert direction_of("Configuration") is None and direction_of("Mobility") is None
    assert direction_of("Protection") is None and direction_of("Type") is None
    assert direction_of("MTOW") is None, "a heavier airframe is a different aircraft"
    # "2 + 10" against "8-14 personnel" is a crew count plus a troop count. One flag
    # cannot be right for both halves, and the archive asserts True on 205 rows.
    assert direction_of("Crew / pax") is None
    assert known("Crew / pax"), "refused on purpose, not by falling through"

    # Spelling and punctuation are not the field. These are one field, not four.
    assert key("Crew / pax") == "crew pax" and key("Combat  Weight") == "combat weight"
    assert direction_of("MAXIMUM RANGE") is True
    assert direction_of("Maximum Speed") is direction_of("Max speed") is True

    # A label the table has never seen asserts nothing, and is recorded.
    UNKNOWN.clear()
    assert direction_of("Widget alignment index") is None
    assert not known("Widget alignment index")
    assert UNKNOWN["widget alignment index"] == 1, UNKNOWN
    UNKNOWN.clear()

    # THE SAME FIELD MUST GET THE SAME ANSWER ON EVERY ROW. That is the whole point,
    # so it is asserted rather than assumed.
    rows = [[{"l": "Rate of fire", "hi": None}, {"l": "Calibre", "hi": True}],
            [{"l": "Rate of fire", "hi": True}, {"l": "Calibre", "hi": None}],
            [{"l": "rate of fire"}]]
    got = set()
    for r in rows:
        stamp(r)
        for s in r:
            got.add((key(s["l"]), s["hi"]))
    assert got == {("rate of fire", True), ("calibre", None)}, got
    # ...including the row that had no `hi` key at all
    assert rows[2][0]["hi"] is True

    # stamp REPLACES; it does not defer to what the archive typed.
    s = [{"l": "Crew / pax", "hi": True}]
    stamp(s)
    assert s[0]["hi"] is None, s

    # A count, so a silent emptying of the table is a visible failure.
    assert sum(1 for v in DIRECTION.values() if v is True) >= 25
    assert sum(1 for v in DIRECTION.values() if v is False) >= 8
    assert sum(1 for v in DIRECTION.values() if v is None) >= 30
    print("ok  (%d fields: %d higher-better, %d lower-better, %d directionless)"
          % (len(DIRECTION),
             sum(1 for v in DIRECTION.values() if v is True),
             sum(1 for v in DIRECTION.values() if v is False),
             sum(1 for v in DIRECTION.values() if v is None)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.apply:
        main(True)
    elif a.dry:
        main(False)
    else:
        demo()
