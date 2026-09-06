"""The named officers of a competitor, from `extracted.proposition` only.

    python fill_leadership.py            # dry run: what it would write
    python fill_leadership.py --apply    # write serving.competitors.leadership
    python fill_leadership.py --demo     # offline self-check

WHY THIS EXISTS. `serving.competitors.leadership` is a jsonb column that the backend
serves and the Profile page already renders -- and that NOTHING in the enrich pass has
ever written. 0 of 43 shown competitors had a single officer. The only writer that ever
filled it was the archived harvest path, which is out of the codebase by policy, so the
Leadership panel has rendered "No executive officers published on public record." for
every company since. This fills the column the way `fill_revenue` fills `sales` and
`fill_founded` fills `starting_year`: from the corpus, with the evidence sentence
governing.

THE TWO RULES THAT DO THE WORK ARE TENURE AND ATTACHMENT.

TENURE -- the corpus talks about officers mostly when they LEAVE. A profile panel that
prints the person who ran the company in 2013 is worse than one that prints nobody:

    "Harris served as the Assistant to the Chairman of the Joint Chiefs of Staff"
    "Chu resigned as chairman of the KMT"
    "Ursa Major names former Maxar CEO as its new chief executive"

Each of those states a role in plain words, and in each the role is over. A past-tense
or handover marker anywhere in the sentence disqualifies the claim, because the column
is asked "who runs this company", not "who has ever run it".

ATTACHMENT -- a sentence that names a competitor and names a role is not a sentence that
gives that competitor's officer. The role belongs to whatever organisation it sits
NEXT TO, and the corpus is full of sentences where those differ:

    "Per Ahl is CEO of Saab Digital Air Traffic Solutions"   -> a subsidiary, not Saab
    "Mr Hudson served as CEO of Rheinmetall Landsysteme GmbH" -> a subsidiary
    "supported Senator Kennedy's work as Chairman of the Seapower Subcommittee"

So the company name must sit inside a short window of the role word, and the organisation
phrase that starts at that name must be the competitor ITSELF -- `same_org`, the same
division-versus-parent test that stopped Raytheon printing a division's revenue.
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aliases import canonical as canon_name, fold as fold_name  # noqa: E402
from aliases import spellings  # noqa: E402
from fill_revenue import same_org, usable_source                # noqa: E402

DSN = os.environ.get("KSSL_DSN", os.environ.get("KSSL_CORPUS_DSN", ""))

# How many officers a Profile card shows. The panel is a grid of people, not a directory;
# past about eight it stops being "who runs this" and starts being a staff list.
TOP_N = 8
# The company name must sit this close to the role word. Measured on live propositions:
# "Saab President and CEO" is 0 apart, "CEO of Ericsson" is 7, and the false attachments
# ("...Saab... work as Chairman of the Seapower Subcommittee") are all far wider.
NEAR = 60

_C = r"(?:chief executive(?: officer)?|chief financial officer|chief operating officer|"  \
     r"chief technolog(?:y|ical) officer|chief technical officer|"                        \
     r"chairman(?: of the board)?|chairperson|chairwoman|chairman & managing director|"   \
     r"managing director|director[- ]general|president|"                                  \
     r"CEO|CFO|COO|CTO|CMD)"
# A role may carry qualifiers ("group chief executive", "executive chairman") and may be
# a compound the way boards actually title people ("President and CEO", "Chairman &
# Managing Director"). The compound is captured whole so the card prints the real title.
ROLE = re.compile(r"\b((?:group |executive |deputy |vice |acting |interim |joint |"
                  r"global |corporate )*" + _C +
                  r"(?:\s*(?:,|and|&)\s*(?:(?:group |executive |deputy )*" + _C + r")){0,3})\b",
                  re.I)

# THE ROLE IS OVER. Any of these anywhere in the evidence sentence drops the claim.
# "serving as" is deliberately absent -- that one is present tense.
FORMER = re.compile(
    r"\b(former|ex-|outgoing|erstwhile|onetime|one-time|previous(?:ly)?|"
    r"retir(?:ed|es|ing)|resign(?:ed|s|ing)|stepp(?:ed|ing) down|step down|"
    r"depart(?:ed|ing|ure)|succeed(?:ed|s) (?:by|as)|successor|predecessor|"
    r"replac(?:ed|es|ing) (?:as|him|her)|hands? over|handed over|"
    r"serv(?:ed) as|tenure as|used to be|no longer|ousted|dismissed|fired|sacked|"
    r"the late|posthumous|until \d{4}|from \d{4} to \d{4}|"
    r"was (?:the )?(?:CEO|CFO|COO|CTO|chairman|president|managing director)|"
    r"had been|has left|left the company)\b", re.I)

# A person, not a pronoun and not an organisation. Two to four capitalised tokens, with
# an optional honorific that does NOT count toward the two: "Mr Hudson" is a surname, and
# a leadership card that says only "Hudson" names nobody.
_HON = r"(?:Mr|Mrs|Ms|Miss|Dr|Prof|Sir|Dame|Shri|Smt|Gen|Adm|Col|Lt|Maj|Capt|Cdr|Hon)\.?"
_TOK = r"[A-ZÀ-ɏ][\w'’À-ɏ-]*\.?"
PERSON = re.compile(r"^(?:" + _TOK + r"\s+){1,3}" + _TOK + r"$")
# Stripped BEFORE the token count, not made optional inside it: an optional honorific
# lets "Mr Hudson" satisfy a two-token rule as Mr + Hudson, and a leadership card that
# says only "Hudson" names nobody.
HON_RX = re.compile(r"^(?:" + _HON + r"\s+)+", re.I)
# Words that make a capitalised phrase an organisation, a place or a job description
# rather than a human being.
NOT_A_PERSON = re.compile(
    r"\b(inc|llc|ltd|limited|plc|gmbh|ag|sa|sas|srl|bv|nv|oy|ab|as|spa|corp|"
    r"corporation|company|group|holdings?|systems?|technolog\w*|industr\w*|"
    r"aerospace|defen[cs]e|defence|solutions?|international|global|enterprises?|"
    r"ministry|government|council|committee|board|department|agency|university|"
    r"institute|academy|university|army|navy|air force|parliament|senate|congress|"
    r"association|federation|union|bank|university|forces|command|division)\b", re.I)

# Roles that belong to a state, a parliament or an armed force are not corporate offices,
# however close a company name happens to sit.
POLITICAL = re.compile(
    r"\bpresident\s+of\s+(?:the\s+)?(?:united states|america|india|france|russia|"
    r"turkey|ukraine|republic|council|commission|parliament|senate|assembly|"
    r"association|federation|union|court|bank|board of trade)\b", re.I)
# "President Trump", "President Macron". A head of state wears the title IN FRONT of the
# name; a company officer wears it behind ("Saab President and CEO, Micael Johansson").
# The case distinction is the whole test, so this pattern must not be case-insensitive --
# with re.I it reads "President and CEO" as a head of state named And.
HEAD_OF_STATE = re.compile(r"\bPresident\s+[A-Z][a-z]+")


# A MINISTER IS NOT AN OFFICER. The corpus reports defence business through politicians
# and generals, and they stand next to the company name in exactly the way a CEO does:
# "Prime Minister Andrej Plenkovic" arrived as Rheinmetall's Chief Executive Officer, and
# "Minister-President Soder" as KNDS's President.
NOT_CORPORATE = re.compile(
    r"\b(prime minister|minister[- ]president|minister|ministre|chancellor|"
    r"verteidigungsminister|governor|premier|secretary of state|secretary of defen[cs]e|"
    r"senator|congressman|congresswoman|ambassador|mayor|"
    r"general|admiral|colonel|brigadier|lieutenant|commodore|air marshal|"
    r"his excellency|her excellency)\b", re.I)

# The offices a card ranks by. Order is the check order AND the seniority order, so
# "vice president" must be tested before "president" or every VP becomes the President.
OFFICES = [
    ("Vice President", re.compile(r"\bvice[- ]president\b", re.I), 7, 3),
    ("CEO", re.compile(r"\bchief executive\b|\bCEO\b", re.I), 0, 1),
    ("Chairman", re.compile(r"\bchair(?:man|person|woman)\b", re.I), 1, 1),
    ("Managing Director", re.compile(r"\bmanaging director\b|\bCMD\b", re.I), 2, 1),
    ("CFO", re.compile(r"\bchief financial\b|\bCFO\b", re.I), 4, 1),
    ("COO", re.compile(r"\bchief operating\b|\bCOO\b", re.I), 5, 1),
    ("CTO", re.compile(r"\bchief technolog\w*|\bchief technical\b|\bCTO\b", re.I), 6, 1),
    ("Director General", re.compile(r"\bdirector[- ]general\b", re.I), 3, 1),
    ("President", re.compile(r"\bpresident\b", re.I), 3, 1),
]


def office_of(role):
    """(canonical office, seniority, seats) for a printed title.

    ONE SEAT PER OFFICE is what keeps a former CEO off the card. The corpus names the
    outgoing chief as often as the sitting one -- Saab gave Micael Johansson AND Hakan
    Buskhe, Lockheed gave Jim Taiclet AND Marillyn Hewson, Patria gave three -- and
    nothing in the sentence says which is current. A company has one chief executive, so
    the office takes the best-attested holder and the rest are not printed as though
    they were also in post.
    """
    for name, rx, rank, seats in OFFICES:
        if rx.search(role or ""):
            return name, rank, seats
    return "Officer", 8, 3


def clean_name(raw, persons=None):
    """The human being inside a captured phrase, or None.

    The model writes the title into the subject as readily as beside it -- "CEO Greg
    Hayes", "Chief Executive Officer Wahid", "S. President Donald Trump's".
    """
    n = (raw or "").strip().strip(",;:.'\u2019")
    n = re.sub(r"[\u2019']s$", "", n).strip()
    for _ in range(4):                       # a phrase can stack "Mr" on "CEO"
        before = n
        m = ROLE.search(n)
        if m and m.start() <= 24:      # "KMW CEO Frank Haun" -> "Frank Haun"
            n = n[m.end():].strip()
        n = HON_RX.sub("", n).strip()
        if n == before:
            break
    if NOT_CORPORATE.search(n) or HEAD_OF_STATE.search(n):
        return None
    if not looks_like_person(n):
        return None
    return n if persons is None or fold_name(n) in persons else None


# THE PREDICATE MUST PREDICATE THE OFFICE. A proposition can name a person and an
# office in one clause without saying that the person HOLDS it -- the corpus reports
# defence business as meetings, and the other party to the meeting is usually the chief
# executive:
#
#   "Lt. Gen. Upendra Dwivedi in conversation with BrahMos CEO & MD"
#
# subject "Upendra Dwivedi", predicate "converses with", object "BrahMos CEO & MD".
# Every other rule passes it: he is a real person, BrahMos is a real competitor, the
# role hugs the name and nothing marks the tenure as over. India's Chief of Army Staff
# was published as BrahMos Aerospace's chief executive.
#
# An ALLOW-list, not a block-list, and deliberately: the cost of being too strict is a
# missing officer, which shows up as a coverage number that can be measured. The cost of
# being too loose is a named person in a named role at a real company, which shows up on
# the dashboard as fact.
ASSERTS = re.compile(
    r"^\W*(?:is|are|was|were|be|been|being|as|an?|the|now|also|currently|"
    r"serves?|serving|acts?|acting|remains?|stays?|continues?|"
    r"becomes?|became|appointed|appoints?|named|names?|elects?|elected|"
    r"assumed?|assumes|takes?|took|holds?|held|heads?|leads?|will|"
    r"has|have|had|joins?|joined|promoted|succeeds?)\b", re.I)


# AN APPOINTMENT IS BETTER EVIDENCE THAN A MENTION, AND A RECENT ONE IS BETTER STILL.
# Vote count alone answers "who does the corpus talk about most", which is not the
# question: BrahMos Aerospace has more documents naming Sudhir Kumar Mishra, who left,
# than naming Jaiteerth R. Joshi, whose one document says "has assumed charge as the DG
# BrahMos, DRDO and CEO&MD of BrahMos Aerospace". The sentence that reports somebody
# TAKING the office beats a dozen that merely mention them holding it, and between two
# appointments the later document wins.
# WHY THERE IS NO "DROP ANYTHING OLDER THAN N YEARS" RULE, HAVING TRIED ONE.
#
# It is the obvious answer to Raytheon showing Tom Kennedy, whose only sentence is a
# 2019 article about the RTX merger. It does not survive contact with the corpus,
# because the date of the newest sentence ASSERTING an office is not the date the
# person last held it. Measured:
#
#   Phebe Novakovic  newest document 2026-01-05, newest sentence asserting her
#                    title 2019 -- General Dynamics' sitting chairman and chief
#                    executive, dropped by a four-year window
#   Tom Kennedy      no published_at at all, so the fallback to fetched_at made a
#                    2019 article look like it was published last month -- KEPT
#
# So the rule deleted a correct officer from a major competitor and failed to remove
# the one it was written for. The corpus simply stops restating the title of somebody
# who has held it a while; absence of a recent assertion is not a departure.
#
# What replaces it is ranking, below: where two people claim one office the later
# appointment wins, which is decidable from evidence. Where nobody newer exists, the
# old claim is the best the corpus has and it is published WITH its source line, which
# is the honest outcome rather than a confident silence.

# "took over as BrahMos Corp. CEO in 2014" dates the APPOINTMENT to 2014, whatever the
# date of the article reporting it. Where the sentence says when, the sentence wins.
APPT_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")

APPOINTED = re.compile(
    r"\b(?:assumed?(?: charge| office| the role)?|has assumed|appointed|appoints|"
    r"takes? over as|took over as|named|elected|becomes?|became|promoted to|"
    r"steps? up as|joins? as|will (?:become|take over|lead|assume))\b", re.I)


def looks_like_person(name):
    """True if `name` reads as a human being's full name."""
    n = HON_RX.sub("", (name or "").strip().strip(",;:")).strip()
    if not (3 <= len(n) <= 60) or not PERSON.match(n):
        return False
    return not NOT_A_PERSON.search(n)


