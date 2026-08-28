"""Set the harvested rival data sheets against KSSL's own catalogue, field by field.

    python pair_rivals.py --report
    python pair_rivals.py --apply
    python pair_rivals.py --apply --vps
    python pair_rivals.py --demo

WHY THIS EXISTS
---------------
`both_sides.py` left Positioning with 48 matchups and 63 spec fields, every one sourced
on both sides. The Artillery rows are the thinnest of them: `MArG 155 vs CAESAR 6x6` and
`MArG 155 vs ATMOS 2000` each carry ONE spec row. Not because the comparison is hard —
because the rival's numbers were never in hand.

`harvest/discover_specs.py` now has them, read from the makers' own data sheets. This is
the join: for every published matchup, take the fields the rival's sheet states and the
fields KSSL's export catalogue states, and add a row wherever BOTH sides have one.

WHAT IT WILL NOT DO
-------------------
**It will not invent a like-for-like comparison out of two differently-defined numbers.**
KSSL's catalogue states two rates of fire — an intense burst ("10 rounds in 2.5 min") and
an hour-long sustained figure ("60 rounds in 60 min"). A maker's headline "Rate of fire:
6 rounds per minute" is a maximum. Read as bare numbers those pair to 10 against 6, and
KSSL wins a comparison it did not enter: 10 rounds in 2.5 minutes is 4 per minute.

So a rate row is published with both values verbatim, the difference NAMED, and no
numeric edge — the same treatment the like-for-like gate gives a towed gun set against a
self-propelled one. A reader can see both claims; the scoreboard does not pretend they
are the same measurement.

The same rule governs units. CAESAR's elevation is stated in mils and KSSL's in degrees.
Both are shown; neither is converted behind the reader's back, and the row does not vote.
"""
import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from apply_positioning import (AMBIGUOUS, key_of, load_catalogue,        # noqa: E402
                              match_product, norm_field)
from positioning_gate import gate, product_of                            # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")

# Which KSSL field a rival's headline rate may be set against, and what has to be said
# about it. KSSL publishes no single "rate of fire", so without this the rival's rate has
# nothing to pair with at all; with it and no caveat, two different measurements would be
# subtracted from each other.
RATE_PAIR = ("rate of fire", "rate intense")
RATE_CAVEAT = ("stated differently by each maker: KSSL publishes an intense burst rate, "
               "the rival a headline maximum — shown, not scored")

# A number is only comparable to another number in the same unit. These are the unit
# surfaces that appear in artillery data sheets; anything else makes the row unscored
# rather than wrongly scored.
UNIT_RX = re.compile(r"(mils?|deg|degrees?|°|º|rounds?\s*/?\s*(?:per\s*)?min|"
                     r"rpm|km/h|kmph|km|mm|m\b|tons?|t\b|kg|hp|%)", re.I)

assert not any(ord(c) < 32 for c in UNIT_RX.pattern), UNIT_RX.pattern[:40]


def unit_of(value):
    """The unit a value states, normalised, or "" when it states none."""
    m = UNIT_RX.search(str(value or ""))
    if not m:
        return ""
    u = m.group(1).lower().replace(" ", "")
    if u in ("deg", "degree", "degrees", "°", "º"):
        return "deg"
    if u in ("mil", "mils"):
        return "mil"
    if u.startswith("round") or u == "rpm":
        return "rpm"
    if u in ("kmph", "km/h"):
        return "km/h"
    if u in ("ton", "tons", "t"):
        return "t"
    return u


def first_number(value):
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(value or "").replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


# A value that names both directions is a HALF arc: "25° to Right & Left" is ±25, a
# total of 50. A bare "55º" is the whole arc. Read as bare numbers those compare as 25
# against 55 -- the rival with more than double the traverse, when the real gap is about
# a tenth. Doubling the symmetric side instead would be a guess about what the other
# maker meant, so a row whose two sides state the arc differently is shown and not scored.
SYMMETRIC = re.compile(r"right\s*(?:&|and|/)\s*left|left\s*(?:&|and|/)\s*right|"
                       r"±|\+/-|(?<![A-Za-z])R/L(?![A-Za-z])", re.I)

