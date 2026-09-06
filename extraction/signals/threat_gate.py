"""What makes a signal card a THREAT, and how threat cards are ordered.

    python threat_gate.py --demo

ONE implementation, imported by every writer and by the serving API. Three questions
were being answered in three different places, and none of them was the question the
operator asked:

  1. IS THE COMPANY A DIRECT COMPETITOR?  serving_fill asked roster.on_roster(), which
     reads serving.competitor_roster_allow -- an 82-row CURATION QUEUE, not the roster
     the dashboard serves. 43 companies are served. Huntington Ingalls Industries,
     Northrop Grumman, L3Harris, Czechoslovak Group, Edge Group, Diehl Defence and F3
     Group are all on the allowlist and none of them is on the Competitor tab, so each
     could carry a red THREAT badge pointing at a profile that does not exist. The
     question a threat badge answers is "one of the rivals I track just moved", and the
     rivals the reader tracks are the ones the dashboard shows.

  2. DOES IT TOUCH KSSL?  Nothing asked. A rival's name was the whole test, so a
     Rheinmetall truck contract and a Rheinmetall 155mm shell contract were the same
     colour. The operator: "not all competitor can be a threat to KSSL".

  3. HOW BAD IS IT?  Nothing asked. serving.signal_card has no severity column and the
     feed sorted on direction alone, so 74 threats arrived in an order nobody chose.

WHY THE GRADING HERE USES NO ENGLISH.  This project has three logged incidents of a
closed English keyword list quietly working as a language detector and condemning every
non-English row it met. The corpus is multilingual by construction. So impact is graded
from values the pipeline has ALREADY typed and that are the same in every language:

  * the card's CATEGORY, which parse_card chose from KSSL_CATS -- a closed nine-item
    vocabulary written by us, not a phrase found in the article;
  * the competitor's own PRODUCT BANDS, categorised by the same vocabulary;
  * the PRESENCE of typed evidence rows on the card (a count, not a reading).

No sentence of the article is pattern-matched here in any language.

AND IT FAILS CLOSED.  roster.on_roster's caller carried the `if roster_names:` shape
this repo has been bitten by before -- an empty roster silently skipped the entire check
and every card passed. RosterGate REFUSES to be built from an empty roster. A caller
that cannot read the roster gets an exception it must handle, not a green light.
"""
import re
import sys
import json
from pathlib import Path

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from aliases import (  # noqa: E402  (the repo's identity layer -- not a second one)
    fold as fold_name, is_client, same_org,
)

# ---------------------------------------------------------------------------------
# KSSL's own lines. These are labels from KSSL_CATS (reference_dataset.json), folded.
# serving_fill imported to hold its own copy as _CORE_CATS; two copies of the list that
# decides what "touches KSSL" is how one of them goes stale, so this is now the only one.
#
# READ FROM THE VOCABULARY AND FOLDED THE SAME WAY ITS INPUTS ARE. Typing the set
# by hand went wrong twice at once, and both faults were silent:
#
#   SPELLING. The labels were typed in their human form while every value compared
#   against them arrives through fold_name(), which rewrites "&" as "and". So a card
#   tagged "Protected & Armoured Vehicles" folded to "protected and armoured
#   vehicles" and missed a set holding "protected & armoured vehicles". The two
#   categories containing an "&" are the two biggest on the board -- 24 Protected &
#   Armoured Vehicles cards and 17 UAVs & Drones cards, 41 of the 74 threat cards --
#   and every one was graded "no KSSL line" and demoted to watch. Artillery,
#   Ammunition and Small Arms carry no "&", matched, and made the rule look sound.
#
#   COVERAGE. Six of the nine categories were listed. The three left out -- Marine /
#   Naval, Missiles & Air Defence, Precision Components & Forgings -- are all lines
#   the client's own product workbook carries: naval guns and propulsion shafting,
#   Spike and MRSAM sub-assemblies and CIWS ammunition, and forgings, which is the
#   founding business. A card in any of them was graded as touching nothing KSSL sells.
#
# Reading KSSL_CATS keeps ONE definition of what KSSL does -- the same one
# serving_fill.kssl_cats() files cards into -- so the two cannot drift, and
# test_threat_gate fails loudly if a category is renamed upstream.
def _kssl_lines():
    ref = json.loads((HERE.parent / "reference_dataset.json").read_text(encoding="utf-8"))
    return frozenset(fold_name(c).strip() for c in ref["KSSL_CATS"] if isinstance(c, str))