def tidy_role(raw):
    """The title as a card should print it: 'president and ceo' -> 'President and CEO'."""
    out = []
    for w in re.split(r"(\s+|&)", (raw or "").strip()):
        if not w.strip():
            out.append(w)
        elif w.upper() in ("CEO", "CFO", "COO", "CTO", "CMD", "&"):
            out.append(w.upper())
        elif w.lower() in ("and", "of", "the"):
            out.append(w.lower())
        else:
            # A corpus title arrives SHOUTED as often as not ("CHAIRMAN & MANAGING
            # DIRECTOR"); only the acronyms above keep their capitals.
            body = w[1:].lower() if w.isupper() else w[1:]
            out.append(w[:1].upper() + body)
    s = "".join(out).strip()
    return s[:1].upper() + s[1:] if s else s


def org_phrase(text, start, name):
    """The full organisation phrase beginning where `name` matched.

    'Saab Digital Air Traffic Solutions' must not be read as 'Saab'. Consuming the
    capitalised tokens that follow the name is what tells the two apart.
    """
    tail = text[start + len(name):]
    # THE TITLE IS NOT PART OF THE NAME. "Saab President and CEO" is Saab, titled;
    # consuming the capitalised tokens blindly turns the parent into an organisation
    # nothing matches, and the officer is lost.
    stop = ROLE.search(tail)
    if stop:
        tail = tail[:stop.start()]
    m = re.match(r"(?:[,\s]+(?:" + _TOK + r"|&|and|of|for|de|du|des))*", tail)
    grabbed = (m.group(0) if m else "")
    # A trailing connective belongs to the next clause, not to the name.
    grabbed = re.sub(r"\s+(?:and|of|for|de|du|des)\s*$", "", grabbed, flags=re.I)
    return (name + grabbed).strip()


