# -*- coding: utf-8 -*-
"""Whether two products may be compared at all.

The Positioning tab paired "Adani Defence & Aerospace · SkyStriker" with
"KSSL · Bayonet" and then reported, correctly, that none of the sourced values
were comparable on both sides. The sourcing gate was working. The pairing should
never have been proposed, and three separate faults put it on the screen:

  1. NOBODY CHOOSES THE PAIRS. revive_matchups.py republishes the 507 hand-built
     archive rows (origin='reference') whose numbers it can ground. It never asks
     whether the two products compete. The archive is a cross product -- one rival
     list multiplied by two KSSL names -- so every loitering rival appears twice,
     against Bayonet and against Cleaver, with identical spec tables.

  2. THE ARCHIVE IS NOT SCOPED TO THE ROSTER. Neither copy of revive_matchups.py
     contains the word roster. That is how "HESA · Shahed-136" became a rival:
     HESA is not one of the 44 tracked competitors and appears in no workbook, so
     the archive is the only thing that could have introduced it.

  3. THE KSSL SIDE NEED NOT BE A KSSL PRODUCT. "Bayonet" and "Cleaver" are not in
     the client's own workbook. The string "bayonet" occurs there once, as a
     bayonet lug on the Protective Carbine. KSSL's actual UAV in the workbook is
     the Bharat 150 -- an X-8 multi-rotor VTOL of 150 kg MTOW, which is not the
     same kind of object as a 35 kg one-way attack munition anyway.

And the same row carries a fourth fault this module cannot fix: the audited
50-company workbook attributes SkyStriker to ELBIT SYSTEMS, while the archive
attributes it to Adani. One of them is wrong and the screen shows the archive's
answer.

So: a pairing is proposed only when the maker is tracked, the KSSL side is a
product the client actually publishes, and the two sides already share at least
one directional measurable. Fail closed. A pairing with nothing comparable has
nothing to say, and a row that says nothing still counts in the badge and in
"N rivals" -- which turns absence of evidence into presence of competitors.

TWO WAYS TO BE WRONG, NOT ONE. The first draft of this gate refused all 117
published rows. Refusing a real pairing costs exactly as much as publishing a
fake one, and identity was where it went wrong both times:

  * "Advanced Weapons and Equipment India Limited" IS on the roster -- as AWEIL.
    Nineteen rows read as off-roster because nothing folded the legal name onto
    the initials. The fix belongs in aliases.py, the one identity layer, not in a
    second table here.
  * "MPV", "LTV", "LBPV", "ATC", "ULSV" and "M4" ARE client products -- the
    workbook spells them "Mine Protected Vehicle", "Light Tactical Vehicle" and
    "Kalyani M4". An initialism is generated from the product's own words rather
    than hand-listed, so a product added to the workbook tomorrow needs no entry
    here.

WHAT COUNTS AS COMPARABLE IS NOT A WORD LIST. A spec row carries `hi`: True when
higher is better, False when lower is, None when the field has no better and worse
at all. Calibre is None -- 155 mm is not better than 105 mm -- so direction does the
work a `calibre|bore|type|class` regex was doing. That regex survives only for rows
that carry no direction at all, because a closed keyword list is a language detector
and this repo has paid for that lesson three times.

...BUT DIRECTION IS NOT READ OFF THE ROW ANY MORE. It was never computed: it was
typed into each of the 507 archive rows by hand, and the same field came out
directional on one row and blank on the next -- Rate of fire is directional on 1 of
the 35 live rows that hold it. This gate therefore called the same field comparable
on one pairing and incomparable on another. spec_direction.DIRECTION is the one table,
keyed by field label, and it is asked first.

AND AN EMPTY LIST IS A REFUSAL. `if roster_names:` / `if client_products:` meant both
checks stood down when their list was empty -- which is the state of a database whose
serving.competitors or serving.client_product has not been loaded, i.e. exactly when
an unchecked pairing gets published. Being unable to check is not having checked.
KSSL_PAIRING_ALLOW_EMPTY_LISTS=1 restores the old behaviour on purpose, loudly.
"""
import os
import re
import sys
import unicodedata

import aliases
import spec_direction