KSSL_LINES = _kssl_lines()

# The only values serving.competitors.threat may hold. It is a LEVEL, and the migration
# that ships with this module adds the CHECK constraint that says so -- two production
# rows hold a paragraph of partnership prose in this column today, which every consumer
# then renders as if it were a rating.
LEVELS = ("high", "medium", "low")

# Impact states, worst-ranking last. "not_assessed" is deliberately its own state and
# deliberately ranks BELOW every assessed one: a card we could not grade must never
# borrow the ordering of a card we graded and found harmless.
IMPACT_STATES = ("direct", "adjacent", "none", "not_assessed")
IMPACT_RANK = {"direct": 0, "adjacent": 1, "none": 2, "not_assessed": 3}

# Severity, and the ONE definition of its sort position. This number is computed here,
# served as `severityRank`, and read -- never recomputed -- by the browser. The last
# time a number in this codebase was derived in both places, the frontend silently
# overwrote the served value and a 1-0 winner was scored as behind.
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, None: 3}
SEVERITY_UNASSESSED = None
# What a reader is told when severity could not be established. "low" is a measurement;
# this is the absence of one, and they must not look the same.
SEVERITY_UNASSESSED_LABEL = "severity not assessed"
IMPACT_UNASSESSED_LABEL = "impact not assessed"


class EmptyRosterError(RuntimeError):
    """The roster the gate would check against is empty.

    Raised, not swallowed. An empty roster is a broken read (a view renamed, a
    connection lost, a migration mid-flight), and the previous behaviour on that
    reading -- skip the check, publish everything as a threat -- is the failure mode
    this whole module exists to remove.
    """


def threat_level(value):
    """The stored `threat` value as a LEVEL, or None if it is not one.

    The write-boundary validator. serving.competitors.threat is a three-value column
    with no constraint on it, and two rows hold prose:

        "Adani Defence - 9 mapped partnership(s), 1 touching KSSL core lines. Lead:
         Alpha Design Technologies - CORE OVERLAP (ammunition/propellants...)"

    That is a threatNote, written into threat. Every reader of the column -- the Profile
    dot, the Products dot, the patent leader sort, and now severity -- treats whatever
    it finds as a rating, so the paragraph renders as one. Length alone would not have
    caught it ("high " passes any length test and "low" is three characters): the test
    is membership in the vocabulary, which is the only thing the column means.

    None is returned for a genuinely absent rating too. The two are the same fact to a
    consumer -- there is no level here -- and severity_of turns both into
    "not assessed", which is not "low".
    """
    if value is None:
        return None
    v = str(value).strip().lower()
    return v if v in LEVELS else None


def is_level(value):
    """True only for a stored value that IS a level. Used by the audit/repair pass to
    tell a missing rating (None -> nothing to fix) from a corrupt one (prose -> fix)."""
    return value is not None and str(value).strip().lower() in LEVELS


def looks_like_prose(value):
    """A non-empty, non-level value in a level column. What the repair pass moves."""
    return value is not None and str(value).strip() != "" and not is_level(value)


