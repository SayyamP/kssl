# -*- coding: utf-8 -*-
"""Join KSSL's OWN published specifications onto a pairing, field by field.

    python spec_join.py --demo      # hermetic: the field table and the join, no DB

THE FAULT THIS CLOSES
---------------------
The operator asked it plainly: "why we had no specs for kssl cqb carbine its simply on
kssl website directly? https://www.kssl.in/small-arms".

The specifications were never missing. serving.client_product holds the CQB Carbine
(product_id 'cqb-carbine-f90') with 28 bullets parsed straight off that page -- calibre,
cartridge, three barrel options, three overall lengths, fire mode, cyclic / normal /
rapid / maximum rates, muzzle velocity, magazine capacity, two weights, MRBS/MRBF,
operating principle. The served pairing (matchup 20102, CQB Carbine vs AK-203) carried
ONE of them, and the panel read "1 value(s) sourced, none comparable on both sides".

Three separate defects, all in the same join:

  1. THE ARCHIVE DROVE THE LOOP. revive_matchups.rebuild iterates the ARCHIVE row's
     spec list (`for s in (specs or [])`, revive_matchups.py:932) and asks the workbook
     only for a label the archive already named -- `client_portfolio.kssl_side(fit, lab,
     ...)` at line 940. The archive names five labels for a small arm (Calibre,
     Effective range, Weight, Action, Barrel). Nothing in the codebase ever enumerated
     client_product.specs, so 23 of the 28 published values had no label to hang on and
     were never looked at, on any row, in any category.

  2. THE BORE RULE SILENCED THE VALUE INSTEAD OF UNSCORING IT.
     client_portfolio.kssl_side refuses EVERY label except "Calibre" when two products'
     bores differ, and measured on matchup 20102 that refusal alone removed four of the
     five archive labels -- KSSL's 3.15 kg, its 508/407/360 mm barrel, its gas-operated
     bullpup action. The rule must stay as a SCORING rule: a 105 mm gun weighs a third
     of a 155 mm gun, Weight is hi=False, and a per-field relaxation scored that class
     difference as a KSSL lead (test_client_portfolio's Garuda 105 case caught it). What
     was wrong was the consequence. Refusing to COMPARE two figures is not a reason to
     hide one of them, so a bore-refused field is published here as KSSL's own stated
     value with no number attached: readable, and unable to decide anything.
     BORE_SENSITIVE below is the narrower list of fields the cartridge governs so
     directly that setting the two values side by side would mislead on its own.

  3. THE FIELD KEY WAS COMPUTED AND THEN THROWN AWAY. client_portfolio.py:544 returns
     the workbook's own key with the figure (`"key": key or cands[0]["k"]`) and
     revive_matchups.py:1003 stores only the value (`e["kv"], e["kp"] = pk["kv"], "s"`).
     A matchup spec entry therefore carries the ARCHIVE's display label `l` and no field
     key at all, which is why `specs->0->>'k'` is NULL for every entry in the table and
     why nothing downstream could ever match KSSL's side to a rival's field to field.

WHAT THIS MODULE ADDS, AND WHAT IT REFUSES TO ADD
-------------------------------------------------
  * Every keyed bullet the client publishes for the anchor product reaches the pairing,
    carrying `k` -- the canonical field name -- so the join is field to field and not
    label to label.
  * A KSSL value with no rival counterpart is SHOWN, flagged `noCounterpart`, with cv
    and cn left None. It is not scored: revive_matchups.comparable() already requires a
    number on BOTH sides, so a stated-but-unmatched value cannot move `edge` and cannot
    appear in a verdict as a lead. Absence is displayed as absence.
  * A rival value is NEVER invented to make a pair. The rival side comes only from what
    the archive stated and the corpus grounded; where that is nothing, it stays nothing.
  * An existing value is never overwritten. This module fills gaps and appends fields;
    a figure that survived grounding is left exactly as it was.
  * A bullet with no key in the workbook (the parser leaves `k` None on a handful of
    stray lines -- "Weight", "Operating system") is not a keyed specification and is
    refused, counted, not guessed at.

ONE NORMALISER, NOT A SECOND ONE
--------------------------------
The label spelling comes from spec_direction.key(), which is what the direction table
already compares on. The unit sizes come from revive_matchups.BASE, extended here with
the surfaces the workbook writes and the corpus does not (inches, pounds, m/s) -- see
UNITS. The value reader is client_portfolio._figure, the same one that reads the
workbook for the existing path. This file adds a FIELD vocabulary; it does not add a
second way to read a number or a unit.
"""
import argparse
import collections
import re
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import spec_direction                                            # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Labels this table has never been asked about on purpose. Same contract as
# spec_direction.UNKNOWN: an unrecognised label is a gap to close, not a guess to make.
# It does NOT cost the spec its place on the panel -- an unmatched label keeps its own
# normalised spelling as its field key, so nothing is ever dropped for being unfamiliar.
UNKNOWN = collections.Counter()
REFUSALS = collections.Counter()

