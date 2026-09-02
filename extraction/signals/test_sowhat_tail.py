"""The 'so what' line must not end mid-clause.

    python3 test_sowhat_tail.py

_TAIL_RX cuts an invented KSSL tie off the end of a sentence. Its hedge alternative
is a pattern meant for "possibly" -- which also matches "position", so a sentence
ending "...strengthening its position in the naval market against KSSL offerings" was
cut at "position", losing the whole substantive clause and leaving

    Saab secures a significant order for A26 submarines, strengthening its.

with a full stop appended to a possessive. All 17 served cards were in this shape.

This file loads strip_kssl_tail OUT OF serving_fill.py and runs the real thing. The
first version of this test reimplemented the repair inline and passed green while
production was untouched: the fix had been written with a backslash-b that reached the
file as a single 0x08 backspace byte, so the pattern matched nothing and the loop never
fired. A test that reimplements the code under test cannot see that class of fault at
all, which is why this one loads the shipped source the hard way -- and why it refuses
outright if that source contains a control byte.

Every INPUT below is reconstructed from a served row; every string in WAS is what the
dashboard actually displayed.
"""
import io
import re
import sys
import types
from pathlib import Path

HERE = Path(__file__).parent


def load_strip():
    """strip_kssl_tail, compiled from the shipped source.

    serving_fill.py opens a database and imports the corpus at module level, so the
    function is compiled on its own -- but from the real file, so a corrupt byte or a
    broken pattern in what actually ships fails this test.
    """
    src = io.open(HERE / "serving_fill.py", encoding="utf-8").read()

    if chr(8) in src:
        raise AssertionError(
            "serving_fill.py contains a literal backspace byte. A regex written as "
            "backslash-b became ONE character instead of two, so that pattern matches "
            "nothing and still compiles without complaint.")

    mod = types.ModuleType("serving_fill_under_test")
    mod.re = re

    def grab(start, after=None):
        i = src.index(start)
        j = src.index("\ndef ", i + 1) if after is None else src.index(after, i)
        return src[i:j]

    # the module-level regexes strip_kssl_tail closes over, then the helper, then it
    head = src[: src.index("def strip_kssl_tail")]
    for line in ("_TAIL_RX", "_TIE_PLAIN", "_KSSL_SENT", "_FILLER_RX"):
        k = head.index("\n%s = " % line)
        end = head.index(")\n", k) + 2
        exec(compile(head[k:end], "serving_fill.py", "exec"), mod.__dict__)
    exec(compile(grab("def _has_concrete"), "serving_fill.py", "exec"), mod.__dict__)
    exec(compile(grab("def strip_kssl_tail"), "serving_fill.py", "exec"), mod.__dict__)
    return mod.strip_kssl_tail


DANGLES = re.compile(
    r"\b(?:its|their|his|her|our|your|the|an?|of|in|on|at|by|from|with|and|but|to|for)"
    r"\s*[.!?]?\s*$", re.I)

CASES = [
    # (input sentence, what the dashboard showed BEFORE the fix)
    ("Saab secures a significant order for A26 submarines, strengthening its position "
     "in the naval market against KSSL offerings.",
     "Saab secures a significant order for A26 submarines, strengthening its."),
    ("Thales secures a significant radar contract, strengthening its position where "
     "KSSL competes.",
     "Thales secures a significant radar contract, strengthening its."),
    ("The order represents a significant milestone for Rheinmetall, expanding its "
     "customer base and solidifying its position in the artillery segment, a market "
     "KSSL also targets.",
     "The order represents a significant milestone for Rheinmetall, expanding its "
     "customer base and solidifying its."),
    ("Rheinmetall's win solidifies its position in a market KSSL also targets.",
     "Rheinmetall's win solidifies its."),
    ("The acquisition allows GDELS to strengthen its position against KSSL products.",
     "The acquisition allows GDELS to strengthen its."),
]

# a sentence carrying no KSSL tie must survive untouched
UNTOUCHED = "Hanwha delivered the first K9 howitzers to Poland in March."


def main():
    strip = load_strip()
    bad = []

    for src, was in CASES:
        got = (strip(src) or "").strip()
        if got == was:
            bad.append("STILL TRUNCATED: %r" % got)
        elif got and DANGLES.search(got):
            bad.append("ends on a function word: %r" % got)

    keep = (strip(UNTOUCHED) or "").strip()
    if UNTOUCHED.rstrip(".") not in keep:
        bad.append("a sentence with no KSSL tie was altered: %r" % keep)

    if bad:
        print("FAIL\n  " + "\n  ".join(bad))
        return 1
    print("ok - strip_kssl_tail, %d repaired + 1 passthrough, nothing ends on a "
          "function word" % len(CASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