class RosterGate:
    """Resolves a card's company to a SERVED competitor, or refuses it.

    Built from the names on the Competitor tab -- serving.competitors -- because that is
    the roster the badge is a claim about. Not competitor_roster_allow, which is the
    queue of names a human is willing to consider.

    Resolution is alias-aware through aliases.same_org, the repo's own rule, so the four
    shapes the corpus actually writes all reach their parent instead of being dropped:

        suffix       "Anduril Industries"        -> "Anduril"
        division     "BAE Systems Bofors"        -> "BAE Systems"
        country arm  "Hanwha Aerospace Romania"  -> "Hanwha Aerospace"
        joint venture"Rheinmetall MAN"           -> "Rheinmetall"

    Seventeen of the 74 live threat cards name a company that is not on the served
    roster; ten of them are one of those four shapes and belong to a rival we do track.
    Dropping them would have been the opposite error to the one being fixed.
    """

    def __init__(self, names, allow_empty=False):
        clean = [str(n).strip() for n in (names or []) if n and str(n).strip()]
        # The client is never its own rival. It is on serving.competitors (dir='client')
        # and would otherwise resolve its own news to a threat against itself.
        clean = [n for n in clean if not is_client(n)]
        if not clean and not allow_empty:
            raise EmptyRosterError(
                "threat gate built from an empty roster: refusing to grade any card "
                "rather than passing every card. Check serving.competitors.")
        self.names = clean
        # folded -> display name, longest folded key first so the most specific roster
        # entry wins when two of them match ("BAE Systems" over "BAE").
        self._by_fold = {}
        for n in clean:
            f = fold_name(n)
            if f:
                self._by_fold.setdefault(f, n)
        self._ordered = sorted(self._by_fold.items(), key=lambda kv: -len(kv[0]))

    def __len__(self):
        return len(self.names)

    def resolve(self, company):
        """The served competitor this spelling belongs to, or None.

        None means "not one of the companies this dashboard tracks", which is a real
        and common answer: a buyer, a government, a supplier, or a defence company that
        simply is not a rival of KSSL's (Huntington Ingalls builds warships).
        """
        if not company:
            return None
        c = str(company).strip()
        if not c or is_client(c):
            return None
        f = fold_name(c)
        if f in self._by_fold:
            return self._by_fold[f]
        for rf, name in self._ordered:          # longest roster name first
            if same_org(c, name):
                return name
        return None

    def classify(self, company):
        """(resolved_name, reason). reason is None when the company resolved.

        The reason is recorded on the demoted card rather than thrown away, because
        "this used to be a threat" and "this was never a threat" are different states
        and only one of them is worth an operator's attention.
        """
        name = self.resolve(company)
        if name:
            return name, None
        return None, "not-a-served-competitor"


def refusing_gate(reason):
    """A gate that resolves NOTHING, for a caller whose roster read failed.

    The honest object for that situation. It is not a no-op: every card it sees is
    demoted with the reason attached, so the outage is visible in the data instead of
    being invisible in the absence of a check.
    """
    g = RosterGate([], allow_empty=True)
    g._refusal = reason
    g.resolve = lambda company: None                                   # noqa: ARG005
    g.classify = lambda company: (None, reason)                        # noqa: ARG005
    return g


# ---------------------------------------------------------------------------------
# IMPACT


def _fold_cat(value):
    return fold_name(value or "").strip()


def card_line(card):
    """The KSSL line a card is filed under, folded -- or "" if it has none.

    `tags` is written by serving_fill as card["category"], one of KSSL_CATS. `meta` is
    "Category · Company · from Source" and carries the same value, so it is the fallback
    for a row written before tags existed. Neither is article text.
    """
    tags = card.get("tags") if isinstance(card, dict) else None
    line = _fold_cat(tags)
    if line:
        return line
    meta = (card.get("meta") if isinstance(card, dict) else None) or ""
    first = str(meta).split("·")[0]
    return _fold_cat(re.sub(r"<[^>]+>", "", first))


def competitor_lines(comp):
    """The KSSL lines a competitor's own catalogue falls in, folded.

    Read from serving.competitors.products, whose rows carry a `category` assigned by
    enrich_serving.categorise_product from the same nine-item vocabulary. A product list
    of bare strings (older rows) yields nothing -- which is an unknown, not a zero, and
    impact_of treats it as one.
    """
    out = set()
    for p in ((comp or {}).get("products") or []):
        if isinstance(p, dict):
            c = _fold_cat(p.get("category") or p.get("cat"))
            if c:
                out.add(c)
    return out


def evidence_rows(card):
    """How many typed evidence rows the card carries. A COUNT of structured rows --
    subject/predicate/object plus the located quote -- never a reading of them."""
    sec = (card or {}).get("sec")
    if isinstance(sec, list):
        return len(sec)
    return 0


