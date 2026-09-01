"""Checks for the card date logic: url_date and is_fetch_fallback.

    python extraction/signals/test_article_date.py

Every URL below is a real one from the corpus. The bug these guard against:
serving.signal_card dated a 13 Jul 2026 story "Aug 2026", because
documents.published_at held the fetch timestamp rather than a publication date.
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

# serving_fill imports httpx (via llmapi) and psycopg2; the date helpers do not.
# Load just those two functions so the checks run anywhere.
import re                                                            # noqa: E402
src = (HERE / "serving_fill.py").read_text(encoding="utf-8")
ns = {"re": re}
for fn in ("_URL_DATE = ", "def url_date", "def is_fetch_fallback"):
    i = src.index(fn)
    j = src.index("\n\n\n", i)
    exec(compile(src[i:j], "serving_fill.py", "exec"), ns)            # noqa: S102
url_date = ns["url_date"]
is_fetch_fallback = ns["is_fetch_fallback"]

fails = []


def check(name, got, want):
    ok = got == want
    print("  %s %-46s %s" % ("ok  " if ok else "FAIL", name,
                             "" if ok else "got %r want %r" % (got, want)))
    if not ok:
        fails.append(name)


# --- url_date: the real corpus URLs -------------------------------------
check("asdnews /2026/07/13/ (the reported bug)",
      url_date("http://www.asdnews.com/news/defense/2026/07/13/"
               "ai-battle-lab-prepare-british-army-modern-warfare"),
      (2026, 7, 13))
check("https + no www",
      url_date("https://asdnews.com/news/defense/2025/10/08/red-cat-introduces-fang"),
      (2025, 10, 8))
check("wordpress /2026/06/ style with day",
      url_date("https://breakingdefense.com/2026/06/rheinmetall-vantor-plan-joint-isr/"),
      None)                                   # month-only path: not a full date
check("dashed 2026-07-13",
      url_date("https://example.com/news/2026-07-13/some-story"), (2026, 7, 13))
check("date at end of path",
      url_date("https://example.com/news/2026/07/13"), (2026, 7, 13))

# --- url_date must NOT fire on things that only look like dates ---------
check("no date in path", url_date("https://example.com/news/some-story"), None)
check("year only", url_date("https://example.com/2026/some-story"), None)
check("compact id 20260713 is not a date",
      url_date("https://example.com/news/20260713/story"), None)
check("month 13 rejected", url_date("https://example.com/2026/13/01/x"), None)
check("day 32 rejected", url_date("https://example.com/2026/07/32/x"), None)
check("day 00 rejected", url_date("https://example.com/2026/00/07/x"), None)
check("a date in the QUERY is a filter, not a byline",
      url_date("https://example.com/list?d=2026/07/13"), None)
check("a date in the FRAGMENT is ignored",
      url_date("https://example.com/list#2026/07/13"), None)
check("empty / None", url_date(""), None)
check("None url", url_date(None), None)
check("1999 is out of the 20xx window",
      url_date("https://example.com/1999/07/13/x"), None)

# --- is_fetch_fallback --------------------------------------------------
# The exact shape of the reported bug.
check("same date + midnight -> fallback",
      is_fetch_fallback("2026-08-03T00:00:00Z", "2026-08-03T12:35:20Z"), True)
# Every one of the 30 CORRECT dates in the corpus is midnight too. Midnight
# alone must never condemn a date, or all 30 are lost.
check("midnight but a DIFFERENT day -> real date",
      is_fetch_fallback("2026-07-15T00:00:00", "2026-07-30T20:39:04"), False)
check("same day but a real clock time -> real date",
      is_fetch_fallback("2026-08-03T09:14:02Z", "2026-08-03T12:35:20Z"), False)
check("no published_at", is_fetch_fallback("", "2026-08-03T12:35:20Z"), False)
check("no fetched_at (older synced docs) -> cannot judge, keep the date",
      is_fetch_fallback("2026-08-03T00:00:00Z", ""), False)
check("both missing", is_fetch_fallback(None, None), False)
check("date-only strings, same day",
      is_fetch_fallback("2026-08-03", "2026-08-03"), True)
check("date-only strings, different day",
      is_fetch_fallback("2026-07-13", "2026-08-03"), False)

print()
print("all date checks passed" if not fails else "FAILED: %s" % ", ".join(fails))
sys.exit(1 if fails else 0)
