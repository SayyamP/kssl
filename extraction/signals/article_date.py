"""Read an article's publication date out of its own HTML.

The corpus stores `documents.published_at`, but the crawler falls back to the
FETCH time when a page declares no date -- so a 2017 story arrives stamped with
the day we happened to crawl it. Measured over the documents behind the live
cards: 72 carried the fetch date, and where the URL also stated a date, 63 of 63
disagreed, 62 of them claiming the story was newer than it is.

Patching that per-site (a URL pattern for asdnews, another for analisidifesa)
does not scale and silently rots. The publisher already states the date in the
markup, in a handful of standards every CMS emits, and that is what this reads:

    article:published_time      OpenGraph / WordPress / Yoast
    JSON-LD  datePublished      schema.org NewsArticle -- near-universal
    <time datetime=... pubdate> HTML5
    dcterms.date, DC.date       Dublin Core, common on institutional sites
    <meta name="date">          the plain fallback

Pure and offline: no network, no HTML parser dependency, stdlib only, so it is
unit-testable against saved pages and needs no new package in the extraction
image. `pick_date` returns (y, m|None, d|None) or None.

WHAT IT REFUSES
A modified/updated timestamp is not a publication date (a 2017 article re-saved
last week would read as current), so `article:modified_time` and `dateModified`
are read only to be ignored. A date in the future cannot be a publication date.
Returning None is a real answer -- undated is honest, wrongly dated is not.
"""
import html as html_mod
import re

__all__ = ["pick_date", "date_candidates", "parse_iso_date"]

# Anything with a year outside this band is a typo, a copyright line, or a
# forecast -- not a publication date for a corpus crawled in the 2020s.
_MIN_YEAR = 1990


_MONTH_WORDS = {}
for _i, _names in enumerate((
        ("jan", "january", "januari", "januar", "janvier", "enero", "gennaio"),
        ("feb", "february", "februari", "februar", "fevrier", "febrero", "febbraio"),
        ("mar", "march", "maart", "marz", "mars", "marzo"),
        ("apr", "april", "avril", "abril", "aprile"),
        ("may", "mai", "mei", "mayo", "maggio"),
        ("jun", "june", "juni", "juin", "junio", "giugno"),
        ("jul", "july", "juli", "juillet", "julio", "luglio"),
        ("aug", "august", "augustus", "aout", "agosto"),
        ("sep", "sept", "september", "septembre", "septiembre", "settembre"),
        ("oct", "october", "oktober", "octobre", "octubre", "ottobre"),
        ("nov", "november", "novembre", "noviembre"),
        ("dec", "december", "dezember", "decembre", "diciembre", "dicembre")), 1):
    for _n in _names:
        _MONTH_WORDS[_n] = _i


def _month_word(w):
    return _MONTH_WORDS.get((w or "").strip(".,").lower())


def parse_iso_date(s):
    """'2023-01-26T09:14:02+01:00' -> (2023, 1, 26). Also 2023-01, 2023.

    Deliberately narrow: this reads MACHINE-WRITTEN metadata, where the format
    is ISO-8601 or a close relative. Prose dates are the body-span parser's job.
    """
    if not s:
        return None
    s = html_mod.unescape(str(s).strip())
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y >= _MIN_YEAR and 1 <= mo <= 12 and 1 <= d <= 31:
            return y, mo, d
        return None
    # "09 June 2026" / "1 december 2025" -- Janes and Saab put a human-readable
    # date in the datetime attribute and in itemprop content. Twenty-one Janes
    # documents and every Saab press release resolved to nothing without this.
    m = re.match(r"^(\d{1,2})\s+([A-Za-zÀ-ɏ]{3,12})\.?,?\s+(\d{4})$", s)
    if m:
        mo = _month_word(m.group(2))
        y, d = int(m.group(3)), int(m.group(1))
        if mo and y >= _MIN_YEAR and 1 <= d <= 31:
            return y, mo, d
        return None
    m = re.match(r"^([A-Za-z]{3,12})\.?\s+(\d{1,2}),?\s+(\d{4})$", s)   # June 9, 2026
    if m:
        mo = _month_word(m.group(1))
        y, d = int(m.group(3)), int(m.group(2))
        if mo and y >= _MIN_YEAR and 1 <= d <= 31:
            return y, mo, d
        return None
    # Some CMSs emit d/m/Y or m/d/Y in a meta tag, often with a clock after it
    # (Kongsberg: "7/8/2026 1:30:04 PM"). Ambiguous by nature: take the month
    # only when the two readings agree, rather than guessing a day.
    m = re.match(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?:\s|$)", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y >= _MIN_YEAR:
            if a > 12 and 1 <= b <= 12:
                return y, b, a                      # unambiguously d/m/Y
            if b > 12 and 1 <= a <= 12:
                return y, a, b                      # unambiguously m/d/Y
            if a == b and 1 <= a <= 12:
                return y, a, a                      # same either way
            if 1 <= b <= 12:
                return y, b, None                   # ambiguous: keep the month only
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})$", s)
    if m and int(m.group(1)) >= _MIN_YEAR and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)), int(m.group(2)), None
    m = re.match(r"^(\d{4})$", s)
    if m and int(m.group(1)) >= _MIN_YEAR:
        return int(m.group(1)), None, None
    return None