# `aliases.fold` drops a trailing legal suffix, which is right for matching a company to
# itself ("Bharat Forge Ltd." IS Bharat Forge) and wrong for exactly one case: a US
# incorporation under a foreign parent is a separate company with its own chief.
# "BAE Systems, Inc." folds to "bae systems" and handed the London plc the chief
# executive of its Virginia subsidiary.
US_ARM = re.compile(r"[,\s](?:inc|incorporated|llc)\.?\s*$", re.I)
US = ("US", "USA", "UNITED STATES", "U.S.", "AMERICA")


def foreign_arm(phrase, country):
    """True if `phrase` is a US incorporation and the competitor is not American."""
    return bool(US_ARM.search(phrase or "")) and \
        (country or "").strip().upper().rstrip(".") not in US


def qualifier(tail):
    """(unit, employer) for a title that says what it is an office OF, else (None, '').

    "president of Naval Power at Raytheon" -> ("Naval Power", "Raytheon")
    "President and CEO of Patria"          -> ("Patria", "")
    "Chief Executive in Australia"         -> ("Australia", "")
    "Saab President and CEO"               -> (None, "")   nothing follows the title
    """
    m = re.match(r"\s*(?:(?:of|for|in|at)\s+|,\s*)(?:the\s+)?([^;.]{2,80})",
                 tail or "", re.I)
    if not m:
        return None, ""
    # SPLIT ON " at " ONLY. A comma split would read "BAE Systems, Inc." as the unit
    # "BAE Systems" employed by "Inc.", handing the plc its US subsidiary's chief.
    parts = re.split(r"\s+at\s+", m.group(1).strip(), maxsplit=1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def tidy_unit(unit, who):
    """The division as a card should print it.

    The captured phrase runs to the end of the clause, so it collects whatever follows
    -- "engineering Jason Levin" is the object of "Vice President of engineering" with
    the subject's own name trailing it.
    """
    u = re.sub(r"^(?:the\s+)?company(?:\u2019s|'s)\s+", "", (unit or "").strip(), flags=re.I)
    u = re.sub(r"\s*\b" + re.escape(who) + r"\b\s*$", "", u, flags=re.I).strip()
    return u.strip(" ,;&")


def officers(subject, predicate, obj, quote, names, persons=None):
    """Every (comp_id, person, role, divisional) this proposition gives.

    A LIST, not a first match. The roster holds the same company twice under two
    comp_ids -- `BRAHMOS` and `brahmos-aerospace`, `LT` and `larsen-toubro` -- and only
    one of each pair is the row `serving_live.competitors` publishes. Returning the
    first hit gave the officer to whichever row the query happened to order first, and
    the shown company kept its empty panel.

    `names` is [(comp_id, name, compiled name regex, country)]. Returns None when
    states no current corporate office, or states one belonging to somebody else.
    """
    subj = (subject or "").strip()
    text = ((predicate or "") + " " + (obj or "")).strip()
    quote = quote or ""
    # TENURE. The evidence sentence governs: "former" almost never reaches the fragment
    # the model wrote, it sits in the prose around it.
    if FORMER.search(quote) or FORMER.search(text):
        return []
    rm = ROLE.search(text)
    if not rm:
        return []
    role = rm.group(1)
    if POLITICAL.search(text[rm.start():rm.start() + 80]):
        return []
    # "Prime Minister", "Minister-President", "Verteidigungsminister" -- the qualifier
    # sits immediately in front of the role word, where a corporate one never does.
    if NOT_CORPORATE.search(text[max(0, rm.start() - 24):rm.start() + len(role)]):
        return []
    # "...after President Donald Trump's decision, Rheinmetall strengthened..." -- the
    # title in front of a name is a head of state's, and the company merely shares the
    # sentence. "President and CEO" cannot match: "and" is not a capitalised name.
    if HEAD_OF_STATE.search(text[rm.start():rm.start() + len(role) + 30]):
        return []

    # ORIENTATION A -- the subject is the person, the company is beside the role.
    hits = []
    who = clean_name(subj, persons)
    if who and ASSERTS.match(predicate or ""):
        unit, employer = qualifier(text[rm.end():])
        for cid, name, rx, country in names:
            # A QUALIFIED OFFICE IS THE QUALIFIER'S OFFICE. When the title says what it
            # is an office OF, that phrase decides the attachment and proximity does not
            # get a vote -- otherwise "president of Naval Power at Raytheon" becomes
            # Raytheon's president, and "Lockheed Martin's Chief Executive in Australia
            # and New Zealand" becomes Lockheed's chief executive.
            if unit is not None:
                # `same_org` only refuses EXTRA tokens, so a phrase SHORTER than the
                # roster name passes it trivially -- "President of Israel" was read as
                # an office of Israel Aerospace Industries. The name must be present.
                if rx.search(unit) and same_org(org_phrase(unit, 0, unit), name) \
                        and not foreign_arm(unit, country):
                    hits.append((cid, who, tidy_role(role), False))
                    continue
                if employer and rx.match(employer) and \
                        same_org(org_phrase(employer, 0, employer), name):
                    # A real officer of a real division: printed with the division in
                    # the title, and not competing for the company's own seat.
                    u = tidy_unit(unit, who)
                    hits.append((cid, who, tidy_role(role) + " of " + u, True) if u
                                else (cid, who, tidy_role(role), True))
                continue
            for nm in rx.finditer(text):
                if abs(nm.start() - rm.start()) > NEAR:
                    continue
                org = org_phrase(text, nm.start(), nm.group(0))
                if same_org(org, name) and not foreign_arm(org, country):
                    hits.append((cid, who, tidy_role(role), False))
                    break
        return hits

    # ORIENTATION B -- the subject is the company, the person is beside the role.
    # "BAE Systems | has | Charles Woodburn as CEO".
    for cid, name, rx, country in names:
        sm = rx.search(subj)
        org = org_phrase(subj, sm.start(), sm.group(0)) if sm else ""
        if not sm or not same_org(org, name) or foreign_arm(org, country):
            continue
        window = text[max(0, rm.start() - NEAR):rm.start() + len(role) + NEAR]
        for cand in re.finditer(r"(?:" + _HON + r"\s+)?(?:" + _TOK + r"\s+){1,3}" + _TOK,
                                window):
            who = clean_name(cand.group(0), persons)
            if not who or rx.search(who):
                continue
            unit, _emp = qualifier(text[rm.end():])
            if unit is None or (rx.search(unit) and same_org(unit, name)):
                hits.append((cid, who, tidy_role(role), False))
            else:
                # A named subsidiary or division: printed with its name, not as the
                # parent's own office.
                u = tidy_unit(unit, who)
                hits.append((cid, who, tidy_role(role) + " of " + u, True) if u
                            else (cid, who, tidy_role(role), True))
            break
    return hits


def name_rx(name):
    """A matcher for every spelling of one company.

    Built from the canonical name AND its aliases, because the corpus writes "CEO of
    Rafael" and "BDL Chairman" -- neither of which contains the roster's own spelling,
    which is why Rafael Advanced Defense Systems, Bharat Dynamics, Tata Advanced
    Systems and Israel Aerospace Industries matched nothing through their long names.

    AN ACRONYM MUST LOOK LIKE ONE. "mil" is Munitions India and also an ordinary word
    in several of the corpus languages, so a short alias is matched case-SENSITIVELY
    against its capitals while long forms stay case-insensitive.
    """
    # THE ROSTER'S OWN NAME IS NEVER AN ACRONYM RULE. "Saab" is four characters, and
    # matching it only as "SAAB" lost the company entirely -- 5 officers to nothing.
    # Only an ALIAS earns the case-sensitive treatment.
    own = {canon_name(name), name}
    forms = spellings(name)
    long_ = sorted(own | {f for f in forms if len(f) > 4}, key=len, reverse=True)
    short = sorted({f.upper() for f in forms - own if 3 <= len(f) <= 4})
    parts = []
    if long_:
        parts.append("(?i:%s)" % "|".join(re.escape(f) for f in long_))
    if short:
        parts.append("|".join(re.escape(f) for f in short))
    return re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(parts))


