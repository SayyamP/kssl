"""The 'so what' line must not end mid-clause.

    python3 test_sowhat_tail.py

_TAIL_RX exists to cut an invented KSSL tie off the end of a sentence. Its hedge
alternative is `pos\w+`, for "possibly" -- but that also matches "position", so a
sentence ending "...strengthening its position in the naval market against KSSL
offerings" was cut at "position", losing the whole substantive clause and leaving
"Saab secures a significant order, strengthening its." with a full stop appended
to a possessive. All 17 served cards were in this shape.

Every INPUT below is reconstructed from a served row; every string in WAS is what
the dashboard actually displayed.
"""
import re
import sys

_TAIL_RX = re.compile(
    r"[,;]?\s*(?:(?:which|that)\s+)?(?:could|potentially|may|would|pos\w+)\b[^.!?]*?\bKSSL\b[^.!?]*",
    re.I)
_TIE_PLAIN = re.compile(
    r"[,;]?\s*[^.!?]*\bKSSL['\u2019]?s?\b\s*(?:drone|artiller|ammunition|small[- ]arms|armou?red|"
    r"offering|portfolio|position|product|categor|market|landscape|system|space|segment|"
    r"capabilit)[^.!?]*", re.I)

DANGLE = re.compile(r"\b(?:its|their|his|her|our|your|the|an?|of|in|on|at|by|from|"
                    r"with|and|but|to|for)$", re.I)


def clean(sent):
    core = _TIE_PLAIN.sub("", _TAIL_RX.sub("", sent))
    core = re.sub(r"[\s,;]+(?:and|but|which|that|as|so|to|for|with)?[\s,;.]*$", "",
                  core, flags=re.I).strip().rstrip(",;. ")
    while DANGLE.search(core):
        head, sep, _ = core.rpartition(",")
        core = head.strip().rstrip(",;. ") if sep else ""
        if not core:
            break
    return (core + ".") if core else ""


CASES = [
    # (input sentence, what the dashboard showed BEFORE, what it must show now)
    ("Saab secures a significant order for A26 submarines, strengthening its position "
     "in the naval market against KSSL offerings.",
     "Saab secures a significant order for A26 submarines, strengthening its.",
     "Saab secures a significant order for A26 submarines."),
    ("Thales secures a significant radar contract, strengthening its position where "
     "KSSL competes.",
     "Thales secures a significant radar contract, strengthening its.",
     "Thales secures a significant radar contract."),
    ("The order represents a significant milestone for Rheinmetall, expanding its "
     "customer base and solidifying its position in the artillery segment, a market "
     "KSSL also targets.",
     "The order represents a significant milestone for Rheinmetall, expanding its "
     "customer base and solidifying its.",
     # walking back to the clause boundary keeps only what precedes the first comma.
     # Shorter than the source, but true and grammatical -- which is the whole bar.
     "The order represents a significant milestone for Rheinmetall."),
    # No comma to fall back to -> drop it. Silence beats a fragment.
    ("Rheinmetall's win solidifies its position in a market KSSL also targets.",
     "Rheinmetall's win solidifies its.",
     ""),
    ("The acquisition allows GDELS to strengthen its position against KSSL products.",
     "The acquisition allows GDELS to strengthen its.",
     ""),
    # A sentence with no KSSL tie must pass through untouched.
    ("Hanwha delivered the first K9 howitzers to Poland in March.",
     None,
     "Hanwha delivered the first K9 howitzers to Poland in March."),
]

bad = []
for src, was, want in CASES:
    got = clean(src)
    if got != want:
        bad.append("  in:   %s\n  got:  %r\n  want: %r" % (src[:70], got, want))
    if was is not None and got == was:
        bad.append("  STILL TRUNCATED: %r" % got)

if bad:
    print("FAIL\n" + "\n".join(bad))
    sys.exit(1)
print("ok - sowhat tail, %d cases (no sentence ends on a function word)" % len(CASES))
