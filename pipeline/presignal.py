"""Cheap pre-signal score: will this page plausibly produce a signal card?

WHY THIS EXISTS
---------------
Layer A costs ~10 minutes of CPU per article (measured 2026-08-26: 805 s of a
911 s run, 99.6% of the pipeline). The card gate then refuses most of what it is
given -- "no client, competitor or defence term", "no provable date",
"off-portfolio". Every one of those refusals cost the full ten minutes to reach.

This module answers the same question from the RAW TEXT in about a millisecond,
using only string matching, so the expensive stage can be spent on pages that
might actually produce something. It is a PRE-filter, not a replacement: it is
deliberately generous, because a false negative here is a signal we never see,
and recall lost at the front of a pipeline is unrecoverable downstream.

WHAT IT SCORES ON
-----------------
Everything comes from reference_dataset.json -- the same file the card writer
uses -- so the vocabulary cannot drift away from the product:
    competitors   28 named rivals (COMPSYN / competitors / compOrder)
    portfolio      9 KSSL categories + 29 aliases (POS_CATS / CAT_ALIASES)
    partners      11 named partners (KSSL_PARTNERS)
plus a small closed list of event verbs and a date probe.

    from presignal import score
    s = score(title, text)
    s.total     0..100
    s.verdict   'high' | 'medium' | 'low' | 'skip'
    s.reasons   why, for the audit row

MULTILINGUAL, DELIBERATELY
--------------------------
The corpus spans 20+ languages. An English-only keyword list silently becomes a
LANGUAGE DETECTOR -- it has happened repeatedly on this project -- so the event
verbs carry their common European/Indian equivalents, and company and category
names (which are mostly proper nouns and travel unchanged) do the heavy lifting.
Any check added here MUST be tested per language, not on an English average.
"""
from __future__ import annotations

import json
import pathlib
import re
import unicodedata
from dataclasses import dataclass, field

HERE = pathlib.Path(__file__).resolve().parent
REF = HERE.parent / "reference_dataset.json"

from presignal_terms import term_ok

# The gate. `medium` and above reach Layer A; `low` and `skip` do not. Every
# saving figure quoted anywhere must be derived from THIS constant.
PASS_THRESHOLD = 45

# Words that are a company name in the dataset and an ordinary word in prose.
# A first-token shortcut ('Adani Defence' -> 'adani') is what makes the
# competitor list usable on real headlines; this is the list that stops the same
# shortcut from turning 'Solar Industries' into a solar-panel detector.
_AMBIGUOUS_TOKENS = {
    "solar", "force", "defence", "defense", "bharat", "indian", "india",
    "national", "global", "united", "premier", "advanced", "general",
    "industries", "systems", "limited", "group", "motors", "aerospace",
}


def _distinctive_tokens(name: str) -> set:
    """The one token a journalist would actually write. 'Adani Defence' -> adani,
    'Ashok Leyland' -> ashok; 'Solar Industries' -> nothing, on purpose."""
    tok = re.split(r"[^A-Za-z0-9&]+", (name or "").lower())
    return {t for t in tok[:1] if len(t) >= 4 and t not in _AMBIGUOUS_TOKENS}

# Event words that mark a thing HAPPENING rather than a description. Not English
# only -- see the module docstring. Kept small on purpose: this is a prior, not
# a classifier.
EVENT = [
    # english
    "wins", "won", "awards", "awarded", "contract", "order", "deal", "selects",
    "selected", "partnership", "joint venture", "mou", "delivers", "delivered",
    "signs", "signed", "launches", "unveils", "acquires", "acquisition",
    "tender", "procure", "procurement", "commissions", "inducted",
    # french / spanish / portuguese / italian
    "contrat", "marché", "commande", "contrato", "adjudicación", "pedido",
    "encomenda", "contratto", "appalto", "accordo",
    # german / dutch / nordic
    "auftrag", "vertrag", "beschaffung", "opdracht", "kontrakt", "avtale",
    # polish / czech / ukrainian / russian
    "kontrakt", "zamówienie", "zakázka", "контракт", "закупівля", "поставка",
    # hindi / indian english usage
    "अनुबंध", "आपूर्ति", "crore", "lakh",
    # chinese / japanese / korean -- WITHOUT these, looks_like_listing() has no
    # escape hatch in an unspaced script and condemns every CJK headline
    "合同", "签署", "采购", "中标", "交付", "订单",
    "契約", "受注", "調達", "納入", "締結",
    "계약", "수주", "조달", "납품", "체결",
    # arabic / turkish / greek
    "عقد", "توريد", "صفقة", "sözleşme", "ihale", "teslim",
    "σύμβαση", "προμήθεια",
]

