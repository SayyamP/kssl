"""Two spec strings -> the one quantity they BOTH state, or nothing.

    python spec_number.py --demo

WHY THIS EXISTS. 91 served specs carry a value on both sides, but only 53 compare: on
32 of them the rival has a parsed number and the KSSL side is text that plainly
contains one -- "185 hp" against "220hp / ECAS susp". The panel takes its
"one side has no number" branch and draws chips, so a comparison the operator can make
by eye is not made by the page. Reported as: "compare the specs which we have on both".

WHY IT IS NOT "PARSE THE FIRST NUMBER". Every string below is real, from the served
data, and a first-number parse gets three of them wrong in a way that INVERTS the
verdict or invents one:

    465 hp, 140 km/h   vs  600hp / 100km/h    hp says KSSL is behind (465<600);
                                              km/h says KSSL leads (140>100).
                                              One field, two quantities, two answers.
    224 hp @ 2,400 rpm vs  220hp / 8245mm L   first number is right here by luck; the
                                              2,400 and the 8,245 are different units.
    burst 3 rounds /   vs  6 rds/min          3 rounds per 30 sec IS 6 rds/min. A first
    30 sec, sustained                         -number parse reads 3 against 6 and
    42 rounds / 60 min                        reports the rival at twice the rate, on
                                              figures that are equal.

So the rule is: find the unit BOTH strings state, and compare the numbers attached to
THAT unit. Where the two sides share more than one unit, refuse -- the field is really
two fields ("Power / speed") and picking one silently chooses the verdict. Where they
share none, refuse. A refusal keeps today's behaviour: both values shown, nothing
claimed.

RANGES. "230-280 hp" against 220 is a real comparison -- every value in the range beats
it. "230-280" against 250 is not. A range decides only when it falls entirely on one
side of the other number; otherwise it is refused rather than collapsed to a midpoint
nobody published.
"""
import re
import sys

# Units seen in this corpus, longest first so 'km/h' wins over 'km' and 'm'.
# Written as alternatives rather than a generic \w+ because a generic one reads the 'L'
# in "8245mm L" and the 'rpm' in "224 hp @ 2,400 rpm" as comparable quantities.
_UNITS = [
    "km/h", "kmh", "rds/min", "rounds/min", "hp", "kw", "km", "mm", "cm",
    "tonnes", "tonne", "kg", "t", "deg", "rpm", "mph", "knots", "nm",
]
_UNIT_RX = "|".join(re.escape(u) for u in _UNITS)

# number, optional range, then the unit -- the unit is what anchors the number.
_QTY = re.compile(
    r"(?P<lo>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*[-–—]\s*(?P<hi>\d[\d,]*(?:\.\d+)?))?"
    r"\s*(?P<unit>" + _UNIT_RX + r")\b",
    re.I,
)

_CANON = {"kmh": "km/h", "rounds/min": "rds/min", "tonne": "tonnes", "t": "tonnes"}


def quantities(text):
    """{unit: (lo, hi)} for every number in `text` that names a unit.

    A unit stated twice with different numbers is DROPPED, not merged: "127 mm / 57 mm"
    is two measurements of different things sharing a label, and averaging or picking
    one of them would publish a figure nobody wrote.
    """
    out, dropped = {}, set()
    for m in _QTY.finditer(str(text or "")):
        unit = _CANON.get(m.group("unit").lower(), m.group("unit").lower())
        lo = float(m.group("lo").replace(",", ""))
        hi = float(m.group("hi").replace(",", "")) if m.group("hi") else lo
        span = (min(lo, hi), max(lo, hi))
        if unit in out and out[unit] != span:
            dropped.add(unit)
        out[unit] = span
    for u in dropped:
        out.pop(u, None)
    return out


def shared_quantity(kv, cv):
    """-> (unit, (klo, khi), (clo, chi)) for the ONE unit both sides state, else None."""
    kq, cq = quantities(kv), quantities(cv)
    both = sorted(set(kq) & set(cq))
    if len(both) != 1:          # none to compare on, or more than one -- see the module docstring
        return None
    u = both[0]
    return u, kq[u], cq[u]


def decides(krange, crange):
    """Do these two ranges separate cleanly? Overlapping ranges decide nothing."""
    return krange[1] < crange[0] or crange[1] < krange[0] or krange == crange