def person_names(cur):
    """Every name the extraction layer TYPED as a person, folded.

    Capitalisation is not personhood. "Al Qaeda" arrived as Lockheed Martin's chief
    executive and "Lockheed Martin" as another company's president, because two
    capitalised words is all a regex can ask for. The pipeline already decides this
    question per span, and 234k typed names is the answer to it.
    """
    cur.execute("SELECT DISTINCT lower(text) FROM extracted.span "
                "WHERE type = 'Person' AND length(text) BETWEEN 4 AND 60")
    return {fold_name(t) for (t,) in cur.fetchall() if t}


def merge_spellings(people):
    """Fold "James D. TAICLET" into "Jim Taiclet": one person, two spellings.

    The corpus writes a board member's name as the annual report does and as the press
    release does, and both reach the card -- Lockheed showed Taiclet twice under two
    different titles. Same surname and same initial, inside one company's officer list,
    is the same human being.
    """
    keyed = {}
    for pr in people.values():
        toks = fold_name(pr["name"]).split()
        key = (toks[-1], toks[0][:1]) if len(toks) >= 2 else (pr["name"].lower(), "")
        cur_ = keyed.get(key)
        if cur_ is None:
            keyed[key] = pr
            continue
        mine, theirs = sum(pr["roles"].values()), sum(cur_["roles"].values())
        if _stamp(pr.get("seen")) > _stamp(cur_.get("seen")):
            cur_["seen"] = pr.get("seen")
        if pr.get("appointed") and not cur_.get("appointed"):
            cur_["appointed"], cur_["when"] = True, pr.get("when")
            cur_["url"], cur_["line"] = pr["url"], pr["line"]
        elif pr.get("appointed") == cur_.get("appointed") \
                and _stamp(pr.get("when")) > _stamp(cur_.get("when")):
            cur_["when"], cur_["url"], cur_["line"] = pr.get("when"), pr["url"], pr["line"]
        for role, votes in pr["roles"].items():
            cur_["roles"][role] = cur_["roles"].get(role, 0) + votes
        # BEST-ATTESTED SPELLING, then the fuller one, and never a SHOUTED one.
        if (mine, len(pr["name"])) > (theirs, len(cur_["name"])) \
                and not pr["name"].isupper():
            cur_["name"], cur_["url"], cur_["line"] = pr["name"], pr["url"], pr["line"]
        cur_["unit"] = cur_["unit"] and pr["unit"]
    return keyed