def _meta_patterns(keys):
    """<meta> with the key on property/name/itemprop, either attribute order."""
    alt = "|".join(re.escape(k) for k in keys)
    key = r"""(?:"(?:%s)"|'(?:%s)'|(?:%s)(?=[\s/>]))""" % (alt, alt, alt)
    return (
        r"""<meta[^>]*?\b(?:property|name|itemprop)\s*=\s*""" + key +
        r"""[^>]*?\bcontent\s*=\s*["']([^"']+)["']""",
        r"""<meta[^>]*?\bcontent\s*=\s*["']([^"']+)["'][^>]*?"""
        r"""\b(?:property|name|itemprop)\s*=\s*""" + key,
    )


# Ordered best-first. Each is a publisher's own machine-readable statement of
# when the article was published; the earlier ones are the most specific.
_PUBLISHED_KEYS = (
    ("article:published_time", "og:article:published_time"),
    ("article:published", "published_time", "datePublished", "date_published"),
    ("dcterms.date", "dc.date.issued", "dcterms.issued", "DC.date.issued", "DC.date"),
    ("citation_publication_date", "citation_date", "sailthru.date", "parsely-pub-date"),
    ("pubdate", "publish-date", "publication_date", "publishdate", "date", "created"),
)

# Read only so they can be rejected: an article re-saved yesterday is not news
# from yesterday. Nothing in this module ever returns one.
_MODIFIED_KEYS = ("article:modified_time", "dateModified", "og:updated_time",
                  "lastmod", "modified", "updated_time")

# JSON-LD. datePublished is the schema.org field; matched directly rather than
# by parsing the block, because news pages ship several JSON-LD islands and some
# of them are invalid JSON.
_LD_PUBLISHED = re.compile(r'"datePublished"\s*:\s*"([^"]{4,40})"', re.I)

# `dateCreated` is the CMS node's creation, not the article's publication, and
# the two diverge: pilatus-aircraft.com carries dateCreated 2024-12-18 beside
# datePublished 2024-05-22 for a story published in May. Kept as a LAST resort
# rather than an equal alternative, so it can never outrank datePublished by
# happening to appear earlier in the byte stream.
_LD_CREATED = re.compile(r'"dateCreated"\s*:\s*"([^"]{4,40})"', re.I)

# HTML5 <time datetime="..."> -- preferred when it carries a pubdate marker or
# a publication-ish class, since a bare <time> may be any date in the page.
_TIME_PUBDATE = re.compile(
    r"""<time[^>]*?\bdatetime\s*=\s*["']([^"']+)["'][^>]*?>""", re.I)

# `itemprop="datePublished"` on any element, with the machine value in a
# `content` or `datetime` attribute (either attribute order).
_ITEMPROP_PUB = re.compile(
    r"""<[a-z]+[^>]*?\bitemprop\s*=\s*["']datePublished["'][^>]*?"""
    r"""\b(?:content|datetime)\s*=\s*["']([^"']+)["']"""
    r"""|<[a-z]+[^>]*?\b(?:content|datetime)\s*=\s*["']([^"']+)["'][^>]*?"""
    r"""\bitemprop\s*=\s*["']datePublished["']""", re.I)
_TIME_IS_PUB = re.compile(
    r"pubdate|published|entry-date|post-date|article[-_]?date", re.I)

# A clock, not a byline: `<time id="current-date">` prints today's date in the
# navbar. This is the tag the crawler scraped, which is why documents.published_at
# so often equals the fetch date exactly.
_TIME_IS_CLOCK = re.compile(
    r"current[-_]?date|today|now[-_]?date|clock|navbar", re.I)

# An "updated" stamp can wear a publication-ish class, so the modified marker
# has to be checked explicitly rather than assumed absent.
_TIME_IS_MODIFIED = re.compile(
    r"dateModified|modified[-_]?(?:date|time)|date[-_]?modified"
    r"|updated[-_]?(?:date|time|on)|last[-_]?updated|revised", re.I)


