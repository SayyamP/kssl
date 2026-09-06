"""Turn extracted documents into serving rows -- the local LLM step.

    python serving_fill.py                  # process every unprocessed document
    python serving_fill.py --limit 5
    python serving_fill.py --demo

For each document in `extracted`, the card model reads the document's own PROPOSITIONS (never the raw
page -- the propositions carry evidence quotes with offsets) and decides whether it contains a
competitive signal worth showing a KSSL analyst. If yes, it emits one card; if no, it says NONE
and the refusal is counted. Cards land in serving.signal_card / serving.signal_detail with
origin='pipeline', appended after the reference rows.

WHAT KEEPS THIS HONEST
----------------------
  * The model only ever sees propositions the extractor grounded with quotes, and every card's
    detail carries those quotes verbatim in its lens rows. A reader can always get from a card
    to the sentences behind it.
  * A document with no propositions is skipped, not summarised from raw text.
  * The model's output is validated field by field; a malformed reply is a counted failure,
    never a half-written row.
  * Idempotent: cards are keyed pl_<document_id>, so re-running replaces rather than duplicates.
"""
import argparse
import html as _html
import json
import os
import re
import stage_timer
import roster
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from aliases import (  # noqa: E402  (shared identity layer)
    canonical as canon_name, client_led, fold as fold_name, is_client, is_force, is_one_org,
)
from llmapi import client as llm_client  # noqa: E402  (every model call goes through the API)
import corpus  # noqa: E402  (the article's stored markup, one fetch per card)
from article_date import pick_date as pick_html_date  # noqa: E402
from article_image import resolve_image  # noqa: E402
import glance  # noqa: E402  ("At a glance" rows from typed spans, each with its quote)
import translate  # noqa: E402  (source-language lead-ins -> English; never the quote)

DSN = os.environ.get("KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
# NOT used by this module any more -- every model call here goes through the LLM API.
# It survives for bench_models.py, which reads `sf.OLLAMA` and must dial a model server
# DIRECTLY: it exists to compare models on one endpoint, and a benchmark that silently
# failed over to a second node would be measuring the router instead of the model.
OLLAMA = os.environ.get("KSSL_OLLAMA", "http://127.0.0.1:11434")
# The card step reads PROPOSITIONS, not raw text -- the hard reading was already done
# by Layer A, and what is left is a short judgement plus ~100 tokens of output. The 14b
# was doing that job at roughly twice the cost per token for a task the 7b does on the
# same evidence. Override with KSSL_MODEL if a card ever needs the bigger model.
MODEL = os.environ.get("KSSL_MODEL", "qwen2.5:7b")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# The nine product categories come from the reference dataset; the model must file the signal
# into one of them or refuse, because a free-text category joins nothing downstream.
def kssl_cats():
    ref = json.loads((HERE.parent / "reference_dataset.json").read_text(encoding="utf-8"))
    return ref["KSSL_CATS"]


_COUNTRIES = None


def country_names():
    """Folded country names from the reference dataset. A bare country is not a
    company: the prompt says 'not just the country', but a prompt is not a gate --
    'Thailand', 'Australia' and 'India' all reached signal_card.company."""
    global _COUNTRIES
    if _COUNTRIES is None:
        ref = json.loads((HERE.parent / "reference_dataset.json").read_text(encoding="utf-8"))
        names = set(ref.get("geoCountries", [])) | set(ref.get("tpAllCountries", []))
        for comp in ref.get("geoData", {}).values():
            names |= set(comp.keys())
        names |= {"United States", "USA", "US", "U.S.", "United Kingdom", "UK",
                  "Britain", "Thailand", "Australia", "New Zealand", "Japan",
                  "South Korea", "Norway", "Sweden", "Finland", "Denmark", "Estonia",
                  "Latvia", "Lithuania", "Netherlands", "Belgium", "Portugal", "Spain",
                  "Greece", "Turkey", "Ukraine", "Russia", "Vietnam", "Indonesia",
                  "Singapore", "Malaysia", "Bangladesh", "Nepal", "Qatar", "Kuwait",
                  "Oman", "Nigeria", "Ghana", "Zambia", "Mozambique", "Canada",
                  "Mexico", "Chile", "Peru", "Colombia", "Hungary", "Romania"}
        # AND THE ENGINE'S LIST, because this one is built from whatever the reference
        # dataset happens to mention. It had 67 names and no Kazakhstan, which is how
        # "Paramount Group <-> Kazakhstan" was stored as a strategic PARTNERSHIP --
        # the country is the market, never the partner. lexicon.COUNTRIES is the
        # extraction engine's own 81-name list; merging beats growing a third one.
        try:
            import importlib.util as _il
            _lp = HERE.parent / "engine" / "lexicon.py"
            _sp = _il.spec_from_file_location("engine_lexicon", str(_lp))
            _m = _il.module_from_spec(_sp); _sp.loader.exec_module(_m)
            names |= set(getattr(_m, "COUNTRIES", ()) or ())
        except Exception as _e:                                      # noqa: BLE001
            # Advisory, like the roster gate: a missing engine narrows the list, it
            # does not take the pass down.
            print("country_names: engine lexicon unavailable (%s)" % _e, flush=True)
        _COUNTRIES = {fold_name(n) for n in names if n}
        _COUNTRIES.discard("")
    return _COUNTRIES


# A force/ministry/government body is a BUYER, never a rival defence maker. The competitive
# pillar is "a rival COMPANY's move", so a force named as the competitor is a mislabel; the
# SAME body in a MARKET signal (a force placing an order) is the legitimate actor -- so the
# caller gates the competitive pillar only. The test itself is aliases.is_force (folds first,
# multilingual, already the group's canonical "not a company" gate) -- not a second copy here.

# Generic filler the prompt forbids in sowhat -- its two literal examples, word-anchored.
# ponytail: deliberately narrow. A blunt "could potentially" killed specific sowhats where
# the phrase is only appended garnish ("...could potentially displace KSSL's bid"); widen
# this list only if contentless cards actually slip through, never pre-emptively.
# Fable-5 ban-list: a sowhat that hedges instead of stating a concrete consequence is
# filler. Banning the hedge words forces the model to cite a real number/product/capability
# or reply NONE -- "no generic filler" as a vibe let it paraphrase its way around.
# Narrow ban-list: the pure-filler TELLS a sowhat has no substance. A card that carries a
# real fact plus a mild hedge ("...which could threaten KSSL") is fine; the _has_concrete
# gate handles substance. Banning common hedges ("could impact") killed good cards, so only
# the phrases that are ALWAYS filler are banned here.
_FILLER_RX = re.compile(
    r"\bcompetitive landscape\b|\bmarket position\b|\bshowcas(?:e|es|ing)\b|"
    r"\bcompetitive categor(?:y|ies)\b|\bsets? (?:a )?new standards?\b", re.I)


def _has_concrete(sowhat):
    """A real sowhat carries a concrete anchor: a digit, or a capitalised token that is
    not KSSL/Kalyani/Bharat Forge (a product, company or place the statements named)."""
    if any(c.isdigit() for c in sowhat):
        return True
    for tok in re.findall(r"[A-Z][A-Za-z0-9-]{2,}", sowhat):
        if tok.lower() not in ("kssl", "kalyani", "bharat", "forge", "the", "this"):
            return True
    return False


_YEAR_RX = re.compile(r"\b(?:19|20)\d\d\b")


def content_year_max(props):
    """Newest 4-digit year mentioned across the evidence quotes, or None. `props` rows are
    (subject, predicate, object, modality, ev_quote) -- the quote is the 5th field."""
    yrs = []
    for pr in props:
        q = pr[4] if len(pr) > 4 else ""
        yrs += [int(y) for y in _YEAR_RX.findall(q or "")]
    return max(yrs) if yrs else None


def is_filler(sowhat):
    return bool(_FILLER_RX.search(sowhat or ""))


_MONEY_RX = re.compile(r"[$€£]?\s?(\d[\d,.]*)\s?(bn|billion|b|m|million|mn)\b", re.I)


def money_key(company, text, known_rx=None):
    """fix3: (folded company, amount, b/m) -- the same award reported by two outlets shares
    it even when titles differ ('$515m' vs '$515 million', 'US Navy' vs 'U.S. Navy'). The
    company is CANONICAL: a known maker named in the text wins over the field, so the key is
    stable no matter which of the two cards got maker-recovered first (Fable-5 R4)."""
    mm = _MONEY_RX.search(text or "")
    if not mm:
        return None
    comp = (known_rx and find_competitor(text, known_rx)) or company
    return (fold_name(comp), mm.group(1).replace(",", "").rstrip("."), mm.group(2).lower()[0])


PROMPT = """You are an analyst for KSSL (Kalyani Strategic Systems, the defence arm of the
Kalyani Group / Bharat Forge -- Indian maker of artillery, ammunition, armoured vehicles,
small arms, drones). Below are the extracted statements of ONE news article, each with its
supporting quote.

Decide: does this article carry ONE signal a KSSL analyst should see? File it into exactly
one pillar:
- competitive: a RIVAL defence COMPANY's move -- an order won, a partnership, an expansion,
  a product launch that changes KSSL's competitive field. The actor is a maker/supplier;
  an armed force, ministry or government buyer is a MARKET signal, never a competitive one.
- market: a procurement or demand event with NO single winning maker -- a tender issued, a
  budget, a stated requirement, an import or export decision. (A contract AWARDED to a named
  supplier is that supplier's WIN and is competitive, not market -- see the tiebreak.)
- technology: a capability or R&D advance -- a new system demonstrated, a technical
  milestone, an innovation that shifts what is technically expected in a KSSL category.
  The company is the MAKER/developer; a fielding armed force or ministry is not the actor.
Tiebreak for a contract/order AWARD: if the actor named is the WINNING maker/supplier it is
COMPETITIVE, not market. market is buyer-side only -- a tender issued, a budget approved, a
requirement announced, an import/export policy -- an event with no single maker as the actor.
Routine corporate news, politics without procurement, and non-defence stories are NOT
signals. Kalyani / KSSL / Bharat Forge is the CLIENT GROUP, never a rival and never a
threat: its own capability news files under technology, a procurement it wins under market,
and it NEVER files under competitive.

If there is no signal, reply exactly: NONE
If the signal fits NONE of the listed categories, also reply NONE -- never stretch the
nearest category.

CONSISTENCY: if the "company" you name is a maker/supplier that WON a contract, order, or
selection (not a government body), then "pillar" MUST be competitive -- never market.

Otherwise reply with ONLY this JSON (no prose around it):
{"pillar": "<competitive | market | technology>",
 "title": "<one factual headline, max 90 chars, only facts the statements state>",
 "company": "<the ONE organization that ACTED. For a COMPETITIVE or TECHNOLOGY signal this
             is the rival COMPANY -- the maker, developer or supplier; an armed force,
             ministry or government body is NOT it (a force buying or fielding is a MARKET
             signal). For a market signal name the issuing agency or government body. For a
             CONTRACT or ORDER a supplier WON, the actor is the WINNING supplier (name it,
             e.g. the shipbuilder or manufacturer) -- NEVER the government that awarded it,
             even if the government issued the announcement. NEVER just the country, and if
             two organizations acted jointly name the one the statements put first -- NEVER
             write 'X and Y'>",
 "category": "<exactly one of: %s>",
 "dir": "<threat ONLY for a concrete GAIN by a rival in a KSSL category -- an order,
         contract, selection, or delivery won. A display, demo, exhibition, or bare
         announcement is watch, never threat>",
 "what": "<one factual sentence: what happened, exactly as stated -- announced is not
          delivered, an order is not a delivery, a plan is not a contract>",
 "sowhat": "<Sentence 1 (required): the key fact FROM THE STATEMENTS and what it changes --
            a comparison, a consequence, or a capability gap. Restating specifications is
            NOT significance. Sentence 2 (OPTIONAL): the KSSL line it competes in, chosen
            ONLY from artillery / ammunition / armoured vehicles / small arms / drones, and
            ONLY if the product itself belongs to that line -- a system that counters,
            carries, or merely coexists with a category is NOT in it. If no line genuinely
            fits, write sentence 1 ONLY -- do NOT invent a KSSL connection. Good: 'The
            58-calibre gun reaches 60-80 km, a longer range than 52-calibre artillery in
            the same class.' Bad: 'showcases advances that could impact KSSL's landscape.'>"}

Write title, what and sowhat in ENGLISH, whatever language the statements are in.
Rules: use ONLY the statements below; no numbers or names that are not in them.

Article: %s (%s, %s)
Statements:
%s"""


def esc(t):
    """Card text is rendered as HTML by the UI; article/LLM text is not curated
    HTML, so it is escaped here where the fragments are composed."""
    return _html.escape(str(t or ""), quote=False)


def clip(t, n):
    """Truncate WITH a visible ellipsis -- a silently cut quote wrapped in
    curly quotes reads as complete, which it is not."""
    t = t or ""
    return t if len(t) <= n else t[:n].rstrip() + "…"


# --- corpus selection gate (operator rule: only recent, KSSL-portfolio/competitor
# docs feed the serving layer; everything else is counted out, not silently lost) ---

_NATIVE_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹"
                               "٠١٢٣٤٥٦٧٨٩",
                               "01234567890123456789")

# Recency is per-ARTICLE, never per-set: a fetch date is not a publish date --
# an Aug-2026 news query happily returns a July-2024 article (it did). A document
# proves its date from its own extracted Date spans; the publication date is the
# earliest-positioned span that parses. No parseable date -> not provably recent
# -> excluded. Year-only dates pass on the current year (month unprovable).
RECENT_WINDOW_DAYS = 92

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


_MON_RX = "(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"


def _clamp(v, lo, hi):
    v = int(v)
    return v if lo <= v <= hi else None