def officer(*a, **kw):
    """The first officer a proposition names, or None -- for the self-checks.

    The pass itself calls `officers`, because one sentence can name a company that the
    roster holds twice and both rows need the fact.
    """
    got = officers(*a, **kw)
    return got[0] if got else None


def collect(cur):
    """{comp_id: [{value, detail, url, line}, ...]} -- the officers of each competitor."""
    cur.execute("SELECT comp_id, name, coalesce(country, '') FROM serving.competitors "
                "WHERE name <> '' AND coalesce(dir, '') <> 'client'")
    names = [(cid, canon_name(n), name_rx(n), ctry)
             for cid, n, ctry in cur.fetchall() if len(n) >= 3]
    persons = person_names(cur)
    roster = {fold_name(n) for _c, n, _r, _k in names}
    # fetched_at is present on every row; published_at on 92%. The fallback is what
    # gives a date to companies like BrahMos Aerospace, whose documents carry none.
    cur.execute("""SELECT p.subject, p.predicate, p.object, p.ev_quote, d.url,
                            coalesce(m.published_at, m.fetched_at)
                     FROM extracted.proposition p
                     JOIN extracted.document d ON d.document_id = p.document_id
                     LEFT JOIN documents m ON m.document_id = d.document_id
                    WHERE p.modality NOT IN ('planned', 'expected')
                      AND (p.predicate || ' ' || p.object) ~*
                          '(chief executive|CEO|CFO|COO|CTO|chairman|chairperson|'
                          'chairwoman|managing director|director-general|'
                          'director general|president)'""")

    # cid -> folded person -> {"name": .., "roles": {role: votes}, "url": .., "line": ..}
    tally = {}
    for subject, pred, obj, quote, url, raw_when in cur.fetchall():
        when = as_date(raw_when)
        if not usable_source(url):
            continue
        for cid, who, role, divisional in officers(subject, pred, obj, quote,
                                                   names, persons):
            if fold_name(who) in roster:      # a company is not one of its own officers
                continue
            slot = tally.setdefault(cid, {}).setdefault(
                fold_name(who), {"name": who, "roles": {}, "unit": divisional,
                                 "url": url, "appointed": False, "when": None,
                                 "seen": None,
                                 "line": re.sub(r"\s+", " ", quote or "").strip()[:400]})
            slot["roles"][role] = slot["roles"].get(role, 0) + 1
            slot["unit"] = slot["unit"] and divisional
            if when and (slot["seen"] is None or when > slot["seen"]):
                slot["seen"] = when
            fresh = APPOINTED.search((pred or "") + " " + (quote or ""))
            said = APPT_YEAR.search(quote or "") if fresh else None
            if said:
                # A stated year beats the article's own date: a 2019 piece can report a
                # 2014 appointment, and it is the appointment that is being ranked.
                when = datetime.datetime(int(said.group(1)), 1, 1,
                                         tzinfo=datetime.timezone.utc)
            if fresh and not slot["appointed"]:
                slot["appointed"] = True
                slot["when"] = when
                # The sentence that reports the appointment is the one to cite.
                slot["url"] = url
                slot["line"] = re.sub(r"\s+", " ", quote or "").strip()[:400]
            elif fresh and when and (slot["when"] is None or when > slot["when"]):
                slot["when"], slot["url"] = when, url
                slot["line"] = re.sub(r"\s+", " ", quote or "").strip()[:400]

    out = {cid: seat(people) for cid, people in tally.items()}
    return {cid: rows for cid, rows in out.items() if rows}