# ---------------------------------------------------------------------------
# the field vocabulary
# ---------------------------------------------------------------------------
# ORDERED, first match wins, specific before general -- the same shape as
# positioning_gate.KINDS, and for the same reason: "Barrel manufacture" must reach its
# own entry before "Barrel", and "Weight with full magazine" before "Weight".
#
# The table exists to MERGE spellings of one measurement, not to enumerate the world:
# 'Muzzle velocity' / 'Muzzle Velocity, m/s' / 'Velocity' are one field; 'Cyclic rate'
# and 'Normal rate' are two, because they measure different things and the client
# publishes both. A label no entry matches keeps its own spelling and is counted in
# UNKNOWN, so the panel never loses a value to a missing table row.
#
# Patterns are matched (fullmatch) against spec_direction.key(label): lower-case, with
# every run of punctuation collapsed to one space.
FIELDS = [
    # -- weights: the loaded figure is a different measurement from the bare one, and
    #    the existing ("sa","Weight") recipe already excludes it by name.
    ("Loaded weight", r"(weight|mass)( with)? (full |loaded )?magazine|"
                      r"(weight|mass) with (full |loaded )?(magazine|ammunition box)|"
                      r"loaded (weight|mass)"),
    ("Weight", r"(combat |system |total |all up |complete system |gross |kerb |curb |dry |"
               r"unladen |empty )?(weight|mass)( carbine only| weapon only| gun only)?|"
               r"combat gross weight|gvm|gvw"),
    # -- barrel: what it is made of is not how long it is
    ("Barrel manufacture", r"barrel (manufacture|manufacturing|construction|material|"
                           r"profile|treatment)"),
    ("Barrel length", r"barrel( length)?( options| option)?|barrel length options"),
    ("Overall length", r"(overall|total) length( options| option)?"
                       r"( stock (open|closed|folded|extended))?|"
                       r"length (overall|with stock (open|closed|folded|extended))"),
    # -- velocity: the operator's own example of label variation
    ("Muzzle velocity", r"(muzzle|projectile|initial) (velocity|speed)( m s)?|velocity( m s)?"),
    ("Muzzle energy", r"muzzle energy"),
    # -- rate of fire: the client publishes four DIFFERENT rates for one carbine and
    #    they are not interchangeable (client_portfolio's own recipe says so).
    ("Cyclic rate", r"(nominal |normal gas setting )?cyclic rate( of fire)?"),
    ("Normal rate", r"normal rate( of fire)?"),
    ("Rapid rate", r"rapid rate( of fire)?"),
    ("Maximum rate", r"(maximum|max) (specified |sustained |burst )?rate( of fire)?|"
                     r"(burst|intense|sustained) rate( of fire)?"),
    ("Rate of fire", r"rate of fire|rate"),
    # -- reach. "Effective range" and a gun's "Max range" are the archive's own two
    #    labels; a communication-link range is neither and is excluded upstream.
    ("Effective range", r"effective( firing)? range"),
    ("Max range", r"(maximum|max|firing|operational|flight|mission)( firing)? range|range"),
    # -- identity
    ("Calibre", r"calibre|caliber|bore|published calibre options|"
                r"(publicly stated |published )?calibre range|calibre options"),
    ("Cartridge", r"cartridge|ammunition type"),
    ("Fire mode", r"fir(e|ing) modes?|selector|trigger modes?"),
    ("Action", r"operating (principle|system|mechanism)|action|mechanism"),
    ("Magazine capacity", r"magazine( capacity| size)?|feed capacity"),
    # -- reliability. MRBS and MRBF are two published figures, not one.
    ("MRBS", r"mrbs( rounds)?|mean rounds between stoppages"),
    ("MRBF", r"mrbf( rounds)?|mean rounds between failures"),
    ("System life", r"system life|service life|barrel life"),
    ("Reliability", r"(all[- ]terrain )?reliability"),
    # -- crew and carriage, so the vehicle classes merge the same way
    ("Crew", r"crew( accommodation| capacity)?"),
    ("Crew / pax", r"crew (/ ?)?(pax|troop capacity)|crew troop capacity|troop capacity"),
    ("Protection", r"(ballistic |stanag )?protection( class| level)?"),
    ("Configuration", r"configuration|drive layout|layout|drive"),
    ("Power / speed", r"engine power|power|engine"),
    ("Mobility", r"mobility|(self[- ]propelled|towing|maximum towing) speed"),
    ("Endurance", r"(minimum battery |battery )?endurance|loiter time"),
    ("Payload", r"(demonstrated )?payload( capacity)?"),
    ("MTOW", r"(maximum )?take ?off weight|mtow"),
    ("Type", r"(system |vehicle |product )?(type|form)|product form|"
             r"ammunition effect (/ ?)?family"),
]
FIELDS = [(n, re.compile("(?:%s)$" % p)) for n, p in FIELDS]