def parse_date(s):
    """'2026-08-06' / '03/07/2024' / 'July 3, 2024' / '28 May 2026' / 'year 2025'
    -> (y, m|None, d|None), or None. Numeric d/m/y is read day-first (the sources
    that use it are European); only year and month decide recency anyway."""
    s = s.translate(_NATIVE_DIGITS).lower()
    m = re.search(r"\b(20\d\d)-(\d{1,2})(?:-(\d{1,2}))?\b", s)          # iso y-m-d
    if m:
        return int(m.group(1)), _clamp(m.group(2), 1, 12), \
            _clamp(m.group(3), 1, 31) if m.group(3) else None
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](20\d\d)\b", s)         # d.m.y
    if m:
        return int(m.group(3)), _clamp(m.group(2), 1, 12), _clamp(m.group(1), 1, 31)
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s{1,3}" + _MON_RX       # 28 May 2026
                  + r"[a-z]*\.?,?\s{1,3}(20\d\d)\b", s)
    if m:
        return int(m.group(3)), _MONTHS[m.group(2)], _clamp(m.group(1), 1, 31)
    m = re.search(r"\b" + _MON_RX                                       # May 28, 2026 / May 2026
                  + r"[a-z]*\.?\s{0,3}(\d{1,2})?(?:st|nd|rd|th)?,?\s{0,3}(20\d\d)\b", s)
    if m:
        return int(m.group(3)), _MONTHS[m.group(1)], \
            _clamp(m.group(2), 1, 31) if m.group(2) else None
    m = re.search(r"\b(20\d\d)\b", s)                                   # year present:
    if m:                                                               # try non-English months
        y = int(m.group(1))                                             # before settling for it
        for tok in re.findall(r"[^\W\d_]+", s, re.UNICODE):
            mm = _ml_month(tok)
            if mm:
                # The day sits on one side of the month word or the other in every
                # language here: '01 settembre 2026', 'settembre 1, 2026',
                # 'vasario 17 d.'. This branch used to return None for it, so an
                # English page yielded '30 Aug 2026' and an Italian one carrying the
                # same information yielded 'Sep 2026' -- the English path had day
                # precision and no other language did. On the served corpus that cost
                # the day on 85 of 825 cards, 42 of them one Italian publisher.
                esc = re.escape(tok)
                near = (re.search(r"\b(\d{1,2})\s{0,2}[.,-]?\s{0,2}" + esc, s)
                        or re.search(esc + r"[^\W\d_]*\.?[\s,]{0,2}(\d{1,2})(?!\d)", s))
                return y, mm, _clamp(near.group(1), 1, 31) if near else None
        return y, None, None
    return None


# Month names for the corpus's languages (de fr es it pt lt fi cs pl ms tr ru uk).
# Without this, a Lithuanian "vasario 17 d." parses as year-only and a February
# article passes the recency window on the current-year concession -- the
# closed-keyword-list-is-a-language-detector failure, in a date parser.
_ML_MONTHS = {
    "januar": 1, "janvier": 1, "enero": 1, "gennaio": 1, "janeiro": 1, "sausio": 1,
    "tammiku": 1, "leden": 1, "ledna": 1, "styczen": 1, "stycznia": 1, "januari": 1,
    "ocak": 1, "январ": 1, "січн": 1,
    "februar": 2, "fevrier": 2, "febrero": 2, "febbraio": 2, "fevereiro": 2,
    "vasario": 2, "helmiku": 2, "unora": 2, "lutego": 2, "februari": 2, "subat": 2,
    "феврал": 2, "лютог": 2,
    "marz": 3, "maerz": 3, "marzo": 3, "marca": 3, "marco": 3, "kovo": 3,
    "maalisku": 3, "brezna": 3, "март": 3, "березн": 3,
    "abril": 4, "avril": 4, "aprile": 4, "balandzio": 4, "huhtiku": 4, "dubna": 4,
    "kwietnia": 4, "nisan": 4, "апрел": 4, "квітн": 4,
    "mayo": 5, "maggio": 5, "maio": 5, "geguzes": 5, "toukoku": 5, "kvetna": 5,
    "maja": 5, "mayis": 5, "мая": 5, "травн": 5,
    "junio": 6, "juin": 6, "giugno": 6, "junho": 6, "birzelio": 6, "kesaku": 6,
    "cervna": 6, "czerwca": 6, "haziran": 6, "июн": 6, "червн": 6,
    "julio": 7, "juillet": 7, "luglio": 7, "julho": 7, "liepos": 7, "heinaku": 7,
    "cervence": 7, "lipca": 7, "julai": 7, "temmuz": 7, "июл": 7, "липн": 7,
    "agosto": 8, "aout": 8, "rugpjucio": 8, "eloku": 8, "srpna": 8, "sierpnia": 8,
    "ogos": 8, "agustos": 8, "август": 8, "серпн": 8,
    "septiembre": 9, "septembre": 9, "settembre": 9, "setembro": 9, "rugsejo": 9,
    "syysku": 9, "zari": 9, "wrzesnia": 9, "eylul": 9, "сентябр": 9, "вересн": 9,
    "octubre": 10, "octobre": 10, "ottobre": 10, "outubro": 10, "spalio": 10,
    "lokaku": 10, "rijna": 10, "pazdziernika": 10, "oktober": 10, "ekim": 10,
    "октябр": 10, "жовтн": 10,
    "noviembre": 11, "novembre": 11, "novembro": 11, "lapkricio": 11, "marrasku": 11,
    "listopadu": 11, "listopada": 11, "kasim": 11, "ноябр": 11, "листопад": 11,
    "diciembre": 12, "decembre": 12, "dicembre": 12, "dezembro": 12, "gruodzio": 12,
    "jouluku": 12, "prosince": 12, "grudnia": 12, "disember": 12, "aralik": 12,
    "декабр": 12, "грудн": 12, "dezember": 12,
}
_ML_SHORT = {"mai": 5, "mars": 3, "maj": 5, "mac": 3, "mart": 3, "jun": 6, "mei": 5}


def _fold(tok):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", tok.lower())
                   if not unicodedata.combining(c))


def _ml_month(tok):
    t = _fold(tok)
    if t in _ML_SHORT:                       # short names match only exactly
        return _ML_SHORT[t]
    for k, v in _ML_MONTHS.items():
        if len(k) >= 4 and t.startswith(k):  # longer names match by stem (inflection)
            return v
    return None


# A news CMS puts the publication date in the path: /news/defense/2026/07/13/slug
# or /2026-07-13/slug. The publisher generated it, it cannot drift, and it is the
# one date on the page that no parser had to guess. Anchored to a path segment so
# a slug like "top-10-of-2026" or an id "20260713" cannot match.
_URL_DATE = re.compile(r"/(20\d{2})[/-](0[1-9]|1[0-2])[/-](0[1-9]|[12]\d|3[01])(?=[/-]|$)")

# WordPress's default permalink is /YYYY/MM/slug -- no day. Missing this shape
# left 35 cards showing "Jul 2026" for analisidifesa.it stories published as far
# back as September 2017: the day pattern did not match, so the fetch-stamped
# published_at was used instead. Month precision is enough -- the card renders
# "Sep 2017" and the recency gate compares year and month anyway.
_URL_YM = re.compile(r"/(20\d{2})[/-](0[1-9]|1[0-2])(?=/|$)")


def url_date(url):
    """-> (y, m, d) or (y, m, None) from the article's own URL path, or None.

    Day precision is tried first: it is the more specific shape, and a
    /2026/07/13/ path would otherwise match the month pattern and lose the day.
    """
    if not url:
        return None
    # Query and fragment are not the path; ?date=... is a filter, not a byline.
    path = url.split("#", 1)[0].split("?", 1)[0]
    m = _URL_DATE.search(path)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = _URL_YM.search(path)
    if m:
        return int(m.group(1)), int(m.group(2)), None
    return None


def is_fetch_fallback(published_at, fetched_at):
    """True when `published_at` is really just the moment we fetched the page.

    The crawler stamps the fetch date when it cannot find a publication date.
    Measured on the 290 documents behind the cards: 72 look like this, and where
    the URL also carries a date, 63 of 63 disagree with it -- 62 claiming the
    story is NEWER than it is, by a median of 77 days and as much as 3.8 years.
    A stale story dated today also walks straight through the recency gate, so
    this is not merely cosmetic.

    BOTH conditions are required. A midnight timestamp on its own proves nothing
    -- all 30 documents whose published_at agrees with their URL date are ALSO
    stamped midnight, because date-only metadata is normal. Rejecting on
    midnight alone would have thrown away every one of those correct dates. It
    is the match with the FETCH date that separates them: 62 of 63 wrong, 0 of
    30 right.
    """
    if not published_at or not fetched_at:
        return False
    if published_at[:10] != fetched_at[:10]:
        return False
    return published_at[11:19] in ("00:00:00", "")


def card_image(did, page_url):
    """The article's lead image, or None. Never raises.

    Reads the same stored markup article_date() reads -- corpus.fetch_html holds
    one connection, so asking for both costs one round-trip per card, not two.
    A card without a picture is not broken; the UI has an empty state. So a
    corpus outage costs the picture, never the card.
    """
    try:
        url, html = corpus.fetch_html(did)
        if not html:
            return None
        return resolve_image(html, url or page_url or "", timeout=10)
    except Exception as e:                                    # noqa: BLE001
        print("  image lookup failed for %s: %s" % (did, e), flush=True)
        return None


def date_step(coarse, ymd, today_ym):
    """One candidate, in trust order -> (answer_or_None, coarse).

    `answer_or_None` is None to keep looking; `coarse` is the best month-only
    answer seen so far and becomes the fallback when nothing better arrives.

    THE RULE: trust picks the MONTH, and a later source may only add a DAY to the
    month already chosen -- never move it.

    Two bugs have lived in this handful of lines, so both are written down.

    A more-trusted source naming only a month used to END the search, so a day in
    a less-trusted one was never reached: the URL path /2026/09/ answered
    'Sep 2026' for an article whose own byline read '01 Settembre 2026'.

    Then the repair for that returned `coarse` when a candidate fell in a
    DIFFERENT month -- which enforced the rule but ended the search just as
    finally. Step 3 is `published_at`, routinely the fetch stamp and so routinely
    another month, and it cut the search off before the body was read: two
    analisidifesa articles from 2021 and 2025, crawled in 2026, lost the day
    their own text stated. An out-of-month candidate is SKIPPED now. That is
    equally safe -- only a same-month dated candidate is ever returned -- and the
    caller's fallthrough still answers `coarse`.

    A date in the future is not a publication date; it is a delivery forecast or
    a broken clock, and it is skipped without becoming the fallback.
    """
    if ymd is None or (ymd[0], ymd[1] or 1) > today_ym:
        return None, coarse
    if ymd[2] is not None:
        if coarse is None or coarse[:2] == ymd[:2]:
            return ymd, coarse
        return None, coarse
    return None, coarse if coarse is not None else ymd


def article_date(cur, did, today_ym=None):
    """-> (y, m|None, d|None): when the article was published, or None.

    Sources in order of how much they can be trusted:
      1. what the ARTICLE'S OWN MARKUP declares -- article:published_time,
         JSON-LD datePublished, Dublin Core. The publisher's machine-readable
         statement about the page, and it needs no site-specific rule.
      2. the date in the article's own URL path -- also publisher-generated,
         and the fallback for CMSs that declare nothing (measured: it covers
         the analisidifesa.it archive, which states no metadata at all)
      3. `published_at` from the crawler, unless it is the fetch stamp in
         disguise. It is NOT proven: on asdnews the crawler scraped
         `<time id="current-date">`, the navbar clock, so it equalled the day
         we crawled.
      4. Date spans in the body, earliest first

    A date in the FUTURE cannot be a publication date -- '2027 delivery' and
    '2040 vision' spans are forecasts -- so those are skipped and the scan
    continues. Returning None is a real answer: the card is then counted
    `undated` and left out, which is better than dating it wrongly.
    """
    if today_ym is None:
        import datetime
        t0 = datetime.date.today()
        today_ym = (t0.year, t0.month)

    cur.execute("SELECT url, meta->>'published_at', meta->>'fetched_at' "
                "FROM extracted.document WHERE document_id=%s", (did,))
    row = cur.fetchone()
    url, pub, fetched = (row[0], row[1], row[2]) if row else (None, None, None)

    coarse = [None]      # first usable answer that names no day

    def take(ymd):
        answer, coarse[0] = date_step(coarse[0], ymd, today_ym)
        return answer

    # 1. The publisher's own declaration, read out of the stored markup. Costs a
    #    corpus round-trip, which is shared with the card's image lookup.
    html_url, html = corpus.fetch_html(did)
    from_url = url_date(url or html_url)
    if html:
        # The URL goes in as a cross-check, not a fallback: markup regenerated
        # by a site migration can be confidently wrong (boeing.com dated a June
        # 2024 mission update 2025-10-16), and the permalink is the one thing a
        # CMS cannot rewrite without breaking its own links.
        got = take(pick_html_date(html, html_url or url, url_ymd=from_url))
        if got:
            return got

    # 2. The URL path.
    got = take(from_url)
    if got:
        return got

    # 3. published_at, unless it is the fetch stamp wearing a publication date's
    #    clothes. `fetched_at` is carried into meta by store_pg; when it is
    #    absent (documents extracted before that) the check cannot fire and
    #    behaviour is exactly as it was.
    if pub and not is_fetch_fallback(pub, fetched):
        # ISO timestamps arrive as 2026-08-25T14:03:11Z; the T has to go or the
        # parser reads the year and month and drops the day.
        got = take(parse_date(pub.replace("T", " ")[:24]))
        if got:
            return got

    # 4. Date spans in the body, earliest position first. This is where a byline
    #    the CMS never declared in markup finally turns up.
    cur.execute("""SELECT text, gloss FROM extracted.span
                    WHERE document_id=%s AND type='Date'
                    ORDER BY start_c LIMIT 15""", (did,))
    for t, g in cur.fetchall():
        got = take(parse_date("%s %s" % (t or "", g or "")))
        if got:
            return got

    return coarse[0]


def date_label(ymd):
    """(2026, 5, 28) -> '28 May 2026'; month/day degrade honestly.

    Every date parser here validates the day as 1-31 without knowing the month,
    so a page carrying `content="2026-02-30"` yields (2026, 2, 30) and this used
    to raise ValueError -- inside the card loop, outside every try, killing the
    whole serving run on one junk attribute. An impossible day is dropped to
    month precision rather than trusted or thrown.
    """
    y, m, d = ymd
    if m and d:
        import datetime
        try:
            return datetime.date(y, m, d).strftime("%d %b %Y").lstrip("0")
        except ValueError:
            pass                       # 31 February and friends -> month only
    return ago_of((y, m))


def recent_cutoff(today=None):
    import datetime
    today = today or datetime.date.today()
    back = today - datetime.timedelta(days=RECENT_WINDOW_DAYS)
    return (back.year, back.month), today.year


def is_recent_ym(ym, cutoff, cur_year):
    if ym is None:
        return False
    y, m = ym
    if m is None:
        return y >= cur_year
    return (y, m) >= cutoff


def ago_of(ym):
    import datetime
    y, m = ym
    return datetime.date(y, m, 1).strftime("%b %Y") if m else str(y)


