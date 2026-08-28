"""Is this pairing a comparison at all?

    python positioning_gate.py --demo        # self-check
    python positioning_gate.py --audit       # score every matchup in the DB

THE FAULT THIS CLOSES
---------------------
Positioning was pairing KSSL products against rivals that share a CATEGORY but are not
the same kind of thing. Two real rows from the live dashboard:

  KSSL "Shell forgings"  vs  Raytheon "Excalibur (precision)"
  KSSL "CQB Carbine"     vs  AWEIL "MTMG tank machine gun"

Both passed every check the pipeline had, because both checks were about the NUMBERS:
revive_matchups.py grounds each spec value in a document, and enrich_serving.py groups by
`catKey`. Neither asks whether the two products compete. `catKey` is 'amm' for a forged
empty shell body and for a guided artillery round; it is 'sa' for a 3 kg carbine and for a
tank-mounted machine gun. A category is a shelf, not a match.

KSSL's own export catalogue settles the ammunition case in three words. Page 37:
"Ammunition 100mm to 155mm Shells (Only empties)", and page 31: "*Ready to Fill Shells".
KSSL sells the empty body. Excalibur is a complete precision-guided projectile. They are
at different points of the same supply chain, so "KSSL leads on weight" is not a finding,
it is a unit error.

THE RULE
--------
A pairing is published only when both products resolve to the SAME KIND, where kind is
finer than category and is what a procurement officer would actually put out to tender as
one lot.

FAIL CLOSED. A product whose kind cannot be read from its name is REFUSED, not defaulted
to its category. The whole failure above came from defaulting; a pairing we cannot justify
is worth less than no pairing, because the operator cannot tell the two apart on screen.
"""
import argparse
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ordered: the FIRST kind whose pattern matches wins, so the specific tests must precede
# the general ones. "tank machine gun" has to reach `machine-gun` before `tank`, and
# "155mm shell forging" has to reach `shell-empty` before `shell-complete`.
KINDS = [
    # ---- ammunition: the distinction that started this ----
    ("shell-empty", r"\b(forging|forgings|shell body|shell bodies|empt(y|ies)|"
                    r"ready[ -]to[ -]fill|blank|billet|mortar bod(y|ies))\b"),
    ("shell-guided", r"\b(excalibur|precision|guided|course[ -]correct|katana|"
                     r"vulcano|bonus|smart)\b"),
    ("shell-complete", r"\b(he-?\d*|erfb|hesh|heer|illuminating|smoke|bb|bt|"
                       r"cartridge|round|ammunition|assegai|m107|m795|projectile)\b"),
    # ---- small arms ----
    ("machine-gun", r"\b(machine ?gun|lmg|hmg|gpmg|mmg|mag \d|negev|mtmg|pkt)\b"),
    ("rcws", r"\b(rcws|remote (weapon|controlled)|turret)\b"),
    ("sniper-rifle", r"\b(sniper|anti[ -]materiel|awm|axmc|trg-?\d+|t-?5000|"
                     r"vidhwansak|scorpio|ballista)\b"),
    ("smg", r"\b(smg|sub[ -]?machine|uzi|jvpc|mp\d)\b"),
    ("carbine", r"\b(carbine|cqb|tavor|x95|tar\b|tricar?|ak-?\d+|"
                r"assault rifle|galil|sig ?7\d\d|car ?816|tikuna)\b"),
    ("pistol", r"\b(pistol|handgun|revolver)\b"),
    # ---- artillery ----
    ("howitzer-spg", r"\b(self[ -]propelled|sph|k9|pzh|nora|firtina|archer|caesar|"
                     r"rch-?155|atmos|grizzly)\b"),
    ("howitzer-mounted", r"\b(mounted gun|marg|mounted|truck[ -]mounted)\b"),
    ("howitzer-towed", r"\b(towed|ultra[ -]?light|ulh|m777|atags|bharat \d|"
                       r"garuda|fh-?\d+|light field gun|ifg)\b"),
    ("gun-barrel", r"\b(barrel|ordnance|breech|muzzle brake|recoil system)\b"),
    # ---- vehicles ----
    ("mrap", r"\b(mine[ -]protected|mrap|mpv)\b"),
    ("apc", r"\b(apc|troop carrier|personnel carrier|maverick|infantry fighting|ifv)\b"),
    ("light-armoured", r"\b(lamv|lapv|light armoured|light armored|bullet ?proof|"
                       r"light tactical|light specialist|ltv|lsv|l\.b\.p\.v|humvee|jltv)\b"),
    ("main-battle-tank", r"\b(main battle tank|\bmbt\b|arjun|t-?90|leopard|abrams)\b"),
    # ---- unmanned & marine ----
    ("uav", r"\b(uav|uas|drone|loitering|unmanned aerial)\b"),
    ("ugv", r"\b(ugv|unmanned ground|ecars)\b"),
    ("uuv", r"\b(uuv|uuws|unmanned underwater|underwater system|torpedo)\b"),
    ("naval-vessel", r"\b(corvette|frigate|patrol (boat|vessel)|interceptor|"
                     r"submarine|usv)\b"),
]
KINDS = [(k, re.compile(p, re.I)) for k, p in KINDS]