# WHICH FIELDS THE BORE ACTUALLY GOVERNS.
#
# client_portfolio.kssl_side refuses every non-Calibre field the moment two products
# differ in bore. The rule is real -- a 105 mm gun's range next to a 155 mm gun's is a
# class difference wearing a comparison's chrome -- and it was written for artillery
# ranges, then applied to everything. A carbine's mass, its barrel length, its overall
# length, its magazine capacity and its operating principle are the same measurements
# whatever cartridge the rival fires.
#
# Listed here, so the refusal can be READ rather than inferred from a mismatch. The
# safe direction is to ADD to this set: an entry costs a comparison that could have
# been made, a missing entry publishes one that should not have been.
#
# Calibre and Cartridge are deliberately ABSENT. They are not a comparison the bore
# invalidates, they are the statement OF the bore -- the one field that tells the reader
# these two weapons fire different rounds. Both are directionless in spec_direction, so
# neither can be scored as a lead.
BORE_SENSITIVE = frozenset((
    "Effective range", "Max range", "Muzzle velocity", "Muzzle energy",
    "Cyclic rate", "Normal rate", "Rapid rate", "Maximum rate", "Rate of fire",
))

# Placeholder prose the archive and the workbook both use where a figure was never
# published. Same vocabulary withhold_matchups.nothing_published judges on, so the two
# modules cannot disagree about what "no figure" looks like.
_NOFIG = re.compile(r"no published|undisclosed|not stated|not disclosed|n/?a\b|^[-—–\s]*$", re.I)


def stated(v):
    """Is this a value the client actually published, rather than a placeholder?"""
    s = str(v or "").strip()
    return bool(s) and not _NOFIG.search(s)


def field_of(label):
    """-> the canonical field name for a label from EITHER side of a pairing.

    A label the table has never seen keeps its own normalised spelling (and is counted
    in UNKNOWN). That is deliberate: an unfamiliar label is a gap in this table, and it
    must not cost the client a published specification. It simply will not MERGE with
    another spelling until someone adds the row."""
    k = spec_direction.key(label)
    if not k:
        return None
    for name, rx in FIELDS:
        if rx.match(k):
            return name
    UNKNOWN[k] += 1
    return label.strip() if isinstance(label, str) and label.strip() else k


def field_key(label):
    """The dict key two sides are joined on. One spelling, always."""
    f = field_of(label)
    return spec_direction.key(f) if f else None


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------
_UNITS = None


def units():
    """revive_matchups.BASE, plus the surfaces a spec sheet writes and prose does not.

    Not merged into UNIT_FORMS on purpose. That table is read against raw document
    TEXT, and "in" is an English word: adding it there would read "40 in the trials" as
    forty inches. Here the unit token has already been isolated beside its number by
    client_portfolio._UNIT_RX, so the ambiguity does not arise."""
    global _UNITS
    if _UNITS is None:
        import revive_matchups                                   # noqa: E402
        u = dict(revive_matchups.BASE)
        for k, v in (("in", ("length", 0.0254)), ("inch", ("length", 0.0254)),
                     ("inches", ("length", 0.0254)), ("cm", ("length", 0.01)),
                     ("ft", ("length", 0.3048)),
                     ("lbs", ("mass", 0.45359237)), ("g", ("mass", 0.001)),
                     ("m/s", ("speed", 3.6)), ("mph", ("speed", 1.609344)),
                     ("h", ("time", 1.0)), ("hr", ("time", 1.0)),
                     ("min", ("time", 1 / 60.0))):
            u.setdefault(k, v)
        _UNITS = u
    return _UNITS


