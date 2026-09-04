"""Is this document worth thirteen minutes of Layer A? -- answered in under a millisecond.

    python presignal.py --demo
    python presignal.py --score "Zen Technologies secures 295 crore MoD order"

WHY
---
Layer A took 805 s of a 911 s pipeline run: 99.6% of wall clock. The card gate at the far end then
refuses most of what it is handed -- no competitor named, no provable date, off-portfolio -- and
every refusal costs the full thirteen minutes to reach. Measured on 1,250 real trade-press pages
(25 from each of 50 domains), 34% pass this gate; refusing the other 822 downstream instead would
have cost 184 CPU-HOURS.

So this asks the same question from raw text, before anything is queued, using the SAME
`ds.json` the card writer uses. Sharing the vocabulary is the point: a private word list here
would drift from the product and start refusing things the product wants.

THE THREE BUGS THIS IS BUILT AROUND
-----------------------------------
Each of these already cost a real measurement, so they are designed out rather than tested for.

1. THE `FORCE` BUG. An earlier scorer matched the competitor code FORCE (Force Motors) inside the
   words "Air Force", and the Anduril and General Atomics Air Force awards scored 100 and were
   quoted as proof the ranking worked. Word boundaries do NOT fix this -- "Force" in "Air Force"
   is perfectly word-bounded. The fix is that short codes are not competitor terms at all: we
   match company NAMES, and a bare code only when it is standalone, upper-case, and not an
   ordinary English word. `ds.json` is full of codes like LT, BEL, PEL, WIL and ZEN, every one of
   which is a substring of a common word.

2. THE CJK BUG. A `\\b` word-boundary test rejects every match in an unspaced script, because the
   neighbouring characters are alphanumeric to the regex engine. That silently zeroed Chinese,
   Japanese and Korean entirely. Terms containing unspaced script are matched as plain substrings.

3. THE LANGUAGE-DETECTOR TRAP -- the expensive one. A first version matched portfolio terms in
   40% of English articles and 0% of Russian and Hindi ones. Ranking sources on that yield would
   have ranked THE SCORER'S OWN VOCABULARY, not the sources, quietly starving every non-English
   source including the Indian ones, while looking like a clean optimisation. Hence the
   multilingual term lists below -- and hence the rule, enforced in route.py rather than here,
   that scores are compared only WITHIN a language cohort, never across.

WHAT THIS DOES NOT DO
---------------------
It does not decide trust. A tier-3 aggregator can score 100 here and it should: idrw.org is the
joint-highest-yielding source measured (72%) and must never be cited alone. Crawl eagerly, cite
never. Trust is `source_tiers.publishable()`, at the other end of the pipeline.
"""
import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

PASS_THRESHOLD = 45

# The scoring table, from the measured design. Positive signals say "a competitor did something
# concrete in our market"; negative ones say "this is not an article, or not about a rival".
W_COMPETITOR = 40    # 
W_CATEGORY   = 25    # one of the nine KSSL portfolio categories
W_PARTNER    = 15    # a named KSSL partner
W_EVENT      = 15    # wins / awarded / contract / order -- something HAPPENED
W_VALUE      = 10    # a currency amount or a unit count
W_NO_DATE    = -15   # the recency gate refuses undated pages outright
W_OWN_NEWS   = -20   # client named with no competitor: not competitive intelligence
W_LOOKS_INDEX = -45  # short verbless head, or a wall of link-length lines

# Unspaced scripts: Han, Hiragana/Katakana, Hangul, plus Thai and Lao which also lack word spaces.
_UNSPACED = re.compile(r"[一-鿿㐀-䶿぀-ヿ가-힯฀-໿]")

# Codes that are also ordinary words, in any of the languages we crawl. A competitor code on this
# list is never matched on its own -- only the full company name will do. This list is the direct
# descendant of the FORCE bug and should grow, never shrink.
# The first version of this list blocked every short code, which was too blunt: it silently
# dropped ZEN (Zen Technologies), a real rival that appears in ds.json ONLY as a code. Word
# boundaries already stop `BEL` matching "below" -- substring collisions were never the danger.
# The danger is a code that is ALSO an ordinary standalone word, which is precisely what the FORCE
# bug was: "Force" is perfectly word-bounded inside "Air Force". So the list holds only codes that
# occur as normal words in the languages we crawl, and every entry needs that justification.
_CODE_STOPLIST = {
    "FORCE",    # "Air Force", "task force" -- the original bug
    "SOLAR",    # Solar Industries vs "solar power"
    "ART",      # a portfolio code, and a word
    "SA",       # "S.A." is a company suffix across FR/ES/PT
    "PC",       # "PC" as in computer
    "MRO",      # maintenance, repair, overhaul -- industry jargon, not a company
    "AMMO",
    "IT", "US", "AS", "IN", "AT", "ON", "OR", "SO", "NO", "AN", "BE", "DO", "GO", "IS", "IF",
    "OF", "TO",
    # Added after measuring every one-token term against 77,788 real documents. Each of these
    # is a company on the live roster whose name is ALSO an ordinary word in a language this
    # corpus is actually written in -- the FORCE bug, four more times, in four more languages.
    # The count is documents matched; the verdict is what the surrounding text actually said.
    "DAHER",      # 348 docs, 335 of them German: "daher" = therefore. Zero were the French
                  # aerospace firm. Costs us Daher, which appears nowhere else in the roster.
    "WIL",        # 206 docs, 154 Dutch: "wil" = wants. Walchandnagar Industries' COMPSYN code,
                  # and the company still matches by its full name "Walchandnagar".
    "PARAMOUNT",  # 544 docs, nearly all the English adjective ("where safety is paramount"),
                  # the rest Paramount Pictures. "Paramount Group" -- the roster row and the
                  # KSSL partner label -- is multi-word and unaffected.
    "REGENT",     # 22 docs: regent of Finland, Hungarian regent. Costs us REGENT the seaglider
                  # maker; it had 3 genuine hits against 19 heads of state.
    "ARI",        # 52 docs: Indonesian "Asy'ari", a mining project, the US Army's Aviation
                  # Restructure Initiative. One genuine hit.
}