# Kinds that are NEVER interchangeable even though a careless reader might pair them.
# Stated explicitly so the reason can be printed, rather than falling out of a mismatch.
NEVER = {
    ("shell-empty", "shell-complete"):
        "KSSL supplies EMPTY shell bodies (catalogue p37: \"Only empties\"); a filled or "
        "complete round is a different product at a different point of the supply chain",
    ("shell-empty", "shell-guided"):
        "a forged shell body has no guidance section, fuze or payload to compare against "
        "a precision-guided projectile",
    ("carbine", "machine-gun"):
        "a 3 kg individual weapon and a vehicle- or tripod-mounted support weapon are not "
        "procured as one lot",
    ("carbine", "sniper-rifle"):
        "a close-quarter carbine and a precision rifle answer different requirements; "
        "comparing their effective ranges reads as a deficiency that is a design choice",
    ("carbine", "rcws"):
        "a remote weapon station is a mount, not a rifle",
}


# A kind's FAMILY. Two different kinds in one family still compete - a towed gun and a
# truck-mounted gun of the same calibre are bid into the same 155mm programme, and an
# MRAP and an APC answer the same protected-mobility requirement. They are published,
# with the difference NAMED, because hiding it would be the mirror of the original fault.
#
# Two kinds in DIFFERENT families do not compete, and that is the refusal.
# `shell-body` is a family of one on purpose: an empty forging competes with other
# empty forgings and with nothing else.
FAMILY = {
    "shell-empty": "shell-body",
    "shell-complete": "ammunition-round", "shell-guided": "ammunition-round",
    "carbine": "individual-weapon", "smg": "individual-weapon",
    "pistol": "individual-weapon",
    "sniper-rifle": "precision-rifle",
    "machine-gun": "support-weapon", "rcws": "support-weapon",
    "howitzer-towed": "artillery-gun", "howitzer-mounted": "artillery-gun",
    "howitzer-spg": "artillery-gun",
    "gun-barrel": "ordnance-component",
    "mrap": "protected-vehicle", "apc": "protected-vehicle",
    "light-armoured": "protected-vehicle",
    "main-battle-tank": "tracked-combat-vehicle",
    "uav": "uav", "ugv": "ugv", "uuv": "uuv",
    "naval-vessel": "naval-vessel",
}

# What to SAY when a pairing is published across two kinds of one family. Without this
# the panel shows a towed gun losing on mobility to a self-propelled one and calls it a
# gap, when it is the difference between the two products.
CAVEAT = {
    ("howitzer-towed", "howitzer-spg"):
        "different mount: one is towed, the other self-propelled - mobility and crew "
        "figures are not a deficiency on either side",
    ("howitzer-towed", "howitzer-mounted"):
        "different mount: towed vs truck-mounted",
    ("howitzer-mounted", "howitzer-spg"):
        "different mount: wheeled truck-mounted vs tracked self-propelled",
    ("mrap", "light-armoured"):
        "different protection class: mine-protected hull vs light armoured",
    ("mrap", "apc"): "different role: mine-protected patrol vs troop carrier",
    ("apc", "light-armoured"): "different protection class",
    ("carbine", "smg"): "different cartridge class",
    ("machine-gun", "rcws"): "one is the weapon, the other the mount",
    ("shell-complete", "shell-guided"):
        "one is unguided, the other precision-guided - accuracy figures are not "
        "comparable on the same basis",
}


def product_of(label):
    """"Yantra India Limited · 155mm ERFB" -> "155mm ERFB". Also accepts a bare name."""
    s = (label or "").replace("·", "·")
    if "·" in s:
        s = s.split("·", 1)[1]
    return s.strip()


def kind_of(label):
    """The kind, or None. None means REFUSE — never a default."""
    name = product_of(label)
    if not name:
        return None
    for k, rx in KINDS:
        if rx.search(name):
            return k
    return None