def figure(value):
    """-> (number, unit, base_value, quantity) for a value stating ONE figure.

    The reader is client_portfolio._figure -- the same one the existing workbook path
    uses -- so a range ("640-840 rounds/min"), a compound ("2+4"), a variant set
    ("508 / 407 / 360 mm") and plain text all come back with no number, which is what
    keeps the front end drawing chips instead of bars."""
    import client_portfolio                                      # noqa: E402
    n, unit, kind = client_portfolio._figure(value)
    if n is None or kind not in ("single", "bound"):
        return None, unit or "", None, None
    q = units().get((unit or "").strip().lower())
    if not q:
        return n, unit or "", None, None
    return n, unit, n * q[1], q[0]


# ---------------------------------------------------------------------------
# the join
# ---------------------------------------------------------------------------
def client_fields(prow):
    """-> OrderedDict field_key -> {k, l, v, n, unit, base, q} for one client product.

    One entry per FIELD, not per bullet: the workbook states the CQB Carbine's barrel
    twice ("Barrel options" and "Barrel length options") and its muzzle velocity twice,
    and those are one field each. The bullet carrying a readable figure wins; failing
    that, the first one stated.

    A bullet under a hedged sub-heading is refused by client_portfolio._hedged -- the
    same rule the existing path applies -- and a bullet with no key at all is refused
    here, because a specification with no field name cannot be joined to anything."""
    import client_portfolio                                      # noqa: E402
    out = collections.OrderedDict()
    for b in (prow.get("specs") or []):
        k = (b.get("k") or "").strip()
        if not k:
            REFUSALS["workbook bullet has no field name"] += 1
            continue
        if not stated(b.get("v")):
            REFUSALS["workbook states no figure for this field"] += 1
            continue
        if client_portfolio._hedged(b):
            REFUSALS["bullet under a hedged sub-heading in the workbook"] += 1
            continue
        fk = field_key(k)
        if not fk:
            continue
        n, unit, base, q = figure(b.get("v"))
        e = {"k": field_of(k), "l": field_of(k), "wk": k, "v": str(b["v"]).strip(),
             "n": n, "unit": unit, "base": base, "q": q}
        prev = out.get(fk)
        if prev is None or (prev["base"] is None and e["base"] is not None):
            out[fk] = e
    return out


def sources_of(prow):
    """-> (urls, why, tier) or (None, why, None) when the row cannot clear the bar.

    The SAME publishability rule the corpus path applies (engine/source_tiers), reached
    through client_portfolio so there is one caller's worth of it, not two."""
    import client_portfolio                                      # noqa: E402
    urls = list(prow.get("sources") or [])
    ok, why, tier, _n = client_portfolio.publishable(urls, client_portfolio.CLIENT)
    if not ok:
        return None, why, None
    return urls, "stated in KSSL's own portfolio (client-supplied workbook); " + why, tier