def compare(kv, cv):
    """-> (kn, cn) to store, or None when the two strings cannot be compared.

    The numbers returned are the range ENDS nearest the other side, so a range only
    ever decides by its weakest member -- "230-280 hp" beats 220 on 230, not on 280.
    """
    got = shared_quantity(kv, cv)
    if not got:
        return None
    _u, kr, cr = got
    if kr == cr:
        return kr[0], cr[0]     # equal: a real, comparable parity
    if not decides(kr, cr):
        return None             # the ranges overlap; nobody leads
    if kr[1] < cr[0]:           # KSSL entirely below
        return kr[1], cr[0]
    return kr[0], cr[1]         # KSSL entirely above


def fill(specs):
    """Fill kn/cn on the specs where both sides state the same quantity. In place.

    NEVER overwrites a number the pipeline already parsed -- this only reaches rows
    where at least one side has none, so a figure the extraction layer grounded is
    always the one that stands. Rows it cannot compare are returned untouched, which
    is today's behaviour: both values shown, nothing claimed.
    """
    for s in specs or []:
        if not isinstance(s, dict):
            continue
        if s.get("kn") is not None and s.get("cn") is not None:
            continue
        if s.get("kv") is None or s.get("cv") is None:
            continue
        got = compare(s.get("kv"), s.get("cv"))
        if got:
            s["kn"], s["cn"] = got
    return specs


def _demo():
    ok = True

    def ck(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  %-62s %s" % (label, "ok" if good else "FAIL got=%r want=%r" % (got, want)))

    print("the comparisons that were being missed (real served strings):")
    ck("185 hp vs 220hp / ECAS susp", compare("185 hp", "220hp / ECAS susp"), (185.0, 220.0))
    ck("224 hp @ 2,400 rpm vs 220hp / 8245mm L  (rpm and mm ignored)",
       compare("224 hp @ 2,400 rpm", "220hp / 8245mm L"), (224.0, 220.0))
    ck("230-280 hp vs 220hp  (a range entirely above decides, on its low end)",
       compare("230–280 hp", "220hp / ECAS susp"), (230.0, 220.0))
    ck("465 hp, 140 km/h vs 220hp / 8245mm L  (only hp is shared)",
       compare("465 hp, 140 km/h", "220hp / 8245mm L"), (465.0, 220.0))

    print("the ones that must stay refused -- each would invert or invent a verdict:")
    ck("465 hp, 140 km/h vs 600hp / 100km/h  (hp and km/h disagree)",
       compare("465 hp, 140 km/h", "600hp / 100km/h"), None)
    ck("burst 3 rounds / 30 sec ... vs 6 rds/min  (3 per 30s IS 6/min)",
       compare("burst 3 rounds / 30 sec, sustained 42 rounds / 60 min", "6 rds/min"), None)
    ck("127 mm / 57 mm vs 30mm  (one label, two different measurements)",
       compare("127 mm / 57 mm", "30mm"), None)
    ck("6-8 personnel vs 2  (the rival states no unit)",
       compare("6–8 personnel", "2"), None)
    ck("a range that STRADDLES the other value decides nothing",
       compare("230–280 hp", "250 hp"), None)
    ck("no number at all", compare("wheeled chassis", "tracked"), None)
    ck("a number with no unit on either side", compare("18", "22"), None)

    print("equality is a comparison, not a refusal:")
    ck("155 mm / 52 calibre vs 155mm", compare("155 mm / 52 calibre", "155mm"), (155.0, 155.0))

    print("filling a spec list:")
    rows = [{"l": "Power / speed", "kv": "185 hp", "cv": "220hp / ECAS susp",
             "kn": None, "cn": 220, "hi": True},
            {"l": "Rate of fire", "kv": "burst 3 rounds / 30 sec", "cv": "6 rds/min",
             "kn": None, "cn": 6, "hi": True},
            {"l": "Weight", "kv": "18 tonnes", "cv": None, "kn": None, "cn": None}]
    fill(rows)
    ck("the comparable row is filled", (rows[0]["kn"], rows[0]["cn"]), (185.0, 220.0))
    ck("the ambiguous row is left alone", rows[1]["kn"], None)
    ck("a one-sided row is left alone", rows[2]["kn"], None)
    already = [{"kv": "185 hp", "cv": "220 hp", "kn": 999.0, "cn": 220}]
    fill(already)
    ck("a number the pipeline already parsed is never overwritten",
       already[0]["kn"], 999.0)

    print("\n%s" % ("all checks passed" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_demo())