def gate(bf, comp, kinds=None):
    """(verdict, kind, reason) where verdict is 'pass' | 'refuse' | 'unresolved'.

    THREE states, not two. The first audit run collapsed them into one and reported
    "200 of 219 refused", which reads as "the pairings are wrong" — but 165 of those were
    only "this name means nothing to a keyword table" (MaxxPro, Kestrel, Bharat 52). Those
    two need opposite work: a REFUSE is a finding and the row should go, an UNRESOLVED is
    a gap in our sourcing and the row is waiting on that maker's data sheet. Publishing
    neither is right; reporting them as one number is not.

    `kinds` optionally maps a product name to the kind read from its OWN catalogue — see
    fetch_brochures.py. A kind carried by the maker's data sheet always beats one guessed
    from the product's name, which is the only way "MaxxPro" ever becomes an MRAP.
    """
    kb = (kinds or {}).get(product_of(bf).lower()) or kind_of(bf)
    kc = (kinds or {}).get(product_of(comp).lower()) or kind_of(comp)
    if kb is None or kc is None:
        which = product_of(bf) if kb is None else product_of(comp)
        return "unresolved", None, "no kind for %r - needs that maker's data sheet" % which
    if kb == kc:
        return "pass", kb, ""
    why = NEVER.get((kb, kc)) or NEVER.get((kc, kb))
    if why:
        return "refuse", None, why
    if FAMILY.get(kb) and FAMILY.get(kb) == FAMILY.get(kc):
        note = CAVEAT.get((kb, kc)) or CAVEAT.get((kc, kb)) or             "different kinds within %s: %s vs %s" % (FAMILY[kb], kb, kc)
        return "pass", FAMILY[kb], note
    return "refuse", None, "%s is not comparable with %s (%s vs %s)" % (
        kb, kc, FAMILY.get(kb, "?"), FAMILY.get(kc, "?"))


def demo():
    # the two pairings the operator caught, and why each is refused
    v, _, why = gate("KSSL · Shell forgings", "Raytheon · Excalibur (precision)")
    assert v == "refuse" and "guidance" in why, why
    v, _, why = gate("KSSL · Shell forgings", "Rheinmetall · 155mm Assegai / M107 (filled)")
    assert v == "refuse" and "empties" in why.lower(), why
    v, _, why = gate("KSSL · CQB Carbine", "AWEIL · MTMG tank machine gun")
    assert v == "refuse" and "one lot" in why, why
    v, _, why = gate("KSSL · CQB Carbine", "Accuracy International · AWM / AXMC")
    assert v == "refuse", why

    # and the pairings that SHOULD survive
    v, k, _ = gate("KSSL · CQB Carbine", "Kalashnikov Concern · AK-203")
    assert v == "pass" and k == "carbine"
    v, k, _ = gate("KSSL · ATAGS", "BAE Systems · M777")
    assert v == "pass" and k == "howitzer-towed", k
    # different kinds, SAME family: published, but the difference is named
    v, k, note = gate("KSSL · MArG 155", "KNDS · CAESAR 6x6")
    assert v == "pass" and k == "artillery-gun" and "mount" in note, note
    # different family: refused
    v, _, why = gate("KSSL · CQB Carbine", "Nammo · 155 HE-ER")
    assert v == "refuse", why

    # a name that says nothing is UNRESOLVED, never a quiet pass and never a finding
    v, _, why = gate("KSSL · Shell forgings", "Some Co · Advanced Solution")
    assert v == "unresolved" and "data sheet" in why, why
    # ...and a catalogue-supplied kind outranks the silent name
    v, k, _ = gate("KSSL · Shell forgings", "Some Co · Advanced Solution",
                   kinds={"advanced solution": "shell-empty"})
    assert v == "pass" and k == "shell-empty"

    # ordering: the specific test must beat the general one
    assert kind_of("AWEIL · MTMG tank machine gun") == "machine-gun"
    assert kind_of("KSSL · 155mm shell forgings") == "shell-empty"
    print("demo ok")


def audit():
    import psycopg2 as pg
    dsn = os.environ.get("KSSL_DSN",
                         "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
    with pg.connect(dsn, connect_timeout=10) as cx, cx.cursor() as cur:
        cur.execute("select matchup_id, cat, bf, comp from serving.matchup "
                    "where origin='pipeline' order by matchup_id")
        rows = cur.fetchall()
    buckets = {"pass": [], "refuse": [], "unresolved": []}
    for mid, cat, bf, comp in rows:
        v, kind, why = gate(bf, comp)
        buckets[v].append((mid, cat, bf, comp, kind or why))
    print("pipeline matchups: %d" % len(rows))
    print("  pass       %4d  publishable like-for-like" % len(buckets["pass"]))
    print("  refuse     %4d  provably not a comparison - these are the bad rows" % len(buckets["refuse"]))
    print("  unresolved %4d  waiting on that maker's data sheet" % len(buckets["unresolved"]))

    print()
    print("-- REFUSED (findings) --")
    reasons = {}
    for _, _, bf, comp, why in buckets["refuse"]:
        reasons.setdefault(why[:80], []).append((product_of(bf), product_of(comp)))
    for why, pairs in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
        print("%4d  %s" % (len(pairs), why))
        for a, b in pairs[:3]:
            print("        %-26s vs %s" % (a[:26], b[:44]))

    print()
    print("-- UNRESOLVED, by product (the sourcing worklist) --")
    need = {}
    for _, _, bf, comp, why in buckets["unresolved"]:
        m = re.search(r"no kind for '([^']+)'", why)
        if m:
            need[m.group(1)] = need.get(m.group(1), 0) + 1
    for name, n in sorted(need.items(), key=lambda kv: -kv[1])[:20]:
        print("%4d rows blocked by  %s" % (n, name))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--audit", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    elif a.audit:
        audit()
    else:
        demo()