class Impact(object):
    """A graded impact, and the grounds it was graded on.

    `state` is one of IMPACT_STATES. `basis` lists the structured facts that produced
    it, so a card can show why it is red rather than asserting that it is.
    """

    __slots__ = ("state", "basis")

    def __init__(self, state, basis=None):
        assert state in IMPACT_STATES, state
        self.state, self.basis = state, list(basis or [])

    @property
    def assessed(self):
        return self.state != "not_assessed"

    @property
    def rank(self):
        return IMPACT_RANK[self.state]

    @property
    def label(self):
        if self.state == "not_assessed":
            return IMPACT_UNASSESSED_LABEL
        return {"direct": "hits a KSSL line KSSL and this rival both sell",
                "adjacent": "touches a KSSL line",
                "none": "outside every KSSL line"}[self.state]

    def __eq__(self, other):
        return (isinstance(other, Impact) and other.state == self.state
                and other.basis == self.basis)

    def __repr__(self):
        return "Impact(%r, %r)" % (self.state, self.basis)


def impact_of(card, comp):
    """How a card's event bears on KSSL. Structured inputs only.

    comp is the SERVED competitor row (serving.competitors) the card resolved to, or
    None when it resolved to nobody.

      direct        the card's line is one of KSSL's AND this rival's own catalogue
                    covers that same line -- the two companies meet on it
      adjacent      the card's line is one of KSSL's, but the rival's catalogue does not
                    cover it (or we do not know their catalogue)
      none          the card's line is not one of KSSL's -- graded, and graded harmless
      not_assessed  the card carries no line we can read AND there is no catalogue to
                    fall back on. NOT zero, NOT "none": we did not measure it.

    The distinction between `none` and `not_assessed` is the whole point. "This is about
    warships, KSSL does not build warships" is a finding. "This card has no category and
    the competitor row has no products" is a gap, and it must not be dressed up as the
    finding.
    """
    line = card_line(card)
    lines = competitor_lines(comp)
    basis = []
    if not line:
        if not lines:
            return Impact("not_assessed",
                          ["card carries no KSSL category",
                           "no product bands on the competitor row"])
        # No line on the card, but the rival is known to sell into KSSL lines. That is
        # something, and it is not nothing -- but it is not a graded impact either: the
        # EVENT is ungraded. Say so.
        return Impact("not_assessed",
                      ["card carries no KSSL category",
                       "rival sells in %d KSSL line(s)" % len(lines & KSSL_LINES)])
    if line not in KSSL_LINES:
        return Impact("none", ["card line %r is outside KSSL's catalogue" % line])
    basis.append("card line %r is a KSSL line" % line)
    n_ev = evidence_rows(card)
    if n_ev:
        basis.append("%d typed evidence row(s)" % n_ev)
    if line in lines:
        basis.append("rival's own catalogue covers %r" % line)
        return Impact("direct", basis)
    if lines:
        basis.append("rival's catalogue covers %s, not %r"
                     % (", ".join(sorted(lines)) or "nothing", line))
    else:
        basis.append("rival's catalogue unknown")
    return Impact("adjacent", basis)


# ---------------------------------------------------------------------------------
# SEVERITY
#
# DERIVED AT SERVE TIME, not stored. serving.signal_card has no severity column, and
# the two inputs live in tables the API already reads on the same request: the
# competitor's rated threat level, and the card's own impact. Deriving it here means
# there is exactly one definition of it and no window in which a card's severity and
# the rating it came from disagree because one pass ran and the other did not.
#
# The migration that ships with this change therefore adds no severity column. It adds
# the CHECK constraint that keeps `threat` a level (without which severity is derived
# from prose) and the dir_reason column that records a demotion.

_SEVERITY = {
    ("high", "direct"): "high",
    ("high", "adjacent"): "medium",
    ("high", "none"): "low",
    ("medium", "direct"): "medium",
    ("medium", "adjacent"): "low",
    ("medium", "none"): "low",
    ("low", "direct"): "low",
    ("low", "adjacent"): "low",
    ("low", "none"): "low",
}