# One directional field is thin, but it is a comparison; the engine already shrinks
# a one-field verdict towards parity by n/(n+1) so it cannot print maximum severity
# on the thinnest evidence. Zero is not thin, it is empty.
MIN_SHARED_FIELDS = 1

# Fallback only -- see the module docstring. Applied when a spec row carries no `hi`
# at all AND the field's label is not in spec_direction's table, which is the shape a
# hand-built archive row has before the engine parses it.
AXIS_FIELDS = re.compile(
    r"\b(calibre|caliber|bore|configuration|type|class|variant|family|role)\b", re.I)

# THE ONE OVERRIDE, AND IT SAYS SO. Both list checks below used to be written
# `if roster_names:` and `if client_products:`, so an empty list SKIPPED the check and
# every anchor and every rival walked through -- and the lists are empty in exactly the
# situation that matters: a run against a database whose serving.competitors or
# serving.client_product has not been loaded yet. A gate that cannot fail closed is not
# a gate. Absence is a refusal now; this variable is how someone says otherwise on
# purpose, and refuse() reports that they did.
ALLOW_EMPTY = "KSSL_PAIRING_ALLOW_EMPTY_LISTS"


def allow_empty():
    return os.environ.get(ALLOW_EMPTY) == "1"

_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _num(v):
    """The first real number in a value, or None. '155 mm' -> 155.0, '-' -> None."""
    if v is None:
        return None
    m = _NUM.search(str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def product_of(label):
    """'KNDS · CAESAR 6x6' -> 'CAESAR 6x6'. The maker is not the product."""
    return (label or "").split("·")[-1].strip()


def maker_of(label):
    """'KNDS · CAESAR 6x6' -> 'KNDS'."""
    parts = (label or "").split("·")
    return parts[0].strip() if len(parts) > 1 else ""


# An initialism needs at least this many words, all of them words. A TWO-token name
# was enough before, and the first letter of a token was taken whether that token was a
# word or a number -- so "MaRG 45" reduced to 'm' + '4' = "m4" and
# same_product("M4", "MaRG 45") came back True: an armoured vehicle validated as a
# client product by a wheeled howitzer. Every real case is three words or more ("Mine
# Protected Vehicle", "Light Tactical Vehicle", "Ultra Light Specialist Vehicle"), and
# a two-letter initialism collides with far too much to be evidence of anything.
MIN_INITIALISM_TOKENS = 3


def initialism(name):
    """'Mine Protected Vehicle' -> 'mpv'. The client's own abbreviations.

    Generated, not listed: the workbook writes the long name and the matchup writes
    the short one, and there are six of them. A hand-list would need an entry for
    every product added after today.

    Returns "" -- never a partial answer -- when the name is too short to abbreviate or
    carries a model number, because a model number is part of the NAME and not one of
    the words being abbreviated.
    """
    toks = [t for t in norm(name).split() if t]
    if len(toks) < MIN_INITIALISM_TOKENS:
        return ""
    if not all(t.isalpha() for t in toks):
        return ""
    return "".join(t[0] for t in toks)


def same_product(candidate, published):
    """Is `candidate` the client product `published`, however it is written?"""
    a, b = norm(candidate), norm(published)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) > 3 and a in b:
        return True
    if len(b) > 3 and b in a:
        return True
    if a == initialism(published):
        return True
    # A single token that IS one of the product's words: 'M4' in 'Kalyani M4'.
    # Only a single token, so a two-word name cannot half-match its way in.
    if " " not in a and a in b.split():
        return True
    return False


# ONE ORGANISATION RULE, NOT TWO. This was a private copy here for a day, and the
# news writer needed the same decision -- a division reaching its parent, with the
# guard that stops "Elbit" absorbing Elbit Imaging. A display label used as a join key
# has already cost this project a whole layer, so the rule lives in aliases.py and
# both callers ask it.
same_org = aliases.same_org