# The press short-forms, listed explicitly -- NEVER derived. Deriving them is exactly what the
# old head-token rule did: it took the first word of any multi-word name of six characters or
# more, which turned "General Dynamics" into `General` and "Israel Aerospace Industries" into
# `Israel`. Measured over 75,480 documents, `General` matched 6,843 of them where no General
# Dynamics or General Atomics was present at all, and `Israel` 3,286.
#
# But refusing every short form loses real intelligence in the other direction, which the same
# measurement shows: `BrahMos` appears in 266 documents that never write "BrahMos Aerospace",
# `Hanwha` in 208, `Safran` in 555. Those are ordinary competitor stories written the way the
# trade press actually writes them, and the old rule was the only reason they scored.
#
# So this list is DEFAULT-DENY and hand-checked. Every entry is a coinage that means one company
# and nothing else. Deliberately ABSENT, though all of them are heads of real roster names:
# ordinary words (General, Shield, Premier, Applied, Quantum, Impulse, Infinite, Envision,
# Voyager, Firestorm), industry nouns (Munitions, Ordnance, Armoured, Naval), places and peoples
# (Israel, Israeli, Ukraine, Korea, Bharat, Hindustan), and surnames that are also companies
# (Larsen, Collins, Huntington, Rafael, Mehler). Adding one of those is how the +40 signal gets
# handed to an article about a general election.
_ALIASES = [
    "BrahMos",        # BrahMos Aerospace
    "Hanwha",         # Hanwha Aerospace / Defense USA / Group / Ocean: four rows, one word
    "Lockheed",       # Lockheed Martin
    "Northrop",       # Northrop Grumman
    "Dassault",       # Dassault Aviation
    "Safran",         # Safran Helicopter Engines
    "Thyssenkrupp",   # Thyssenkrupp Marine Systems
    "Oshkosh",        # Oshkosh Defense
    "Mahindra",       # Mahindra Defence
    "Milrem",         # Milrem Robotics
    "UVision",        # UVision Air
    "Omnisys",        # Omnisys Engenharia
]


def _stoplisted(name):
    """A ONE-TOKEN name that is also an ordinary word is never a competitor term.

    The FORCE bug, generalised: LENGTH IS NOT PROTECTION. `Force` is five characters and would
    sail past any minimum-length rule straight into the name path, where it is perfectly
    word-bounded inside "Air Force". `CSG` is a carrier strike group before it is a company and
    `MPF` is Mobile Protected Firepower. A multi-word name cannot collide this way -- "Force
    Motors" is unambiguous -- so only single tokens are tested, and both the name path and the
    code path ask this same question.
    """
    n = name.strip()
    return " " not in n and n.upper() in _CODE_STOPLIST


def _union(terms):
    """Many terms -> ONE compiled pattern per script class.

    Measured on 1,200 real documents, scanning ~200 separately-compiled patterns cost 17.9 ms per
    document. The design budget is under half a millisecond, because this gate has to be
    negligible against the 13 minutes it is deciding about -- a gate that costs real time stops
    being free and starts being a second bottleneck. Two unions are needed, not one: spaced
    scripts get word boundaries, unspaced scripts cannot have them (see the CJK bug).
    """
    spaced = sorted({t.strip() for t in terms if t and t.strip() and not _UNSPACED.search(t)},
                    key=len, reverse=True)
    unspaced = sorted({t.strip() for t in terms if t and t.strip() and _UNSPACED.search(t)},
                      key=len, reverse=True)
    out = []
    if spaced:
        out.append(re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in spaced) + r")(?!\w)",
                              re.IGNORECASE))
    if unspaced:
        out.append(re.compile("|".join(re.escape(t) for t in unspaced)))
    return out


def _term_re(term):
    """One term -> one compiled pattern, with the boundary rule its script actually needs."""
    t = term.strip()
    if not t:
        return None
    if _UNSPACED.search(t):
        return re.compile(re.escape(t))                    # bug 2: no boundaries in unspaced text
    # (?<!\w) rather than \b so that a term ending in punctuation still anchors correctly.
    return re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.IGNORECASE)