def date_candidates(html, url="", debug=False):
    """Every publication date the markup states, best source first.

    TWO TIERS, and the difference is what makes this trustworthy.

    Tier 1 -- SELF-DESCRIBING metadata: `article:published_time`, JSON-LD
    `datePublished`, Dublin Core. These appear once per page and describe THE
    PAGE. If one is present it is the answer.

    Tier 2 -- a `<time>` element marked as a publication date, but ONLY when the
    page states exactly one. A `<time pubdate>` is per-item markup, so on any
    page that also lists other articles it appears once per listed item: an
    analisidifesa.it story from January 2023 carries NINE of them, all from the
    sidebar's recent-posts widget, and the first in document order is the newest
    sidebar entry. Taking it dated a 2023 article "29 Jul 2026". So more than
    one distinct date here means the page cannot tell us which is its own, and
    this tier yields nothing rather than guessing.

    Exposed separately from `pick_date` so an audit can see what was on offer
    and which source won.
    """
    if not html:
        return []
    # Publication metadata lives in <head> and the article header. Capping the
    # scan keeps a 2 MB page cheap and keeps comment timestamps and
    # related-story datelines out of the candidate list.
    head = html[:250000]

    out = []
    seen = set()

    def add(raw, source):
        ymd = parse_iso_date(raw)
        if ymd and ymd not in seen:
            seen.add(ymd)
            out.append((ymd, source) if debug else ymd)

    # --- tier 1 -----------------------------------------------------------
    for group in _PUBLISHED_KEYS:
        for pat in _meta_patterns(group):
            for m in re.finditer(pat, head, re.I | re.S):
                add(m.group(1), "meta:%s" % group[0])

    for m in _LD_PUBLISHED.finditer(head):
        add(m.group(1), "json-ld:datePublished")

    # Microdata on an ordinary element, not a <meta>. Saab puts the date on a
    # <span class="date" content="2025-12-01T09:00" itemprop="datePublished">
    # and Kongsberg on a <p itemprop="datePublished" content="7/8/2026 ...">.
    # Both are unambiguous statements about the page, so they belong in tier 1 --
    # every Saab press release resolved to nothing without this.
    for m in _ITEMPROP_PUB.finditer(head):
        add(m.group(1) or m.group(2), "itemprop:datePublished")

    if out:
        return out

    # --- tier 2 -----------------------------------------------------------
    times = []
    for m in _TIME_PUBDATE.finditer(head):
        tag = m.group(0)
        # `<time id="current-date">` is a navbar clock printing today. asdnews
        # ships one on every page, and it is exactly what the crawler scraped
        # into published_at -- which is why published_at kept equalling the
        # fetch date. Never a publication date.
        if _TIME_IS_CLOCK.search(tag):
            continue
        # A "last updated" stamp often wears a publication-ish class
        # (`class="entry-date"` with `itemprop="dateModified"`), so the class
        # alone is not enough: an explicit modified marker disqualifies the tag
        # however it is dressed.
        if _TIME_IS_MODIFIED.search(tag):
            continue
        if not _TIME_IS_PUB.search(tag):
            continue
        ymd = parse_iso_date(m.group(1))
        if ymd:
            times.append(ymd)

    # Partial tuples stay partial. Re-serialising (y, m, None) as "y-m-01" and
    # re-parsing it invented a day: `datetime="2026-07"` rendered as "1 Jul
    # 2026", and `datetime="2026"` became 1 January -- which then failed the
    # 92-day window and silently dropped a possibly-current article, defeating
    # is_recent_ym's deliberate year-only concession.
    distinct = set(times)
    if len(distinct) == 1:
        ymd = times[0]
        if ymd not in seen:
            seen.add(ymd)
            out.append((ymd, "time[pubdate]") if debug else ymd)
        return out

    # --- tier 3: a single bare <time> on the whole page --------------------
    # Thales and Janes mark the date with a plain `<time datetime=...>` and no
    # publication class. One such tag on the page is as unambiguous as a marked
    # one; several are a listing, and are refused for the same reason as tier 2.
    bare = []
    for m in _TIME_PUBDATE.finditer(head):
        tag = m.group(0)
        if _TIME_IS_CLOCK.search(tag) or _TIME_IS_MODIFIED.search(tag):
            continue
        ymd = parse_iso_date(m.group(1))
        if ymd:
            bare.append(ymd)
    if len(set(bare)) == 1 and bare[0] not in seen:
        seen.add(bare[0])
        out.append((bare[0], "time[single]") if debug else bare[0])
        return out

    # --- last resort ------------------------------------------------------
    for m in _LD_CREATED.finditer(head):
        add(m.group(1), "json-ld:dateCreated")
    return out


def pick_date(html, url="", today=None, url_ymd=None):
    """The article's publication date as (y, m|None, d|None), or None.

    A date in the future is skipped, not returned: '2027 delivery' in a metadata
    field is a forecast or a broken clock, never a publication date.

    `url_ymd`, when given, is the date the URL states, and it is used as a
    CROSS-CHECK rather than a fallback. Markup is not automatically right:
    boeing.com's JSON-LD says datePublished 2025-10-16 for a story whose
    permalink is /mission-updates/2024/06/ and whose subject is a June 2024
    mission -- a site migration regenerated the metadata sixteen months late.
    When the two disagree on year-and-month, the permalink wins: it is the one
    a CMS cannot silently rewrite without breaking its own links.
    """
    if today is None:
        import datetime
        t = datetime.date.today()
        today = (t.year, t.month, t.day)
    for ymd in date_candidates(html, url):
        if (ymd[0], ymd[1] or 1, ymd[2] or 1) > today:
            continue
        if url_ymd and (ymd[0], ymd[1]) != (url_ymd[0], url_ymd[1]):
            return url_ymd
        return ymd
    return None