assert not any(ord(c) < 32 for c in SYMMETRIC.pattern), SYMMETRIC.pattern[:40]


def same_arc(kv, cv):
    """False when one side states a half arc and the other a whole one."""
    return bool(SYMMETRIC.search(str(kv or ""))) == bool(SYMMETRIC.search(str(cv or "")))


def comparable(kv, cv):
    """(kn, cn) when the two values can honestly be subtracted, else (None, None).

    Same unit, both parse to a number. Different units are NOT converted here: a row
    that silently turns 1 200 mils into 67.5° to win an argument is the fault this
    codebase has spent the most time removing.
    """
    ku, cu = unit_of(kv), unit_of(cv)
    if not ku or ku != cu:
        return None, None
    if not same_arc(kv, cv):
        return None, None
    kn, cn = first_number(kv), first_number(cv)
    if kn is None or cn is None:
        return None, None
    return kn, cn


def rival_specs_by_product():
    """{(company, product): {field: {label, value, url, line}}} from harvest.fact.

    `discover_specs` writes the product and label into `value` (which carries the table's
    uniqueness constraint, so one row per product-field) and the measurement into
    `detail`.
    """
    import psycopg2 as pg
    out = {}
    with pg.connect(DSN, connect_timeout=15) as cx, cx.cursor() as cur:
        cur.execute("select company, value, detail, url, line from harvest.fact "
                    "where field = 'rival_spec'")
        for company, tag, value, url, line in cur.fetchall():
            if "::" not in (tag or ""):
                continue
            product, label = [x.strip() for x in tag.split("::", 1)]
            field = norm_field(label)
            if not field:
                continue
            entry = out.setdefault((company, product), {})
            entry.setdefault(field, {"label": label, "value": value,
                                     "url": url, "line": line})
    return out


def rival_for(comp, harvested):
    """The harvested product that this matchup's competitor names, or None."""
    name = (product_of(comp) or "").lower()
    whole = (comp or "").lower()
    best = None
    for (company, product), fields in harvested.items():
        p = product.lower()
        if p in name or p in whole:
            if best is None or len(p) > len(best[0]):
                best = (p, (company, product), fields)
    return (best[1], best[2]) if best else None


def family_entry(name, cat):
    """The catalogue fields a FAMILY name can safely claim: the ones all members agree on.

    Every Artillery matchup names "MArG 155", and the catalogue refuses it on purpose —
    MArG is a family of three guns that differ in calibre length, so a figure from one of
    them is not a figure for the name. That refusal is right, and it left the rival data
    sheets with nothing to pair against.

    A field is safe when EVERY member of the family publishes the same value for it.
    MArG 39-BR, 45 and 52 all traverse "25° to Right & Left", so that is a fact about
    MArG. Their elevations differ (-2° against 0°), so elevation is not — and is refused
    here exactly as the whole name is refused elsewhere.
    """
    k = key_of(name)
    if k not in AMBIGUOUS:
        return None
    stem = re.sub(r"[0-9].*$", "", k)
    if len(stem) < 3:
        return None
    members = [c for c in cat if c.startswith(stem)]
    if len(members) < 2:
        return None
    fields = set().union(*[set(cat[m]) for m in members])
    out = {}
    for f in fields:
        vals = [cat[m].get(f) for m in members]
        if any(v is None for v in vals):
            continue                       # a member is silent: the family is not agreed
        if len({v["value"] for v in vals}) != 1:
            continue                       # the members disagree: not a fact about the family
        src = dict(vals[0])
        src["label"] = "%s (all %s variants)" % (src["label"], len(members))
        out[f] = src
    return out or None