def _code_re(code):
    """A bare competitor code, word-bounded and case-INSENSITIVE.

    Case-insensitive because ds.json stores `ZEN` while the press writes "Zen Technologies" -- an
    upper-case-only match found neither. Safety comes from the boundary plus the stoplist, not
    from case: `BEL` cannot match "below" once bounded, and `FORCE` is excluded by name because
    boundaries would not have saved it.
    """
    if code.upper() in _CODE_STOPLIST or len(code) < 3:
        return None
    return re.compile(r"(?<!\w)" + re.escape(code) + r"(?!\w)", re.IGNORECASE)


# Event words, multilingual. English alone was the language-detector trap: these are the languages
# actually present in the corpus, and the list is deliberately verbs-and-nouns-of-happening rather
# than defence vocabulary, which the category terms already cover.
EVENT_TERMS = [
    "win", "wins", "won", "award", "awards", "awarded", "contract", "contracts", "order",
    "orders", "ordered", "deal", "tender", "procurement", "delivery", "delivered", "selected",
    "signs", "signed", "secures", "secured", "bags", "wins order", "framework agreement",
    "auftrag", "vertrag", "beschaffung", "geliefert", "erhalten",                    # de
    "contrat", "commande", "marché", "attribué", "livré",             # fr
    "contrato", "pedido", "adjudicado", "entregado", "licitação",          # es/pt
    "contratto", "ordine", "aggiudicato", "consegnato",                              # it
    "контракт", "заказ",
    "поставка", "тендер",  # ru
    "kontrakt", "zamówienie", "przetarg", "dostawa",                            # pl
    "sözleşme", "sipariş", "ihale", "teslim",                         # tr
    "करार", "ऑर्डर", "निविदा",  # hi
    "合同", "订单", "交付", "招标",                  # zh
    "契約", "発注", "納入",                                  # ja
]

# A currency amount or a unit count. `crore`/`lakh` matter because the client's own magnitude is
# crore and Indian reporting uses them constantly.
VALUE_RE = re.compile(
    r"(?:[$€£₹]\s?\d|\b\d[\d,.]*\s?(?:crore|lakh|million|billion|bn|mn|"
    r"млн|млрд|units?|systems?|vehicles?|rounds?|"
    r"pieces?|stück|unidades)\b)", re.IGNORECASE)

# A date the recency gate could actually parse. Deliberately permissive about format and strict
# about having a YEAR: "last Tuesday" is not a date this pipeline can act on.
_MONTH = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?|"
          r"(?:янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)[а-я]*|"
          r"(?:ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)|"
          r"(?:styczn|lut|marc|kwiet|maj|czerw|lip|sierp|wrześ|paździer|listopad|grud)[a-ząćęłńóśźż]*")

# DAY-MONTH-YEAR was missing from the first version, which is the dominant written form in Britain
# and India -- most of this corpus. Undated pages are penalised, so a date format the regex cannot
# read is not a small inaccuracy: it is a -15 applied to a whole region's reporting style, and it
# would have looked exactly like "Indian sources score badly".
DATE_RE = re.compile(
    r"(?:\b\d{1,2}\s+(?:%(m)s)\s+(?:19|20)\d{2}\b|"                 # 4 April 2024
    r"\b(?:%(m)s)\s+\d{1,2},?\s+(?:19|20)\d{2}\b|"                  # April 4, 2024
    r"\b(?:19|20)\d{2}\b.{0,20}?\b(?:%(m)s)|"                        # 2024 ... April
    r"\b\d{1,2}[./-]\d{1,2}[./-](?:19|20)?\d{2}\b|"                  # 12.03.2024
    r"\b(?:19|20)\d{2}[./-]\d{1,2}[./-]\d{1,2}\b|"                   # 2024-03-12
    r"(?:19|20)\d{2}\s*年\s*\d{1,2}\s*月)"                            # 2024年3月
    % {"m": _MONTH}, re.IGNORECASE)

# "Says it is one" -- an index page at any score. These are not articles, so they are not scored.
SAYS_INDEX = re.compile(
    r"(?:\bpage\s+\d+\s+of\s+\d+\b|\barchives?\b\s*$|/category/|/tag/|/page/\d+|"
    r"^\s*(?:archive|archives|latest news|all news|news index|sitemap)\s*$)",
    re.IGNORECASE | re.MULTILINE)


def _load_ds(path=None):
    """The shared reference dataset. Returns {} if absent -- callers must check `ready()`."""
    here = Path(__file__).resolve()
    cands = [path, os.environ.get("C_DS_JSON")]
    # parents[] is not guaranteed to be that deep -- a module sitting in /tmp has two levels, and
    # indexing past them raised IndexError while the tuple was still being BUILT, so the explicit
    # C_DS_JSON override never got a chance to be read. Walk what exists instead of assuming.
    for parent in here.parents[:4]:
        cands.append(str(parent / "app" / "ds.json"))
        cands.append(str(parent / "ds.json"))
    for c in cands:
        if c and Path(c).exists():
            try:
                return json.loads(Path(c).read_text(encoding="utf-8")), c
            except Exception:
                continue
    return {}, "ds.json not found"