def shared_measurables(specs):
    """How many fields can actually decide a lead, on BOTH sides.

    This is the test the engine already performs to write its verdict -- "N value(s)
    sourced, none comparable on both sides". Performing it AFTER the row exists
    produces a row whose whole content is the news that it has nothing to say. It
    belongs here, before the row.
    """
    n, fields = 0, []
    for s in specs or []:
        label = s.get("l") or s.get("label") or ""
        # THE FIELD DECIDES ITS OWN DIRECTION. Reading `hi` off the row asked the
        # archive, which typed it by hand and disagreed with itself: Rate of fire is
        # directional on 1 of the 35 live rows that hold it and blank on the other 34,
        # so this gate called the same field comparable on one pairing and not on the
        # next. spec_direction.DIRECTION is the one answer.
        if spec_direction.known(label):
            hi = spec_direction.direction_of(label)
        elif "hi" in s:
            hi = s.get("hi")
        else:
            # Neither the table nor the row says anything. The regex survives for this
            # case only -- a closed keyword list is a language detector, and this repo
            # has paid for that lesson three times.
            if AXIS_FIELDS.search(label):
                continue
            hi = True
        if hi is None:
            continue
        # The engine's own definition: a number on each side, and a field that has a
        # better and a worse.
        #
        # The text fallback is for a row that carries no cn/kn AT ALL -- the shape a
        # hand-built archive row has before the engine parses it. A cn that is present
        # and None is a DECISION: rebuild() blanks both when the two sides resolve to
        # different quantities ("one side's unit is unknown: not comparable") or when a
        # side's sources failed the credibility bar. Reading the numbers back out of
        # the display text would undo that, and put a 47-against-18000 comparison back
        # on the screen.
        if "cn" in s or "kn" in s:
            cn, kn = s.get("cn"), s.get("kn")
        else:
            cn, kn = _num(s.get("cv")), _num(s.get("kv"))
        if cn is not None and kn is not None:
            n += 1
            fields.append(label)
    return n, fields


_warned = [False]


def _warn_override(what):
    """Say it once, on stderr, loudly. An override nobody can see is a silent pass."""
    if _warned[0]:
        return
    _warned[0] = True
    sys.stderr.write(
        "\n*** %s IS SET. %s is empty and the check that uses it is being SKIPPED for\n"
        "*** every row in this run. This is the fault that put 'HESA - Shahed-136'\n"
        "*** and 'KSSL - Bayonet' on the Positioning tab. Unset it unless you know why\n"
        "*** you want it.\n\n" % (ALLOW_EMPTY, what))
    sys.stderr.flush()


def refuse(row, roster_names=(), client_products=()):
    """-> (reason, detail) when the pairing must not be published, else (None, '').

    `row` is the shape revive_matchups builds: comp, compBy, bf, bfBy, specs.
    `roster_names` are the tracked competitors' names; `client_products` are the
    product names the client's own workbook holds.

    AN EMPTY LIST IS A REFUSAL, NOT A PASS. `if roster_names:` and
    `if client_products:` meant the gate stood down exactly when it had nothing to
    check against -- a database whose serving.competitors or serving.client_product
    had not been loaded -- and admitted every anchor and every rival. Being unable to
    check is not the same as having checked. Set KSSL_PAIRING_ALLOW_EMPTY_LISTS=1 to
    go back to the old behaviour on purpose; it prints a warning when it does.
    """
    lenient = allow_empty()
    if not [r for r in roster_names if r]:
        if not lenient:
            return ("no tracked-competitor roster to check the maker against",
                    "serving.competitors returned nothing")
        _warn_override("the competitor roster")
    if not [p for p in client_products if p]:
        if not lenient:
            return ("no client portfolio to check the KSSL side against",
                    "serving.client_product returned nothing")
        _warn_override("the client portfolio")

    comp_by = row.get("compBy") or maker_of(row.get("comp"))
    if roster_names:
        # A row that names no maker at all cannot be checked against the roster
        # either, and `if comp_by and ...` let it through for the same reason the
        # empty list did.
        if not comp_by:
            return ("the pairing names no maker", str(row.get("comp") or "")[:60])
        if not any(same_org(comp_by, r) for r in roster_names if r):
            return ("maker is not a tracked competitor", comp_by)

    if client_products:
        bf = product_of(row.get("bf"))
        if not bf:
            return ("the pairing names no KSSL product", str(row.get("bf") or "")[:60])
        if not any(same_product(bf, p) for p in client_products if p):
            return ("the KSSL side is not a product the client publishes", bf)

    n, fields = shared_measurables(row.get("specs"))
    if n < MIN_SHARED_FIELDS:
        return ("nothing comparable on both sides", "%d shared" % n)
    return (None, ", ".join(fields[:4]))