def join(specs, prow, bore_differs=False):
    """-> (new_specs, report) for ONE pairing.

    `specs` is the pairing's spec list as it stands (matchup.specs); `prow` the client's
    own product row (serving.client_product). Every existing entry is kept and stamped
    with its field key; every published KSSL field that is not already there is
    appended, marked `noCounterpart` where the rival side states nothing.

    NOTHING IS INVENTED AND NOTHING IS OVERWRITTEN. cv/cn are never written by this
    function. kv is written only into an entry that has no value at all.
    """
    rep = {"stamped": 0, "filled": 0, "added": 0, "bore_refused": 0,
           "unmatched": 0, "refused_sources": None}
    specs = [dict(s) for s in (specs or [])]
    urls, why, tier = sources_of(prow)
    if urls is None:
        rep["refused_sources"] = why
        for s in specs:                       # the key still travels; the values do not
            s["k"] = field_of(s.get("l") or "")
            rep["stamped"] += 1
        return specs, rep

    have = {}
    for s in specs:
        f = field_of(s.get("l") or "")
        s["k"] = f
        rep["stamped"] += 1
        if f:
            have.setdefault(spec_direction.key(f), s)

    cf = client_fields(prow)
    for fk, e in cf.items():
        # THE BORE RULE, PER FIELD. See BORE_SENSITIVE: a differing bore refuses the
        # measurements the cartridge governs, and only those.
        if bore_differs and e["k"] in BORE_SENSITIVE:
            rep["bore_refused"] += 1
            continue
        cur = have.get(fk)
        if cur is not None:
            # Fill a gap; never replace a figure that survived grounding.
            if not stated(cur.get("kv")):
                cur["kv"] = e["v"]
                cur["kp"] = "s"
                cur["srcK"], cur["whyK"], cur["tierK"] = urls, why, tier
                # A number only where the RIVAL's number is the same quantity -- the
                # front end subtracts cn from kn, and two quantities in one subtraction
                # is the unit error this pipeline has already paid for once.
                #
                # ...and NEVER when the bores differ. That is the whole of what the bore
                # rule is for: the two values may sit side by side as text, because both
                # are published facts, and neither may be turned into a bar or a lead.
                if (not bore_differs and e["base"] is not None
                        and cur.get("cn") is not None
                        and _quantity_of(cur) == e["q"]):
                    cur["kn"] = e["base"]
                elif bore_differs:
                    cur["kn"] = None
                    cur["boreUnscored"] = True
                rep["filled"] += 1
            continue
        rep["added"] += 1
        rep["unmatched"] += 1
        specs.append({
            "k": e["k"], "l": e["l"], "u": "", "cv": None, "cn": None,
            "kv": e["v"], "kn": None, "kp": "s",
            "hi": spec_direction.direction_of(e["l"]),
            "srcC": [], "whyC": None, "tierC": None,
            "srcK": urls, "whyK": why, "tierK": tier,
            # SHOWN, AND NOT SCORED. revive_matchups.comparable() already refuses a
            # spec without a number on both sides, so cn=None is what keeps this out
            # of `edge` and out of the verdict's lead counts. The flag is what lets
            # the panel say WHY the rival column is empty: nobody published a
            # counterpart, which is not the same statement as "not sourced".
            "noCounterpart": True,
        })
    return specs, rep


def _quantity_of(s):
    """The quantity the rival's stored number is in, read off its own unit."""
    import revive_matchups                                       # noqa: E402
    _v, q = revive_matchups.to_base(s.get("cn"), s.get("u"))
    return q


def scored(specs):
    """The entries a verdict and an edge may be computed from.

    A stated-but-unmatched KSSL value is a fact about KSSL, not a comparison, so it is
    excluded before revive_matchups.edge_of / verdict_of are asked anything -- otherwise
    the sentence "N value(s) sourced, none comparable on both sides" would count values
    that were never offered as a comparison in the first place."""
    return [s for s in (specs or []) if not s.get("noCounterpart")]


# ---------------------------------------------------------------------------
def _is_comparable(s):
    """revive_matchups.comparable(), asked about one entry -- the one definition."""
    import revive_matchups                                        # noqa: E402
    return bool(revive_matchups.comparable([s]))