def _load_roster(dsn=None):
    """The LIVE competitor roster, read from serving.competitors.

    ds.json is the SEED of that table, not its content. Its 24 competitors became the table's
    29 `origin='reference'` rows; the pipeline then discovered 178 more and wrote them back as
    `origin='pipeline'`. By September the product knew 207 companies and this gate still knew
    24, so Airbus, Boeing, BAE Systems, Northrop Grumman and Babcock were invisible to the +40
    competitor signal -- and a document naming one of them topped out at 40 against a threshold
    of 45, failing by five. Audited over 43,151 gate rejections, that was the single
    demonstrated cause of false rejection.

    Reading the table rather than re-seeding ds.json is the point: a copy would drift again, and
    the drift is what this fixes. ds.json stays the fallback and keeps everything else it owns
    (codes, categories, partners, the client).

    NEVER FATAL. No DSN, no psycopg, no table, no network -- all return an empty roster and the
    scorer runs on ds.json alone, exactly as it did before. A gate that refused to start because
    a projection table was briefly unavailable would stop the queue for a vocabulary refresh.
    """
    dsn = dsn or os.environ.get("C_ROSTER_DSN") or os.environ.get("KSSL_CORPUS_DSN")
    if not dsn:
        return [], "no dsn"
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=5) as c:
            # dir='client' is us. The name filter below catches it too, but excluding it here
            # means the client is never even carried as a candidate rival.
            rows = c.execute("SELECT DISTINCT name FROM serving.competitors "
                             "WHERE name <> '' AND dir IS DISTINCT FROM 'client'").fetchall()
        return [r[0] for r in rows], "serving.competitors (%d)" % len(rows)
    except Exception as e:
        return [], "unavailable (%s: %s)" % (type(e).__name__, e)


