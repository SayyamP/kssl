"""What counts as a partnership, pinned.

    python3 test_partnership_concept.py        (no database, no model)

Part 1 made step_partnerships finish. This file is about the other half: WHAT it stores
when it does. Every case below was visible on the dashboard on 2026-09-06, or was a
relationship the corpus states and the pipeline could not express.

  * Adani was shown as a partner of the INDIAN NAVY, typed "Supply / customer" -- one
    bucket holding a supplier and a buyer, which are opposite relationships.
  * Two Adani rows were ACQUISITIONS ("Acquisition / stake"). Ownership has its own
    table and its own step; storing it here duplicated the claim under a name that
    said the opposite of what it was.
  * Mahindra/BAE Systems was typed "Historical Joint Venture (Ended 2013)" -- the type
    label was the only place an ended relationship could be said, so the graph drew a
    thirteen-year-dead JV as a live alliance edge.
  * MANUFACTURING, DISTRIBUTION, R&D, INTEGRATION and LICENSING had no value at all;
    they collapsed into `tech` or `other`.
  * Supplier language was not in PART_RX, so "X supplies engines to Y" was never even
    nominated -- the `supply` type existed and the corpus could not reach it.
  * publishable()'s verdict was computed into a variable nothing read, so a tie stated
    by the manufacturer and a tie from one anonymous blog were stored identically.

The refusals matter as much as the acceptances, so both are asserted: a filter that
silently drops rows is indistinguishable from a quiet corpus, which is exactly why the
acquisitions sat on the tab unnoticed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from enrich_serving import (PART_NOT_A_TIE, PART_RX, PART_STRONG_RX, PART_TYPES,
                                REL_PTYPE, owned_elsewhere, parse_partnership,
                                tie_confidence)
except Exception as e:                                              # noqa: BLE001
    print("SKIP test_partnership_concept: cannot import enrich_serving (%s: %s)"
          % (type(e).__name__, e))
    sys.exit(0)

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print("  ok   %s" % name)
    else:
        fail += 1
        print("  FAIL %s\n    got  %r\n    want %r" % (name, got, want))


BASIS = {"jv": "joint venture", "manufacturing": "manufacture", "supply": "supply",
         "licensing": "licence", "technology": "technology transfer",
         "rnd": "research", "integration": "integrate", "distribution": "distribute",
         "strategic": "", "other": ""}
HAY = ("rheinmetall and knds signed a joint venture to manufacture supply licence "
       "technology transfer research integrate distribute forged hulls for the new "
       "vehicle under a subcontract")


def parsed(rel, note="agreed to work together on forged hulls", **kw):
    """One well-formed answer, with `rel` and any extra field under test. A `basis` is
    supplied by default because a narrow type without one is now DOWNGRADED, not
    stored -- tests that are not about the basis should not trip over it."""
    import json as _j
    body = {"a": "Rheinmetall", "b": "KNDS", "rel": rel, "note": note,
            "basis": BASIS.get(rel, "")}
    body.update(kw)
    return parse_partnership(_j.dumps(body), HAY)


# ------------------------------------------------------------ the candidate regex
print("what the corpus can even nominate")

# PART_RX runs on the PREDICATE and decides which relationships can ever exist. Each
# verb below is a partnership type the tab claims to have; before this change none of
# them matched, so the type was unreachable however often the corpus said it.
for verb, why in [
    ("supplies engines to", "supply -- the type existed and nothing could reach it"),
    ("supplied the turret for", "supply, past tense"),
    ("is a supplier to", "supply, as a noun"),
    ("subcontracts the hull to", "manufacturing"),
    ("manufactures the airframe for", "manufacturing"),
    ("builds the chassis for", "manufacturing"),
    ("co-develops the engine with", "R&D"),
    ("co-produces the missile with", "R&D"),
    ("jointly develops radar with", "R&D"),
    ("distributes the system for", "distribution"),
    ("resells the platform for", "distribution"),
    ("is the channel partner for", "distribution"),
    ("formed a consortium with", "consortium"),
]:
    got = bool(PART_RX.search(verb))
    check("nominates %-34s (%s)" % ('"%s"' % verb, why), got, True)

# ...and the announcement vocabulary that already worked must not have been lost.
for verb in ["signed a joint venture with", "signed an MoU with", "partnered with",
             "formed an alliance with", "licensed the design to",
             "collaborates with", "teamed up with"]:
    check('still nominates "%s"' % verb, bool(PART_RX.search(verb)), True)

# A verb with no relationship in it must stay out, or the bound Part 1 bought is spent
# on sentences that cannot contain a tie.
for verb in ["said", "reported that", "unveiled", "will attend", "test-fired",
             "was founded in", "is headquartered in"]:
    check('ignores "%s"' % verb, bool(PART_RX.search(verb)), False)

# THE OVER-MATCHES, which are the real cost of widening. `.{0,30}for` with no word
# boundary matches the START of "forces", "forgings", "foreign" and "forward" -- and a
# defence corpus is full of all four. Each one below was measured nominating before the
# boundaries went in; each is a model call spent on a sentence that cannot hold a tie.
for verb in ["builds up its forces", "assembled forces near the border",
             "produces armoured forgings", "manufactures foreign variants of"]:
    check('does not nominate "%s"' % verb, bool(PART_RX.search(verb)), False)
# Nouns that share a stem with a relationship verb but state none.
for verb in ["supply chain disruption", "supplies of ammunition ran low",
             "had a disagreement with"]:
    check('does not nominate "%s"' % verb, bool(PART_RX.search(verb)), False)
# ...while the real thing, one word away, still does.
for verb in ["supplies engines to", "distribution agreement with",
             "is the exclusive dealer for", "manufactures the hull for",
             "distributes the system for"]:
    check('  but still nominates "%s"' % verb, bool(PART_RX.search(verb)), True)

# THE RESIDUE, ASSERTED RATHER THAN HIDDEN. These three DO nominate and cannot be
# excluded by a verb pattern: "distributes the system for" and "distributes dividends
# to" differ in the object, not the verb, and "builds capability for the future" has
# the exact shape of "builds the chassis for KNDS". A lookahead was tried and dropped
# real ties with them. What pays for the residue is the RANK: none of them is strong
# evidence, so the cap discards them before any genuine tie, and the model refuses
# what survives. If one ever ranks strong, that is a regression and this fails.
for verb in ["distributed the report to", "distributes dividends to shareholders",
             "builds capability for the future"]:
    check('accepts "%s" as a candidate...' % verb, bool(PART_RX.search(verb)), True)
    check('  ...but never as strong evidence',
          bool(PART_STRONG_RX.search(verb)), False)

# THE CAP MUST RANK THE NEW TYPES. PART_RX widened and PART_STRONG_RX did not, so a
# genuine supply statement scored the same as an over-match and lost the tie-break on
# quote length -- the cap would have discarded exactly the statements the new types
# were added for.
for verb in ["supplies engines to", "subcontracts the hull to",
             "co-develops the engine with", "is the distributor for",
             "signed a joint venture with"]:
    check('the cap ranks "%s" as strong evidence' % verb,
          bool(PART_STRONG_RX.search(verb)), True)
check("and a weak verb is still weak",
      bool(PART_STRONG_RX.search("collaborates with")), False)


# ------------------------------------------------------------------- the ten types
print("\nthe nine types")

# NINE, not ten. `other` and `strategic` were two catch-alls with descriptions the model
# could not tell apart, and a museum sponsorship landed on `other` for exactly that
# reason. Removing the catch-all altogether is worse -- measured, the model over-commits
# when it has one (`manufacturing` for a supply tie) and would commit harder without.
# One catch-all, last in the decision tree. `other` stays in REL_PTYPE for stored rows.
check("there are nine storable types", len(PART_TYPES), 9)
check("and exactly one of them is the catch-all",
      sorted(k for k in PART_TYPES if "partnership" in PART_TYPES[k].lower()),
      ["strategic"])
check("a legacy 'other' row still prints a label", bool(REL_PTYPE.get("other")), True)
for t in sorted(PART_TYPES):
    got = parsed(t)
    check("%-14s survives the parser and prints a label" % t,
          bool(got and got["rel"] == t and REL_PTYPE[t]), True)

# The five that had nowhere to go before. Named individually because "it is in the
# dict" and "the pipeline can produce it" are different claims.
for t in ("manufacturing", "distribution", "rnd", "integration", "licensing"):
    check("%-14s is no longer folded into tech/other" % t, t in PART_TYPES, True)
check("'other' is no longer a second catch-all", "other" in PART_TYPES, False)

# The retired keys must NOT be silently accepted -- a stale answer that still says
# "tech" should be refused and counted, not stored under a key nothing renders.
for old in ("tech", "mou", "acq"):
    check('the retired key "%s" is refused' % old, parsed(old), None)

# ...but rows ALREADY on the table carry them, so the label map must still print
# something rather than raising on a row written last week.
for old in ("tech", "mou", "acq", "supply", "jv", "other"):
    check('a stored "%s" row still prints a label' % old, bool(REL_PTYPE.get(old)), True)

# "Supply / customer" was one bucket for two opposite relationships, and it is what
# put the Indian Navy on the tab as a partner.
check("supply no longer means 'or customer'",
      "customer" in REL_PTYPE["supply"].lower(), False)


# ------------------------------------------------- the four that are not partnerships
print("\nwhat is not a partnership")

check("there are four excluded kinds", len(PART_NOT_A_TIE), 4)
check("and none of them is also storable",
      set(PART_TYPES) & set(PART_NOT_A_TIE), set())

# NAMED, NOT SILENTLY DROPPED. This is the whole reason they come back from the parser
# instead of returning None: a refusal nothing counts is why two acquisitions sat on
# the tab for weeks without anyone noticing.
for kind in sorted(PART_NOT_A_TIE):
    got = parsed(kind)
    check("%-12s comes back named, so it can be counted" % kind,
          bool(got and got["rel"] == kind), True)
    check("  and is not storable as a partnership", kind in PART_TYPES, False)

check("acquisition says where it belongs",
      "step_structure" in PART_NOT_A_TIE["acquisition"], True)


# -------------------------------------------------------------- status and ended
print("\na relationship that is over")

g = parsed("jv", note="the joint venture was dissolved in 2013",
           status="ended", ended="2013")
check("an ended tie is stored as ended", (g["status"], g["ended"]), ("ended", "2013"))
check("  and its type stays a type", g["rel"], "jv")

# The model contradicting itself: a stated end date is the harder fact.
g = parsed("jv", note="the joint venture was dissolved in 2013",
           status="active", ended="2013")
check("a stated end date outranks a claimed 'active' status", g["status"], "ended")

# An end date with no status at all still ends the tie.
g = parsed("jv", note="the joint venture was dissolved in 2013", ended="2013")
check("an end date with no status still ends it", g["status"], "ended")

# Garbage or missing status must not take the pass down, and must not invent an end.
for bad in (None, "", "nonsense", "Active", 7):
    g = parsed("jv", status=bad)
    check("an unusable status %-9r falls back to active" % (bad,),
          (g["status"], g["ended"]), ("active", None))

# A DATE HAS A DIGIT IN IT. `_s` nulls only null/none/n-a/unknown/not-stated, so a model
# answering the prompt's "else null" with a word produced a truthy `ended` -- and the
# "a stated end date outranks status" rule then flipped a LIVE joint venture to ended.
# Every string below did exactly that before the digit check.
for bad in ("ongoing", "no", "not applicable", "-", "present", "N/A", "still active"):
    g = parsed("jv", status="active", ended=bad)
    check("ended=%-14r does not end a live tie" % bad,
          (g["status"], g["ended"]), ("active", None))
# ...and the opposite mistake: _s refuses non-strings, so a bare year was thrown away.
g = parsed("jv", status="active", ended=2013)
check("ended=2013 as a NUMBER is still a real end date",
      (g["status"], g["ended"]), ("ended", "2013"))
for good in ("2013", "March 2013", "2013-04-01", "Q2 2019"):
    g = parsed("jv", status="active", ended=good)
    check("ended=%-12r ends the tie" % good, g["status"], "ended")

g = parsed("jv", status="announced")
check("'announced' is kept -- signed is not yet operating", g["status"], "announced")


# --------------------------------------------------------------------- confidence
print("\nhow much the source is worth")

check("the maker's own page is official for its own tie",
      tie_confidence(["https://www.rheinmetall.com/x"], "Rheinmetall")[0], "official")
# TWO URLS ONLY REACH THIS FUNCTION IF THE STEP PASSES THEM. It used to call
# tie_confidence with the single surviving document, so `corroborated` was unreachable
# and every tie in the system graded single_source -- a three-value scale shipping as
# two. This assertion was passing while that was true, which made it worse than no
# assertion. test_partnership_pass now checks the step actually passes the siblings.
check("two independent domains corroborate",
      tie_confidence(["https://idrw.org/a", "https://janes.com/b"], "Rheinmetall")[0],
      "corroborated")
check("one news domain is a single source, and says so",
      tie_confidence(["https://idrw.org/a"], "Rheinmetall")[0], "single_source")
check("the same domain twice is not corroboration",
      tie_confidence(["https://idrw.org/a", "https://idrw.org/b"], "Rheinmetall")[0],
      "single_source")
check("no source at all is not official",
      tie_confidence([], "Rheinmetall")[0], "single_source")
# A rival's site is not an authority on this tie -- the same rule the specs use.
check("a third party's official page does not make it official for this tie",
      tie_confidence(["https://www.knds.com/x"], "Rheinmetall")[0] == "official", False)
# The prose is still returned: the UI shows the verdict, a reader gets the reason.
check("the reason survives alongside the verdict",
      bool(tie_confidence(["https://idrw.org/a"], "Rheinmetall")[1]), True)


# ------------------------------------------------ what the parser must still refuse
print("\nthe refusals Part 1 relied on are still in force")

check("an unknown rel is refused", parsed("BFF"), None)
check("two orgs in one field are refused",
      parse_partnership('{"a":"Rheinmetall and KNDS","b":"Saab","rel":"jv",'
                        '"note":"agreed to jointly build a new vehicle"}', None), None)
check("a one-word note states nothing",
      parsed("jv", note="collaborates"), None)
check("an org absent from the statement is refused",
      parse_partnership('{"a":"Rheinmetall","b":"Boeing","rel":"jv",'
                        '"note":"agreed to jointly build a new vehicle"}',
                        "rheinmetall and knds agreed to build a vehicle"), None)
check("both sides the same company is refused",
      parse_partnership('{"a":"Saab","b":"Saab","rel":"jv",'
                        '"note":"agreed to jointly build a new vehicle"}', None), None)


# ------------------------------------------------- neither side is an organisation
print("\na country is a market and a force is a buyer")

# FOUND BY PROBING THE LIVE 14b AGAINST THE REAL CORPUS, not by any assertion above.
# 25 real statements produced 10 ties, and three of them had a country or an armed
# force on one side -- stored as partners of a defence manufacturer.
def two(a, b, rel="strategic", note="agreed to jointly build and supply vehicles"):
    import json as _j
    # the hay carries every basis word, so these cases test the ENTITY gates and are
    # not tripped by the separate basis gate
    hay = ("%s and %s agreed to build manufacture supply licence technology transfer "
           "research integrate distribute vehicles together in a joint venture"
           % (a, b)).lower()
    return parse_partnership(_j.dumps({"a": a, "b": b, "rel": rel, "note": note,
                                       "basis": BASIS.get(rel, "")}), hay)

# The probe's actual output, one line each.
check("Paramount Group <-> Kazakhstan is not a partnership",
      two("Paramount Group", "Kazakhstan"), None)
check("Elbit Systems <-> Australia is not a partnership",
      two("Elbit Systems", "Australia", "customer"), None)
check("Rheinmetall MAN <-> Australian Defence Force is not a partnership",
      two("Rheinmetall MAN Military Vehicles", "Australian Defence Force", "supply"),
      None)
# The singular form is what slipped through: only "defence forceS" was listed.
for f in ("Australian Defence Force", "Japan Self-Defense Force", "Indian Navy",
          "Ministry of Defence", "the Brazilian government"):
    check("a force/ministry is refused: %s" % f, two("Saab", f), None)
# A spread of countries, from both source lists.
for cn in ("Kazakhstan", "India", "Brazil", "Poland", "Australia", "Sweden"):
    check("a bare country is refused: %-11s" % cn, two("Saab", cn), None)
# ...and the real ties from the same probe run still pass, unchanged.
for a, b, rel in (("Saab", "Embraer", "strategic"),
                  ("Northrop Grumman", "Rheinmetall", "technology"),
                  ("ASC", "BAE Systems", "supply"),
                  ("CAE", "Saab", "strategic"),
                  ("QinetiQ", "Paramount Group", "strategic")):
    g = two(a, b, rel)
    check("a real tie still passes: %-18s <-> %s" % (a, b), (g or {}).get("rel"), rel)


# ---------------------------------------------------- the label, and what backs it
print("\nthe label has to point at its own evidence")

# THE GATE THAT REPLACED A VOCABULARY CHECK ON THE QUOTE. A 300-character defence quote
# contains "technology" and "develop" almost unconditionally, so gating the quote passes
# everything; a fifteen-word span the model had to copy cannot be vacuous the same way.
# ONLY THE THREE the gate guards. Gating all eight was measured and made the labelling
# worse -- the catch-all went 57% -> 80% on the same corpus, because the model's basis
# quotes the context that decided the type and not the type's own keyword.
for rel in ("jv", "licensing", "distribution"):
    g = parsed(rel, basis="")
    check("%-14s with no basis is downgraded, not stored" % rel,
          (g["rel"], g["downgraded"]), ("strategic", True))
    g = parsed(rel, basis="words that were never in the quote at all")
    check("  ...and an invented basis is not evidence either", g["rel"], "strategic")
    g = parsed(rel)
    check("  ...while a real one stands", g["rel"], rel)

# A basis that is real but says nothing about THIS type is not evidence for it.
check("a basis quoting the wrong thing downgrades",
      parsed("jv", basis="forged hulls")["rel"], "strategic")
# ...and the five types the gate does NOT guard keep their answer even with no basis,
# because their vocabulary is too ordinary for its absence to mean anything.
for rel in ("manufacturing", "supply", "technology", "rnd", "integration"):
    check("%-14s is not gated on its basis" % rel, parsed(rel, basis="")["rel"], rel)
# The catch-all itself has nothing to point at, so it is never downgraded.
check("the catch-all needs no basis", parsed("strategic", basis="")["rel"], "strategic")

# DOWNGRADE, NOT REFUSE: a mis-typed tie is still a tie, and vague-and-true beats
# specific-and-wrong. Losing it would be worse than labelling it loosely.
check("a downgraded answer is still stored", parsed("jv", basis="") is not None, True)


# ------------------------------------------------- ownership is not a partnership
print("\nownership wearing partnership words")

# THE MIRROR OF parse_structure's GUARD, which kept partnership language out of
# ownership and had no counterpart. The hand-written rows had exactly this shape:
# rel=jv over a note reading "Strategic stake in drone company".
check("a note about a stake is an acquisition, whatever rel says",
      parsed("jv", note="acquired a 50% stake in the drone company")["rel"],
      "acquisition")
check("  and so is 'Strategic stake in drone company', the live row's own words",
      parsed("jv", note="Strategic stake in drone company")["rel"], "acquisition")
for n in ("acquired a majority stake in the firm", "is a wholly-owned subsidiary of it",
          "completed the takeover of the drone business",
          "owns the remaining shares of the company",
          "bought a 26 per cent equity holding in the firm"):
    check("ownership note -> acquisition: %-42s" % n[:42],
          parsed("supply", note=n)["rel"], "acquisition")
# ...but a JOINT venture is jointly OWNED, and stays a tie.
check("a jointly owned company is still a partnership",
      parsed("jv", note="formed a joint venture jointly owned by the two firms")["rel"],
      "jv")


# ------------------------------------------- the acquisition stated somewhere else
print("\nthe acquisition the statement does not mention")

# Adani's 50% purchase of General Aeronautics reached the model as "partnering with",
# over a CEO quote saying "is partnering with us". The model answered faithfully; the
# acquisition is in a DIFFERENT proposition of the same article.
def prop(s_, p_, o_):
    return {"s": s_, "p": p_, "o": o_, "q": "", "t": None, "pl": None, "m": None}

tie = prop("Adani Defence & Aerospace", "partnering with", "General Aeronautics")
own = prop("Adani Defence & Aerospace", "acquires", "50% equity stake in General Aeronautics")
check("a sibling stating ownership of the same pair is found",
      owned_elsewhere({"d1": [tie, own]}, "d1", tie) is own, True)
check("  and the tie alone is not flagged",
      owned_elsewhere({"d1": [tie]}, "d1", tie), None)

# PAIR-SCOPED, not document-scoped. A subsidiary aside about a THIRD party must not
# refuse a real tie -- measured, document scope would have refused 10 of 33 real ties.
other = prop("Paramount Land Systems", "is a subsidiary of", "Paramount Group")
loi = prop("Paramount Land Systems", "signed an LOI with", "Defensphere OU")
check("ownership about a third party does not refuse the tie",
      owned_elsewhere({"d1": [loi, other]}, "d1", loi), None)
# A compound subject folds to nothing matchable: a miss, never a false refusal.
comp = prop("Saab and Embraer", "partnering with", "the programme")
check("a compound subject is a miss, not a false refusal",
      owned_elsewhere({"d1": [comp, own]}, "d1", comp), None)


# ------------------------------------------------------- names that are not names
print("\nnames that are not names")

check("a trailing comma is stripped: 'Merlin,'",
      (two("Merlin,", "Israel Aerospace Industries") or {}).get("a"), "Merlin")
# AND THE FORM THE MODEL ACTUALLY RETURNS. canon_name is what creates the problem:
# "Merlin, Inc." trims to "Merlin, Inc", the legal-suffix fold drops "Inc", and the
# comma comes back. Trimming only on the way in looked like a fix and shipped the same
# broken name to the tab twice.
check("...and 'Merlin, Inc.' does not become 'Merlin,' again",
      (two("Merlin, Inc.", "Israel Aerospace Industries") or {}).get("a"), "Merlin")
for raw, want in (("Thales,", "Thales"), ("Saab AB.", "Saab"),
                  ("KNDS Deutschland,", "KNDS Deutschland")):
    check("  %-22s -> %s" % (raw, want), (two(raw, "Rheinmetall") or {}).get("a"), want)
check("'Australian industry' is a phrase, not a firm",
      two("Kongsberg Defence", "Australian industry"), None)
check("a museum is a sponsorship, not a business partnership",
      two("Patria", "Finnish Aviation Museum"), None)
for nc in ("Rotary Foundation", "Defence Industry Association", "Chamber of Commerce"):
    check("non-commercial body refused: %-30s" % nc, two("Saab", nc), None)
# ...but a university or research council IS a real R&D counterparty and must stay.
for uni in ("Kyiv School of Economics", "CSIR", "Aalto-yliopisto"):
    check("a research body is kept: %-26s" % uni,
          (two("Saab", uni, "rnd") or {}).get("rel"), "rnd")
# One corporate family is ownership, not a tie.
for a, b in (("Nammo Cheltenham", "Nammo"), ("Rheinmetall", "American Rheinmetall"),
             ("BAE Systems", "BAE Systems Hagglunds")):
    check("one corporate family is not a tie: %-18s / %s" % (a, b), two(a, b), None)


print()
if fail:
    print("%d failure(s)" % fail)
    sys.exit(1)
print("ok - the ten types are reachable, the four exclusions are named, an ended tie "
      "says so, and the source verdict is kept")