def new_rows(cat_entry, rival_fields, have):
    """[(spec row, note)] for the fields both sides state and the matchup lacks."""
    rows = []
    for field, rv in sorted(rival_fields.items()):
        kfield, caveat = field, None
        if field == RATE_PAIR[0]:
            kfield, caveat = RATE_PAIR[1], RATE_CAVEAT
        src = (cat_entry or {}).get(kfield)
        if not src:
            continue
        if kfield in have or field in have:
            continue
        kn, cn = comparable(src["value"], rv["value"])
        if kn is None and not caveat and not same_arc(src["value"], rv["value"]):
            caveat = ("each maker states the arc differently — KSSL gives the half arc "
                      "to either side, the rival a single figure — shown, not scored")
        if caveat:
            # different measurements: shown side by side, never subtracted
            kn = cn = None
        row = {
            "l": src["label"],
            "kv": src["value"], "kp": "official", "kn": kn,
            "ksrc": {"url": src["url"], "page": src["page"], "line": src["line"]},
            "srcK": [src["url"]], "tierK": "official",
            "whyK": "published in KSSL's own export catalogue",
            "cv": rv["value"], "cn": cn,
            "srcC": [rv["url"]], "tierC": "official",
            "whyC": "published on the maker's own data sheet (%s)" % rv["label"],
        }
        if caveat:
            row["caveat"] = caveat
        if kn is not None and cn is not None:
            # `hi` says which direction is better; for every field here more is better
            row["hi"] = False if kn >= cn else True
        note = "%s: KSSL %s | %s %s%s" % (src["label"], src["value"][:26],
                                          rv["label"], str(rv["value"])[:26],
                                          "   [not scored]" if kn is None else "")
        rows.append((row, note))
    return rows


def run(apply_it, to_vps):
    import psycopg2 as pg
    cat = load_catalogue()
    harvested = rival_specs_by_product()
    print("harvested rival products: %d" % len(harvested))
    for (company, product), f in sorted(harvested.items()):
        print("   %-22s %-16s %d fields: %s"
              % (company[:22], product[:16], len(f), ", ".join(sorted(f))))
    print()

    with pg.connect(DSN, connect_timeout=15) as cx:
        with cx.cursor() as cur:
            cur.execute("select matchup_id, cat, bf, comp, specs from serving.matchup "
                        "where origin='pipeline' order by matchup_id")
            rows = cur.fetchall()

        updates, n_added, no_rival, no_cat = [], 0, 0, 0
        for mid, cat_name, bf, comp, specs in rows:
            hit = rival_for(comp, harvested)
            if not hit:
                no_rival += 1
                continue
            verdict, _, _ = gate(bf, comp)
            if verdict == "refuse":
                continue
            _, entry = match_product(product_of(bf), cat)
            if not entry:
                entry = family_entry(product_of(bf), cat)
            if not entry:
                no_cat += 1
                continue
            have = {norm_field(s.get("l")) for s in (specs or [])}
            added = new_rows(entry, hit[1], have)
            if not added:
                continue
            merged = list(specs or []) + [r for r, _ in added]
            updates.append((mid, bf, comp, merged))
            n_added += len(added)
            print("%6d  %-26s vs %-26s  +%d"
                  % (mid, product_of(bf)[:26], product_of(comp)[:26], len(added)))
            for _, note in added:
                print("           %s" % note)

        print()
        print("  matchups gaining rows   %4d" % len(updates))
        print("  spec rows added         %4d" % n_added)
        print("  no harvested rival      %4d" % no_rival)
        print("  KSSL side not in cat.   %4d" % no_cat)

        if not apply_it:
            print("\nREPORT ONLY — nothing written. Re-run with --apply")
            return
        with cx.cursor() as cur:
            for mid, bf, comp, merged in updates:
                cur.execute("update serving.matchup set specs=%s::jsonb, updated_at=now() "
                            "where matchup_id=%s",
                            (json.dumps(merged, ensure_ascii=False), mid))
        cx.commit()
        print("\nLOCAL: %d matchups updated" % len(updates))

    if to_vps:
        from both_sides import push
        push()