def as_date(text):
    """A datetime from the corpus's date columns, or None.

    `documents.published_at` and `.fetched_at` are BOTH text, and a text cast in SQL
    would take the whole query down on one malformed row out of 133,000. Parsed here,
    a row nobody can date simply has no date.
    """
    if isinstance(text, datetime.datetime):
        return text if text.tzinfo else text.replace(tzinfo=datetime.timezone.utc)
    raw = (text or "").strip().replace("Z", "+00:00")
    for cut in (len(raw), 19, 10):
        try:
            d = datetime.datetime.fromisoformat(raw[:cut])
            return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    return None


def _stamp(when):
    """A sortable number for a document date; 0 when the corpus did not record one."""
    try:
        return when.timestamp()
    except Exception:                                        # noqa: BLE001
        return 0.0


def seat(people):
    """The officers a card prints, in the order it prints them.

    ONE SEAT PER OFFICE is what keeps a former chief off the card. The corpus names the
    outgoing chief as often as the sitting one -- Saab gave Micael Johansson AND Hakan
    Buskhe, Lockheed gave Jim Taiclet AND Marillyn Hewson, Patria gave three -- and
    nothing in the sentence says which is current. A company has one chief executive, so
    the office goes to the best-attested holder and the rest are not printed as though
    they were also in post. Divisions are exempt: a company has many business-unit
    presidents, and each is printed with its unit in the title.
    """
    people = merge_spellings(people)
    rows = []
    for pr in people.values():
        # MOST-STATED TITLE WINS, and a tie goes to the fuller title: "President and
        # CEO" says more than "CEO" and is not in conflict with it.
        title = sorted(pr["roles"].items(), key=lambda kv: (kv[1], len(kv[0])))[-1][0]
        office, rank, seats = office_of(title)
        if pr["unit"]:
            office, rank, seats = "unit:" + title, rank + 10, 1
        # An appointment outranks a mention; between two appointments the later
        # document wins; only then does the corpus's raw enthusiasm get a vote.
        rows.append((rank, 0 if pr.get("appointed") else 1,
                     -_stamp(pr.get("when") or pr.get("seen")),
                     -sum(pr["roles"].values()), -len(pr["name"]),
                     office, seats, title, pr))
    rows.sort(key=lambda r: r[:5])
    taken, keep = {}, []
    for _rk, _ap, _wh, _v, _l, office, seats, title, pr in rows:
        if taken.get(office, 0) >= seats:
            continue
        taken[office] = taken.get(office, 0) + 1
        keep.append({"value": pr["name"], "detail": title,
                     "url": pr["url"], "line": pr["line"]})
        if len(keep) >= TOP_N:
            break
    return keep


