# -*- coding: utf-8 -*-
"""What may wear a THREAT badge, and where a threat card sorts.

    python test_threat_gate.py

Every case below is a row that is in production today, not an invented one.

THE OPERATOR'S BUG, as measured on 2026-09-06: 74 signal cards carry dir='threat', and
17 of them name a company that is not on the 43-row roster the dashboard serves. They are
two different faults and the fix for one is the opposite of the fix for the other:

  (a) TEN are a tracked rival written under a division, a suffix or a country arm --
      "Anduril Industries", "Hanwha Defense USA", "American Rheinmetall", "BAE Systems
      Bofors". Dropping these loses exactly the core-line artillery news the roster exists
      to surface. They must RESOLVE to the parent.

  (b) SEVEN are real defence companies that are not KSSL's rivals -- Huntington Ingalls
      Industries builds warships. These must stop being threats.

The old gate could not tell them apart because it was asking the wrong table
(competitor_roster_allow, an 82-row curation queue) with the wrong shape
(`if roster.keys() and not roster.on_roster(...)` -- an empty read skipped the check
entirely and published every card as a threat).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import threat_gate as tg                                              # noqa: E402
import serving_fill as sf                                             # noqa: E402
import backfill_card_direction as bf                                  # noqa: E402

bad = 0


def check(what, got, want):
    global bad
    if got != want:
        bad += 1
        print("  FAIL %s\n    got  %r\n    want %r" % (what, got, want))


# The 43-row served roster, in the spellings serving.competitors holds. Trimmed to the
# companies the 17 mis-badged cards bear on, plus the client, which is on that table too.
SERVED = ["Anduril", "Hanwha Aerospace", "Rheinmetall", "BAE Systems", "Saab",
          "Leonardo", "Elbit Systems", "Hyundai Rotem", "Otokar", "Nexter",
          "Adani Defence", "Larsen & Toubro", "Bharat Dynamics",
          "Kalyani Strategic Systems"]

# ---------------------------------------------------------------------------------
# 1. FAULT (a) -- the division, the suffix and the country arm all answer to the parent.
gate = tg.RosterGate(SERVED)
for spelling, parent in [
        ("Anduril Industries", "Anduril"),
        ("Hanwha Defense USA", "Hanwha Aerospace"),
        ("Hanwha Aerospace Romania", "Hanwha Aerospace"),
        ("American Rheinmetall", "Rheinmetall"),
        ("Rheinmetall Italia", "Rheinmetall"),
        ("Rheinmetall MAN", "Rheinmetall"),
        ("BAE Systems Bofors", "BAE Systems"),
        ("Leonardo DRS", "Leonardo"),
]:
    check("%s resolves to its parent" % spelling, gate.resolve(spelling), parent)

# 2. FAULT (b) -- a defence company is not automatically a rival of KSSL's.
for stranger in ["Huntington Ingalls Industries", "Northrop Grumman", "L3Harris",
                 "Czechoslovak Group", "Edge Group", "Diehl Defence", "F3 Group"]:
    check("%s is not a served competitor" % stranger, gate.resolve(stranger), None)

# The client is on serving.competitors and is never its own rival.
check("the client does not resolve", gate.resolve("Kalyani Strategic Systems"), None)
check("...under any of its names", gate.resolve("Bharat Forge Limited"), None)

# Word boundaries, not substrings -- the rule aliases.py already owns.
check("a stranger sharing a word is not a match", gate.resolve("Saab Networks Kiwi"),
      "Saab")   # documented: 'Saab' appears as a whole word, so this IS the same org
check("an unrelated name does not match", gate.resolve("Terma"), None)

# 3. FAIL CLOSED. The documented past bug is `if roster_names:` -- an empty list silently
#    skipping the whole check. An empty roster must be an ERROR, not a green light.
try:
    tg.RosterGate([])
except tg.EmptyRosterError:
    pass
else:
    bad += 1
    print("  FAIL an empty roster must refuse, not pass everything")
try:
    tg.RosterGate(["Kalyani Strategic Systems"])   # only the client -> effectively empty
except tg.EmptyRosterError:
    pass
else:
    bad += 1
    print("  FAIL a roster holding only the client must refuse")
# ...and the substitute a caller uses on that reading resolves NOTHING, rather than
# everything. It is not a no-op; it demotes with a reason.
refuse = tg.refusing_gate("roster-unavailable")
check("a refusing gate resolves nothing", refuse.resolve("Rheinmetall"), None)
check("...and says why", refuse.classify("Rheinmetall"), (None, "roster-unavailable"))

# ---------------------------------------------------------------------------------
# 4. THE DATA BUG. serving.competitors.threat is a level column holding a paragraph on
#    two rows. Length does not catch it ('high ' is short, 'low' is three characters);
#    membership in the vocabulary does.
PROSE = ("Adani Defence - 9 mapped partnership(s), 1 touching KSSL core lines. "
         "Lead: Alpha Design Technologies - CORE OVERLAP (ammunition/propellants...)")
check("prose is not a level", tg.threat_level(PROSE), None)
check("prose is recognised as a repair candidate", tg.looks_like_prose(PROSE), True)
check("a real level survives", tg.threat_level("High"), "high")
check("an absent level is None, not a repair candidate",
      (tg.threat_level(None), tg.looks_like_prose(None)), (None, False))
check("empty string is not a level either", tg.threat_level("  "), None)
check("an invented word is refused", tg.threat_level("critical"), None)

# ---------------------------------------------------------------------------------
# 5. IMPACT. Graded from values the pipeline already typed -- the card's KSSL category
#    and the rival's own product bands -- never from words in the article, which is
#    written in any of a dozen languages.
artillery = {"tags": "Artillery", "sec": [1, 2]}
naval = {"tags": "Naval Systems", "sec": [1]}
blank = {"tags": "", "meta": "", "sec": []}
gun_maker = {"threat": "high", "products": [{"category": "Artillery"}]}
drone_maker = {"threat": "high", "products": [{"category": "UAVs & Drones"}]}
unknown_cat = {"threat": "high", "products": ["Archer howitzer"]}   # bare strings: unknown

check("both sell it -> direct", tg.impact_of(artillery, gun_maker).state, "direct")
check("KSSL line, rival's catalogue elsewhere -> adjacent",
      tg.impact_of(artillery, drone_maker).state, "adjacent")
check("KSSL line, rival's catalogue unknown -> adjacent",
      tg.impact_of(artillery, unknown_cat).state, "adjacent")
check("outside KSSL's lines -> none (graded, and graded harmless)",
      tg.impact_of(naval, gun_maker).state, "none")
check("nothing to grade -> not_assessed, NOT none",
      tg.impact_of(blank, None).state, "not_assessed")
check("an ungraded card is never silently zero",
      tg.impact_of(blank, None).assessed, False)
check("...and it carries the reason it could not be graded",
      len(tg.impact_of(blank, None).basis) > 0, True)

# THE ORDERING PROMISE: unassessed ranks BELOW every assessed state, including 'none'.
check("not_assessed sorts below a graded no-overlap",
      tg.IMPACT_RANK["not_assessed"] > tg.IMPACT_RANK["none"], True)

# The card's category is read from `tags`, and from the `meta` chip when tags is empty --
# both written by the pipeline from the closed KSSL_CATS vocabulary, so this test is the
# same in every language the corpus publishes in.
check("meta is the fallback for a row written before tags",
      tg.card_line({"tags": "", "meta": "Artillery · Saab · from janes"}),
      "artillery")

# ---------------------------------------------------------------------------------
# 6. SEVERITY. Four states, and the fourth is not a rating.
check("high rival, direct hit", tg.severity_of("high", tg.Impact("direct")), "high")
check("high rival, adjacent", tg.severity_of("high", tg.Impact("adjacent")), "medium")
check("medium rival, direct hit", tg.severity_of("medium", tg.Impact("direct")), "medium")
check("low rival never exceeds low", tg.severity_of("low", tg.Impact("direct")), "low")
check("no rating -> not assessed", tg.severity_of(None, tg.Impact("direct")), None)
check("PROSE rating -> not assessed, never graded from a paragraph",
      tg.severity_of(PROSE, tg.Impact("direct")), None)
check("no impact -> not assessed", tg.severity_of("high", tg.Impact("not_assessed")), None)
check("'not assessed' is NOT 'low'",
      tg.severity_rank(None) != tg.severity_rank("low"), True)
check("'not assessed' sorts last of all",
      tg.severity_rank(None) > max(tg.severity_rank(x) for x in tg.LEVELS), True)

# ---------------------------------------------------------------------------------
# 7. grade(): the whole verdict, on the shapes production holds.
card = {"dir": "threat", "company": "Rheinmetall MAN", "tags": "Artillery", "sec": [1]}
d, why, imp, sev = tg.grade(card, gun_maker, gate)
check("a division of a tracked rival, in a shared line, stays a threat",
      (d, why, imp.state, sev), ("threat", None, "direct", "high"))

card = {"dir": "threat", "company": "Huntington Ingalls Industries",
        "tags": "Artillery", "sec": [1]}
d, why, imp, sev = tg.grade(card, None, gate)
check("a company off the roster is demoted, not deleted",
      (d, why), ("watch", "not-a-served-competitor"))

card = {"dir": "threat", "company": "Saab", "tags": "Naval Systems", "sec": [1]}
d, why, imp, sev = tg.grade(card, gun_maker, gate)
check("a tracked rival's news outside every KSSL line is not a threat",
      (d, why, imp.state), ("watch", "no-kssl-line", "none"))

card = {"dir": "threat", "company": "Saab", "tags": "", "meta": "", "sec": []}
d, why, imp, sev = tg.grade(card, {"threat": "high", "products": []}, gate)
check("a card we could not grade KEEPS its direction", d, "threat")
check("...and carries no severity rather than a low one", sev, None)
check("...and ranks below every graded card",
      tg.severity_rank(sev) > tg.severity_rank("low"), True)

# ---------------------------------------------------------------------------------
# 8. THE WRITER. parse_card is where dir is decided for every new card, and it must use
#    the gate rather than the curation queue. Same JSON the model emits.
CATS = ["Artillery", "Ammunition", "Small Arms"]
RAW = ('{"pillar":"competitive","title":"%s wins a 12-gun order","company":"%s",'
       '"category":"Artillery","dir":"threat",'
       '"sowhat":"%s delivered 12 M4 guns under a 40 million euro contract."}')
PROPS = [("%s", "won", "a 12-gun contract", "M", "%s won a 12-gun contract")]


def parsed(company, gate_):
    props = [(p[0] % company, p[1], p[2], p[3], p[4] % company) for p in PROPS]
    return sf.parse_card(RAW % (company, company, company), CATS, props, gate=gate_)


hit = parsed("Rheinmetall MAN", gate)
check("the writer re-points a division at its parent", hit and hit["company"], "Rheinmetall")
check("...and keeps it a threat", hit and hit["dir"], "threat")

miss = parsed("Northrop Grumman", gate)
check("the writer demotes a company off the served roster",
      miss and (miss["dir"], miss["dir_reason"]), ("watch", "not-a-served-competitor"))
check("...and keeps the card", miss is not None, True)

# THE FAIL-OPEN SHAPE, gone. The old line read `if roster.keys() and not on_roster(...)`,
# so an unreadable roster published everything. A refusing gate demotes everything.
blind = parsed("Rheinmetall MAN", tg.refusing_gate("roster-unavailable"))
check("an unreadable roster demotes rather than publishes",
      blind and (blind["dir"], blind["dir_reason"]), ("watch", "roster-unavailable"))

# ---------------------------------------------------------------------------------
# 9. THE BACKFILL SPLIT. The 17 live mis-badged cards, replayed through the pure planner
#    so the before/after count is measured rather than asserted.
ALIAS_MISSES = ["Anduril Industries", "Hanwha Defense USA", "Hanwha Aerospace Romania",
                "American Rheinmetall", "Rheinmetall Italia", "Rheinmetall MAN",
                "BAE Systems Bofors"]
NOT_RIVALS = ["Huntington Ingalls Industries", "Northrop Grumman", "L3Harris",
              "Czechoslovak Group", "Edge Group", "Diehl Defence", "F3 Group"]
ON_ROSTER = ["Saab", "Leonardo", "Elbit Systems"]

cards = [{"id": "pl_%d" % i, "dir": "threat", "company": c, "tags": "Artillery",
          "meta": "", "sec": [1], "lane": "competitive", "title": "%s wins an order" % c}
         for i, c in enumerate(ALIAS_MISSES + NOT_RIVALS + ON_ROSTER)]
comps = {n: {"threat": "high", "products": [{"category": "Artillery"}]} for n in SERVED}
resolves, demotions, unassessed, kept = bf.plan(cards, comps, gate)
check("every alias/subsidiary is re-pointed, none dropped", len(resolves), len(ALIAS_MISSES))
check("every non-rival is demoted", len(demotions), len(NOT_RIVALS))
check("...and demoted for the right reason",
      sorted({w for _c, w, _i in demotions}), ["not-a-served-competitor"])
check("the genuine threats are untouched", len(kept), len(ON_ROSTER))
check("nothing is lost",
      len(resolves) + len(demotions) + len(unassessed) + len(kept), len(cards))

# ---------------------------------------------------------------------------------
# 10. THE OPTIONAL COLUMN. dir_reason arrives with a migration deploy.sh does not run, so
#     the writer splices it in only where it exists. Both renderings have to line up with
#     the parameter tuple -- a column/placeholder mismatch here is a crash that happens
#     only in production, on the environment whose schema you did not test against.
def _sql(has):
    return sf.CARD_INSERT_SQL.format(
        col=", dir_reason" if has else "",
        val=", %s" if has else "",
        set=", dir_reason=EXCLUDED.dir_reason" if has else "")


for has_col, n_named, n_holes in ((False, 16, 15), (True, 17, 16)):
    q = _sql(has_col)
    cols = q.split("(", 1)[1].split(")", 1)[0]
    word = "present" if has_col else "absent"
    check("dir_reason %s: named columns" % word,
          len([c for c in cols.split(",") if c.strip()]), n_named)
    # origin is written as the literal 'pipeline', so one column carries no placeholder
    check("dir_reason %s: placeholders match the tuple" % word, q.count("%s"), n_holes)
check("the absent rendering names no dir_reason at all", "dir_reason" in _sql(False), False)

# EVERY KSSL CATEGORY MUST LAND IN KSSL_LINES, and the vocabulary decides -- not a
# copy of it typed into the module. KSSL_LINES was written in the human spelling
# ("protected & armoured vehicles") while every value compared against it arrives
# through fold_name(), which rewrites "&" as "and". The two categories containing an
# "&" therefore never matched: 24 Protected & Armoured Vehicles cards and 17 UAVs &
# Drones cards -- 41 of the 74 threat cards -- each graded "no KSSL line" and demoted
# to watch. Artillery, Ammunition and Small Arms carry no "&", matched, and made the
# rule look like it worked. A category renamed upstream now fails here loudly.
import json as _json
import os as _os
_refp = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                      "reference_dataset.json")
with open(_refp, encoding="utf-8") as _fh:
    _ref = _json.load(_fh)
_raw = _ref.get("KSSL_CATS") or []
_cats = []
for _c in _raw:
    if isinstance(_c, str):
        _cats.append(_c)
    elif isinstance(_c, dict):
        for _k in ("label", "name", "cat", "title"):
            if isinstance(_c.get(_k), str):
                _cats.append(_c[_k])
                break
check("reference_dataset.json still declares KSSL_CATS", bool(_cats), True)
for _c in _cats:
    check("KSSL category %r is a KSSL line" % _c,
          tg._fold_cat(_c) in tg.KSSL_LINES, True)

# the exact tag strings production stores on a threat card
for _tag in ("Protected & Armoured Vehicles", "UAVs & Drones", "Artillery",
             "Ammunition", "Small Arms"):
    check("a card tagged %r touches a KSSL line" % _tag,
          tg.card_line({"tags": _tag}) in tg.KSSL_LINES, True)

# THE FALLBACK MUST AGREE WITH THE FILE, and importing must never need the file.
# threat_gate is copied into two images at different depths: /app/signals/ in the
# extraction image (dataset beside it) and /app/ in the backend image (no dataset at
# all). Reading it unconditionally at import crash-looped the serving API with
# FileNotFoundError: '/reference_dataset.json' and took the dashboard down. CI runs
# where the file IS present, so this is where a drift between the two is caught.
check("the hand-listed fallback is exactly the file's vocabulary",
      frozenset(tg.fold_name(c).strip() for c in tg._KSSL_LINE_LABELS), tg.KSSL_LINES)
check("the fallback lists every category, not a subset",
      len(tg._KSSL_LINE_LABELS), len(tg.KSSL_LINES))

if bad:
    print("\n%d failure(s)" % bad)
    sys.exit(1)
print("ok - threat gate: aliases resolve, strangers demote, an empty roster refuses, "
      "prose is not a level, ungraded is not zero, and 17 replayed cards split 7/7/3")