def load_terms():
    """KSSL portfolio + competitor vocabulary -> compiled word-boundary patterns.
    Rules: >=4 chars (a short substring is a false-positive machine -- 'bus'),
    boundary-anchored, case-folded. Predicates/objects of propositions are
    English-normalised by the extractor, so this is not a language detector."""
    ref = json.loads((HERE.parent / "reference_dataset.json").read_text(encoding="utf-8"))
    names = [v.get("name", "") for v in ref.get("competitors", {}).values()]
    names += [g.get("name", "") for g in ref.get("geoComps", [])]
    # matchup comp/global are "Company · Product" composites; both halves are terms
    for m in ref.get("matchups", {}).values():
        for v in (m.get("comp"), m.get("global")):
            if isinstance(v, str):
                names += [part.strip() for part in v.split("·")]
    names += [r.get("company") for r in ref.get("sourceRegistry", [])
              if isinstance(r.get("company"), str)]
    names += ["Kalyani", "Bharat Forge", "KSSL"]
    kws = list(ref.get("CAT_ALIASES", {}).keys()) + ref.get("KSSL_CATS", [])

    def rx(terms):
        return [re.compile(r"(?<!\w)" + re.escape(t.lower()) + r"(?!\w)")
                for t in sorted({x.strip() for x in terms if len(x.strip()) >= 4})]

    # (relevance patterns, competitor-name-only patterns -- the latter order the feed)
    return rx(names + kws), rx(names)


def is_relevant(patterns, title, props):
    hay = " ".join([title or ""] + ["%s %s" % (p[0], p[2]) for p in props]).lower()
    return any(rx.search(hay) for rx in patterns)


def is_listing(url):
    """Homepages, tag/category indexes and paginated archives are collections of
    headlines, not one story -- a card built from one conflates stories and its
    'date' is whatever year appears anywhere on the page (audit F1/F2/F5)."""
    from urllib.parse import urlsplit
    u = urlsplit(url or "")
    path = (u.path or "").rstrip("/")
    if not path:
        return True
    low = path.lower()
    # An author page and a topic index are the same thing as a tag page: a list
    # of other people's headlines. They reached extraction and cost a full model
    # pass each before being refused here.
    for seg in ("/tag/", "/tags/", "/category/", "/label/", "/author/", "/authors/",
                "/topic/", "/topics/", "/section/",
                "/search/", "/page/",
                # Drupal publishes its tag indexes as /term/ and /taxonomy/term/,
                # which this list did not cover -- so aviationweek.com/term/saab and
                # aviationweek.com/taxonomy/term/157261 walked straight through the
                # gate and became 37 dated cards. A tag index has no publication date
                # at all, so whatever date they showed was manufactured from a page of
                # mixed headlines. That is precisely what this gate exists to stop.
                "/term/", "/taxonomy/",
                # A per-organisation index is a tag page wearing a company name.
                # asdnews.com/company/104104/hanwha-aerospace-europe put THREE
                # cards on the dashboard, each citing a source that opens a list
                # of headlines rather than a story -- and one merged two separate
                # articles ("Arion-SMET UGV", "K9PL howitzers") into a single
                # claim, which is exactly what a listing page makes a summariser
                # do, and what this gate exists to prevent.
                "/company/", "/companies/", "/organisation/", "/organisations/",
                "/organization/", "/organizations/", "/supplier/", "/suppliers/",
                "/vendor/", "/vendors/", "/profile/", "/profiles/"):
        if seg in low + "/":
            return True
    # `page=` as a WHOLE query parameter. Matching it as a substring rejected a
    # real pixxel.space article whose tracking param merely ended "..._page=11".
    for kv in (u.query or "").lower().split("&"):
        if kv.split("=", 1)[0] in ("page", "paged", "p") and "=" in kv:
            return True
    last = low.rsplit("/", 1)[-1]
    # An archive INDEX ends at /archive; an archived ARTICLE lives beneath one.
    # armyrecognition.com/archives/archives-land-defense/.../syria-... is a real
    # story, and treating any /archive/ segment as a listing deleted the lot.
    return last in ("news", "media", "press", "press-releases", "newsroom",
                    "press-room", "media-centre", "media-center",
                    "archive", "archives", "news.html", "news.aspx", "news.php",
                    # non-English news indexes seen in the corpus: tr / fr / de / es
                    "haberler", "urunler", "actualites", "nachrichten",
                    "noticias", "actualidad") \
        or last.endswith("-in-media")


# The publisher naming its own page an index. Independent of the URL, so it
# catches a listing at a path no pattern anticipated -- the failure mode a
# URL-only rule always eventually has.
_INDEX_PHRASE = re.compile(
    r"^(?:"
    r"news\s*(?:&(?:amp;)?|and)\s*press\s*releases"
    r"|press\s*releases?\s*(?:&(?:amp;)?|and)\s*news"
    r"|news\s+archive|all\s+news|latest\s+news"
    r"|news\s*(?:&(?:amp;)?|and)\s*events"
    r"|newsroom|press\s*room|media\s*cent(?:er|re)|media\s*hub|news"
    r")$", re.I)
# The phrase must END the title's first segment, not merely appear in it.
# "Hanwha Aerospace Europe News & Press Releases | ASDNews" is an index whose
# first segment carries the company name; "HII is Awarded Contracts ... | HII
# Newsroom" is an ARTICLE whose first segment ends in "Submarines".
_INDEX_TAIL = re.compile(
    r"(?:^|[\s:\-])(?:"
    r"news\s*(?:&(?:amp;)?|and)\s*press\s*releases"
    r"|press\s*releases?\s*(?:&(?:amp;)?|and)\s*news"
    r"|news\s+archive|all\s+news|latest\s+news"
    r"|news\s*(?:&(?:amp;)?|and)\s*events"
    r"|newsroom|press\s*room|media\s*cent(?:er|re)|media\s*hub"
    r")$", re.I)

# A publisher's <title> is nearly always "<the story> | <the site>". Only the
# FIRST segment names the page; the rest is site furniture.
_TITLE_SPLIT = re.compile(r"\s*[|–—·]\s*|\s+-\s+")


def is_index_title(title):
    """True when the page's own <title> says it IS a list, not a story.

    The phrase has to BE the title (or its leading segment), not merely appear
    somewhere in it. Searching anywhere was a silent catastrophe: HII titles
    every press release "... | HII Newsroom", so `\\bnewsroom\\b` matched every
    one of them and the whole source vanished before the model ever saw it --
    528 article-shaped pages across HII, Airbus, MBDA and SSTL, counted only in
    stats["listing"] with no per-document trace. A false positive here is worse
    than a false negative: a listing that slips through produces one bad card,
    but a rejected publisher produces silence.
    """
    if not title:
        return False
    head = _TITLE_SPLIT.split(title.strip(), 1)[0].strip()
    return bool(_INDEX_TAIL.search(head))


def suppressed_ids():
    """Doc ids an audit ruled out (pipeline/suppressed.txt, hash comments)."""
    f = HERE / "suppressed.txt"
    if not f.exists():
        return set()
    out = set()
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def title_tokens(t):
    return frozenset(w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if len(w) > 2)


def is_dup(seen, company, title):
    """Same company + near-identical title = the same story syndicated across
    pages (brahmos.com carries dozens of copies of one delivery)."""
    toks = title_tokens(title)
    cf = (company or "").casefold()
    for c, t in seen:
        if not (toks and t):
            continue
        jac = len(toks & t) / len(toks | t)
        if jac >= 0.75 or (c == cf and jac >= 0.6):
            return True
    return False




# llm_opts() and LLM_TIMEOUT used to live here, and in two more modules besides.
# Both now belong to the API (llmapi/nodes.py: options(), read_timeout()), because both
# are properties of the NODE serving the call, not of the caller:
#
#   * num_thread must equal the serving container's cpu cap. Ollama sizes its thread pool
#     from the HOST's core count and ignores the cgroup, so a capped container spends its
#     slice context-switching. Measured on the 8-core VPS with qwen2.5:7b, 4 cores:
#     6.0 tok/s default -> 11.4 tok/s pinned.
#   * num_gpu=0 is true of vps-b and false of a GPU box.
#   * the timeout is derived from the tokens asked for and THAT node's measured tok/s.
#     The old fixed 180s was a GPU-era number: on 4 pinned cores at ~11 tok/s a long
#     prefill plus a 300-token answer runs past it, the socket closes with an empty body,
#     and the reply is lost whole while the work is charged anyway.
#
# num_ctx is still always set explicitly server-side: a model whose default context is
# 262k asks ollama for a 95 GB KV cache and the request dies as an opaque HTTP 500.


def ask(prompt, timeout=None, doc_id=None, npredict=420):  # 14B writes longer; avoid mid-JSON truncation
    """One card-step generation, through the LLM API.

    The API owns node selection, the Bearer key, the num_thread/num_gpu options and the
    timeout -- all of which used to be four copies of the same code in this package. What
    stays here is the instrumentation, because this is still the one place that can answer
    "what does the LLM stage cost": the server returns the model's own eval_count, so the
    recorded tok/s is the model's and not a stopwatch's.
    """
    with stage_timer.stage("llm", doc_id=doc_id, meta={"model": MODEL}) as st:
        text, meta = llm_client.ask(prompt, npredict=npredict, timeout=timeout,
                                    model=MODEL, with_meta=True)
        st.items(1).tokens(int(meta.get("eval_count") or 0))
        return text


# --- code-side classification (Fable-5 R2: with a 7B the LLM writes prose, CODE classifies;
#     every rule left in the prompt was violated, every rule moved to code held) ----------
# The fabricated KSSL tie takes two shapes: a hedged clause ("...which could threaten KSSL's
# small arms...") and a plain aside ("...competes with KSSL's drone offerings"). Cut both,
# not the whole sentence -- the 7B interleaves real substance with the invented tie.
_TAIL_RX = re.compile(
    r"[,;]?\s*(?:(?:which|that)\s+)?(?:could|potentially|may|would|pos\w+)\b[^.!?]*?\bKSSL\b[^.!?]*",
    re.I)
_TIE_PLAIN = re.compile(
    r"[,;]?\s*[^.!?]*\bKSSL['’]?s?\b\s*(?:drone|artiller|ammunition|small[- ]arms|armou?red|"
    r"offering|portfolio|position|product|categor|market|landscape|system|space|segment|"
    r"capabilit)[^.!?]*", re.I)
# a competitive EVENT: an award/win/partnership/expansion/acquisition/MoU (NOT a product
# unveil, which is tech). Widened per Fable-5 R3: sign MoU/agreement, invites partnership,
# teaming, acquisition, new facility all read as competitive when a maker is the actor.
_EVENT_RX = re.compile(
    r"\b(won|wins?|awarded?|contract|order(?:s|ed)?|selected?|secured?|clinch\w*|bagged|"
    r"partnership|joint venture|teaming|team(?:ed|s)? up|expand\w*|acquir\w*|acquisition|"
    r"mou|memorandum|sign\w*|invit\w*|framework|new (?:facility|plant|line))\b", re.I)
# the FIVE KSSL product lines -- a threat badge is meaningless outside them (a rival gaining
# in missiles or naval, which KSSL does not make, is watch, not threat).
_CORE_CATS = {"artillery", "ammunition", "protected & armoured vehicles",
              "armoured vehicle mro", "small arms", "uavs & drones"}
# capital-city / metonym names journalists use for a government -- not a company.
_CITIES = {"tokyo", "seoul", "moscow", "beijing", "london", "paris", "delhi", "new delhi",
           "washington", "berlin", "rome", "madrid", "ankara", "canberra", "ottawa",
           "brussels", "warsaw", "kyiv", "kiev", "tel aviv", "riyadh", "abu dhabi"}
# forces / countries the reference lists miss (is_force/country_names don't know them).
_EXTRA_FORCE = {"bundeswehr", "gendarmerie", "carabinieri", "peshmerga", "the bundeswehr"}
_EXTRA_COUNTRY = {"taiwan", "kosovo", "palestine", "somaliland"}
_LEAD_SKIP = {"the", "new", "additional", "five", "seven", "major", "us", "u.s.",
              "first", "second", "third", "fourth", "fifth"}
_ORG_TOKEN = re.compile(r"([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,3})")


_BUYER_RX = re.compile(
    r"\b(mod|dod|ministry|ministr\w+|government|govt|armed forces?|defen[cs]e forces?|"
    r"contracting command|procurement|air force|army|navy|coast guard|national guard)\b",
    re.I)


def is_buyer(name):
    """A force / ministry / government / country / capital-city -- a BUYER, not a maker."""
    n = (name or "").strip().lower()
    return (is_force(name) or n in _EXTRA_FORCE or n in _EXTRA_COUNTRY or n in _CITIES
            or fold_name(name) in country_names() or bool(_BUYER_RX.search(n)))


def maker_from_title(title):
    """The winning maker is usually the first real org in the headline ('Elbit awarded ...',
    'KONGSBERG and OSI sign ...'). Take the first capitalised org that is not a buyer."""
    for m in _ORG_TOKEN.finditer(title or ""):
        cand = m.group(1).strip().rstrip(",.").rstrip("'s").strip()
        while cand and cand.split()[0].lower() in _LEAD_SKIP:
            cand = " ".join(cand.split()[1:])
        if cand and cand[:1].isupper() and not is_buyer(cand) and not is_org_fragment(cand):
            return cand
    return None
# a real GAIN (gates dir=threat); a demo/announcement is not a gain
_GAIN_RX = re.compile(
    r"\b(won|wins?|awarded|award|contract|order|selected|delivered?|acquired|secured|"
    r"rights|deal|bagged|clinch(?:ed)?)\b", re.I)
_HELI_RX = re.compile(r"\b(helicopters?|rotorcraft|rotary[- ]wing)\b", re.I)
_LASER_RX = re.compile(r"\b(laser|directed[- ]energy|high-energy)\b", re.I)
# 20-57mm is an autocannon; "5.56x45mm" is a carbine and "12.7x99mm" a heavy machine gun.
# The old \b\d{2} matched the "56" after the dot in 5.56x45 and made a carbine a conflict.
_AUTOCANNON_RX = re.compile(r"(?<![\d.])(?:[2-5]\d)\s*[x×]\s*\d{2,}\s*mm\b", re.I)
# Hebrew / Arabic / Cyrillic / CJK / Japanese -- the prompt says English; a card in the
# source language is unusable in the UI, and the 7B echoes the source when it slips.
_NONLATIN_RX = re.compile(r"[֐-׿؀-ۿЀ-ӿ一-鿿぀-ヿ]")
_GENERIC_ORG = {"nigam", "limited", "ltd", "defence", "defense", "systems", "corporation",
                "corp", "industries", "group", "aerospace", "technologies", "technology",
                "company", "navy", "army", "forces", "force", "ministry", "command"}