def severity_of(comp_threat, impact):
    """high | medium | low | None.

    None means NOT ASSESSED and is a fourth state, not a fourth-worst rating. It is
    returned whenever either input is missing: an ungraded event under a rated rival is
    as unmeasured as a graded event under an unrated one.
    """
    level = threat_level(comp_threat)
    state = impact.state if isinstance(impact, Impact) else impact
    if level is None or state == "not_assessed" or state is None:
        return SEVERITY_UNASSESSED
    return _SEVERITY[(level, state)]


def severity_rank(severity):
    """The ONE sort position for a severity. Served to the browser as `severityRank`."""
    return SEVERITY_RANK.get(severity, SEVERITY_RANK[None])


def grade(card, comp, gate=None):
    """The whole verdict for one card: (dir, reason, impact, severity).

    `dir` is what the card should be published as. A card is only a threat when all
    three hold, and the reason names the first one that did not:

      1. its company resolves to a company on the SERVED roster;
      2. its impact is assessed;
      3. that impact touches a KSSL line.

    A card that fails 1 or 3 is DEMOTED to watch and keeps its reason -- never deleted.
    Losing the card would lose the article; the badge is what was wrong, not the news.
    A card that fails 2 keeps whatever direction it had: we have not established that it
    is harmless, only that we could not grade it, and severity None puts it below every
    graded card wherever cards are ordered.
    """
    dirv = (card or {}).get("dir") or "watch"
    if dirv != "threat":
        imp = impact_of(card, comp)
        return dirv, None, imp, severity_of((comp or {}).get("threat"), imp)
    if gate is not None:
        resolved, why = gate.classify((card or {}).get("company"))
        if not resolved:
            imp = impact_of(card, comp)
            return "watch", why, imp, severity_of((comp or {}).get("threat"), imp)
    imp = impact_of(card, comp)
    if imp.state == "none":
        return "watch", "no-kssl-line", imp, severity_of((comp or {}).get("threat"), imp)
    return "threat", None, imp, severity_of((comp or {}).get("threat"), imp)


# ---------------------------------------------------------------------------------


def served_roster_names(cur, schema="serving"):
    """Every company name on the Competitor tab. The gate's input.

    dir is NOT filtered on. The served roster holds dir='rival' and dir='threat' rows
    (39 and 4 in production) and both are companies the reader can open a profile for;
    filtering to one of the two spellings would silently re-create the bug this module
    is here to remove. The client is dropped by RosterGate itself.
    """
    cur.execute("SELECT name FROM %s.competitors WHERE name IS NOT NULL" % schema)
    return [r[0] if not isinstance(r, dict) else r["name"] for r in cur.fetchall()]


def gate_from_db(cur, schema="serving"):
    """RosterGate over the served roster. Raises EmptyRosterError if it is empty."""
    return RosterGate(served_roster_names(cur, schema))


def _demo():                                                          # pragma: no cover
    roster = RosterGate(["Anduril", "Rheinmetall", "BAE Systems", "Hanwha Aerospace",
                         "Saab", "Kalyani Strategic Systems"])
    assert roster.resolve("Anduril Industries") == "Anduril"
    assert roster.resolve("Huntington Ingalls Industries") is None
    assert roster.resolve("Kalyani Strategic Systems") is None, "the client is not a rival"
    try:
        RosterGate([])
    except EmptyRosterError:
        pass
    else:
        raise AssertionError("an empty roster must refuse, not pass everything")
    art = {"dir": "threat", "company": "Rheinmetall MAN", "tags": "Artillery",
           "sec": [1, 2]}
    comp = {"threat": "high", "products": [{"category": "Artillery"}]}
    d, why, imp, sev = grade(art, comp, roster)
    assert (d, why, imp.state, sev) == ("threat", None, "direct", "high"), (d, why, imp, sev)
    assert threat_level("Adani Defence - 9 mapped partnership(s)...") is None
    assert severity_of("high", Impact("not_assessed")) is None
    print("ok - threat gate demo: alias resolve, empty roster refuses, "
          "prose is not a level, ungraded impact has no severity")


if __name__ == "__main__":                                            # pragma: no cover
    _demo()