def _demo():
    ok = [0]

    def ck(name, cond):
        print("  %-64s %s" % (name, "ok" if cond else "FAIL"))
        if not cond:
            ok[0] += 1
        return cond

    # -- the operator's own example of label variation
    ck("'Muzzle velocity' / 'Muzzle Velocity, m/s' / 'Velocity' are one field",
       field_of("Muzzle velocity") == field_of("Muzzle Velocity, m/s")
       == field_of("Velocity") == "Muzzle velocity")
    ck("'Weight, carbine only' and 'Mass' are one field",
       field_of("Weight, carbine only") == field_of("Mass") == "Weight")
    ck("...but the LOADED weight is a different measurement",
       field_of("Weight with full magazine") == "Loaded weight")
    ck("'Barrel options' and 'Barrel length options' are one field",
       field_of("Barrel options") == field_of("Barrel length options") == "Barrel length")
    ck("...and 'Barrel manufacture' is not the barrel's length",
       field_of("Barrel manufacture") == "Barrel manufacture")
    ck("the four published rates stay four fields",
       len({field_of("Cyclic rate"), field_of("Normal rate"),
            field_of("Rapid rate"), field_of("Maximum rate")}) == 4)
    ck("'Cyclic rate of fire' merges with 'Cyclic rate'",
       field_of("Cyclic rate of fire") == field_of("Nominal cyclic rate") == "Cyclic rate")
    ck("'Operating principle' is the archive's 'Action'",
       field_of("Operating principle") == field_of("Action") == "Action")

    # -- a label nobody has mapped keeps its value and is RECORDED, never dropped
    UNKNOWN.clear()
    ck("an unmapped label keeps its own name", field_of("Bolt locking lugs") == "Bolt locking lugs")
    ck("...and is counted as a gap in this table", UNKNOWN["bolt locking lugs"] == 1)
    UNKNOWN.clear()

    # -- units: the two the brief names
    n, u, base, q = figure("3.15 kg")
    ck("kg reads as mass", (n, q) == (3.15, "mass") and abs(base - 3.15) < 1e-9)
    n, u, base, q = figure("8 lb")
    ck("lb reads as the same quantity", q == "mass" and abs(base - 3.6287) < 0.001)
    n, u, base, q = figure("20 in")
    ck("in reads as length in metres", q == "length" and abs(base - 0.508) < 1e-9)
    n, u, base, q = figure("508 mm")
    ck("...and mm gives the same 0.508", q == "length" and abs(base - 0.508) < 1e-9)
    ck("a variant set states no single figure",
       figure("508 / 407 / 360 mm")[0] is None)
    ck("a range states no single figure", figure("640-840 rounds/min")[0] is None)

    # -- the join itself
    prow = {"name": "CQB Carbine - F90", "catKey": "sa",
            "sources": ["https://www.kssl.in/small-arms"],
            "specs": [{"k": "Calibre", "v": "5.56 mm", "note": None, "ctx": None},
                      {"k": "Weight, carbine only", "v": "3.15 kg", "note": None, "ctx": None},
                      {"k": "Muzzle velocity", "v": "nominal 920 m/s (F1 ball)",
                       "note": None, "ctx": None},
                      {"k": None, "v": "Weight", "note": None, "ctx": None}]}
    got, rep = join([{"l": "Calibre", "cv": "7.62x39mm", "cn": 7.62, "kv": "5.56 mm",
                      "kn": None, "u": "mm", "hi": None}], prow)
    ck("the rival's own value is untouched", got[0]["cv"] == "7.62x39mm")
    ck("every entry carries its field key", all(s.get("k") for s in got))
    ck("a bullet with no field name is refused, not guessed",
       len(got) == 3 and rep["added"] == 2)
    w = [s for s in got if s["k"] == "Weight"][0]
    ck("KSSL's published weight reaches the pairing", w["kv"] == "3.15 kg")
    ck("...marked as having no counterpart", w["noCounterpart"] is True)
    ck("...with no rival value invented for it", w["cv"] is None and w["cn"] is None)
    ck("...and therefore not scoreable", w["cn"] is None)
    ck("a no-counterpart value is not offered to the verdict",
       [s["k"] for s in scored(got)] == ["Calibre"])

    # -- the bore rule: shown, and unscorable
    got, rep = join([{"l": "Weight", "cv": "3.8 kg", "cn": 3.8, "kv": None, "kn": None,
                      "u": "kg", "hi": False}], prow, bore_differs=True)
    keys = [s["k"] for s in got]
    ck("a differing bore still refuses the muzzle velocity",
       "Muzzle velocity" not in keys and rep["bore_refused"] == 1)
    ck("...and still STATES the calibre, which is what the bore difference is",
       "Calibre" in keys)
    w = [s for s in got if s["k"] == "Weight"][0]
    ck("...and KSSL's weight is SHOWN beside the rival's", w["kv"] == "3.15 kg")
    ck("...with no number, so a class difference cannot score as a lead",
       w["kn"] is None and w.get("boreUnscored") is True)
    ck("...and it is not comparable to anything", not _is_comparable(w))

    # -- sources that cannot clear the bar publish nothing
    got, rep = join([{"l": "Calibre", "cv": "7.62x39mm"}],
                    dict(prow, sources=[]))
    ck("a row whose sources fail the bar adds nothing",
       len(got) == 1 and rep["added"] == 0 and rep["refused_sources"])
    ck("...but the field key is still stamped", got[0]["k"] == "Calibre")

    print("all checks passed" if not ok[0] else "%d FAILED" % ok[0])
    return 1 if ok[0] else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.parse_args()
    # No DB writer lives here, so a bare invocation runs the self-check rather than
    # being a usage error.
    sys.exit(_demo())