_ORG_SUFFIX = {"limited", "ltd", "inc", "corp", "corporation", "co", "company", "plc",
               "gmbh", "sa", "ag", "llc", "pvt", "private", "nigam"}


def is_org_fragment(company):
    """fix5: an NER fragment, not a real name -- 'Nigam Limited' is AVNL (Armoured Vehicles
    Nigam Limited) with the identifying words dropped, leaving just 'corporation limited'."""
    toks = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", company or "")]
    core = [t for t in toks if t not in _ORG_SUFFIX]
    return (not core) or (len(core) == 1 and core[0] in _GENERIC_ORG)


_KSSL_SENT = re.compile(r"\bKSSL\b", re.I)


def strip_kssl_tail(sowhat):
    """fix1: remove the fabricated KSSL-tie. Per sentence: if it mentions KSSL, cut the hedge
    clause; keep only a substantive remainder that doesn't just restate 'This/KSSL...' -- a
    bare demonstrative ('This capability.') or a 'KSSL competes...' aside is dropped whole, so
    no dangling fragment survives. Fall back to the original only if we emptied everything."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", (sowhat or "").strip()):
        if not _KSSL_SENT.search(sent):
            if _FILLER_RX.search(sent):
                continue                 # a filler sentence ('This showcases advances...') ->
                                         # drop it, keep the substantive sentences (a richer
                                         # 14B often writes fact-then-filler)
            out.append(sent)
            continue
        core = _TIE_PLAIN.sub("", _TAIL_RX.sub("", sent))
        # tidy a dangling connective the cut left behind ('...Middle East and')
        core = re.sub(r"[\s,;]+(?:and|but|which|that|as|so|to|for|with)?[\s,;.]*$", "",
                      core, flags=re.I).strip().rstrip(",;. ")
        # _TAIL_RX's `pos\w+` is meant for the hedge "possibly". It also matches
        # "position", so on "...strengthening its position in the naval market against
        # KSSL offerings" the cut begins at "position" and eats the whole substantive
        # clause, leaving "Saab secures a significant order, strengthening its." The
        # tidy above does not strip a possessive, so a full stop was appended to a
        # fragment. Walk back to the last clause boundary; if there is none, drop the
        # sentence -- a dangling fragment reads worse than silence.
        #
        # Narrowing `pos\w+` to `possibl\w+` is the deeper fix and CANNOT land alone:
        # with _TAIL_RX no longer firing, _TIE_PLAIN matches leftmost-greedy from the
        # sentence start and removes the whole sentence instead, so every one of these
        # cards disappears rather than being repaired.
        # A cut that landed mid-clause leaves a stranded possessive or preposition
        # ('...strengthening its'). Trying to repair the fragment word by word only
        # moves the problem -- strip "its" and the verb it belonged to is stranded
        # instead ('...strengthening'). Walk back to the last clause boundary, which is
        # always grammatical, and if there is no comma to fall back to, drop the
        # sentence: a dangling fragment reads worse than silence.
        while re.search(r"\b(?:its|their|his|her|our|your|the|an?|of|in|on|at|by|from|"
                        r"with|and|but|to|for)$", core, re.I):
            head, sep, _ = core.rpartition(",")
            core = head.strip().rstrip(",;. ") if sep else ""
            if not core:
                break
        if _KSSL_SENT.search(core):      # couldn't cleanly excise KSSL -> drop the sentence
            core = ""
        words = len(re.findall(r"\w+", core))
        demo = bool(re.match(r"\s*(this|these|it)\b", core, re.I))
        if core and _has_concrete(core) and words > 4 and not (demo and words <= 7):
            out.append(core if core.endswith((".", "!", "?")) else core + ".")
        # else drop the sentence -- fabricated tie or a bare demonstrative fragment
    # empty -> the whole sowhat was a fabricated tie; parse_card drops the card (no significance)
    return " ".join(out).strip()


# ---------------------------------------------------------------------------------
# OFF-PORTFOLIO SUBJECT GATE
#
# The client's first report: "there are some camera signals that KSSL doesn't work in".
# Measured on the live rows, it was not just cameras -- about a third of every served
# surface was about a product class KSSL has no line in, and 33 of 103 THREAT badges
# were off-portfolio. The one that names the problem:
#
#   "Leonardo DRS Secures Contract for Over 50,000 Thermal Imaging Cameras"
#       category: UAVs & Drones      dir: threat
#
# WHY IT GOT THROUGH. parse_card's only subject test was `if cat not in cats` -- that
# the LLM's label is one of the nine, never that the ARTICLE is about that category.
#
# WHY A NEGATIVE LIST, NOT A POSITIVE ONE. Requiring a CAT_META keyword in the title is
# the obvious fix and it is wrong: measured, it refuses ~70% of RELEVANT cards, because
# the keyword lists have no Centauro, Archer, NLAW, Carl-Gustaf or Lynx. Naming what
# KSSL does not make is a short, closed list; naming everything it does make is not.
#
# THE OVERRIDE IS THE LOAD-BEARING PART. A negative word alone would refuse
# "BrahMos fired from a Su-30" (aircraft) and "Archer howitzer with a radar-guided
# shell" (radar) -- both real missile/artillery signals. So a hit is IGNORED when a
# KSSL line is also named: the article is then about KSSL's line, mentioning the other
# thing. Off-portfolio means the SUBJECT is elsewhere, not that a foreign word appears.
#
# THE SECOND REPORT (2026-09-05): "for each should be KSSL relevant means portfolio
# relevant because otherwise it will not make sense" -- the whole site, not the feed.
# Audited again, on every surface, with the client's own 59-product master list
# (portfolio.py) as ground truth. Three faults, each pinned in test_portfolio_surfaces.py:
#
#   1. THE SUBJECT IS THE HEADLINE. The gate looked at one blob of title + what (+ in
#      the audit, sowhat -- which names the category by construction). "Thales wins
#      U.S. Marine Corps order for Minerva cameras" was served because "vehicles"
#      appeared in the body. Now: a negative term in the TITLE with no KSSL line named
#      in the title is off-portfolio; a negative term only in the BODY is an accessory
#      (the radar on a Skyranger, the SAL guidance on an Excalibur, the helicopter a
#      Spike was fired from) unless nothing anywhere names a KSSL line.
#   2. THE OVERRIDE MATCHED PREFIXES AND CORPUS-BROAD WORDS. `isr` rescued "Israeli",
#      `vehicle` rescued field hospitals and cameras, `marg` would rescue "margin".
#      Now whole-word (plural-tolerant), with the words that describe a NAVY or a
#      SENSOR rather than a product dropped (the same set enrich_serving already
#      drops for the competitor gate), and with the names the corpus actually uses
#      for KSSL's lines added -- the client's own product list first (portfolio.py),
#      then the corpus product names the competitor gate had already earned.
#   3. BUGS: the autocannon rule matched "5.56x45mm" (a carbine became a conflict);
#      "Orbital ATK" hit `orbital`; bare `laser` hit laser GUIDANCE, which is how a
#      155mm shell or a rocket is steered, not a laser weapon.
#
# WHAT THE CLIENT'S FILE CHANGED. It lists a Counter-UAS mobile system, a ground rover
# (ECARS), a loitering munition, MRSAM and Spike subsystems, torpedo homing-head MRO,
# naval guns and tank drivelines. So counter-drone, UGV, loitering-munition, missile-
# subsystem and vehicle-MRO news is ON-portfolio and none of those words is negative
# here. The file is incomplete by the client's own account, so it only ever ADDS.
import portfolio as _portfolio                                        # noqa: E402

_OFF_PORTFOLIO_RX = re.compile(
    r"\b("
    # optics / sensors -- the client's own example
    r"cameras?|thermal imag\w*|night[- ]vision|image intensif\w*|optronic\w*|"
    r"electro[- ]optical|eo/ir|periscopes?|binocular\w*|targeting pods?|vision suites?|"
    # sights: the client's complaint is optics, so name the forms they appear in.
    # NOT a bare "sight" -- "line of sight" and "sighted in" are ordinary prose.
    r"sight systems?|(?:weapon|thermal|smart|optical|aiming|reflex|holographic)[- ]sights?|"
    r"aiming devices?|telescopes?|"
    # radar / sonar / EW / signals / communications
    r"radars?|sonars?|electronic warfare|ew (?:suite|system)s?|jammers?|jamming|"
    r"signals intelligence|communications? systems?|comms|tacan|navigation systems?|"
    r"datalinks?|radios?|satcom|antennas?|transceivers?|"
    r"combat (?:management )?systems?|command[- ]and[- ]control|c4i|c5isr|c2 systems?|"
    r"mission systems?|"
    # space
    r"satellites?|spacecraft|orbital(?!\s+atk)|in[- ]orbit|on[- ]orbit|lunar|"
    r"launch vehicles?|constellations?|space (?:force|launch|robotics|domain|test)|"
    r"electromagnetic launchers?|"
    # software / IT / comms
    r"software|cyber ?security|cyber range|cyber\w*|data platforms?|battle[- ]management|"
    r"air[- ]traffic|cloud comput\w*|cloud|semiconductor\w*|wafers?|fib(?:er|re)[- ]optic|"
    # manned aircraft and engines
    r"helicopters?|rotorcraft|rotary[- ]wing|fighter jets?|fighter aircraft|fighters|"
    r"trainer jets?|trainer aircraft|pilot training|flight training|"
    r"transport aircraft|airliners?|aero[- ]?engines?|turbofans?|turboprops?|jet engines?|eVTOL|"
    r"aw1\d\d\w*|aw2\d\d\w*|nh90|m-346\w*|m-345|gripen\w*|f-35\w*|f-16\w*|f-15\w*|"
    # "typhoon" only as the fighter: Rafael's TYPHOON is a naval gun mount and Roketsan's
    # Typhoon is a ballistic missile -- both real rows, both KSSL lines
    r"f/a-18\w*|c-130\w*|kc-46|a400m|su-30\w*|rafale|eurofighter|typhoon (?:fighter|jet)s?|gcap|fcas|"
    r"tempest|apache|ah-64\w*|black hawk|uh-60\w*|mh-60\w*|seahawk|chinook|ch-47\w*|"
    r"c-27j|c-390|p-8\w*|(?<!nora )b-52\w*|b-1b|t-7a?|"        # Nora B-52 is a howitzer
    # directed energy -- a laser WEAPON. Laser GUIDANCE (SAL, laser-guided, designator)
    # is how KSSL's own shells and rockets are steered and is not listed.
    r"laser weapons?|laser (?:weapon )?systems?|laser cannons?|laser (?:source|demonstrator)s?|"
    r"high[- ]energy lasers?|\d+ ?kw(?:-class)? lasers?|helws?|directed[- ]energy|"
    r"high[- ]power microwave|"
    # medical / training / civil / corporate
    r"medical|hospitals?|field hospitals?|ambulances?|"
    r"training contract|simulation|simulators?|"
    r"order intake|revenue guidance|fy\d\d guidance|annual results|sustainability report"
    r")\b", re.I)

# Phrases that must never band and must never condemn: normalised BEFORE either check.
#   * an UNMANNED helicopter is a UAV, whatever the model called it;
#   * the platform a weapon is fired FROM is where it was, not what the story is about
#     ("Spike NLOS missile fired from Apache helicopter", "LRASM fit checks on F-35");
#   * a space rocket is not artillery.
_UNMANNED_PLATFORM_RX = re.compile(
    r"\b(?:unmanned|uncrewed|autonomous|robotic|optionally[- ]piloted|remotely[- ]piloted)"
    r"[- ]+(?:helicopter|rotorcraft|rotary[- ]wing|tiltrotor|fighter(?: jets?| aircraft)?|"
    r"combat aircraft|aircraft|jets?)\w*", re.I)
_LAUNCH_PLATFORM_RX = re.compile(
    r"\b(?:from|on|aboard|onto|off)\s+(?:an?\s+|the\s+|its\s+)?(?:[A-Za-z0-9/.-]+\s+){0,2}?"
    r"(?:helicopters?|rotorcraft|fighters?|fighter (?:jets?|aircraft)|jets?|aircraft|bombers?|"
    r"f-\d\d\w*|f/a-18\w*|su-\d\d\w*|apache|ah-64\w*|eurofighter|typhoon|rafale|gripen\w*|"
    r"b-1b|b-52\w*)\b", re.I)
_LAUNCHED_FROM_RX = re.compile(
    r"\b(?:helicopter|ship|air|submarine|surface)[- ](?:launched|borne|transported|mounted)\b", re.I)
_SPACE_ROCKET_RX = re.compile(
    r"\b(?:hybrid|sounding|space|orbital|suborbital) rockets?\b|\brocket (?:engine|motor)s?\b", re.I)


def _subject_text(text):
    """The text with the phrases above neutralised, so the checks see the subject."""
    if not text:
        return ""
    t = _UNMANNED_PLATFORM_RX.sub(" unmanned uas ", text)
    t = _LAUNCH_PLATFORM_RX.sub(" platform ", t)
    t = _LAUNCHED_FROM_RX.sub(" launched ", t)
    t = _SPACE_ROCKET_RX.sub(" propulsion ", t)
    return t


# CAT_META words that band a NAVY or a SENSOR, not a product KSSL sells -- the same
# set enrich_serving._GATE_DROP removes for the competitor gate. `vehicle` is how a
# camera order and a field-hospital order were rescued; `isr` (as a prefix) rescued
# "Israeli"; `naval` rescued a helicopter delivery.
_OVERRIDE_DROP = {"vehicle", "naval", "marine", "isr", "male", "swarm", "troop"}

# Corpus product names for KSSL's lines that CAT_META lacks. Every entry was taken from a
# real served row a human reads as obviously on-portfolio and the keyword list could not
# see -- the competitor gate's earned list (enrich_serving._GATE_ADD) plus the ones the
# innovation surface added. Keyed by the CAT_META display label.
_OVERRIDE_ADD = {
    "artillery": ["nemo", "archer", "himars", "m777", "self-propelled howitzer",
                  "mobile howitzer", "ramjet artillery", "cannon", "chain gun", "mortar",
                  "excalibur", "guided rocket", "rocket launcher", "rch 155"],
    "ammunition": ["dpicm", "cased telescoped", "munition", "guided munition", "airburst",
                   "air-bursting", "projectile", "120mm", "30mm", "35mm", "40mm"],
    "small arms": ["negev", "arad", "ak-203", "ak200", "belt-fed", "shotgun"],
    "protected & armoured vehicles": [
        "6x6", "humvee", "hmmwv", "jltv", "rws", "remote weapon station",
        "active protection", "aps", "ifv", "light tank", "main battle tank", "mbt",
        "combat vehicle", "armoured platform", "armored platform", "leopard", "boxer",
        "lynx", "turret", "weapon station"],
    "marine / naval": ["uuv", "unmanned underwater", "autonomous underwater", "remus",
                       "hugin", "seafox", "seacat", "mrauv", "underwater vehicle"],
    "uavs & drones": ["unmanned aerial system", "uncrewed aerial", "unmanned aircraft system",
                      "unmanned air system", "unmanned air vehicle", "unmanned systems",
                      "unmanned system", "switchblade", "kargu", "warmate", "fpv",
                      "black hornet", "collaborative combat", "cca", "ucav", "unmanned combat",
                      "loyal wingman", "rpas", "interceptor drone", "drone interceptor",
                      "ugs", "a-ugs"],
    "missiles & air defence": [
        "pac-3", "nasams", "samp/t", "iris-t", "aster", "surface-to-air", "cruise missile",
        "air-defence", "air-defense", "manpads", "shorad", "m-shorad", "strike missile",
        "ballistic missile", "jsm", "nsm", "anti-ship", "anti-tank", "interceptor", "nlaw",
        "javelin", "hellfire", "jagm", "apkws", "laser-guided", "lrasm", "amraam", "aim-120",
        "aim-260", "aim-424", "agm-158", "sm-2", "sm-3", "sm-6", "asbm"],
    "precision components & forgings": ["forged", "machined", "machining", "armour steel",
                                        "armor steel", "armox", "barrel", "casting",
                                        "titanium"],
}

_CAT_KW = None
_LINE_RX = None        # [(label, source, compiled regex)] -- source is "file" or "keyword"
_MODIFIER_RX = None


def _cat_keywords():
    """CAT_META keyword lists, keyed by the display category name.

    Loaded once. These are the words that say an article IS about a KSSL line, and they
    exist only to CANCEL an off-portfolio hit -- never to demand one.
    """
    global _CAT_KW
    if _CAT_KW is None:
        _CAT_KW = {}
        try:
            ref = json.loads((HERE.parent / "reference_dataset.json").read_text(
                encoding="utf-8"))
            meta = ref.get("CAT_META", {})
            for key, m in meta.items():
                label = (m.get("label") or "").lower()
                kws = [str(w).lower() for w in (m.get("kw") or []) if str(w).strip()]
                if label:
                    _CAT_KW[label] = kws
        except Exception as e:                                        # noqa: BLE001
            print("off_portfolio: CAT_META unavailable (%s) -- override disabled" % e,
                  flush=True)
            _CAT_KW = {}
    return _CAT_KW


def _term_rx(terms):
    """One regex for a list of terms: whole-word, plural-tolerant, hyphen/space-tolerant.

    A term ending in a digit ("155", "5.56", "ak-203") is closed by a non-digit so that
    "155mm" and "5.56x45" still match; a word term may take an s/es plural. Whole-word
    on BOTH sides: `isr` no longer reaches "Israeli", `marg` no longer reaches "margin".
    """
    parts = []
    for t in sorted(set(t.strip().lower() for t in terms if t and t.strip()), key=len,
                    reverse=True):
        body = r"[\s-]+".join(re.escape(p) for p in re.split(r"[\s-]+", t) if p)
        if re.fullmatch(r"[\d.]+", t):
            # a bare number ("155", "5.56") is a calibre only next to its unit or its
            # case length -- "$155M radar contract" must not rescue itself
            parts.append(body + r"(?:\s*mm\b|\s*[x×]\s*\d|/\d)")
        elif t[-1].isdigit():
            parts.append(body + r"(?!\d)")
        else:
            parts.append(body + r"(?:e?s)?(?![\w-])")
    if not parts:
        return None
    # A hyphen BEFORE the term is allowed ("micro-drone", "mini-UAV" are drones); a hyphen
    # AFTER it is not ("drone-mounted radar", "vehicle-mounted radar" are about the radar).
    return re.compile(r"(?<![\w$€£.,])(?:" + "|".join(parts) + r")", re.I)


def _line_rxs():
    """-> [(label, source, rx)]: the client's file anchors first, then CAT_META keywords
    (minus the dropped words, plus the corpus names). Built once."""
    global _LINE_RX, _MODIFIER_RX
    if _LINE_RX is None:
        out = []
        all_terms = []
        for label, anchors in _portfolio.ANCHORS.items():
            rx = _term_rx(anchors)
            if rx:
                out.append((label.lower(), "file", rx))
                all_terms.extend(anchors)
        for label, kws in _cat_keywords().items():
            terms = [k for k in kws if k not in _OVERRIDE_DROP] + _OVERRIDE_ADD.get(label, [])
            rx = _term_rx(terms)
            if rx:
                out.append((label, "keyword", rx))
                all_terms.extend(terms)
        _LINE_RX = out
        # An anchor that directly MODIFIES a negative term describes the foreign thing
        # ("submarine combat system", "missile radar", "armoured vehicle cameras") and
        # must not rescue it. Built from the same vocabulary.
        # ATOMIC, so the longest anchor at a position is the only one tried: without it
        # "Drone Jammer System" backtracks from "drone jammer" (a KSSL C-UAS product) to
        # "drone" + jammer and strips the very anchor that names the line.
        anchor_rx = _term_rx(all_terms)
        _MODIFIER_RX = (re.compile(r"(?>" + anchor_rx.pattern + r")\s+(?="
                                   + _OFF_PORTFOLIO_RX.pattern + r")", re.I)
                        if anchor_rx else None)
    return _LINE_RX


def _line_named(cat, text):
    """-> "file" | "keyword" | None: does this text name a KSSL line?

    ANY line, not only the card's own category: the LLM's label is the thing we already
    know is unreliable, and the client's loitering munition sits under UAVs while the
    model files Kalashnikov's under Missiles. `cat` is kept for callers and for the
    audit's per-category breakdown; it does not narrow the search.
    """
    if not text:
        return None
    rxs = _line_rxs()
    if _MODIFIER_RX is not None:
        text = _MODIFIER_RX.sub(" ", text)
    found = None
    for _label, source, rx in rxs:
        if rx.search(text):
            if source == "file":
                return "file"
            found = "keyword"
    return found


def off_portfolio(cat, text, title=None):
    """True when the SUBJECT is a product class KSSL has no line in.

    With a `title`, the headline is the subject: a negative term there with no KSSL
    line named there refuses the row; a negative term only in `text` (the body) is an
    accessory unless nothing anywhere names a line. Without a title (the old call
    shape) `text` is one blob and both tests run on it.

    Advisory in the same way the roster gate is: with no CAT_META the override falls
    back to the client's file anchors, never a crash.
    """
    if not text and not title:
        return False
    head = _subject_text(title or "")
    body = _subject_text(text or "")
    if title is None:
        if not _OFF_PORTFOLIO_RX.search(body):
            return False
        return _line_named(cat, body) is None
    if head.strip() and _OFF_PORTFOLIO_RX.search(head):
        return _line_named(cat, head) is None
    if body.strip() and _OFF_PORTFOLIO_RX.search(body):
        return _line_named(cat, head + " " + body) is None
    return False


def portfolio_evidence(cat, text, title=None):
    """-> "file" | "keyword" | None: what names the KSSL line in this row. For the audit's
    provenance column ("this judgement rests on the client's file" vs "on the keyword
    gate"); not a gate."""
    return _line_named(cat, _subject_text("%s %s" % (title or "", text or "")))


# Only the weapon forms: laser GUIDANCE steers KSSL's own shells and rockets.
_LASER_WEAPON_RX = re.compile(
    r"\b(laser weapons?|laser (?:weapon )?systems?|laser cannons?|high[- ]energy lasers?|"
    r"\d+ ?kw(?:-class)? lasers?|helws?|directed[- ]energy|high-energy)\b", re.I)


def category_conflict(cat, text, title=None):
    """fix4: True when the article's own words contradict the LLM's category pick.

    With a `title` the headline is judged (the body's helicopter is where a missile was
    fired from); without one, the whole text. A helicopter is a conflict for EVERY
    category unless the same headline names a KSSL line -- the AW249 the story is about
    versus the Apache a Spike was fired from.
    """
    c = (cat or "").lower()
    subj = _subject_text(title if title is not None else text)
    if title is not None and not subj.strip():
        subj = _subject_text(text)
    if _HELI_RX.search(subj) and _line_named(cat, subj) is None:
        return True
    # A laser weapon filed under drones is usually a counter-UAS story. The client's list
    # HAS a Counter-UAS mobile system, so the same override applies: "DRDO vehicle-mounted
    # counter-drone system with high-energy laser and gun" stays, DragonFire alone does not.
    if (_LASER_WEAPON_RX.search(subj) and ("drone" in c or "uav" in c)
            and _line_named(cat, subj) is None):
        return True
    if _AUTOCANNON_RX.search(subj) and (c == "small arms" or "drone" in c or "uav" in c):
        return True
    if re.search(r"\b(aew&?c|early[- ]warning|awacs|maritime patrol aircraft|globaleye)\b",
                 subj, re.I) and ("drone" in c or "uav" in c):
        return True                      # an AEW&C aircraft is not a drone
    return False


def company_grounded(company, props):
    """fix5: the company name (or a distinctive token of it) must appear in the evidence."""
    if not props:
        return True
    toks = [t for t in re.findall(r"[A-Za-z0-9]+", company or "") if len(t) > 2]
    if not toks:
        return False
    hay = " ".join("%s %s %s" % (pr[0], pr[2], pr[4] or "") for pr in props).lower()
    return any(t.lower() in hay for t in toks)


def find_competitor(text, comp_patterns):
    """fix2b: the known competitor named in the TITLE or evidence -- recovers the maker when
    the LLM put the government BUYER in the company field ('Elbit awarded ...' -> Israel MoD)."""
    if not comp_patterns or not text:
        return None
    for rx in comp_patterns:
        mm = rx.search(text)
        if mm:
            return mm.group(0)
    return None


def parse_card(raw, cats, props=None, comp_patterns=None, known_rx=None):
    """-> dict or None. The 7B writes the prose; this function CLASSIFIES in code, because
    every rule left to the model in-prompt (pillar, dir, category, KSSL tie) is violated."""
    if not raw or raw.strip().upper().startswith("NONE"):
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    pillar = str(d.get("pillar") or "").strip().lower()
    if pillar not in ("competitive", "market", "technology"):
        return None
    title = str(d.get("title") or "").strip()
    company = str(d.get("company") or "").strip().strip(",.;:'\"“” ")
    cat = str(d.get("category") or "").strip()
    direction = str(d.get("dir") or "").strip().lower()
    whatv = str(d.get("what") or "").strip()
    sowhat = strip_kssl_tail(str(d.get("sowhat") or "").strip())      # fix1
    if not title or not company or not sowhat:
        return None
    if cat not in cats:
        return None
    ev = (whatv + " " + title)
    if _NONLATIN_RX.search(title + " " + company + " " + sowhat):
        return None                      # the model failed to output English -> unusable in UI
    # The HEADLINE is the subject and `what` is the body: a radar in the body of a
    # howitzer story is an accessory, a camera in the headline is the story.
    if category_conflict(cat, whatv, title=title):
        return None                      # fix4: helicopter-in-armoured, laser-in-drones, etc.
    if off_portfolio(cat, whatv, title=title):
        return None                      # fix6: cameras, satellites, software, field hospitals
    # fix2: recover the MAKER when the LLM named a force (buyer/customer) as the actor, and
    # make an award/partnership/expansion COMPETITIVE. Search the TITLE too -- the winner is
    # usually in the headline ('Elbit awarded ...') even when the company field holds the buyer.
    is_event = bool(_EVENT_RX.search(ev))
    blob = title + " " + whatv + " " + " ".join("%s %s" % (pr[0], pr[2]) for pr in (props or []))
    if is_buyer(company):
        # recover the maker ONLY as a KNOWN company named in the title/evidence -- never a
        # title regex (which grabbed 'SPY-6' and 'Japan Awarding Contract'). No known maker in
        # the evidence -> leave the buyer; a buyer-named market card is honest, inventing a
        # maker from world knowledge would break the no-fabrication contract.
        maker = find_competitor(blob, known_rx or comp_patterns)
        if maker and not is_buyer(maker):
            company = maker
            pillar = "competitive" if is_event else "technology"
    elif is_event:
        pillar = "competitive"
    if not is_one_org(company):
        return None
    if fold_name(company) in country_names() or company.strip().lower() in _EXTRA_COUNTRY:
        return None
    if pillar in ("competitive", "technology") and is_force(company):
        return None
    if is_org_fragment(company) or not company_grounded(company, props):
        return None                      # fix5: NER fragment / ungrounded company name
    if not (company[:1].isupper() or company[:1].isdigit()):
        return None                      # 'three defense newcomers' is not a proper org name
    if company.strip().lower() in _CITIES:
        return None                      # 'Tokyo' is a metonym for a government, not a company
    if is_filler(sowhat) or not _has_concrete(sowhat):
        return None
    company = canon_name(company).strip().rstrip(" ,;.")     # fix5: no trailing punctuation
    if not company:
        return None
    # fix3: threat only for a concrete GAIN by a rival IN A CORE KSSL LINE; a rival gaining in
    # missiles or naval (which KSSL does not make) is watch, and so is a demo/announcement.
    gain = bool(_GAIN_RX.search(ev))
    # A label is not a subject. "Leonardo DRS ... 50,000 Thermal Imaging Cameras"
    # carried cat="UAVs & Drones", so in_core was True, _GAIN_RX matched "contract"
    # and Leonardo is on the roster -- three greens and a red badge for a camera deal.
    in_core = cat.lower() in _CORE_CATS and not off_portfolio(cat, whatv, title=title)
    if direction == "threat" and not (gain and pillar == "competitive" and in_core):
        direction = "watch"
    elif gain and pillar == "competitive" and in_core:
        direction = "threat"
    if direction not in ("threat", "watch"):
        direction = "watch"
    # A company nobody chose to track cannot be a threat, however good its news. The
    # evidence test above still decides whether a CURATED rival's news is a threat --
    # this only removes the rest, so the badge means "one of my 50 won something in a
    # line I sell". Advisory: with no allowlist, on_roster() is False for everyone and
    # the gate is skipped rather than demoting the world.
    if direction == "threat" and roster.keys() and not roster.on_roster(company):
        direction = "watch"
    return {"pillar": pillar, "title": title[:120], "company": company[:80],
            "category": cat, "dir": direction, "sowhat": sowhat[:500], "what": whatv[:400]}


def _monthval(ago):
    if not ago:
        return 0
    parts = str(ago).split()
    if len(parts) == 2 and parts[0][:3].lower() in _MONTHS:
        return int(parts[1]) * 12 + _MONTHS[parts[0][:3].lower()]
    try:
        return int(parts[0]) * 12
    except ValueError:
        return 0


def order_group(company, comp_patterns):
    """0 = a known KSSL competitor (rivals lead the competitive feed),
    1 = KSSL/client itself, 2 = anyone else."""
    if is_client(company):
        return 1
    if any(rx.search((company or "").lower()) for rx in comp_patterns):
        return 0
    return 2


PILLAR_WORD = {"competitive": "COMPETITIVE", "market": "MARKET", "tech": "TECHNOLOGY"}


def reorder_all(cur, con, comp_patterns):
    """Ord AND the visible rank badges are renumbered from the served position --
    a badge numbered by an internal ordinal that counts archived rows is noise."""
    for lane, word in PILLAR_WORD.items():
        cur.execute("""SELECT id, company, ago FROM serving.signal_card
                        WHERE origin='pipeline' AND lane=%s""", (lane,))
        rows = cur.fetchall()
        if lane == "competitive":
            key = lambda r: (order_group(r[1], comp_patterns), -_monthval(r[2]), r[0])
        else:
            key = lambda r: (-_monthval(r[2]), r[0])
        for i, r in enumerate(sorted(rows, key=key), start=1):
            cur.execute("UPDATE serving.signal_card SET ord=%s, rank=%s WHERE id=%s",
                        (i, str(i).zfill(2), r[0]))
            cur.execute("UPDATE serving.signal_detail SET ord=%s, rank=%s WHERE id=%s",
                        (i, "%s SIGNAL · %02d" % (word, i), r[0]))
    con.commit()


def fill(dsn=DSN, limit=None, verbose=True, only=None):
    import psycopg2
    cats = kssl_cats()
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    # deployment: a marker so documents the model judged NOT-a-signal are not
    # re-run on every loop (the base query only skips docs that produced a card).
    cur.execute("CREATE TABLE IF NOT EXISTS serving.signal_seen (document_id text PRIMARY KEY, at timestamptz DEFAULT now())")
    con.commit()
    # documents not yet turned into a card or a recorded refusal
    # `only` names one document. The bench needs it: submitting one article and
    # then processing whatever happens to be oldest is not "process this
    # article".
    cur.execute("""SELECT d.document_id, d.title, d.source_id, d.language, d.url,
                          d.meta->>'set'
                     FROM extracted.document d
                    WHERE NOT EXISTS (SELECT 1 FROM serving.signal_card c
                                       WHERE c.id = 'pl_' || d.document_id)
                      AND NOT EXISTS (SELECT 1 FROM serving.signal_seen s
                                       WHERE s.document_id = d.document_id)
                      AND (%s IS NULL OR d.document_id = %s)
                    ORDER BY d.document_id LIMIT %s""",
                (only, only, limit or 10 ** 9))
    docs = cur.fetchall()
    if verbose:
        print("%d document(s) to process with %s" % (len(docs), MODEL), flush=True)

    # next ord per lane, after whatever each lane already holds
    ords = {}
    for lane in ("competitive", "market", "tech"):
        cur.execute("SELECT coalesce(max(ord), 0) FROM serving.signal_card WHERE lane=%s",
                    (lane,))
        ords[lane] = cur.fetchone()[0] + 1
    stats = {"cards": 0, "none": 0, "thin": 0, "bad": 0, "stale": 0, "cstale": 0,
             "claimed": 0,
             "offtopic": 0, "undated": 0, "dup": 0, "client_news": 0, "listing": 0,
             "suppressed": 0, "images": 0}
    patterns, comp_patterns = load_terms()
    cutoff, cur_year = recent_cutoff()
    LANE = {"competitive": "competitive", "market": "market", "technology": "tech"}
    banned = suppressed_ids()
    # fix2: comprehensive known-company matcher for maker recovery -- the buyer/force sits in
    # the company field while the real maker is in the title ('Elbit awarded ...').
    cur.execute("SELECT DISTINCT name FROM serving.competitors "
                "WHERE name IS NOT NULL AND length(name) > 3")
    known_rx = [re.compile(r"(?<!\w)" + re.escape(nm) + r"(?!\w)", re.I)
                for (nm,) in cur.fetchall() if nm]
    cur.execute("""SELECT company, title, sowhat FROM serving.signal_card
                    WHERE origin='pipeline'""")
    _rows = cur.fetchall()
    seen = [((c or "").casefold(), title_tokens(t)) for c, t, _s in _rows]
    # fix3: (canonical company, amount) keys -> the same award via two outlets = one card.
    # Seed from the ALREADY-STORED cards so a duplicate is caught across runs (the loop +
    # one-off batches each start a fresh fill(); without this the same award slips a later run).
    seen_money = set()
    for c, t, sw in _rows:
        mk = money_key(c or "", "%s %s" % (t or "", sw or ""), known_rx)
        if mk:
            seen_money.add(mk)

    for did, title, source, lang, url, dset in docs:
        # CLAIM the document, do not merely note it. Every piece of a lease was already
        # here -- signal_seen is a PRIMARY KEY table, the query above excludes anything in
        # it, and an LLM failure DELETEs the row to hand the document back -- except the one
        # line that makes it work with more than one process: nobody checked whether they
        # won the insert. Two fillers would both take the same document, pay for the same
        # model call twice and race to write the same card. With the check, N containers
        # divide the queue between them and the farm sees N requests in flight instead of 1.
        cur.execute("INSERT INTO serving.signal_seen(document_id) VALUES(%s) "
                    "ON CONFLICT DO NOTHING", (did,))
        if cur.rowcount == 0:
            stats["claimed"] = stats.get("claimed", 0) + 1
            continue
        # Publish the claim BEFORE the slow part. Held in an uncommitted transaction until
        # the card is written, it is invisible to the other fillers for the whole length of
        # the model call -- which is exactly the window the claim exists to cover.
        con.commit()
        if did in banned:
            stats["suppressed"] += 1
            continue
        cur.execute("""SELECT subject, predicate, object, modality, ev_quote
                         FROM extracted.proposition WHERE document_id=%s ORDER BY i""",
                    (did,))
        props = cur.fetchall()
        if not props:
            stats["thin"] += 1
            continue
        # A listing is caught by its URL shape OR by the publisher naming its own
        # page an index ("... News & Press Releases"). The title check exists
        # because a URL-only rule always eventually meets a listing at a path
        # nobody anticipated -- which is how three /company/<id> pages became
        # cards, one of them merging two unrelated articles into a single claim.
        if is_listing(url) or is_index_title(title):
            stats["listing"] += 1
            continue
        ymd = article_date(cur, did)
        if ymd is None:
            stats["undated"] += 1
            continue
        if not is_recent_ym(ymd[:2], cutoff, cur_year):
            stats["stale"] += 1
            continue
        # Content-staleness: a fresh publish date on a years-old story (a re-run article) is
        # the fastest way to lose trust -- the Leonardo/BIDEC-2017 card dated 2026. Flag only
        # when the CONTENT is unambiguously old: the newest year across the quotes is >=3
        # years before the article's own year, so a single stale background reference in an
        # otherwise-current story is not enough to drop it.
        cy = content_year_max(props)
        if cy is not None and cy <= ymd[0] - 3:
            stats["cstale"] = stats.get("cstale", 0) + 1
            continue
        if not is_relevant(patterns, title, props):
            stats["offtopic"] += 1
            continue
        props = props[:12]
        lines = "\n".join("- %s %s %s [%s] -- \"%s\"" % (s, p, o, m, (q or "")[:180])
                          for s, p, o, m, q in props)
        try:
            raw = ask(PROMPT % (", ".join(cats), title or did, source, lang, lines))
        except Exception as e:                                    # noqa: BLE001
            stats["bad"] += 1
            if stats["bad"] <= 3:
                print("  %s: %s" % (did, e), flush=True)
            cur.execute("DELETE FROM serving.signal_seen WHERE document_id=%s", (did,))
            con.commit()
            continue
        card = parse_card(raw, cats, props, comp_patterns, known_rx)
        if card is None:
            stats["none"] += 1
            continue
        card["company"] = canon_name(card["company"])[:80]
        # The client's own move is not intelligence about anyone. Excluding it from
        # the COMPETITIVE lane only was half a rule: the TECHNOLOGY lane is the same
        # kind of surface -- "capability signals, sorted threats first" -- and it was
        # running at five client announcements out of ten, one of them the client's
        # own Simha 4x4 filed twice under a partner's name.
        if is_client(card["company"]) or client_led(card["title"]):
            card["dir"] = "watch"          # the client's own win is not a threat to itself
            if card["pillar"] in ("competitive", "technology"):
                stats["client_news"] += 1  # rivals only on the rival surfaces
                continue
        if is_dup(seen, card["company"], card["title"]):
            stats["dup"] += 1
            continue
        mkey = money_key(card["company"], "%s %s" % (card["title"], card["sowhat"]), known_rx)
        if mkey and mkey in seen_money:
            stats["dup"] += 1              # same company + same dollar figure = same event
            continue
        if mkey:
            seen_money.add(mkey)
        seen.append((card["company"].casefold(), title_tokens(card["title"])))
        lane = LANE[card["pillar"]]
        ord_next = ords[lane]
        ords[lane] += 1

        cid = "pl_" + did
        company_chip = card["company"].replace("·", "-")  # the meta chip splits on the dot
        sec = [{"lens": "EVIDENCE",
                "read": esc("%s %s %s -- \"%s\"" % (s, p, o, clip(q, 200)))}
               for s, p, o, _m, q in props[:3]]
        img = card_image(did, url)
        if img:
            stats["images"] += 1
        cur.execute("""INSERT INTO serving.signal_card
                         (id, lane, ord, dir, rank, title, meta, company, lens, sowhat, sec,
                          url, ago, tags, image, origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               'pipeline')
                       ON CONFLICT (id) DO UPDATE SET
                         lane=EXCLUDED.lane, dir=EXCLUDED.dir, title=EXCLUDED.title,
                         meta=EXCLUDED.meta, company=EXCLUDED.company,
                         sowhat=EXCLUDED.sowhat, sec=EXCLUDED.sec, url=EXCLUDED.url,
                         ago=EXCLUDED.ago, tags=EXCLUDED.tags,
                         -- a run that cannot reach the corpus must not wipe a
                         -- picture an earlier run already proved good
                         image=coalesce(EXCLUDED.image, serving.signal_card.image),
                         updated_at=now()""",
                    (cid, lane, ord_next, card["dir"], str(ord_next).zfill(2),
                     esc(card["title"]),
                     esc("%s · %s · from %s" % (card["category"], company_chip, source)),
                     esc(card["company"]), card["pillar"].capitalize(),
                     esc(card["sowhat"]), json.dumps(sec), url,
                     ago_of(ymd[:2]), card["category"], img))
        # No "Primary lens" row: the pillar is the coloured pill in the panel header and
        # the dirtag on the feed row, so a fourth statement of it was the redundancy the
        # client complained about. The rows that follow Company/Category/Date come from
        # the document's typed spans -- deal value, quantity, counterparty, programme,
        # system, key person -- each with the sentence that proves it (see glance.py).
        facts = [["Company", esc(card["company"])], ["Category", card["category"]],
                 ["Date", date_label(ymd)]]
        facts += glance_rows(cur, did, card["company"], card["title"], stats)
        # THE LEAD-IN IS TRANSLATED; THE QUOTE NEVER IS. `ev_quote` is located in the
        # article by offset, so it is provably the publisher's sentence -- translating
        # it would put words inside quotation marks that nobody wrote. subject /
        # predicate / object are not located at all: comprehend asks for "a SHORT
        # phrase" and caps them, so they are the extraction model's own paraphrase, and
        # its language is unspecified by that prompt. That is why the served rows read
        # "sette veicoli ruotati 8x8 Centauro II are forniti" -- an English verb welded
        # to an Italian subject. Translating a paraphrase invents nothing.
        lead = ["%s %s %s" % (s, p, o) for s, p, o, _m, q in props[:6]]
        lead = translate.translate_lines(lead, lang, keep=product_names(cur, did),
                                         stats=stats)
        s0, p0, o0 = props[0][0], props[0][1], props[0][2]
        what = esc(card["what"] or (lead[0] + "." if lead else "%s %s %s." % (s0, p0, o0)))
        lens = [["STATEMENT", "%s — %s" % (esc(lead[i]), quote_html(q, lang))]
                for i, (s, p, o, _m, q) in enumerate(props[:6])]
        cur.execute("""INSERT INTO serving.signal_detail
                         (id, ord, rank, dir, title, facts, what, why, lens, actions, url,
                          suggest, image, origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'[]',%s,'[]',%s,'pipeline')
                       ON CONFLICT (id) DO UPDATE SET
                         title=EXCLUDED.title, facts=EXCLUDED.facts, what=EXCLUDED.what,
                         why=EXCLUDED.why, lens=EXCLUDED.lens, url=EXCLUDED.url,
                         -- same guard as the card: a run that cannot reach the corpus
                         -- must not wipe a picture an earlier run already proved good
                         image=coalesce(EXCLUDED.image, serving.signal_detail.image),
                         updated_at=now()""",
                    (cid, ord_next, "%s SIGNAL · %02d" % (card["pillar"].upper(), ord_next),
                     card["dir"],
                     esc(card["title"]), json.dumps(facts), what, esc(card["sowhat"]),
                     json.dumps(lens), url, img))
        con.commit()
        stats["cards"] += 1
        if verbose and stats["cards"] % 5 == 0:
            print("  %(cards)d card(s), %(none)d none, %(thin)d thin, %(bad)d error" % stats,
                  flush=True)

    con.commit()
    reorder_all(cur, con, comp_patterns)
    con.close()
    if verbose:
        print("done: %(cards)d card(s) written, %(none)d judged not-a-signal, "
              "%(thin)d without propositions, %(stale)d dated too old, "
              "%(cstale)d stale-content, "
              "%(undated)d with no provable date, %(offtopic)d off-portfolio, "
              "%(dup)d duplicate stor(ies), %(client_news)d client-news (not competitive), "
              "%(listing)d listing page(s), %(suppressed)d suppressed, "
              "%(bad)d error(s), %(claimed)d taken by another filler" % stats, flush=True)
    return stats


def quote_html(q, language=None):
    """The publisher's own sentence, marked with the language it is in.

    `lang=` is the semantically correct marker -- screen readers switch voice on it,
    the browser hyphenates by it, and the font stack falls back by it -- and it costs
    the frontend nothing: statementRows passes the string through unchanged."""
    lang = (language or "").strip().lower()[:5]
    tag = ' lang="%s"' % esc(lang) if lang and lang != "en" else ""
    return "<i%s>&ldquo;%s&rdquo;</i>" % (tag, esc(q or ""))


def product_names(cur, did):
    """This document's own product and platform spans, for the translator's keep-list.

    Polish armoured vehicles are animals almost as a rule -- Rosomak is a wolverine,
    Borsuk a badger -- and so are the German and Hebrew ones. A translator that does
    not know Rosomak is a vehicle turns an armoured column into a zoo. These spans are
    offset-exact, so they are the document's own evidence of what its product names
    are, not a guess."""
    try:
        cur.execute("""SELECT DISTINCT text FROM extracted.span
                        WHERE document_id=%s AND type IN ('Product','WeaponSystem','Platform')
                          AND length(text) BETWEEN 3 AND 40""", (did,))
        return [r[0] for r in cur.fetchall()]
    except Exception:                                              # noqa: BLE001
        return []


def glance_rows(cur, did, company, title, stats=None):
    """The typed-span rows of "At a glance" for one document: [[label, value, quote], ...].

    Reads the document's propositions WITH their evidence offsets and the spans of the
    types glance.py knows how to gate, and lets glance_facts decide. Every candidate the
    gate refuses is counted into stats['glance_refused'] -- if that number ever reads
    near zero across a run, the gate has stopped working, not the corpus."""
    cur.execute("""SELECT i, subject, predicate, object, ev_start, ev_end, ev_quote
                     FROM extracted.proposition WHERE document_id=%s ORDER BY i""", (did,))
    props = cur.fetchall()
    cur.execute("""SELECT span_id, start_c, end_c, text, type, type_ner, gloss, in_article,
                          source, score, sent
                     FROM extracted.span WHERE document_id=%s AND type = ANY(%s)
                    ORDER BY start_c""", (did, list(glance.FACT_SPAN_TYPES)))
    spans = cur.fetchall()
    # The article itself, because span offsets index it exactly: a span no proposition
    # happened to cover is still quotable from its own sentence (glance._own_prop).
    cur.execute("SELECT text FROM extracted.document WHERE document_id=%s", (did,))
    got = cur.fetchone()
    refused = {}
    rows = glance.glance_facts(company, title, props, spans, is_buyer=is_buyer,
                               refused=refused, esc=esc, article=got[0] if got else None)
    if stats is not None:
        stats["glance_rows"] = stats.get("glance_rows", 0) + len(rows)
        stats["glance_refused"] = stats.get("glance_refused", 0) + sum(refused.values())
    return rows


def retranslate(dsn=DSN, limit=None, verbose=True, only=None, apply=False):
    """English lead-ins for cards ALREADY served. The forward path only reaches tomorrow's.

    fill() selects documents with NO signal_card and NO signal_seen row, so a card is
    written once and never revisited -- exactly the reason `reglance` exists, and this
    is shaped like it. Without this pass, integrating the translator changes nothing a
    reader can see: 311 of 949 served cards come from a non-English document (192 with
    a language recorded, 119 whose document row has since been pruned).

    Rebuilds `lens` in place from the stored propositions. The quote is re-emitted from
    the same source, so a card that needs no translation is rewritten byte-identically
    and reports as unchanged."""
    import psycopg2
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("""SELECT d.id, doc.language::text
                     FROM serving.signal_detail d
                     LEFT JOIN extracted.document doc
                            ON doc.document_id = substring(d.id from 4)
                    WHERE d.origin='pipeline' AND d.id LIKE 'pl\\_%%'
                      AND (%s IS NULL OR d.id = %s)
                    ORDER BY d.id LIMIT %s""", (only, only, limit or 10 ** 9))
    cards = cur.fetchall()
    stats = {"cards": len(cards), "changed": 0}
    for cid, lang in cards:
        did = cid[3:]
        cur.execute("""SELECT subject, predicate, object, ev_quote
                         FROM extracted.proposition WHERE document_id=%s
                        ORDER BY i LIMIT 6""", (did,))
        props = cur.fetchall()
        if not props:
            continue
        lead = translate.translate_lines(["%s %s %s" % (s, p, o) for s, p, o, _q in props],
                                         lang, keep=product_names(cur, did), stats=stats)
        lens = [["STATEMENT", "%s — %s" % (esc(lead[i]), quote_html(q, lang))]
                for i, (_s, _p, _o, q) in enumerate(props)]
        # AND THE PROSE, WHICH WAS ALREADY SUPPOSED TO BE ENGLISH. The card prompt says
        # "Write title, what and sowhat in ENGLISH, whatever language the statements
        # are in", and mostly the model obeys -- 0 of 949 titles are foreign. Mostly:
        # 5 served rows are Dutch or German prose ("Defensie en Thales Nederland hebben
        # een strategische samenwerking gesloten"). These are the model's own words,
        # under no verbatim rule, so they are translated like the lead-in. Each field
        # is judged on its own string, so an English one costs nothing.
        cur.execute("""SELECT d.lens, d.what, d.why, c.sowhat
                         FROM serving.signal_detail d
                         LEFT JOIN serving.signal_card c ON c.id = d.id
                        WHERE d.id=%s""", (cid,))
        old_lens, old_what, old_why, old_sowhat = cur.fetchone()
        old_lens = old_lens if isinstance(old_lens, list) else json.loads(old_lens or "[]")
        prose = translate.translate_lines([old_what or "", old_why or "", old_sowhat or ""],
                                          lang, stats=stats)
        what2, why2, sowhat2 = prose
        if old_lens == lens and (what2, why2, sowhat2) == (old_what or "", old_why or "",
                                                           old_sowhat or ""):
            continue
        stats["changed"] += 1
        if verbose:
            print("  %s [%s]" % (cid, lang or "?"), flush=True)
            for a, b in zip(old_lens, lens):
                if a != b:
                    print("    - %s" % str(a[1])[:110])
                    print("    + %s" % str(b[1])[:110])
            for nm, a, b in (("what", old_what, what2), ("why", old_why, why2),
                             ("sowhat", old_sowhat, sowhat2)):
                if (a or "") != b:
                    print("    - %s: %s" % (nm, str(a)[:100]))
                    print("    + %s: %s" % (nm, str(b)[:100]))
        if apply:
            cur.execute("""UPDATE serving.signal_detail
                              SET lens=%s, what=%s, why=%s, updated_at=now()
                            WHERE id=%s""", (json.dumps(lens), what2, why2, cid))
            if old_sowhat is not None and sowhat2 != old_sowhat:
                cur.execute("""UPDATE serving.signal_card SET sowhat=%s, updated_at=now()
                                WHERE id=%s""", (sowhat2, cid))
            # COMMIT PER CARD. A single commit after the loop meant a pass that died --
            # or was simply still running -- had written nothing at all: 104 cards and
            # 25 minutes of model work sat in an open transaction, invisible, and a
            # timeout would have discarded every one of them. This is the same shape
            # step_partnerships was fixed for, reproduced here. The entrypoint runs this
            # with --limit 200 every signals cycle, so the window was ~25 minutes of
            # work per cycle riding on nothing going wrong. Each card is independent,
            # so each card is its own unit of progress.
            con.commit()
    if apply:
        con.commit()                      # anything the last card left open
    print("retranslate: %d card(s) scanned, %d rewritten; lines %s%s"
          % (stats["cards"], stats["changed"],
             {k: v for k, v in sorted(stats.items()) if k not in ("cards", "changed")},
             "" if apply else "  (dry run -- nothing written)"), flush=True)
    con.close()
    return stats


# The rows every pipeline card already carried; everything after them is re-derived.
_BASE_FACTS = ("company", "category", "date")


def reglance(dsn=DSN, limit=None, verbose=True, only=None):
    """Re-derive the span rows for cards ALREADY stored (fill() only ever visits documents
    with no card, so a gate change would otherwise reach only tomorrow's cards). Keeps
    Company/Category/Date as stored, drops Primary lens, appends the span rows."""
    import psycopg2
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("""SELECT d.id, c.company, c.title, d.facts
                     FROM serving.signal_detail d JOIN serving.signal_card c ON c.id = d.id
                    WHERE d.origin='pipeline' AND d.id LIKE 'pl_%%'
                      AND (%s IS NULL OR d.id = %s)
                    ORDER BY d.id LIMIT %s""", (only, only, limit or 10 ** 9))
    cards = cur.fetchall()
    stats = {"cards": len(cards), "changed": 0, "with_rows": 0}
    for cid, company, title, facts in cards:
        old = facts if isinstance(facts, list) else json.loads(facts or "[]")
        base = [f for f in old if str(f[0]).strip().lower() in _BASE_FACTS]
        rows = glance_rows(cur, cid[3:], _html.unescape(company or ""), title, stats)
        new = base + rows
        if rows:
            stats["with_rows"] += 1
        if new != old:
            cur.execute("UPDATE serving.signal_detail SET facts=%s WHERE id=%s",
                        (json.dumps(new), cid))
            stats["changed"] += 1
        con.commit()
    con.close()
    if verbose:
        print("glance: %(cards)d card(s), %(with_rows)d with span rows, %(changed)d "
              "rewritten; %(glance_rows)d row(s) emitted, %(glance_refused)d candidate(s) "
              "refused" % {**{"glance_rows": 0, "glance_refused": 0}, **stats}, flush=True)
    return stats


def _demo():
    cats = ["Artillery", "Ammunition"]
    # `threat` is EARNED, not asserted by the model: parse_card grants it only for a
    # concrete gain, in the competitive pillar, in a core KSSL line. The evidence it reads
    # is the card's own what+title -- so a card claiming dir=threat with nothing but a
    # placeholder title is a rival announcement, and comes back as watch. This test used to
    # send exactly that and assert "threat", so it had been failing on every run.
    ok = parse_card('{"pillar":"competitive","title":"Saab wins a 12-gun order",'
                    '"company":"C","category":"Artillery","dir":"threat",'
                    '"sowhat":"Saab delivered 12 M4 guns."}', cats)
    assert ok and ok["dir"] == "threat", "a concrete gain in a core line is a threat"
    # ...and the same card with no gain in its evidence is not.
    nogain = parse_card('{"pillar":"competitive","title":"T","company":"C",'
                        '"category":"Artillery","dir":"threat",'
                        '"sowhat":"Saab delivered 12 M4 guns."}', cats)
    assert nogain and nogain["dir"] == "watch", \
        "threat without a stated gain must fall back to watch"
    # prose around the JSON is tolerated; garbage inside it is not
    assert parse_card('Sure! {"pillar":"market","title":"T","company":"C",'
                      '"category":"Artillery","dir":"watch","sowhat":"Saab delivered 12 M4 guns."} '
                      'hope that helps', cats)
    assert parse_card("NONE", cats) is None
    assert parse_card("", cats) is None
    assert parse_card('{"title":"T"}', cats) is None, "missing fields refuse"
    assert parse_card('{"pillar":"competitive","title":"T","company":"C",'
                      '"category":"Lasers","dir":"watch","sowhat":"Saab delivered 12 M4 guns."}', cats) is None,         "invented category refuses"
    bad_dir = parse_card('{"pillar":"technology","title":"T","company":"C",'
                         '"category":"Ammunition","dir":"URGENT","sowhat":"Saab delivered 12 M4 guns."}', cats)
    assert bad_dir and bad_dir["dir"] == "watch", "unknown dir falls to watch, not to threat"
    # audit H4: one identity, one organization, never a bare country
    bf = parse_card('{"pillar":"technology","title":"T","company":"Bharat Forge Limited",'
                    '"category":"Artillery","dir":"watch","sowhat":"Saab delivered 12 M4 guns."}', cats)
    assert bf and bf["company"] == "Kalyani Strategic Systems",         "the card company is canonicalised at the parser, not at the writer"
    assert parse_card('{"pillar":"competitive","title":"T","company":"Arquus and Daimler '
                      'Truck","category":"Artillery","dir":"watch","sowhat":"Saab delivered 12 M4 guns."}',
                      cats) is None, "two orgs jammed into one company field refuse"
    for bare in ("Thailand", "Australia", "India", "United States"):
        assert parse_card('{"pillar":"market","title":"T","company":"%s",'
                          '"category":"Artillery","dir":"watch","sowhat":"Saab delivered 12 M4 guns."}' % bare,
                          cats) is None, "a bare country is not the acting organization"
    agency = parse_card('{"pillar":"market","title":"T","company":"US Department of '
                        'State","category":"Artillery","dir":"watch","sowhat":"Saab delivered 12 M4 guns."}', cats)
    assert agency, "a NAMED agency is still a valid market-signal actor"
    # a force/ministry is a MARKET actor (a buyer), never a rival maker on the COMPETITIVE
    # or TECHNOLOGY surface (the U.S. Army card the UI showed was filed under technology)
    for body in ("U.S. Army", "Indian Army", "Ministry of Defence", "Pentagon"):
        for rival_pillar in ("competitive", "technology"):
            assert parse_card('{"pillar":"%s","title":"T","company":"%s",'
                              '"category":"Artillery","dir":"threat","sowhat":"Saab delivered 12 M4 guns."}'
                              % (rival_pillar, body), cats) is None, \
                "gov/military body is not a rival maker (%s): %s" % (rival_pillar, body)
        assert parse_card('{"pillar":"market","title":"T","company":"%s",'
                          '"category":"Artillery","dir":"watch","sowhat":"Saab delivered 12 M4 guns."}' % body,
                          cats), "...but the same body IS a valid market actor: %s" % body
    # generic filler in sowhat is the prompt's own NONE case -- gated, not trusted
    assert parse_card('{"pillar":"market","title":"T","company":"Saab","category":"Artillery",'
                      '"dir":"watch","sowhat":"This could potentially impact the market."}',
                      cats) is None, "generic filler sowhat is refused"
    assert len(kssl_cats()) == 9
    assert esc('<b>&"x"') == "&lt;b&gt;&amp;\"x\"", "HTML must be escaped, quotes kept readable"
    assert clip("abcdef", 4).endswith("…") and clip("abc", 4) == "abc"
    pats, _ = load_terms()
    assert is_relevant(pats, "Saab wins order", []), "competitor name must match"
    assert is_relevant(pats, "", [("army", "orders", "howitzer shells")]), "category keyword in props"
    assert not is_relevant(pats, "Football transfer news", [("club", "signs", "player")])
    assert not is_relevant(pats, "Business update", [("firm", "buys", "abusive stake")]),         "no substring matches inside words"
    assert "2026" in "۲۰۲۶".translate(_NATIVE_DIGITS), "native digits normalise"
    assert parse_date("03/07/2024") == (2024, 7, 3), "the Leonardo JV card: d/m/y parses"
    assert parse_date("July 3, 2024") == (2024, 7, 3)
    assert parse_date("28 May 2026") == (2026, 5, 28)
    assert parse_date("2026-08-06") == (2026, 8, 6)
    assert parse_date("06.08.2026") == (2026, 8, 6)
    assert parse_date("May 2026") == (2026, 5, None)
    assert parse_date("year 2025") == (2025, None, None)
    assert parse_date("next week") is None
    assert date_label((2026, 5, 28)) == "28 May 2026"
    assert date_label((2026, 5, None)) == "May 2026" and date_label((2026, None, None)) == "2026"
    cut, cy = recent_cutoff(__import__("datetime").date(2026, 8, 24))
    assert not is_recent_ym((2024, 7), cut, cy), "a July-2024 article must be excluded"
    assert not is_recent_ym(parse_date("03/07/2024")[:2], cut, cy), "end to end: the caught card dies"
    assert is_recent_ym((2026, 8), cut, cy) and is_recent_ym((2026, None), cut, cy)
    assert not is_recent_ym((2026, 4), cut, cy), "April 2026 is outside the 92-day window"
    assert not is_recent_ym(None, cut, cy), "undated is excluded, not assumed recent"

    class _FakeCur:
        """Answers BOTH queries article_date makes: the metadata date, then the Date spans.

        The stub only had fetchall, so when article_date learned to read
        meta->>'published_at' this whole self-check began raising AttributeError instead of
        asserting -- a dead test that looked like a passing one until it was run by hand.

        Then it happened AGAIN: the query grew to three columns (url, published_at,
        fetched_at) and fetchone still handed back a 1-tuple, so the self-check died on
        IndexError. fetchone MUST return one value per column article_date selects; if that
        SELECT gains a column, this returns one more or the check breaks a third time.
        """
        def __init__(self, rows, published=None, url=None, fetched=None):
            self.rows, self.published = rows, published
            self.url, self.fetched = url, fetched
        def execute(self, *_): pass
        def fetchone(self): return (self.url, self.published, self.fetched)
        def fetchall(self): return self.rows

    # the crawler's proven publication date wins over anything in the body
    assert article_date(_FakeCur([("28 May 2026", None)], published="2026-07-14T09:00:00Z"),
                        "x", today_ym=(2026, 8)) == (2026, 7, 14),         "meta published_at is about the ARTICLE and beats a body Date span"
    # ...and a future metadata date is refused, falling back to the body
    assert article_date(_FakeCur([("28 May 2026", None)], published="2031-01-01T00:00:00Z"),
                        "x", today_ym=(2026, 8)) == (2026, 5, 28)
    fut = _FakeCur([("2040", None), ("by 2027", None), ("28 May 2026", None)])
    assert article_date(fut, "x", today_ym=(2026, 8)) == (2026, 5, 28),         "future forecast dates are skipped, the first plausible date wins"
    assert article_date(_FakeCur([("2040 vision", None)]), "x", today_ym=(2026, 8)) is None
    assert ago_of((2026, 8)) == "Aug 2026" and ago_of((2026, None)) == "2026"
    seen = [("brahmos aerospace", title_tokens("India Delivers First Batch of BRAHMOS Missiles to Philippines"))]
    assert is_dup(seen, "BrahMos Aerospace", "India delivers first BRAHMOS missile batch to the Philippines")
    assert is_dup(seen, "Saab", "India Delivers First Batch of BRAHMOS Missiles to Philippines"),         "an identical title is the same story even under a different company spelling (audit F4)"
    assert not is_dup(seen, "Saab", "Saab and BrahMos explore joint missile marketing in Manila"),         "a different story about the same topic is not a dup"
    assert not is_dup(seen, "BrahMos Aerospace", "BrahMos opens new production line in Lucknow")
    ok2 = parse_card('{"pillar":"market","title":"T","company":"C","category":"Artillery",'
                     '"dir":"watch","sowhat":"Saab delivered 12 M4 guns."}', ["Artillery"])
    assert ok2 and ok2["pillar"] == "market"
    assert parse_card('{"pillar":"nonsense","title":"T","company":"C",'
                      '"category":"Artillery","dir":"watch","sowhat":"Saab delivered 12 M4 guns."}',
                      ["Artillery"]) is None, "invented pillar refuses, never coerces"
    assert parse_card('{"title":"T","company":"C","category":"Artillery",'
                      '"dir":"watch","sowhat":"Saab delivered 12 M4 guns."}', ["Artillery"]) is None,         "missing pillar refuses"
    _, comp_rx = load_terms()
    assert order_group("Rheinmetall AG", comp_rx) == 0, "rivals lead"
    assert order_group("Kalyani Strategic Systems Limited", comp_rx) == 1, "client is not a rival"
    assert order_group("Unheard-of Corp", comp_rx) == 2
    assert is_client("Kalyani Strategic Systems") and is_client("Bharat Forge Ltd"),         "client detection covers the whole group"
    assert canon_name("Bharat Forge Limited") == canon_name("Kalyani"),         "the client group is ONE identity"
    assert _monthval("Aug 2026") > _monthval("2026") > _monthval(None)
    assert is_listing("https://defencesecurityasia.com/")
    assert is_listing("https://brahmos.com/brahmos-in-media?page=3")
    assert is_listing("https://defence-industry.eu/tag/rheinmetall")
    assert not is_listing("https://saab.com/newsroom/press-releases/2026/saab-receives-order")
    # Keeps the DAY as of 5b7a68a -- "an Italian article keeps its day". This assertion
    # still demanded the old month-only answer; it never failed visibly because the check
    # above it was already failing and the run never reached here.
    assert parse_date("2026 m. vasario 17 d.") == (2026, 2, 17), \
        "Lithuanian February parses, day and all"
    assert parse_date("2026 m. vasario") == (2026, 2, None), "no day stated, no day invented"
    assert parse_date("published 2026") == (2026, None, None), "no month word stays year-only"
    seen2 = [("kalyani strategic systems", title_tokens("KSSL and Paramount unveil Simha 4x4 armoured vehicle"))]
    assert is_dup(seen2, "Paramount/Kalyani Strategic Systems",
                  "KSSL and Paramount unveil the Simha 4x4 armoured vehicle"),         "same story with a differently-spelled company is still a dup"

    # "At a glance" span rows, through the same loader fill() and reglance() use. The
    # fixture is the real Stinger article: the Army's $215M budget ask is a row; the $4M a
    # missile costs (subject: the missiles) is refused, and counted as refused.
    q1 = ("The Army has asked Congress for $215 million in its fiscal year 2027 budget for "
          "the Stinger replacement along with $713 million for 14 more Sgt. Stout Systems.")
    q2 = ("U.S. air defense missiles — each of which can cost about $4 million — have "
          "been used to shoot down Iranian drones.")

    class _GlanceCur:
        # The article text is the third query, and it is what lets a span no proposition
        # covers still be quoted -- from its own sentence. `article=None` stands for a
        # document row that is missing, which must cost the other rows nothing.
        def __init__(self, article=q1 + " " + q2):
            self.n = 0
            self.article = article
        def execute(self, sql, *_):
            self.n += 1
        def fetchone(self):
            return (self.article,) if self.article is not None else None
        def fetchall(self):
            if self.n == 1:                                  # propositions, with offsets
                return [(0, "The Army", "asks for", "$215 million in its fiscal year 2027 budget",
                         0, len(q1), q1),
                        (1, "U.S. air defense missiles", "have been used to shoot down",
                         "Iranian drones", 1000, 1000 + len(q2), q2)]
            a, b, c = q1.index("$215"), q1.index("14 more"), 1000 + q2.index("$4 million")
            d = q1.index("Sgt. Stout Systems")
            return [("s1", a, a + 12, "$215 million", "Money", None, "a unit of currency",
                     "the amount requested for the Stinger replacement", "gliner", 0.9, 0),
                    ("s2", b, b + 2, "14", "Count", None, "a number",
                     "the number of Sgt. Stout systems", "gliner", 0.9, 0),
                    ("s3", d, d + 18, "Sgt. Stout Systems", "WeaponSystem", None, None,
                     "the system the Army wants more of", "gliner", 0.9, 0),
                    ("s4", c, c + 10, "$4 million", "Money", None, "a unit of currency",
                     "the cost of each U.S. air defense missile", "gliner", 0.9, 1)]
    st = {}
    rows = glance_rows(_GlanceCur(), "doc", "The Army",
                       "US Army seeks thousands of new missiles to replace Stinger", st)
    assert rows == [["Budget", "$215 million", q1],
                    ["Quantity", "14 more Sgt. Stout Systems", q1],
                    ["System", "Sgt. Stout Systems", q1]], rows
    assert st == {"glance_rows": 3, "glance_refused": 1}, st
    assert not any(r[0] == "Primary lens" for r in rows)
    # a document row that cannot be read is not a reason to lose the proposition-backed
    # rows -- the fallback is an addition, never a dependency
    assert glance_rows(_GlanceCur(article=None), "doc", "The Army",
                       "US Army seeks thousands of new missiles to replace Stinger",
                       {}) == rows
    print("ok")


def regate(dsn=DSN, apply=False, recard=False):
    """Re-run the subject gate over the cards ALREADY SERVED.

    fill() is append-only: signal_seen claims a document once and the card written for
    it is never revisited. So a gate tightened on 2026-09-05 changed nothing on the
    dashboard -- the 179 rows it refuses were all written 09-01..09-04 and were still
    served a day later, "Leonardo wins 15 helicopter order" among them. Every future
    tightening has the same shape, so this pass exists: judge each served card by its
    title (subject) and its detail's `what` (body), report per lane and per badge, and
    with --apply delete card + detail. --recard additionally releases the signal_seen
    claim, so the next fill() re-reads the article and judges it with the gate as it
    stands then -- without that, a card-only delete is permanent, including for the
    ~2 percent of refusals the gate gets wrong in the other direction. Report-only by
    default: a corpus-wide delete is something an operator reads first.
    """
    import psycopg2
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("""SELECT c.id, c.lane, c.dir, c.tags, c.title, d.what
                     FROM serving.signal_card c
                     LEFT JOIN serving.signal_detail d ON d.id = c.id
                    WHERE c.origin = 'pipeline'""")
    rows = cur.fetchall()
    gone, by_lane, threats = [], {}, []
    for cid, lane, direction, tags, title, what in rows:
        why = None
        if category_conflict(tags, what or "", title=title):
            why = "conflict"
        elif off_portfolio(tags, what or "", title=title):
            why = "off_portfolio"
        if why is None:
            continue
        gone.append(cid)
        by_lane[lane] = by_lane.get(lane, 0) + 1
        if direction == "threat":
            threats.append(title)
        print("  %-13s %-11s %-5s [%s] %s" % (why, lane, direction or "", tags or "", title),
              flush=True)
    print("regate: %d served card(s), %d fail the subject gate (%s); %d of them wore a "
          "THREAT badge" % (len(rows), len(gone),
                            ", ".join("%s %d" % kv for kv in sorted(by_lane.items())),
                            len(threats)), flush=True)
    if apply and gone:
        cur.execute("DELETE FROM serving.signal_detail WHERE id = ANY(%s)", (gone,))
        cur.execute("DELETE FROM serving.signal_card WHERE id = ANY(%s)", (gone,))
        freed = 0
        if recard:
            # UNCLAIM THE DOCUMENT SO THE FIXED GATE GETS A SECOND LOOK.
            #
            # Deleting the card alone is permanent: signal_seen still holds the
            # document, fill() skips anything already claimed, and no later pass ever
            # reconsiders it. That is right when a row is junk. It is wrong here,
            # because the reason these rows are being removed is that the GATE was
            # wrong when they were written -- and a gate that was wrong in one
            # direction was measured wrong in the other too, at roughly 2% of its
            # refusals. Those are documents that belong on the dashboard and would be
            # deleted forever by a card-only delete.
            #
            # Card ids are 'pl_' + document_id (verified against signal_seen), so the
            # claim is released by stripping the prefix. The next fill() re-reads the
            # article and re-judges it with the gate as it stands then: genuinely
            # off-portfolio documents are refused again and cost one gate call;
            # wrongly-refused ones come back correctly classified.
            docs = [c[3:] for c in gone if c.startswith("pl_")]
            if docs:
                cur.execute("DELETE FROM serving.signal_seen WHERE document_id = ANY(%s)",
                            (docs,))
                freed = cur.rowcount
        con.commit()
        print("regate: deleted %d card(s) and their details%s" %
              (len(gone),
               ("; released %d document(s) for re-carding" % freed) if recard
               else " (documents stay claimed; this is permanent)"), flush=True)
    elif gone:
        print("regate: report only -- re-run with --apply to delete them "
              "(add --recard to let the pipeline judge them again)", flush=True)
    con.close()
    return gone


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None,
                    help="one document_id, for the article bench")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--glance", action="store_true",
                    help="re-derive the 'At a glance' span rows for cards already stored")
    ap.add_argument("--regate", action="store_true",
                    help="re-run the subject gate over the SERVED cards and report; "
                         "add --apply to delete the rows that fail it")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--retranslate", action="store_true",
                    help="rebuild the served statements of stored cards with English "
                         "lead-ins (the forward path only reaches new documents)")
    ap.add_argument("--recard", action="store_true",
                    help="with --regate --apply: also release the signal_seen claim "
                         "on the deleted documents so the pipeline judges them again")
    a = ap.parse_args()
    if a.demo:
        _demo()
    elif a.glance:
        reglance(a.dsn, limit=a.limit, only=a.only)
    elif a.regate:
        regate(a.dsn, apply=a.apply, recard=a.recard)
    elif a.retranslate:
        retranslate(a.dsn, limit=a.limit, only=a.only, apply=a.apply)
    else:
        fill(a.dsn, limit=a.limit, only=a.only)