class Scorer:
    """Compiled once, reused. Building the patterns is the slow part; matching is microseconds."""

    def __init__(self, ds=None, path=None, roster=None):
        self.ds, self.src = (ds, "supplied") if ds is not None else _load_ds(path)
        d = self.ds or {}
        # A SUPPLIED dataset means "use exactly this". The self-check and every regression test
        # below depend on it: a scorer that quietly reached for the live roster as well would
        # pass or fail according to what the pipeline happened to discover that week.
        if roster is not None:
            self.roster, self.roster_src = list(roster), "supplied"
        elif ds is not None:
            self.roster, self.roster_src = [], "not loaded (dataset supplied)"
        else:
            self.roster, self.roster_src = _load_roster()
        self.competitors = _union(self._competitor_terms(d, self.roster))
        self.codes = _union(self._competitor_codes(d, self.roster))
        self.categories = _union(self._category_terms(d))
        self.partners = _union([p.get("label", "") for p in (d.get("KSSL_PARTNERS") or [])])
        self.client = _union(self._client_terms(d))
        self.events = _union(EVENT_TERMS)

    def ready(self):
        """Ready means the DATASET loaded, not merely that some pattern compiled.

        The category and event lists are hard-coded here, so they exist even with no ds.json at
        all -- and a scorer with those but no competitors still returns plausible-looking numbers
        while being blind to the single heaviest signal (+40). It would gate documents on 25
        instead of 65 and quietly refuse most of what matters. Requiring competitor terms is what
        makes the failure loud instead of subtle.
        """
        return bool(self.competitors)

    @staticmethod
    def _all_names(d, roster=()):
        """Every company this gate may treat as a rival: ds.json's table plus the live roster.

        The client itself appears in ds.json's competitor table -- it is the subject of the
        comparison, not a rival. Left in, every piece of our own news scores +40 as competitor
        intelligence instead of -20 as our own announcement, which inverts the exact signal
        this gate exists to produce.
        """
        c = d.get("client") or {}
        mine = {(c.get("name") or "").lower(), (c.get("short") or "").lower(),
                "kalyani strategic systems", "kalyani", "bharat forge", "kssl"}
        names = [((v or {}).get("name") or "") for v in (d.get("competitors") or {}).values()]
        names += list(roster or ())
        out = []
        for name in names:
            # Both sources carry HTML entities from the pages they were extracted from --
            # "Larsen &amp; Toubro" is one row in serving.competitors. Unescaped, the term can
            # never match the prose it came from.
            name = html.unescape(name or "").strip()
            if name and name.lower() not in mine:
                out.append(name)
        return out

    @staticmethod
    def _competitor_terms(d, roster=()):
        """Full company names, matched verbatim.

        NO HEAD TOKENS. The previous version also added the first word of any multi-word name
        of six characters or more, which turned "General Dynamics" into the standalone term
        `General` and "Israel Aerospace Industries" into `Israel`. Audited on the documents that
        PASSED this gate, `General` alone matched 214 of them and 38% of all competitor hits
        rested on nothing but such a token -- articles about COVID variants and Pakistani
        politics scored +40 as competitor intelligence. It is the FORCE bug in a second costume:
        word boundaries are no defence when the token is itself an ordinary word.

        What the head tokens were actually buying -- "Hanwha" for Hanwha Ocean, "Elbit" for
        Elbit America -- the roster now supplies as real rows of its own.
        """
        names = [n for n in Scorer._all_names(d, roster)
                 if (len(n) >= 5 or " " in n) and not _stoplisted(n)]
        # An alias counts only if it is a word of a company this scorer actually knows. That is
        # what keeps the list honest: a typo, or an alias for a company since dropped from the
        # roster, quietly stops being a term instead of quietly becoming a +40 signal of its own.
        tokens = {t.lower() for n in names for t in n.split()}
        return names + [a for a in _ALIASES
                        if a.lower() in tokens and not _stoplisted(a)]

    @staticmethod
    def _competitor_codes(d, roster=()):
        """COMPSYN codes, plus the short one-word names the term path above cannot take.

        Saab and KNDS are four characters with no space, so `_competitor_terms` drops them --
        and neither is in COMPSYN, so before this the gate could not see either at all, though
        both have sat in ds.json since the first import. They belong here, behind exactly the
        stoplist that stops FORCE matching "Air Force".
        """
        short = [n for n in Scorer._all_names(d, roster) if len(n) < 5 and " " not in n]
        return [k for k in {*(d.get("COMPSYN") or {}), *short}
                if len(k) >= 3 and not _stoplisted(k)]

    @staticmethod
    def _category_terms(d):
        terms = set()
        for pair in (d.get("POS_CATS") or []):
            if isinstance(pair, list) and len(pair) == 2:
                terms.add(pair[1])
        terms.update(d.get("CAT_ALIASES") or {})
        terms.update(d.get("KSSL_CATS") or [])
        # Multilingual portfolio vocabulary. Without this the scorer IS a language detector.
        terms.update([
            "artillery", "howitzer", "ammunition", "small arms", "armoured", "armored",
            "drone", "uav", "missile", "air defence", "air defense", "naval", "forging",
            "artillerie", "haubitze", "munition", "gepanzert", "drohne", "rakete",
            "artillería", "obús", "munición", "blindado", "misil",
            "artiglieria", "obice", "munizioni", "blindato", "missile",
            "артиллерия",
            "гаубица", "боеприпасы",
            "броне", "ракета",
            "artyleria", "haubica", "amunicja", "pocisk",
            "obsüs", "topcu", "mühimmat", "zırhlı", "füze",
            "तोप", "गोला", "मिसाइल",
            "火炮", "弹药", "导弹", "装甲",
            "火砦", "弾薬", "ミサイル",
        ])
        return list(terms)

    @staticmethod
    def _client_terms(d):
        c = d.get("client") or {}
        names = {c.get("name", ""), c.get("short", ""), c.get("id", ""),
                 "Kalyani", "Bharat Forge", "KSSL"}
        return [n for n in names if n and len(n) >= 4]

    def score(self, text, title="", published_at=None):
        """-> dict(score, signals, pass). Cheap: this must stay far below the cost of being wrong."""
        blob = ((title or "") + "\n" + (text or ""))[:20000]     # a lede decides this, not page 9
        sig, s = [], 0

        # An index page is not an article at ANY score -- checked first so nothing below can
        # rescue it, and reported as a distinct reason rather than as a very low score.
        if SAYS_INDEX.search(title or "") or SAYS_INDEX.search(blob[:400]):
            return {"score": 0, "signals": ["index_page_declared"], "pass": False}

        n_comp = sum(1 for r in self.competitors if r.search(blob))
        n_comp += sum(1 for r in self.codes if r.search(blob))
        if n_comp:
            s += W_COMPETITOR; sig.append("competitor(%d)" % n_comp)
        if any(r.search(blob) for r in self.categories):
            s += W_CATEGORY; sig.append("portfolio_category")
        if any(r.search(blob) for r in self.partners):
            s += W_PARTNER; sig.append("partner")
        if any(r.search(blob) for r in self.events):
            s += W_EVENT; sig.append("event_word")
        if VALUE_RE.search(blob):
            s += W_VALUE; sig.append("value_or_quantity")
        # THE DATE COMES FROM METADATA FIRST. Measured on 1,200 real documents, a body-text
        # regex found no date in 73% of them -- so this penalty was firing on nearly three
        # quarters of the corpus. But `documents.published_at` exists: the date is usually in a
        # column, not in the prose. Penalising the body for not repeating it punishes house style,
        # not undated reporting, and -15 on 73% of everything moves the whole distribution.
        if not (published_at or DATE_RE.search(blob)):
            s += W_NO_DATE; sig.append("no_parseable_date")
        # Our own client's news is not competitive intelligence -- unless a rival is in it too.
        if not n_comp and any(r.search(blob) for r in self.client):
            s += W_OWN_NEWS; sig.append("client_own_news")
        if self._looks_like_index(title, text or ""):
            s += W_LOOKS_INDEX; sig.append("looks_like_index")
        return {"score": s, "signals": sig, "pass": s >= PASS_THRESHOLD}

    @staticmethod
    def _looks_like_index(title, text):
        """A listing page that never says so: a wall of link-length lines, or a verbless head."""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 8:
            shortish = sum(1 for l in lines if 10 <= len(l) <= 90)
            if shortish / len(lines) > 0.8:
                return True
        return bool(title) and len(title.split()) <= 4 and not re.search(
            r"\b(is|are|was|were|has|have|wins|won|signs|signed|awards?|awarded|secures?|"
            r"delivers?|delivered|orders?|launches|to)\b", title, re.IGNORECASE)


