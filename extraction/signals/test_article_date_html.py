"""Checks for article_date.pick_date -- reading the publication date from markup.

    python extraction/signals/test_article_date_html.py

Every fixture is a shape taken from a page in the corpus. The two bugs these
guard against, both found by running against real HTML rather than by reasoning:

  * asdnews ships `<time id="current-date">` -- a navbar clock printing TODAY.
    The crawler scraped it, which is why documents.published_at kept equalling
    the fetch date exactly.
  * analisidifesa ships NINE `<time pubdate>` tags on one article page, all
    from the sidebar's recent-posts widget. Taking the first dated a January
    2023 story "29 Jul 2026".
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from article_date import date_candidates, parse_iso_date, pick_date   # noqa: E402

TODAY = (2026, 9, 2)
fails = []


def check(name, got, want):
    ok = got == want
    print("  %s %-52s %s" % ("ok  " if ok else "FAIL", name,
                             "" if ok else "got %r want %r" % (got, want)))
    if not ok:
        fails.append(name)


# --- tier 1: self-describing metadata -----------------------------------
check("article:published_time",
      pick_date('<meta property="article:published_time" content="2023-01-26T09:14:02+01:00">',
                today=TODAY), (2023, 1, 26))
check("JSON-LD datePublished (the asdnews article)",
      pick_date('<script type="application/ld+json">{"@type":"NewsArticle",'
                '"datePublished":"2026-07-13","dateModified":"2026-07-13"}</script>',
                today=TODAY), (2026, 7, 13))
check("dcterms.date",
      pick_date('<meta name="dcterms.date" content="2024-05-02">', today=TODAY),
      (2024, 5, 2))
check("content before property",
      pick_date('<meta content="2022-03-04" property="article:published_time">',
                today=TODAY), (2022, 3, 4))
check("itemprop datePublished",
      pick_date('<meta itemprop="datePublished" content="2021-11-09">', today=TODAY),
      (2021, 11, 9))

# --- the two real traps --------------------------------------------------
check("navbar clock `id=current-date` is NOT a publication date",
      pick_date('<time id="current-date" class="navbar-text" datetime="2026-08-03">',
                today=TODAY), None)
check("nine sidebar <time pubdate> -> ambiguous, refuse",
      pick_date("".join(
          '<time pubdate class="entry-date published updated" datetime="2026-07-%02dT09:00:00+02:00">' % d
          for d in (29, 25, 22, 21, 17, 14, 13, 8)), today=TODAY), None)
check("ONE <time pubdate> is trusted (a real single-article page)",
      pick_date('<time pubdate class="entry-date published" datetime="2024-02-11T10:00:00Z">',
                today=TODAY), (2024, 2, 11))
check("the same date repeated is still one date",
      pick_date('<time pubdate class="published" datetime="2024-02-11T10:00:00Z">'
                '<time pubdate class="published" datetime="2024-02-11T18:30:00Z">',
                today=TODAY), (2024, 2, 11))
check("metadata BEATS ambiguous <time> tags",
      pick_date('<meta property="article:published_time" content="2023-01-26">'
                '<time pubdate class="published" datetime="2026-07-29T09:17:40+02:00">'
                '<time pubdate class="published" datetime="2026-07-25T15:03:40+02:00">',
                today=TODAY), (2023, 1, 26))

# --- what must never be returned ----------------------------------------
check("modified time is not a publication date",
      pick_date('<meta property="article:modified_time" content="2026-08-30">',
                today=TODAY), None)
check("dateModified alone is not a publication date",
      pick_date('<script type="application/ld+json">{"dateModified":"2026-08-30"}</script>',
                today=TODAY), None)
check("a FUTURE date is skipped",
      pick_date('<meta property="article:published_time" content="2027-04-01">',
                today=TODAY), None)
check("...and the next candidate is taken instead",
      pick_date('<meta property="article:published_time" content="2027-04-01">'
                '<script type="application/ld+json">{"datePublished":"2026-01-05"}</script>',
                today=TODAY), (2026, 1, 5))
check("empty html", pick_date("", today=TODAY), None)
check("None html", pick_date(None, today=TODAY), None)
check("no dates at all", pick_date("<html><head><title>x</title></head></html>",
                                   today=TODAY), None)
check("a listing page's per-item <time> tags without pub markers are ignored",
      pick_date('<time datetime="2026-07-24"><time datetime="2026-07-06">',
                today=TODAY), None)

# --- parse_iso_date ------------------------------------------------------
check("iso with timezone", parse_iso_date("2023-01-26T09:14:02+01:00"), (2023, 1, 26))
check("iso date only", parse_iso_date("2023-01-26"), (2023, 1, 26))
check("year-month", parse_iso_date("2023-01"), (2023, 1, None))
check("year only", parse_iso_date("2023"), (2023, None, None))
check("unambiguous d/m/Y", parse_iso_date("26/01/2023"), (2023, 1, 26))
check("unambiguous m/d/Y", parse_iso_date("01/26/2023"), (2023, 1, 26))
check("ambiguous d/m vs m/d keeps only the month",
      parse_iso_date("05/06/2023"), (2023, 6, None))
check("month 13 refused", parse_iso_date("2023-13-01"), None)
check("day 32 refused", parse_iso_date("2023-01-32"), None)
check("year 1900 refused (copyright line)", parse_iso_date("1900-01-01"), None)
check("garbage", parse_iso_date("not a date"), None)
check("empty", parse_iso_date(""), None)
check("None", parse_iso_date(None), None)

# --- regressions found by the adversarial audit -------------------------

# Saab: itemprop on a <span>, machine value in `content`. Every Saab press
# release resolved to nothing before this.
check("itemprop datePublished on a <span> with content=",
      pick_date('<span class="smalltxt date" content="2025-12-01T09:00" '
                'itemprop="datePublished">1 december 2025</span>', today=TODAY),
      (2025, 12, 1))
# Kongsberg: d/m/Y with a trailing clock. 7/8/2026 is genuinely ambiguous --
# 7 August or 8 July depending on the writer's locale -- so the day is refused
# and the month kept, read day-first as the rest of this module reads numeric
# dates. Before the trailing-time fix it parsed as nothing at all.
check("itemprop on a <p>, d/m/Y plus a time -> month only",
      pick_date('<p itemprop="datePublished" content="7/8/2026 1:30:04 PM">x</p>',
                today=TODAY), (2026, 8, None))
# Thales / Janes: one bare <time>, no publication class.
check("a single bare <time> is trusted",
      pick_date('<time datetime="2026-07-06T06:01:00+01:00">06 July 2026</time>',
                today=TODAY), (2026, 7, 6))
check("several bare <time> tags are still refused",
      pick_date('<time datetime="2026-07-24"></time><time datetime="2026-07-06"></time>',
                today=TODAY), None)
# Janes puts a human-readable date in the datetime attribute.
check("human-format datetime attribute",
      pick_date('<time datetime="09 June 2026">x</time>', today=TODAY), (2026, 6, 9))
check("US-style month name", parse_iso_date("June 9, 2026"), (2026, 6, 9))
check("Swedish month name", parse_iso_date("1 december 2025"), (2025, 12, 1))

# A "last updated" stamp wearing a publication class must not be returned.
check("dateModified in a <time> with entry-date class is refused",
      pick_date('<time class="entry-date published" itemprop="dateModified" '
                'datetime="2026-08-30">Updated</time>', today=TODAY), None)

# Partial dates must stay partial -- no invented day.
check("month-only <time> stays month precision",
      pick_date('<time pubdate class="published" datetime="2026-07">x</time>',
                today=TODAY), (2026, 7, None))
check("year-only <time> stays year precision",
      pick_date('<time pubdate class="published" datetime="2026">x</time>',
                today=TODAY), (2026, None, None))

# dateCreated is the CMS node, not the article: never above datePublished.
check("datePublished beats an earlier-appearing dateCreated",
      pick_date('<script type="application/ld+json">{"dateCreated":"2024-12-18",'
                '"datePublished":"2024-05-22"}</script>', today=TODAY), (2024, 5, 22))
check("dateCreated alone is a last resort, not a refusal",
      pick_date('<script type="application/ld+json">{"dateCreated":"2024-12-18"}</script>',
                today=TODAY), (2024, 12, 18))

# Boeing: markup regenerated by a migration disagrees with the permalink.
check("URL cross-check overrides re-published markup",
      pick_date('<script type="application/ld+json">{"datePublished":"2025-10-16T14:37:13Z"}</script>',
                today=TODAY, url_ymd=(2024, 6, None)), (2024, 6, None))
check("agreeing markup keeps its finer precision",
      pick_date('<script type="application/ld+json">{"datePublished":"2024-06-05"}</script>',
                today=TODAY, url_ymd=(2024, 6, None)), (2024, 6, 5))

# parse_iso_date must not read an id or a range as a date.
check("no end anchor bug: 2023-01-234", parse_iso_date("2023-01-234"), None)

print()
print("all html-date checks passed" if not fails else "FAILED: %s" % ", ".join(fails))
sys.exit(1 if fails else 0)