def demo():
    """The row that prompted this, and the rows that must survive it."""
    fails = []

    def ck(name, ok, d=""):
        print("  %-64s %s%s" % (name, "PASS" if ok else "FAIL", "  " + str(d) if d else ""))
        if not ok:
            fails.append(name)

    roster = ["Adani Defence", "Elbit Systems", "KNDS", "Tata Advanced Systems",
              "UVision Air", "BAE Systems", "Bharat Dynamics", "AWEIL"]
    client = ["Bharat 150 UAV", "ATAGS", "MaRG 155-BR", "Kalyani M4",
              "Mine Protected Vehicle", "Light Tactical Vehicle",
              "Protective Carbine — 5.56 × 30 mm"]

    skystriker = {
        "comp": "Adani Defence & Aerospace · SkyStriker", "compBy": "Adani Defence",
        "bf": "KSSL · Bayonet", "bfBy": "Kalyani Strategic Systems",
        "specs": [{"l": "Endurance", "cv": "2 h", "kv": None},
                  {"l": "Warhead", "cv": "5 kg", "kv": None}]}
    why, _ = refuse(skystriker, roster, client)
    ck("SkyStriker vs Bayonet is refused",
       why == "the KSSL side is not a product the client publishes", why)

    shahed = {"comp": "HESA · Shahed-136", "compBy": "HESA",
              "bf": "KSSL · Bharat 150 UAV", "bfBy": "KSSL",
              "specs": [{"l": "Range", "cv": "2500 km", "kv": "200 km"},
                        {"l": "Endurance", "cv": "6 h", "kv": "0.5 h"}]}
    why, _ = refuse(shahed, roster, client)
    ck("an off-roster maker is refused even with two shared measurables",
       why == "maker is not a tracked competitor", why)

    empty = {"comp": "KNDS · CAESAR 6x6", "compBy": "KNDS", "bf": "KSSL · MaRG 155-BR",
             "specs": [{"l": "Calibre", "cv": "155 mm", "kv": "155 mm"},
                       {"l": "Range", "cv": "40 km", "kv": None}]}
    why, _ = refuse(empty, roster, client)
    ck("a pairing with no shared measurable is refused",
       why == "nothing comparable on both sides", why)

    ck("calibre alone is never a comparison",
       shared_measurables([{"l": "Calibre", "cv": "155 mm", "kv": "155 mm"}])[0] == 0)

    # The engine's own direction flag, which is what production rows carry.
    ck("a non-directional field is not comparable even with both numbers",
       shared_measurables([{"l": "Calibre", "cn": 0.155, "kn": 0.155, "hi": None}])[0] == 0)
    ck("a directional field with both numbers is comparable",
       shared_measurables([{"l": "Max range", "cn": 40, "kn": 30, "hi": True}])[0] == 1)
    ck("a directional field missing one side is not",
       shared_measurables([{"l": "Max range", "cn": 40, "kn": None, "hi": True}])[0] == 0)

    good = {"comp": "KNDS · CAESAR 6x6", "compBy": "KNDS", "bf": "KSSL · MaRG 155-BR",
            "specs": [{"l": "Calibre", "cn": 0.155, "kn": 0.155, "hi": None},
                      {"l": "Maximum range", "cn": 40, "kn": 45, "hi": True},
                      {"l": "Rate of fire", "cn": 6, "kn": 5, "hi": True}]}
    why, det = refuse(good, roster, client)
    ck("a real like-for-like artillery pairing survives", why is None, why or det)

    ck("the maker is not read as the product",
       product_of("KNDS · CAESAR 6x6") == "CAESAR 6x6" and
       maker_of("KNDS · CAESAR 6x6") == "KNDS")

    # THE FALSE REFUSALS. Each of these was published, real, and thrown away by the
    # first draft of this gate.
    ck("a legal name resolves to the roster's initials",
       same_org("Advanced Weapons and Equipment India Limited", "AWEIL"))
    ck("an initialism resolves to the client's own long name",
       same_product("MPV", "Mine Protected Vehicle") and
       same_product("LTV", "Light Tactical Vehicle"))
    ck("a short model token resolves inside the client's product name",
       same_product("M4", "Kalyani M4"))
    ck("a variant suffix does not hide the client product",
       same_product("MArG 155", "MaRG 155-BR"))
    ck("but an unrelated product still does not match",
       not same_product("Cleaver", "Kalyani M4") and
       not same_product("Bayonet", "Bharat 150 UAV"))
    ck("a real, unrelated company sharing a brand word is not absorbed",
       not same_org("Elbit Imaging", "Elbit Systems"))
    ck("a company that merely shares a word is not the tracked one",
       not same_org("Ashok Leyland", "AWEIL"))

    # A gate that never refuses is not running, and a gate that refuses everything is
    # not a gate either -- both are checked, because both have happened in this repo:
    # the first draft of this very file refused all 117 published rows.
    seen = [refuse(r, roster, client)[0] for r in (skystriker, shahed, empty, good)]
    ck("the gate both refuses and admits", any(seen) and not all(seen))

    # AN EMPTY LIST IS A REFUSAL. `if roster_names:` skipped the check when there was
    # nothing to check against, which is precisely when it mattered.
    os.environ.pop(ALLOW_EMPTY, None)
    why, _ = refuse(good, [], client)
    ck("an empty roster refuses rather than admitting everything",
       why == "no tracked-competitor roster to check the maker against", why)
    why, _ = refuse(good, roster, [])
    ck("an empty client portfolio refuses too",
       why == "no client portfolio to check the KSSL side against", why)
    why, _ = refuse(good, [], [])
    ck("both empty still refuses", why is not None, why)
    # ...and the override is opt-in, named, and restores the old behaviour exactly
    os.environ[ALLOW_EMPTY] = "1"
    _warned[0] = True                       # the warning itself is not under test
    ck("the named override admits it again", refuse(good, [], [])[0] is None)
    os.environ.pop(ALLOW_EMPTY, None)
    _warned[0] = False

    # A row that names nobody cannot be checked against the roster either.
    ck("a pairing with no maker is refused",
       refuse(dict(good, comp="CAESAR 6x6", compBy=""), roster, client)[0]
       == "the pairing names no maker")
    ck("a pairing with no KSSL product is refused",
       refuse(dict(good, bf=""), roster, client)[0]
       == "the pairing names no KSSL product")

    # THE INITIALISM COLLISION. norm("MaRG 45") -> ['marg','45'] -> 'm'+'4' -> "m4",
    # so an armoured vehicle was validated as a client product by a wheeled howitzer.
    ck("a two-token name cannot abbreviate to a short anchor",
       initialism("MaRG 45") == "" and initialism("Kalyani M4") == "",
       "%r / %r" % (initialism("MaRG 45"), initialism("Kalyani M4")))
    ck("M4 is not MaRG 45", not same_product("M4", "MaRG 45"))
    ck("...and M4 is still Kalyani M4", same_product("M4", "Kalyani M4"))
    ck("the real initialisms still resolve",
       initialism("Mine Protected Vehicle") == "mpv"
       and initialism("Ultra Light Specialist Vehicle") == "ulsv")

    # DIRECTION COMES FROM THE FIELD, NOT THE ROW. The same field must be counted the
    # same way whatever the archive typed on this particular row.
    ck("a directionless field is not comparable however the row is marked",
       shared_measurables([{"l": "Calibre", "cn": 155, "kn": 105, "hi": True}])[0] == 0)
    ck("a directional field IS comparable however the row is marked",
       shared_measurables([{"l": "Rate of fire", "cn": 6, "kn": 5, "hi": None}])[0] == 1)
    ck("crew + pax carries no direction: fewer crew is better, more troops is not",
       shared_measurables([{"l": "Crew / pax", "cn": 3, "kn": 8, "hi": True}])[0] == 0)

    print("\n%s" % ("all checks passed" if not fails else "%d FAILED" % len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(demo())