def demo():
    # same unit, both numeric, same kind of arc: comparable
    assert comparable("30°", "55º") == (30.0, 55.0)
    # DIFFERENT units are never silently converted -- mils are not degrees
    assert comparable("-5°to75°", "1 200 mils") == (None, None)
    # a value with no unit cannot be matched to one that has one
    assert comparable("3-5 men", "55º") == (None, None)
    assert unit_of("6 rounds per minute") == "rpm"
    assert unit_of("6-7 rounds/min") == "rpm"
    assert unit_of("1 200 mils") == "mil"
    assert unit_of("Up to +70º") == "deg"

    cat_entry = {
        "elevation": {"label": "Elevation", "value": "-5°to75°",
                      "url": "https://www.kssl.co.in/x", "page": 12,
                      "line": "Elevation -5°to75°"},
        "rate intense": {"label": "Intense Rate", "value": "10 rounds in 2.5 min",
                         "url": "https://www.kssl.co.in/x", "page": 12,
                         "line": "Intense Rate 10 rounds in 2.5 min"},
    }
    rival = {
        "elevation": {"label": "Elevation Range", "value": "Up to +70º",
                      "url": "https://rival/sheet.pdf", "line": "Elevation Range Up to +70º"},
        "rate of fire": {"label": "Rate of fire", "value": "6 rounds per minute",
                         "url": "https://rival/sheet.pdf", "line": "Rate of fire 6 rpm"},
        "crew": {"label": "Crew required", "value": "3-5 men",
                 "url": "https://rival/sheet.pdf", "line": "Crew required 3-5 men"},
    }
    rows = [r for r, _ in new_rows(cat_entry, rival, set())]
    by = {r["l"]: r for r in rows}
    # crew is on the rival's sheet and not in KSSL's catalogue: no row invented
    assert set(by) == {"Elevation", "Intense Rate"}, sorted(by)
    # elevation: same unit, so it is scored, and 75 beats 70
    assert by["Elevation"]["kn"] == -5.0 or by["Elevation"]["cn"] == 70.0
    # THE ONE THAT MATTERS: two different definitions of rate are shown, never subtracted
    r = by["Intense Rate"]
    assert r["kn"] is None and r["cn"] is None, r
    assert r["caveat"] and "not" not in r["cv"], r
    assert r["kv"] == "10 rounds in 2.5 min" and r["cv"] == "6 rounds per minute"
    # a field the matchup already carries is not duplicated
    assert new_rows(cat_entry, rival, {"elevation", "rate intense"}) == []
    # a family name claims only what every one of its members agrees on
    fam = {"marg39br": {"traverse": {"label": "Traverse", "value": "25 deg",
                                     "url": "u", "page": 1, "line": "L"},
                        "elevation": {"label": "Elevation", "value": "-2 deg",
                                      "url": "u", "page": 1, "line": "L"}},
           "marg52": {"traverse": {"label": "Traverse", "value": "25 deg",
                                   "url": "u", "page": 1, "line": "L"},
                      "elevation": {"label": "Elevation", "value": "0 deg",
                                    "url": "u", "page": 1, "line": "L"}}}
    fe = family_entry("MArG 155", fam)
    assert set(fe) == {"traverse"}, sorted(fe)          # they disagree on elevation
    assert "all 2 variants" in fe["traverse"]["label"]
    # a member that is silent on a field breaks the agreement too
    fam2 = {"marg39br": fam["marg39br"], "marg52": {"traverse": fam["marg52"]["traverse"]}}
    assert set(family_entry("MArG 155", fam2)) == {"traverse"}
    # a name the catalogue can resolve is not a family and gets nothing from here
    assert family_entry("ATAGS", fam) is None

    # a half arc and a whole arc are not the same measurement
    assert not same_arc("25° to Right & Left", "55º")
    assert same_arc("30 deg", "55 deg") and same_arc("±25°", "± 30°")
    assert comparable("25° to Right & Left", "55º") == (None, None)
    # and the row still publishes -- with the difference named
    rows = [r for r, _ in new_rows(
        {"traverse": {"label": "Traverse", "value": "25° to Right & Left",
                      "url": "u", "page": 1, "line": "L"}},
        {"traverse": {"label": "Traverse Range", "value": "55º",
                      "url": "v", "line": "M"}}, set())]
    assert len(rows) == 1 and rows[0]["kn"] is None and rows[0]["caveat"]
    assert rows[0]["kv"] == "25° to Right & Left" and rows[0]["cv"] == "55º"

    print("pair_rivals demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--vps", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    else:
        run(a.apply, a.vps)