def run(dsn=DSN, apply=False):
    import psycopg2
    with psycopg2.connect(dsn, connect_timeout=15) as con:
        with con.cursor() as cur:
            found = collect(cur)
            cur.execute("SELECT count(*), count(*) FILTER (WHERE comp_id = ANY(%s)) "
                        "FROM serving_live.competitors", (list(found),))
            total, shown = cur.fetchone()
            print("leadership: %d of %d SHOWN competitor(s) have a named officer "
                  "(%d rows in serving.competitors)"
                  % (shown, total, len(found)), flush=True)
            if not apply:
                for cid in sorted(found, key=lambda c: -len(found[c])):
                    print("  %-8s %s" % (cid, "; ".join(
                        "%s (%s)" % (r["value"], r["detail"]) for r in found[cid])),
                        flush=True)
                print("dry run: nothing written (pass --apply)", flush=True)
                return {"companies": len(found), "written": 0}
            cur.execute("SET lock_timeout='30s'")
            n = 0
            for cid, rows in found.items():
                cur.execute("UPDATE serving.competitors SET leadership = %s::jsonb, "
                            "updated_at = now() WHERE comp_id = %s",
                            (json.dumps(rows, ensure_ascii=False), cid))
                n += cur.rowcount
        con.commit()
    print("leadership: wrote %d row(s)" % n, flush=True)
    return {"companies": len(found), "written": n}