_DEFAULT = None


def ready():
    """-> (bool, where). Module-level, so a caller can refuse to build a queue on a blind scorer
    without having to construct a Scorer and know what `ready` means."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Scorer()
    return _DEFAULT.ready(), _DEFAULT.src


def score(text, title="", published_at=None):
    """Module-level entry point -- what route.py calls."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Scorer()
    return _DEFAULT.score(text, title, published_at)


def _demo():
    # A tiny stand-in dataset so the self-check runs anywhere, including with no ds.json present.
    ds = {"competitors": {"zen": {"name": "Zen Technologies"},
                          "force": {"name": "Force Motors"},
                          "adani": {"name": "Adani Defence"}},
          "COMPSYN": {"ZEN": {}, "LT": {}, "ADANI": {}},
          "POS_CATS": [["art", "Artillery"], ["uav", "UAVs & Drones"]],
          "CAT_ALIASES": {"gun": "Artillery"},
          "KSSL_PARTNERS": [{"label": "Paramount Group"}],
          "client": {"name": "Kalyani Strategic Systems", "short": "KSSL", "id": "KSSL"}}
    sc = Scorer(ds=ds)
    assert sc.ready()

    # THE FORCE BUG, as a permanent regression test. This exact headline scored 100 and was
    # published as proof the ranking worked.
    r = sc.score("Anduril wins US Air Force award for autonomous systems, 12 March 2024")
    assert "competitor" not in " ".join(r["signals"]), \
        "the FORCE bug is back: 'Air Force' matched a competitor code -- %s" % r["signals"]

    # ...while the real company still matches.
    r = sc.score("Force Motors delivers 500 vehicles to the Army, 12 March 2024")
    assert any(s.startswith("competitor") for s in r["signals"]), "Force Motors must still match"

    # The top scorer from the measured run must pass, and comfortably.
    # The top scorer from the measured run: competitor + event + value, and a date it can read.
    # No portfolio category here, correctly -- "Ministry of Defence" is not one of the nine.
    r = sc.score("Zen Technologies Secures 295 Crore Ministry of Defence Order, 4 April 2024")
    assert r["pass"], "known top scorer failed the gate: %d %s" % (r["score"], r["signals"])
    assert r["score"] == W_COMPETITOR + W_EVENT + W_VALUE, \
        "expected 65, got %d %s" % (r["score"], r["signals"])
    assert "no_parseable_date" not in r["signals"], "'4 April 2024' must parse"

    # Every date format the corpus actually uses must read, or a whole region gets a silent -15.
    for d in ("4 April 2024", "April 4, 2024", "12.03.2024", "2024-03-12",
              "12 марта 2024", "2024年3月12日"):
        assert DATE_RE.search("Adani Defence order " + d), "unparsed date format: %s" % d

    # Bug 2: an unspaced script must be able to match at all.
    r = sc.score("中国陆军采购火炮弹药 2024-03-12 Adani Defence")
    assert "portfolio_category" in r["signals"], "CJK terms silently zeroed again"

    # Bug 3: the same story in Russian must not score zero where English scores well.
    en = sc.score("Adani Defence awarded artillery contract worth 300 crore, 12 March 2024")
    ru = sc.score("Adani Defence — контракт на "
                  "артиллерия, 12.03.2024")
    assert ru["score"] >= en["score"] - W_VALUE, \
        "Russian scores %d vs English %d -- the language trap is back" % (ru["score"], en["score"])

    # A declared index page is not an article at any score.
    assert sc.score("Page 3 of 9", "Page 3 of 9")["score"] == 0
    assert sc.score("x", "Archives")["score"] == 0

    # A competitor that exists ONLY as a short code must still match. Zen Technologies is in
    # ds.json as the code ZEN and nowhere else; an over-broad stoplist silently dropped it.
    ds2 = dict(ds); ds2["COMPSYN"] = {"ZEN": {}, "FORCE": {}}
    ds2["competitors"] = {"adani": {"name": "Adani Defence"}}
    sc2 = Scorer(ds=ds2)
    r = sc2.score("Zen Technologies Secures 295 Crore Ministry of Defence Order, 4 April 2024")
    assert any(x.startswith("competitor") for x in r["signals"]), \
        "a code-only competitor must still match: %s" % r["signals"]
    # ...and the code that IS an ordinary word must still be refused.
    r = sc2.score("Anduril wins US Air Force award for autonomous systems, 12 March 2024")
    assert not any(x.startswith("competitor") for x in r["signals"]), \
        "FORCE matched inside 'Air Force' again: %s" % r["signals"]

    # The client is listed among competitors in the real ds.json. It must not count as a rival.
    ds3 = dict(ds)
    ds3["competitors"] = {"k": {"name": "Kalyani Strategic Systems"}, "a": {"name": "Adani Defence"}}
    sc3 = Scorer(ds=ds3)
    r = sc3.score("Kalyani Strategic Systems wins artillery order, 4 April 2024")
    assert "client_own_news" in r["signals"] and not any(
        x.startswith("competitor") for x in r["signals"]), \
        "the client scored as its own competitor: %s" % r["signals"]

    # Our own news, with no rival in it, is not competitive intelligence.
    own = sc.score("Kalyani Strategic Systems announces artillery milestone, 12 March 2024")
    assert "client_own_news" in own["signals"] and not own["pass"]

    # An undated page is penalised, because the recency gate refuses it downstream anyway...
    d1 = sc.score("Adani Defence wins artillery order, 12 March 2024")
    d0 = sc.score("Adani Defence wins artillery order")
    assert d1["score"] - d0["score"] == -W_NO_DATE
    # ...but a published_at from the database counts as a date. 73% of real documents carry no
    # date in their prose; almost all of them have the column.
    dm = sc.score("Adani Defence wins artillery order", published_at="2024-03-12")
    assert "no_parseable_date" not in dm["signals"] and dm["score"] == d1["score"]

    # And the whole thing must stay cheap enough to be free against a 13-minute decision.
    import time as _t
    body = ("Adani Defence wins an artillery contract worth 300 crore. " * 60)
    _t0 = _t.perf_counter()
    for _ in range(200):
        sc.score(body, "Adani Defence wins artillery order")
    _ms = (_t.perf_counter() - _t0) / 200 * 1000
    assert _ms < 2.0, "scoring costs %.2f ms/doc -- the gate is becoming a bottleneck" % _ms

    # A wall of link-length lines is a listing, whatever it calls itself.
    wall = "\n".join("Some defence headline number %d" % i for i in range(12))
    assert "looks_like_index" in sc.score(wall, "News")["signals"]

    # ------------------------------------------------------------------ the roster regressions
    # Four separate failures were measured on 43,151 gate rejections and on the documents that
    # passed. Each is pinned here, because each one scored plausibly while being wrong.

    # 1. THE STALE ROSTER. ds.json holds 24 companies; serving.competitors holds 207. A document
    #    naming one of the other 183 scored category+event = 40 against a threshold of 45 and was
    #    refused by five points. The roster is injected, never inferred, so this stays a test of
    #    the merge and not of what the pipeline discovered this week.
    live = ["Northrop Grumman", "Babcock", "BAE Systems", "Airbus", "Boeing",
            "Larsen &amp; Toubro", "RTX"]
    scr = Scorer(ds=ds, roster=live)
    for who in ("Northrop Grumman", "Babcock", "BAE Systems", "Airbus", "Boeing"):
        r = scr.score("%s awarded artillery contract worth 300 crore, 4 April 2024" % who)
        assert any(x.startswith("competitor") for x in r["signals"]), \
            "%s is on the live roster and must be seen: %s" % (who, r["signals"])
        assert r["pass"], "%s: %d %s" % (who, r["score"], r["signals"])
    # ...and the same document is refused when the roster is absent, which is the bug itself.
    blind = sc.score("Northrop Grumman awarded artillery contract, 4 April 2024")
    assert not any(x.startswith("competitor") for x in blind["signals"])

    # 2. THE GENERIC HEAD TOKEN. "General Dynamics" once contributed the standalone term
    #    `General`, and "Israel Aerospace Industries" contributed `Israel`; 38% of competitor
    #    hits on the passing side rested on such a token alone. Both companies stay matchable by
    #    their real names -- it is the fragment that must not match.
    heads = Scorer(ds=ds, roster=["General Dynamics", "Israel Aerospace Industries",
                                  "General Atomics", "Paramount Group", "Patria"])
    for junk in ("General Motors reports quarterly results, 4 April 2024",
                 "Israel and Egypt sign a peace accord, 4 April 2024",
                 "Should India worry about the COVID BF.7 variant? 4 April 2024",
                 "Paramount Pictures announces a sequel, 4 April 2024"):
        r = heads.score(junk)
        assert not any(x.startswith("competitor") for x in r["signals"]), \
            "a generic head token matched again: %r -> %s" % (junk, r["signals"])
    for real in ("General Dynamics wins a US Army contract, 4 April 2024",
                 "Israel Aerospace Industries delivered the radar, 4 April 2024"):
        assert any(x.startswith("competitor") for x in heads.score(real)["signals"]), \
            "the full name must still match: %r" % real

    # 3. SHORT NAMES ARE CODES, NOT NOTHING. Saab and KNDS are four characters with no space, so
    #    the name path drops them, and neither is in COMPSYN -- so the gate was blind to two
    #    companies that have been in ds.json since the first import.
    shorts = Scorer(ds={"competitors": {"s": {"name": "Saab"}, "k": {"name": "KNDS"}},
                        "COMPSYN": {}, "client": {}})
    for who in ("Saab", "KNDS"):
        assert any(x.startswith("competitor") for x in
                   shorts.score("%s wins an order, 4 April 2024" % who)["signals"]), \
            "%s must match through the code path" % who
    # The stoplist still governs that path: a short name that is an ordinary word is refused.
    assert not any(x.startswith("competitor") for x in Scorer(
        ds={"competitors": {"f": {"name": "FORCE"}}, "COMPSYN": {}, "client": {}}
    ).score("Anduril wins US Air Force award, 4 April 2024")["signals"]), \
        "a stoplisted short name reached the competitor union"

    # 4. HTML ENTITIES. serving.competitors carries "Larsen &amp; Toubro" exactly as the page
    #    that produced it did. Unescaped, the term can never match the prose it came from.
    assert any(x.startswith("competitor") for x in
               scr.score("Larsen & Toubro wins a naval order, 4 April 2024")["signals"]), \
        "an HTML-escaped roster name never matches real text"

    # 5. THE BOUNDARY IS UNCHANGED AT 45. The fix is a vocabulary fix; nothing about the
    #    arithmetic moved, and a document one point short must still fail.
    assert PASS_THRESHOLD == 45
    assert W_COMPETITOR + W_CATEGORY == 65 and W_CATEGORY + W_EVENT == 40
    near = scr.score("Boeing artillery programme continues, 4 April 2024")     # comp+cat = 65
    assert near["score"] == 65 and near["pass"]
    edge = sc.score("The artillery programme was awarded on 4 April 2024")     # cat+event = 40
    assert edge["score"] == 40 and not edge["pass"], \
        "40 must still fail: %d %s" % (edge["score"], edge["signals"])
    assert not Scorer(ds=ds, roster=[]).score(
        "The artillery programme was awarded on 4 April 2024")["pass"]

    # 6. THE VALIDATED ALIAS. The press writes "BrahMos", not "BrahMos Aerospace" -- 266
    #    documents do exactly that -- so the short form has to work. It works because it is on an
    #    explicit list, not because it is the first word of something.
    al = Scorer(ds=ds, roster=["BrahMos Aerospace", "Hanwha Ocean", "General Dynamics"])
    for short in ("Thailand set to join India's growing BrahMos club, 4 April 2024",
                  "Hanwha delivers the K9 howitzer to Poland, 4 April 2024"):
        assert any(x.startswith("competitor") for x in al.score(short)["signals"]), \
            "a listed alias must match: %r" % short
    # `General` is the head of a roster name too, and is deliberately NOT on the list.
    assert "General" not in Scorer._competitor_terms(ds, ["General Dynamics"])
    # An alias for a company the scorer does not know is not a term. Without this, the list
    # becomes a second vocabulary that nobody validates.
    orphan = Scorer(ds={"competitors": {"a": {"name": "Adani Defence"}},
                        "COMPSYN": {}, "client": {}})
    assert "BrahMos" not in orphan._competitor_terms(orphan.ds), \
        "an alias survived with no company behind it"
    # ...and a stoplisted token could never be rescued by being listed as an alias.
    assert not any(_stoplisted(a) for a in _ALIASES), "an alias collides with the code stoplist"

    # 7. THE ORDINARY WORD IN SOMEBODY ELSE'S LANGUAGE. Each of these is a real company on the
    #    live roster whose name is a common word in a language this corpus is written in. They
    #    are the FORCE bug repeated, and the measurement that found them is in the stoplist.
    words = Scorer(ds=ds, roster=["Daher", "Paramount", "REGENT", "ARI", "Walchandnagar"])
    for junk, why in (
            ("Die Systeme sind daher besonders wirtschaftlich, 4 April 2024", "German 'daher'"),
            ("De commissie wil een nieuw contract, 4 April 2024", "Dutch 'wil'"),
            ("A rapid response is paramount for the artillery order, 4 April 2024", "English adj"),
            ("Mannerheim served as regent of Finland, 4 April 2024", "'regent'")):
        r = words.score(junk)
        assert not any(x.startswith("competitor") for x in r["signals"]), \
            "%s matched a competitor: %s" % (why, r["signals"])
    # The company behind a stoplisted CODE is still reachable by its full name.
    assert any(x.startswith("competitor") for x in
               words.score("Walchandnagar wins a naval order, 4 April 2024")["signals"]), \
        "stoplisting WIL took Walchandnagar with it"
    # ...and the multi-word form of a stoplisted single token still matches.
    assert any(x.startswith("competitor") for x in Scorer(ds=ds, roster=["Paramount Group"])
               .score("Paramount Group delivers Mbombe vehicles, 4 April 2024")["signals"]), \
        "stoplisting Paramount took Paramount Group with it"

    # The client must stay excluded no matter which source names it.
    assert not any(x.startswith("competitor") for x in Scorer(
        ds=ds, roster=["Kalyani Strategic Systems", "Bharat Forge"]
    ).score("Kalyani Strategic Systems wins artillery order, 4 April 2024")["signals"]), \
        "the client arrived as a rival through the roster"

    # Report TERMS, not compiled patterns: after unioning there are only one or two patterns per
    # class, and printing "2 competitor terms" would read like the vocabulary had collapsed.
    print("ok  %d competitor / %d category / %d event terms in %d patterns, "
          "%.2f ms/doc, threshold %d"
          % (len(sc._competitor_terms(ds)) + len(sc._competitor_codes(ds)),
             len(sc._category_terms(ds)), len(EVENT_TERMS),
             len(sc.competitors) + len(sc.codes) + len(sc.categories) + len(sc.events),
             _ms, PASS_THRESHOLD))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--score", metavar="TEXT")
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    if a.score:
        sc = Scorer()
        print("dataset:", sc.src)
        r = sc.score(a.score, a.title)
        print("score %(score)d  pass %(pass)s  %(signals)s" % r)
    else:
        _demo()
