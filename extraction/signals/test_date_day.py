"""A non-English article must keep its day, and a month-only source must not hide it.

    python3 test_date_day.py

The Leonardo Centauro II card printed 'Sep 2026' while its source, analisidifesa.it,
carries the byline '01 Settembre 2026' and states 1 September 2026 on the page. Two
faults stacked:

  parse_date  reached its multilingual branch and returned (year, month, None). Every
              English shape above it captures a day; the non-English fallback threw the
              day away, so an English publisher got '30 Aug 2026' and an Italian one
              publishing the same fact got 'Sep 2026'. Third occurrence of a closed
              English list quietly behaving as a language filter.

  article_date returned the FIRST usable candidate. The URL path /2026/09/ is month-only
              and is trusted above the body, so the byline further down was never
              reached. Trust still chooses the month; a later source may now add a day
              to that month, and may never move it.

Measured on the served corpus: 85 of 825 cards carried no day, 42 of them from this one
publisher.

Loads the functions out of the shipped serving_fill.py rather than reimplementing them,
because a test that restates the logic cannot see a fix that shipped dead.
"""
import io
import re
import sys
import types
from pathlib import Path

HERE = Path(__file__).parent


def load():
    src = io.open(HERE / "serving_fill.py", encoding="utf-8").read()
    if chr(8) in src:
        raise AssertionError("serving_fill.py contains a backspace byte: a regex written "
                             "as backslash-b became one character and matches nothing.")
    mod = types.ModuleType("sf_under_test")
    mod.re = re
    head = src[: src.index("def parse_date")]
    # the tables and helpers parse_date closes over
    for name in ("_NATIVE_DIGITS", "_MONTHS", "_MON_RX"):
        k = head.index("\n%s = " % name)
        end = head.index("\n\n", k)
        exec(compile(head[k:end], "serving_fill.py", "exec"), mod.__dict__)
    def assign(name):
        """The whole statement `name = ...`, however many lines its braces span.

        _ML_MONTHS runs over a dozen lines and _ML_SHORT is a one-liner, so a fixed
        end marker cannot find both. Balance the brackets instead.
        """
        k = src.index("\n%s = " % name) + 1
        depth, j = 0, k
        while True:
            ch = src[j]
            if ch in "{[(":
                depth += 1
            elif ch in "}])":
                depth -= 1
                if depth == 0:
                    return src[k:j + 1]
            j += 1

    # _ML_MONTHS and _ML_SHORT are defined AFTER parse_date in the file
    for tbl in ("_ML_MONTHS", "_ML_SHORT"):
        exec(compile(assign(tbl), "serving_fill.py", "exec"), mod.__dict__)
    for fn in ("def _clamp", "def _fold", "def _ml_month"):
        i = src.index(fn)
        j = src.index("\ndef ", i + 1)
        exec(compile(src[i:j], "serving_fill.py", "exec"), mod.__dict__)
    i = src.index("def parse_date")
    j = src.index("\n# Month names for the corpus's languages")
    exec(compile(src[i:j], "serving_fill.py", "exec"), mod.__dict__)
    return mod.parse_date


CASES = [
    # (input, expected (y, m, d)) -- the day must survive in every language
    ("01 Settembre 2026", (2026, 9, 1)),          # the reported card
    ("1 Settembre 2026", (2026, 9, 1)),
    ("17 vasario 2026", (2026, 2, 17)),           # Lithuanian
    ("3 septembre 2026", (2026, 9, 3)),           # French
    ("15 settembre 2026", (2026, 9, 15)),
    ("28 febbraio 2026", (2026, 2, 28)),
    # English shapes must be untouched by the change
    ("30 Aug 2026", (2026, 8, 30)),
    ("May 28, 2026", (2026, 5, 28)),
    ("2026-08-27", (2026, 8, 27)),
    # a month with no day anywhere stays a month
    ("settembre 2026", (2026, 9, None)),
    ("Sep 2026", (2026, 9, None)),
]


def main():
    parse_date = load()
    bad = []
    for text, want in CASES:
        got = parse_date(text)
        if got != want:
            bad.append("%-22r -> %r, want %r" % (text, got, want))

    # a day must never be invented out of the year
    got = parse_date("settembre 2026")
    if got and got[2] is not None:
        bad.append("a day was invented from the year: %r" % (got,))

    if bad:
        print("FAIL\n  " + "\n  ".join(bad))
        return 1
    print("ok - parse_date keeps the day in %d shapes across 4 languages" % len(CASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
