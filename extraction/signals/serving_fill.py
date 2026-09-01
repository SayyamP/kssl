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
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from aliases import (  # noqa: E402  (shared identity layer)
    canonical as canon_name, client_led, fold as fold_name, is_client, is_force, is_one_org,
)
from llmapi import client as llm_client  # noqa: E402  (every model call goes through the API)

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
                return y, mm, None
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


def article_date(cur, did, today_ym=None):
    """-> (y, m|None, d|None) from the document's own Date spans, earliest
    position first (the publication date leads the page). A date in the FUTURE
    cannot be a publication date -- '2027 delivery' and '2040 vision' spans are
    forecasts, so they are skipped and the scan continues."""
    if today_ym is None:
        import datetime
        t0 = datetime.date.today()
        today_ym = (t0.year, t0.month)
    # The crawler's own publication date first, when there is one. It comes from
    # the page's metadata, so it IS proven -- and it is the only date on the page
    # that is about the article rather than about its subject. Body Date spans
    # are the fallback, and they are what made a 2026 story about a 2022 contract
    # read as four years old.
    cur.execute("SELECT meta->>'published_at' FROM extracted.document "
                "WHERE document_id=%s", (did,))
    row = cur.fetchone()
    if row and row[0]:
        # ISO timestamps arrive as 2026-08-25T14:03:11Z; the T has to go or
        # the parser reads the year and month and drops the day.
        ymd = parse_date(row[0].replace("T", " ")[:24])
        if ymd and (ymd[0], ymd[1] or 1) <= today_ym:
            return ymd

    cur.execute("""SELECT text, gloss FROM extracted.span
                    WHERE document_id=%s AND type='Date'
                    ORDER BY start_c LIMIT 15""", (did,))
    for t, g in cur.fetchall():
        ymd = parse_date("%s %s" % (t or "", g or ""))
        if ymd and (ymd[0], ymd[1] or 1) <= today_ym:
            return ymd
    return None


def date_label(ymd):
    """(2026, 5, 28) -> '28 May 2026'; month/day degrade honestly."""
    y, m, d = ymd
    if m and d:
        import datetime
        return datetime.date(y, m, d).strftime("%d %b %Y").lstrip("0")
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
    for seg in ("/tag/", "/category/", "/label/", "/author/", "/authors/",
                "/topic/", "/topics/", "/section/", "/archive/", "/archives/",
                "/search/", "/page/"):
        if seg in low + "/":
            return True
    if "page=" in (u.query or "").lower():
        return True
    last = low.rsplit("/", 1)[-1]
    return last in ("news", "media", "press", "press-releases") or last.endswith("-in-media")


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
_HELI_RX = re.compile(r"\b(helicopter|rotorcraft|rotary-wing)\b", re.I)
_LASER_RX = re.compile(r"\b(laser|directed[- ]energy|high-energy)\b", re.I)
_AUTOCANNON_RX = re.compile(r"\b\d{2}\s*[x×]\s*\d{2,}\s*mm\b", re.I)
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
        if _KSSL_SENT.search(core):      # couldn't cleanly excise KSSL -> drop the sentence
            core = ""
        words = len(re.findall(r"\w+", core))
        demo = bool(re.match(r"\s*(this|these|it)\b", core, re.I))
        if core and _has_concrete(core) and words > 4 and not (demo and words <= 7):
            out.append(core if core.endswith((".", "!", "?")) else core + ".")
        # else drop the sentence -- fabricated tie or a bare demonstrative fragment
    # empty -> the whole sowhat was a fabricated tie; parse_card drops the card (no significance)
    return " ".join(out).strip()


