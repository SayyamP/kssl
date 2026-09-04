"""The order article_date consults its sources in, and what may override what.

    python test_date_order.py

THE RULE: trust picks the MONTH; a later, less-trusted source may only add a DAY
to the month already chosen, and may never move it.

Two bugs have lived in this handful of lines and both are replayed below.

1. A more-trusted source naming only a month ENDED the search, so a day in a
   less-trusted one was never reached. The URL path /2026/09/ answered
   "Sep 2026" for an article whose own byline read "01 Settembre 2026".

2. The repair for that returned the month when a candidate fell in a DIFFERENT
   month -- which enforced the rule, but ended the search just as finally. Step 3
   is published_at, routinely the fetch stamp and so routinely another month, and
   it cut the search off before the body was read. Two analisidifesa articles,
   from 2021 and 2025 and crawled in 2026, lost the day their own text stated.

The second bug is invisible to any test that checks one candidate at a time: it
only appears in a SEQUENCE, where a middle candidate hides a later one. So every
case here feeds a whole list of candidates in trust order, exactly as
article_date does, and asserts the answer.

date_step is loaded out of the shipped file rather than reimplemented, because a
test that restates the logic cannot see a fix that shipped dead.
"""
import io
import sys
from pathlib import Path

HERE = Path(__file__).parent

src = io.open(HERE / "serving_fill.py", encoding="utf-8").read()
i = src.index("def date_step")
j = src.index("\ndef article_date")
ns = {}
exec(compile(src[i:j], "serving_fill.py", "exec"), ns)               # noqa: S102
date_step = ns["date_step"]

TODAY = (2026, 9)
fails = []


def resolve(candidates, today_ym=TODAY):
    """Exactly what article_date does: walk the candidates, first answer wins,
    otherwise fall through to the best month-only one seen."""
    coarse = None
    for ymd in candidates:
        answer, coarse = date_step(coarse, ymd, today_ym)
        if answer:
            return answer
    return coarse


def check(name, got, want):
    ok = got == want
    print("  %s %-54s %s" % ("ok  " if ok else "FAIL", name,
                             "" if ok else "got %r want %r" % (got, want)))
    if not ok:
        fails.append(name)


# --- bug 1: a month-only front-runner must not end the search ---------------
# markup: nothing | url: /2026/09/ | published_at: none | body: "01 Settembre 2026"
check("URL month + a later day in that month -> the day",
      resolve([(2026, 9, None), (2026, 9, 1)]), (2026, 9, 1))

# --- bug 2: an out-of-month candidate must be SKIPPED, not answered with ----
# THE REGRESSION. analisidifesa 2021/05 article, crawled 2026: the fetch stamp
# sits between the URL month and the body's real day.
check("fetch stamp between the URL month and the body day",
      resolve([(2021, 5, None), (2026, 8, 27), (2021, 5, 13)], (2026, 9)),
      (2021, 5, 13))
check("several out-of-month candidates still do not end the search",
      resolve([(2025, 8, None), (2026, 9, 2), (2026, 1, 4), (2025, 8, 31)]),
      (2025, 8, 31))

# --- the rule the skipping must not break: the month never moves ------------
check("a dated candidate from another month cannot win",
      resolve([(2023, 1, None), (2026, 7, 29)]), (2023, 1, None))
check("...not even several of them",
      resolve([(2023, 1, None), (2026, 7, 29), (2026, 6, 11)]), (2023, 1, None))
check("the FIRST month wins; a later month-only candidate cannot move it",
      resolve([(2026, 8, None), (2026, 9, None)]), (2026, 8, None))
check("a day in the second month cannot move it either",
      resolve([(2026, 8, None), (2026, 9, None), (2026, 9, 3)]), (2026, 8, None))

# --- a day arriving first is simply the answer -----------------------------
check("markup states a full date -> nothing later is consulted",
      resolve([(2026, 8, 30), (2026, 8, None), (2026, 8, 1)]), (2026, 8, 30))

# --- the future is a forecast, never a publication date --------------------
check("a future date is skipped and does not become the fallback",
      resolve([(2027, 4, None), (2026, 8, 12)]), (2026, 8, 12))
check("a future date does not hide a month behind it",
      resolve([(2027, 4, 1), (2026, 8, None)]), (2026, 8, None))
check("this month is not the future",
      resolve([(2026, 9, 4)]), (2026, 9, 4))
check("a year-only candidate is usable", resolve([(2026, None, None)]),
      (2026, None, None))

# --- nothing at all ---------------------------------------------------------
check("no candidates -> None", resolve([]), None)
check("only unusable candidates -> None", resolve([None, (2030, 1, 1)]), None)

# --- year precision must not be sharpened by another year's day ------------
check("a day in a different YEAR cannot win",
      resolve([(2026, None, None), (2025, 9, 1)]), (2026, None, None))

print()
print("all date-order checks passed" if not fails else "FAILED: %s" % ", ".join(fails))
sys.exit(1 if fails else 0)
