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
two measurables. Fail closed. A pairing with nothing comparable has nothing to
say, and a row that says nothing still counts in the badge and in "N rivals" --
which turns absence of evidence into presence of competitors.
"""
import re
import unicodedata

MIN_SHARED_FIELDS = 2

# A pairing axis is not a comparison. Calibre, bore and configuration decide WHETHER
# two things are alike; they are not a dimension on which one beats the other, and
# counting them as shared evidence is how a 155 mm gun "compares" with a 105 mm one.
AXIS_FIELDS = re.compile(
    r"\b(calibre|caliber|bore|configuration|type|class|variant|family|role)\b", re.I)

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


def shared_measurables(specs):
    """How many fields carry a real number on BOTH sides.

    This is the test the UI already performs to write its verdict -- "N value(s)
    sourced, none comparable on both sides". Performing it AFTER the row exists
    produces a row that exists to announce it has nothing to say. It belongs here,
    before the row.
    """
    n, fields = 0, []
    for s in specs or []:
        label = s.get("l") or s.get("label") or ""
        if AXIS_FIELDS.search(label):
            continue
        if _num(s.get("kv")) is not None and _num(s.get("cv")) is not None:
            n += 1
            fields.append(label)
    return n, fields


def refuse(row, roster_names=(), client_products=()):
    """-> (reason, detail) when the pairing must not be published, else (None, '').

    `row` is the shape revive_matchups builds: comp, compBy, bf, bfBy, specs.
    `roster_names` are the tracked competitors' names; `client_products` are the
    product names the client's own workbook holds.
    """
    comp_by = row.get("compBy") or maker_of(row.get("comp"))
    if roster_names:
        rn = {norm(x) for x in roster_names if x}
        c = norm(comp_by)
        if c and not any(c == r or (len(r) > 3 and r in c) or (len(c) > 3 and c in r)
                         for r in rn):
            return ("maker is not a tracked competitor", comp_by)

    if client_products:
        cp = {norm(x) for x in client_products if x}
        bf = norm(product_of(row.get("bf")))
        if bf and not any(bf == p or (len(bf) > 3 and bf in p) or
                          (len(p) > 3 and p in bf) for p in cp):
            return ("the KSSL side is not a product the client publishes",
                    product_of(row.get("bf")))

    n, fields = shared_measurables(row.get("specs"))
    if n < MIN_SHARED_FIELDS:
        return ("fewer than %d measurables on both sides" % MIN_SHARED_FIELDS,
                "%d shared" % n)
    return (None, ", ".join(fields[:4]))


def demo():
    """The row that prompted this, and the rows that must survive it."""
    fails = []

    def ck(name, ok, d=""):
        print("  %-64s %s%s" % (name, "PASS" if ok else "FAIL", "  " + str(d) if d else ""))
        if not ok:
            fails.append(name)

    roster = ["Adani Defence", "Elbit Systems", "KNDS", "Tata Advanced Systems",
              "UVision Air", "BAE Systems", "Bharat Dynamics"]
    client = ["Bharat 150 UAV", "ATAGS", "MArG 155", "Protective Carbine — 5.56 × 30 mm"]

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

    thin = {"comp": "KNDS · CAESAR 6x6", "compBy": "KNDS", "bf": "KSSL · MArG 155",
            "specs": [{"l": "Calibre", "cv": "155 mm", "kv": "155 mm"},
                      {"l": "Range", "cv": "40 km", "kv": None}]}
    why, _ = refuse(thin, roster, client)
    ck("a pairing with one shared measurable is refused",
       why and why.startswith("fewer than"), why)

    ck("calibre alone is never a comparison",
       shared_measurables([{"l": "Calibre", "cv": "155 mm", "kv": "155 mm"}])[0] == 0)

    good = {"comp": "KNDS · CAESAR 6x6", "compBy": "KNDS", "bf": "KSSL · MArG 155",
            "specs": [{"l": "Calibre", "cv": "155 mm", "kv": "155 mm"},
                      {"l": "Maximum range", "cv": "40 km", "kv": "45 km"},
                      {"l": "Rate of fire", "cv": "6 rds/min", "kv": "5 rds/min"}]}
    why, det = refuse(good, roster, client)
    ck("a real like-for-like artillery pairing survives", why is None, why or det)

    ck("the maker is not read as the product",
       product_of("KNDS · CAESAR 6x6") == "CAESAR 6x6" and
       maker_of("KNDS · CAESAR 6x6") == "KNDS")

    # A gate that never refuses is not running, and a gate that refuses everything is
    # not a gate either -- both are checked, because both have happened in this repo.
    seen = [refuse(r, roster, client)[0] for r in (skystriker, shahed, thin, good)]
    ck("the gate both refuses and admits", any(seen) and not all(seen))

    print("\n%s" % ("all checks passed" if not fails else "%d FAILED" % len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(demo())