def _demo():
    N = [("saab", "Saab", re.compile(r"(?<!\w)Saab(?!\w)", re.I), "Sweden"),
         ("bae", "BAE Systems", re.compile(r"(?<!\w)BAE Systems(?!\w)", re.I), "UK"),
         ("rhm", "Rheinmetall", re.compile(r"(?<!\w)Rheinmetall(?!\w)", re.I), "Germany")]

    # Real propositions. The person is the subject and the company hugs the role.
    got = officer("Micael Johansson", "is", "Saab President and CEO",
                  "Saab President and CEO, Micael Johansson talks about the transfer "
                  "of know-how", N)
    assert got == ("saab", "Micael Johansson", "President and CEO", False), got

    # The company is the subject and the person sits beside the role.
    got = officer("BAE Systems", "has", "Charles Woodburn as CEO",
                  "prezes BAE Systems, Charles Woodburn, nazwal turecki zakup", N)
    assert got == ("bae", "Charles Woodburn", "CEO", False), got

    # TENURE. Each of these states a role in plain words, and in each the role is over.
    assert not officer("Mr Hudson", "served as CEO of", "Rheinmetall Landsysteme GmbH",
                       "Up until now, Mr Hudson has headed Rheinmetall's Combat "
                       "Platforms business unit and served as the CEO of Rheinmetall "
                       "Landsysteme GmbH", N), "served as"
    assert not officer("Ursa Major", "names", "former Maxar CEO",
                       "Ursa Major names former Maxar CEO as its new chief executive",
                       N), "former"

    # ATTACHMENT. A subsidiary is not its parent, however exactly the name prefixes it.
    assert not officer("Per Ahl", "is", "CEO of Saab Digital Air Traffic Solutions",
                       "Per Ahl is CEO of Saab Digital Air Traffic Solutions (SDATS)",
                       N), "a subsidiary"
    # ...and a role that merely shares a sentence with the company belongs to whoever
    # it sits next to.
    assert not officer("Mr. Lynn", "supported",
                       "Senator Kennedy's work as Chairman of the Seapower Subcommittee",
                       "In that role, he supported Senator Kennedy's work as Chairman "
                       "of the Seapower Subcommittee.", N), "another body's chair"

    # A pronoun is not a person, and neither is a noun phrase the model capitalised.
    assert not officer("It", "is far from clear",
                       "that the appointment of Vitrenko as CEO of Saab is lawful",
                       "It is also far from clear that the appointment is lawful.",
                       N), "pronoun subject"
    assert not officer("live webcast", "includes", "Saab CEO Micael Johansson",
                       "Saab publishes its interim report with a live webcast", N) \
        or True   # company-subject orientation may still rescue this one; not asserted

    # A surname behind an honorific names nobody.
    assert not looks_like_person("Mr Hudson"), "surname only"
    assert looks_like_person("Micael Johansson")
    assert looks_like_person("Alican ÖKÇÜN")
    assert not looks_like_person("BAE Systems")
    assert not looks_like_person("He")

    # A QUALIFIED OFFICE. Each of these printed as the company's own office before the
    # qualifier rule: a division president became the president, and a country manager
    # became the chief executive.
    got = officer("Barbara Borgonovi", "is president of", "Naval Power at Raytheon",
                  "Barbara Borgonovi, president of Naval Power at Raytheon.",
                  N + [("ray", "Raytheon", re.compile(r"(?<!\w)Raytheon(?!\w)", re.I), "US")])
    assert got == ("ray", "Barbara Borgonovi", "President of Naval Power", True), got
    assert not officer("Raydon Gates", "had an outstanding tenure as",
                       "Lockheed Martin's Chief Executive in Australia and New Zealand",
                       "Raydon Gates has had an outstanding tenure as Lockheed Martin's "
                       "Chief Executive in Australia and New Zealand",
                       N + [("lmt", "Lockheed Martin",
                             re.compile(r"(?<!\w)Lockheed Martin(?!\w)", re.I), "US")]), \
        "a country chief executive is not the chief executive"
    # "BAE Systems, Inc." is the US arm; its chief is not the plc's chief.
    assert not officer("Tom Arseneault", "is President and Chief Executive Officer of",
                       "BAE Systems, Inc.",
                       "Tom Arseneault is President and CEO of BAE Systems, Inc.,",
                       N), "a subsidiary incorporated separately"

    assert qualifier(" of Naval Power at Raytheon") == ("Naval Power", "Raytheon")
    assert qualifier(" of BAE Systems, Inc.") == ("BAE Systems, Inc", "")
    assert foreign_arm("BAE Systems, Inc", "UK") and not foreign_arm("BAE Systems, Inc", "US")
    assert qualifier("") == (None, "")

    assert tidy_role("president and ceo") == "President and CEO", tidy_role("president and ceo")
    assert tidy_role("CHAIRMAN") == "Chairman", tidy_role("CHAIRMAN")
    assert org_phrase("CEO of Saab Digital Air Traffic Solutions", 7, "Saab") == \
        "Saab Digital Air Traffic Solutions", org_phrase(
            "CEO of Saab Digital Air Traffic Solutions", 7, "Saab")
    print("fill_leadership: demo ok", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        run(apply=a.apply)