# A number with a unit is what separates "we make artillery" from "an order for
# 155 guns worth $54 million".
MONEY = re.compile(
    r"(?:[$€£₹]\s?\d|\b\d[\d,.]*\s?(?:million|billion|crore|lakh|mln|mrd|"
    r"millones|millionen|miliardi|млн|млрд)\b|\bUSD\b|\bEUR\b|\bINR\b)", re.I)
QTY = re.compile(r"\b\d{1,5}\s?(?:units?|vehicles?|guns?|rounds?|systems?|"
                 r"aircraft|drones?|howitzers?|tanks?)\b", re.I)

_MON = ("jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
        "januar|februar|märz|mai|juni|juli|okt|dez|"
        "enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        "janvier|février|mars|avril|juin|juillet|août|décembre")
# Named months in the other scripts the corpus carries. WITHOUT these the -15
# "no parseable date" penalty fires on every correctly-dated Russian, Ukrainian,
# Greek or Turkish article -- a date probe that only reads Western European month
# names is a language detector wearing a different hat, and named dates are the
# house style in Russian news. Stems, because these languages inflect the month.
_MON_X = ("январ|феврал|март|апрел|мая|май|июн|июл|август|сентябр|октябр|ноябр|декабр|"
          "січн|лют|берез|квітн|травн|черв|липн|серпн|вересн|жовтн|листопад|грудн|"
          "ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık|"
          "ιανουαρ|φεβρουαρ|μαρτ|απριλ|μα[ΐι]|ιουν|ιουλ|αυγουστ|σεπτεμβρ|οκτωβρ|νοεμβρ|δεκεμβρ")
DATE = re.compile(rf"(?:\b(?:{_MON})[a-z]*\.?\s+\d{{1,2}},?\s+20\d\d"
                  rf"|\b\d{{1,2}}\s+(?:{_MON})[a-z]*\.?\s+20\d\d"
                  rf"|\b\d{{1,2}}\s+(?:{_MON_X})\w*\.?\s+20\d\d"
                  rf"|(?:{_MON_X})\w*\s+\d{{1,2}},?\s+20\d\d"
                  rf"|20\d\d\s*年\s*\d{{1,2}}\s*月\s*\d{{1,2}}\s*日"
                  rf"|20\d\d\s*년\s*\d{{1,2}}\s*월\s*\d{{1,2}}\s*일"
                  rf"|\b20\d\d-\d{{2}}-\d{{2}}\b"
                  rf"|\b\d{{1,2}}[./]\d{{1,2}}[./]20\d\d\b)", re.I | re.U)


# A listing/index/tag page is the worst kind of false positive: it is DENSER in
# defence vocabulary than any real article (it is a list of headlines), so pure
# keyword scoring ranks it top. Found by scoring 400 real corpus pages -- five of
# the top eight were section pages like "Golden Dome Archives | Page 3 of 3".
# The card gate refuses these downstream anyway ("listing pages"), so paying ten
# minutes of Layer A to reach that refusal is pure waste.
LISTING_TITLE = re.compile(
    r"(\barchives?\b|\bpage\s+\d+\s+of\s+\d+|\bcategory\b|\btag\b|"
    r"\bdaily digest\b|\bnewsletter\b|\bsubscribe\b|\bhome\s*\||"
    r"\ball (?:news|articles|posts)\b|\blatest news\b|\bnews index\b)", re.I)
LISTING_URL = re.compile(
    r"/(?:category|categories|tag|tags|topic|topics|archive|archives|author|"
    r"page)/|[?&]paged?=\d", re.I)


def listing_kind(title: str, url: str = "", body: str = "") -> str:
    """'' | 'soft' | 'hard'.

    HARD means the page states what it is: "Page 3 of 9", "Archives",
    /category/x/page/2/. That is not a weak article, it is not an article, and
    no amount of defence vocabulary changes that -- a -45 penalty left a
    /category/missiles/page/2/ index carrying two competitors and a money figure
    at 55, above the gate, which is precisely the page the rule was written to
    stop. SOFT means it merely reads like an index (a short verbless head, a
    wall of link-length lines); that stays a penalty, because it can be wrong.

    Deliberately conservative -- a wrongly-skipped article is a signal we never
    see."""
    if LISTING_TITLE.search(title or ""):
        return "hard"
    if LISTING_URL.search(url or ""):
        return "hard"
    # A section, topic or author page is usually "<short noun phrase> | <site>"
    # with no verb -- "Supply Chain | Aviation Week", "F-22 Raptor - Defence
    # Industry Europe", "Steve Trimble | Aviation Week". A real headline states
    # something happening and is longer. Found the same way as the rule above:
    # by looking at what still scored 100 after the first pass.
    # space before the separator is optional: "Europe and NATO| Defense News"
    head = re.split(r"\s*[|–—]\s+|\s+-\s+", (title or "").strip())[0].strip()
    words = [w for w in head.split() if w]
    # ...but ONLY in a script that puts spaces between words. Chinese, Japanese
    # and Korean write scriptio continua, so head.split() always returns one
    # "word" and this rule condemned EVERY CJK headline as a listing page -- a
    # dated, priced Chinese missile-contract story scored 0/skip. Word count is
    # not a measure of length in an unspaced script.
    if (0 < len(words) <= 3 and not _is_scriptio_continua(head)
            and not _found(_fold(head), {_fold(e) for e in EVENT})):
        return "soft"

    # a wall of short lines with no prose is a list of links, not an article
    lines = [l.strip() for l in (body or "")[:1500].splitlines() if l.strip()]
    if len(lines) >= 12 and sum(len(l) < 60 for l in lines) / len(lines) > 0.85:
        return "soft"
    return ""


def looks_like_listing(title: str, url: str = "", body: str = "") -> bool:
    return bool(listing_kind(title, url, body))


def _fold(s: str) -> str:
    """Lowercase + strip accents so 'Rafaël' matches 'rafael'. Length is NOT
    preserved and must not be relied on for offsets -- this is for matching only."""
    s = unicodedata.normalize("NFKD", s or "").lower()
    return "".join(c for c in s if not unicodedata.combining(c))


def _load():
    d = json.loads(REF.read_text(encoding="utf-8"))
    # The competitor DICT is keyed by short codes -- 'MIL', 'PEL', 'ZEN', 'SOLAR'.
    # Matching those as text would fire inside ordinary words in every language,
    # so take the human NAME and keep a code only when it is long enough to be
    # unambiguous. Same class of bug as the Greek short-substring collision.
    comps = set()
    for code, rec in (d.get("competitors") or {}).items():
        if isinstance(rec, dict):
            name = rec.get("name") or ""
            comps.add(name)
            comps |= _distinctive_tokens(name)
    # COMPSYN is keyed by the same short codes and its values are prose, not
    # synonyms -- there is nothing safe to match in it, so it is not a source of
    # needles. The codes themselves are NEVER matched as text: 'SOLAR' and
    # 'FORCE' are ordinary English words, and matching them scored
    # "Air Force awards Anduril drone contract" as a competitor story at 100/high
    # and a solar-farm press release at 60/medium. A length threshold does not
    # make a word unambiguous -- only a dictionary does.
    partners = set()
    for p in d.get("KSSL_PARTNERS") or []:
        if isinstance(p, str):
            partners.add(p)
        elif isinstance(p, dict):
            lab = p.get("label") or p.get("name") or ""
            # 'Rafael Advanced Defense Systems (KRAS JV)' -> 'rafael advanced defense systems'
            lab = re.sub(r"\s*\(.*?\)\s*", " ", lab).strip()
            partners.add(lab)
            # ...and 'rafael', because no journalist writes the full legal name.
            partners |= _distinctive_tokens(lab)
    cats = set()
    for pair in d.get("POS_CATS") or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            cats.add(pair[1])
    for k, v in (d.get("CAT_ALIASES") or {}).items():
        cats.add(k)
        if isinstance(v, str):
            cats.add(v)
        elif isinstance(v, list):
            cats |= {x for x in v if isinstance(x, str)}
    client = d.get("client") or {}
    client_names = {client.get("name", ""), client.get("short", ""), "kalyani"}

    def clean(xs, minlen=3):
        out = set()
        for x in xs:
            x = _fold(x).strip()
            # A minimum length is a LATIN rule -- see term_ok. Applying it flat
            # deleted every 2-3 character Chinese and Korean term on the way in,
            # after presignal_terms had gone to the trouble of collecting them.
            if x and not x.isdigit() and term_ok(x, minlen):
                out.add(x)
        return out

    # The reference dataset's category names are English only. Measured per
    # language on live corpus pages, that made the whole score a language
    # detector: 40% portfolio hits on English, 0% on Russian and Hindi. The
    # terms module carries the same nine categories in the scripts the corpus
    # actually contains.
    from presignal_terms import ALL_TERMS
    cats |= set(ALL_TERMS)

    return (clean(comps, 4), clean(partners, 4), clean(cats, 4),
            clean(client_names, 4))


COMPETITORS, PARTNERS, CATEGORIES, CLIENT = _load()


@dataclass
class Score:
    total: int = 0
    verdict: str = "skip"
    reasons: list = field(default_factory=list)
    hits: dict = field(default_factory=dict)


def _is_scriptio_continua(s: str) -> bool:
    """Chinese, Japanese and Korean write without spaces. A word-boundary test
    is meaningless there -- and worse, it REJECTS every correct match, because
    the neighbouring CJK characters are alphanumeric. Measured: Chinese
    portfolio hits stayed at 8% while every spaced language improved."""
    return any("぀" <= c <= "ヿ" or "㐀" <= c <= "鿿"
               or "가" <= c <= "힯" for c in s)


# Half the vocabulary in presignal_terms is a STEM, on purpose -- Russian
# "артиллер" is meant to cover артиллерия / артиллерии / артиллерийский, Polish
# "modernizacj" to cover modernizacja. A both-sides word boundary makes every one
# of those stems unmatchable: the inflection that follows is alphanumeric, so the
# match is thrown away and the language scores zero. But relaxing the suffix for
# EVERY needle would let "mou" fire inside "mount". So the suffix may continue
# only where the needle is long enough that an accidental extension is
# implausible -- and non-Latin scripts, which is where the stems are, qualify
# sooner because they do not share a word-stock with English prose.
_STEM_MIN_LATIN = 6
_STEM_MIN_OTHER = 4


def _is_stem(n: str) -> bool:
    from presignal_terms import _script_class
    return len(n) >= (_STEM_MIN_LATIN if _script_class(n) == "latin" else _STEM_MIN_OTHER)


def _found(hay: str, needles) -> list:
    # word-ish boundary so "saab" does not fire inside "saabs-something", but
    # multi-word names still match verbatim
    out = []
    for n in needles:
        i = hay.find(n)
        if i < 0:
            continue
        if _is_scriptio_continua(n):
            out.append(n)          # no boundaries to test in an unspaced script
            continue
        before = hay[i - 1] if i else " "
        after = hay[i + len(n)] if i + len(n) < len(hay) else " "
        if before.isalnum():
            continue               # not a word start -- 'mou' inside 'amount'
        if after.isalnum() and not _is_stem(n):
            continue               # short needle, and the word carries on
        out.append(n)
    return out


def score(title: str, text: str, url: str = "", max_chars: int = 6000,
          published_at: str | None = None) -> Score:
    """Cheap prior on whether this page can yield a card. Reads only the first
    max_chars: a news lede carries the who/what/when, and scanning a whole
    100 kB page for a prior costs more than the prior is worth.

    Pass `published_at` when scoring a page the crawler has already stored. The
    date probe below is a fallback for raw text, not a second opinion: measured
    on 1,250 trade-press pages, 79% had "no parseable date" -- and 62% of THOSE
    carried a published_at in the corpus. The -15 was scoring the regex, not the
    article, and the article's date was sitting in the next column."""
    hay = _fold((title or "") + " \n " + (text or "")[:max_chars])
    s = Score()

    comp = _found(hay, COMPETITORS)
    cats = _found(hay, CATEGORIES)
    part = _found(hay, PARTNERS)
    client = _found(hay, CLIENT)
    # _found, not a bare substring test: 'mou' otherwise fires inside 'amount'
    # and 'order' inside 'recorder'. Verified in demo().
    events = _found(hay, {_fold(e) for e in EVENT})

    if comp:
        s.total += 40
        s.reasons.append(f"competitor: {', '.join(sorted(comp)[:3])}")
    if cats:
        s.total += 25
        s.reasons.append(f"portfolio: {', '.join(sorted(cats)[:3])}")
    if part:
        s.total += 15
        s.reasons.append(f"partner: {', '.join(sorted(part)[:2])}")
    if events:
        s.total += 15
        s.reasons.append(f"event word: {', '.join(sorted(events)[:3])}")
    # the same window as every other signal -- a currency string 90 kB deep in a
    # footer is not evidence about the lede
    window = (text or "")[:max_chars]
    if MONEY.search(window) or QTY.search(window):
        s.total += 10
        s.reasons.append("carries a value or quantity")

    # The recency gate downstream REFUSES anything that cannot prove its own
    # date, so a page with no date is not merely weaker -- it is unusable, and
    # the ten minutes would be spent to learn nothing.
    if published_at:
        s.total += 10
        s.reasons.append("has a stored publication date")
    elif DATE.search((title or "") + " " + (text or "")[:max_chars]):
        s.total += 10
        s.reasons.append("has a parseable date")
    else:
        s.total -= 15
        s.reasons.append("NO parseable date (card gate will refuse)")

    # The client's own announcements are not competitive intelligence -- half a
    # tech feed once turned out to be KSSL's own launches.
    if client and not comp:
        s.total -= 20
        s.reasons.append("client's own news, no competitor named")

    kind = listing_kind(title, url, text)
    if kind == "hard":
        s.total = 0
        s.reasons.append("index page (title or URL says so) - never an article")
    elif kind == "soft":
        s.total -= 45
        s.reasons.append("looks like a listing/index page")

    s.total = max(0, min(100, s.total))
    s.hits = {"competitors": comp, "categories": cats, "partners": part,
              "events": events[:5], "client": client}
    s.verdict = ("high" if s.total >= 65 else "medium" if s.total >= 45
                 else "low" if s.total >= 25 else "skip")
    return s


def passes(s: Score) -> bool:
    """Does this page reach Layer A?

    THE THRESHOLD LIVES HERE AND NOWHERE ELSE. The first version of this module
    defined verdict BANDS and never said which band was the gate, so every
    downstream number -- "18% pass", "55 CPU-hours saved", the scheduler's
    `yield_` ("fraction clearing the pre-signal bar") -- was quoting a bar that
    did not exist. A filter without a stated cut-off is not a filter."""
    return s.total >= PASS_THRESHOLD


def demo():
    """Runnable check: the ordering must hold, or the prior is not a prior."""
    card = score(
        "GDLS wins $54 million Stryker sustainment award",
        "General Dynamics Land Systems was awarded a $54 million contract on "
        "Jul 14, 2026 for Stryker armoured vehicle sustainment work.")
    nodate = score(
        "Leonardo wins Army contract to upgrade self-propelled howitzers",
        "Leonardo will upgrade self-propelled howitzer weapon systems under a "
        "new artillery contract.")
    junk = score(
        "Wywlaszcza rosyjskiego biznesmena",
        "A Russian businessman owns a property near a Swedish base.")
    for label, s in (("card-worthy", card), ("no date", nodate), ("junk", junk)):
        print(f"  {label:12s} {s.total:3d}  {s.verdict:7s}  {'; '.join(s.reasons)}")

    assert card.total > junk.total, "a contract award must outrank a property story"
    assert card.verdict in ("high", "medium"), card
    assert junk.verdict in ("skip", "low"), junk
    assert "NO parseable date" in " ".join(nodate.reasons), nodate
    assert nodate.total < card.total, "an undated article must rank below a dated one"

    # regression: a stem must match its own inflections, or every stemmed
    # language scores zero while the unit test stays green
    infl = score("Поставка артиллерийских систем",
                 "Контракт на поставку артиллерийских систем подписан 26 августа 2026 года.")
    assert infl.hits["categories"], f"a stem did not match its inflected form: {infl.hits}"

    # regression: short event words must not match inside longer words
    bogus = score("Quarterly report", "The total amount recorded was steady in 2026-01-05.")
    assert "mou" not in str(bogus.hits["events"]), f"'mou' matched inside 'amount': {bogus.hits}"
    assert "order" not in str(bogus.hits["events"]), f"'order' matched inside 'recorded': {bogus.hits}"

    # regression: competitor CODES must not fire as substrings
    cod = score("Milk prices", "The mil spec and pel factory zen garden amounted to little.")
    assert not cod.hits["competitors"], f"short code matched as substring: {cod.hits}"

    # regression: a keyword-dense LISTING page must not outrank a real article
    listing = score("Golden Dome Archives | Page 3 of 3 | DefenseScoop",
                    "Missile defence contract award artillery drones on Jul 1, 2026")
    assert listing.total < card.total, f"listing outranked an article: {listing}"
    assert "index page" in " ".join(listing.reasons), listing
    # regression: a competitor CODE that is also an ordinary English word must
    # never fire. 'FORCE' (Force Motors) and 'SOLAR' (Solar Industries) scored
    # an Air Force story at 100/high and a solar farm at 60/medium.
    af = score("Air Force awards Anduril drone contract",
               "The US Air Force awarded a $30 million drone contract on Jul 2, 2026.")
    assert not af.hits["competitors"], f"'force' matched as a competitor: {af.hits}"
    sf = score("Solar panel farm opens in Gujarat",
               "A 200 MW solar farm was commissioned on Jul 2, 2026.")
    assert not sf.hits["competitors"], f"'solar' matched as a competitor: {sf.hits}"

    # ...while the real competitor, and the token a journalist actually writes,
    # both still fire
    zen = score("Zen Technologies secures 295 crore MoD order",
                "Zen Technologies won a simulator order on Jul 2, 2026.")
    assert zen.hits["competitors"], f"a named competitor stopped matching: {zen.hits}"
    adani = score("Adani wins artillery ammunition order",
                  "Adani was awarded an ammunition contract on Jul 2, 2026.")
    assert adani.hits["competitors"], f"first-token competitor lost: {adani.hits}"

    # regression, per language -- an average hides exactly this
    zh = score("中国北方工业签署导弹合同",
               "该公司于2026年8月26日签署了一份价值54亿元的导弹采购合同。")
    assert zh.hits["categories"], f"zero Chinese portfolio vocabulary: {zh.hits}"
    assert "NO parseable date" not in " ".join(zh.reasons), f"CJK date unparsed: {zh.reasons}"
    assert "listing" not in " ".join(zh.reasons), f"CJK headline called a listing: {zh.reasons}"
    assert passes(zh), f"a dated Chinese contract story does not reach Layer A: {zh}"

    ru = score("Рособоронэкспорт подписал контракт на поставку артиллерии",
               "Контракт подписан 26 августа 2026 года на поставку артиллерийских систем.")
    assert "NO parseable date" not in " ".join(ru.reasons), f"Russian date unparsed: {ru.reasons}"
    assert ru.hits["categories"], f"zero Russian portfolio vocabulary: {ru.hits}"

    ko = score("한화 미사일 계약 체결",
               "한화는 2026년 8월 26일 미사일 조달 계약을 체결했다.")
    assert ko.hits["categories"], f"zero Korean portfolio vocabulary: {ko.hits}"

    # the listing penalty must survive a listing that carries the very signals
    # it is competing with -- that is the case it was built for
    rich_listing = score(
        "Missiles Archives | Page 2 of 9 | DefenseScoop",
        "Zen Technologies wins $54 million artillery contract Jul 1, 2026 "
        "Adani drone order Jul 2, 2026 ammunition tender Jul 3, 2026",
        url="https://defensescoop.com/category/missiles/page/2/")
    assert not passes(rich_listing), f"a keyword-dense listing reached Layer A: {rich_listing}"

    # a stored publication date must be believed over the text probe
    stored = score("Rheinmetall wins ammunition order",
                   "Rheinmetall will supply artillery ammunition under a new contract.",
                   published_at="2026-07-14T00:00:00Z")
    assert "stored publication date" in " ".join(stored.reasons), stored
    assert "NO parseable date" not in " ".join(stored.reasons), stored

    # the gate itself
    assert passes(card) and not passes(junk), "PASS_THRESHOLD does not separate the demo cases"

    print(f"  vocabulary: {len(COMPETITORS)} competitors, {len(CATEGORIES)} category terms, "
          f"{len(PARTNERS)} partners; gate at {PASS_THRESHOLD}")
    print("ok - ordering holds, and holds per language")


if __name__ == "__main__":
    demo()