def category_conflict(cat, text):
    """fix4: True when the article's own words contradict the LLM's category pick."""
    c = (cat or "").lower()
    if _HELI_RX.search(text) and ("vehicle" in c or "small arms" in c):
        return True
    if _LASER_RX.search(text) and ("drone" in c or "uav" in c):
        return True
    if _AUTOCANNON_RX.search(text) and (c == "small arms" or "drone" in c or "uav" in c):
        return True
    if re.search(r"\b(aew&?c|early[- ]warning|awacs|maritime patrol aircraft|globaleye)\b",
                 text, re.I) and ("drone" in c or "uav" in c):
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
    if category_conflict(cat, ev):
        return None                      # fix4: helicopter-in-armoured, laser-in-drones, etc.
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
    in_core = cat.lower() in _CORE_CATS
    if direction == "threat" and not (gain and pillar == "competitive" and in_core):
        direction = "watch"
    elif gain and pillar == "competitive" and in_core:
        direction = "threat"
    if direction not in ("threat", "watch"):
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
             "offtopic": 0, "undated": 0, "dup": 0, "client_news": 0, "listing": 0,
             "suppressed": 0}
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
        cur.execute("INSERT INTO serving.signal_seen(document_id) VALUES(%s) ON CONFLICT DO NOTHING", (did,))
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
        if is_listing(url):
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
        cur.execute("""INSERT INTO serving.signal_card
                         (id, lane, ord, dir, rank, title, meta, company, lens, sowhat, sec,
                          url, ago, tags, origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               'pipeline')
                       ON CONFLICT (id) DO UPDATE SET
                         lane=EXCLUDED.lane, dir=EXCLUDED.dir, title=EXCLUDED.title,
                         meta=EXCLUDED.meta, company=EXCLUDED.company,
                         sowhat=EXCLUDED.sowhat, sec=EXCLUDED.sec, url=EXCLUDED.url,
                         ago=EXCLUDED.ago, tags=EXCLUDED.tags, updated_at=now()""",
                    (cid, lane, ord_next, card["dir"], str(ord_next).zfill(2),
                     esc(card["title"]),
                     esc("%s · %s · from %s" % (card["category"], company_chip, source)),
                     esc(card["company"]), card["pillar"].capitalize(),
                     esc(card["sowhat"]), json.dumps(sec), url,
                     ago_of(ymd[:2]), card["category"]))
        facts = [["Company", esc(card["company"])], ["Category", card["category"]],
                 ["Date", date_label(ymd)],
                 ["Primary lens", card["pillar"].capitalize()]]
        s0, p0, o0 = props[0][0], props[0][1], props[0][2]
        what = esc(card["what"] or "%s %s %s." % (s0, p0, o0))
        lens = [["STATEMENT", "%s — <i>&ldquo;%s&rdquo;</i>"
                 % (esc("%s %s %s" % (s, p, o)), esc(q or ""))]
                for s, p, o, _m, q in props[:6]]
        cur.execute("""INSERT INTO serving.signal_detail
                         (id, ord, rank, dir, title, facts, what, why, lens, actions, url,
                          suggest, origin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'[]',%s,'[]','pipeline')
                       ON CONFLICT (id) DO UPDATE SET
                         title=EXCLUDED.title, facts=EXCLUDED.facts, what=EXCLUDED.what,
                         why=EXCLUDED.why, lens=EXCLUDED.lens, url=EXCLUDED.url,
                         updated_at=now()""",
                    (cid, ord_next, "%s SIGNAL · %02d" % (card["pillar"].upper(), ord_next),
                     card["dir"],
                     esc(card["title"]), json.dumps(facts), what, esc(card["sowhat"]),
                     json.dumps(lens), url))
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
              "%(bad)d error(s)" % stats, flush=True)
    return stats


def _demo():
    cats = ["Artillery", "Ammunition"]
    ok = parse_card('{"pillar":"competitive","title":"T","company":"C",'
                    '"category":"Artillery","dir":"threat","sowhat":"Saab delivered 12 M4 guns."}', cats)
    assert ok and ok["dir"] == "threat"
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
        """
        def __init__(self, rows, published=None):
            self.rows, self.published = rows, published
        def execute(self, *_): pass
        def fetchone(self): return (self.published,)
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
    assert parse_date("2026 m. vasario 17 d.") == (2026, 2, None), "Lithuanian February parses"
    assert parse_date("published 2026") == (2026, None, None), "no month word stays year-only"
    seen2 = [("kalyani strategic systems", title_tokens("KSSL and Paramount unveil Simha 4x4 armoured vehicle"))]
    assert is_dup(seen2, "Paramount/Kalyani Strategic Systems",
                  "KSSL and Paramount unveil the Simha 4x4 armoured vehicle"),         "same story with a differently-spelled company is still a dup"
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DSN)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None,
                    help="one document_id, for the article bench")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        fill(a.dsn, limit=a.limit, only=a.only)
