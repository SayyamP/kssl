"""'At a glance' rows from TYPED spans -- each row carries the sentence that proves it.

    python glance.py --demo           # self-check, no database

WHY SPANS AND NOT PROSE
-----------------------
The panel used to show four rows (Company, Category, Date, Primary lens). The rows the
reader actually wants -- what the deal was worth, how many, with whom, under which
programme -- sit inside extracted.proposition.ev_quote as free text. Regexing them out
of that prose would be manufacturing structure the extractor never asserted. Layer A
already typed them: extracted.span carries Money / Count / Program / Organization /
Person / WeaponSystem spans with character offsets, a gloss, and `in_article`, the
extractor's own English sentence on what the span IS in this article ("the amount of
money awarded in the contract", "the cost of each U.S. air defense missile"). This
module reads those, never the article.

THE RULE: GROUNDED, AND ENTAILING
---------------------------------
An audit of this project's extraction layer found it believed 59% wrong facts because
grounding checked that evidence EXISTED, not that it MEANT the claim: a dollar figure in
the same article as a company is not that company's contract value ("$4 million" in the
Stinger article is what one interceptor costs; "PLN5 billion" in the Gdynia article is
what a not-yet-chosen partner will have to raise). So every row here passes four gates:

  1. QUOTED    the span lies inside a proposition's evidence sentence, and that sentence
               shows the span's exact text at the span's offset (a misaligned quote
               cannot prove anything and is refused, not trusted);
  2. ANCHORED  the card's company is named in that proposition's subject or object, or
               in the span's own `in_article` -- the extractor tied THIS value to THIS
               company, we did not infer it from co-occurrence;
  3. TYPED     the span's role (its in_article/gloss/predicate) says what kind of value
               it is -- a contract, an investment, a budget line -- and a ceiling
               ("up to"), a speculation ("expected"), or a unit cost is refused rather
               than shown as a value;
  4. VERBATIM  the value on screen is the article's own words (a span, or one contiguous
               slice of the quote such as "11,000 of the missiles"); nothing is composed
               from two places in the text.

A missing row is fine. A wrong row is not. `refused` counts every candidate the gates
turned away, by reason, so a gate that stops refusing is visible.

NOT REDUNDANT
-------------
The client's complaint is rows that restate what is already on screen. Stance, Date and
Publisher were dropped earlier (header pill, feed `ago`, source chips); Primary lens goes
now (the pill and the feed dirtag). A Programme or System that the headline already names
is not emitted either -- the headline is two lines above the block.
"""
import argparse
import html as _html
import re
import unicodedata
from collections import namedtuple

Span = namedtuple("Span", "span_id start_c end_c text type type_ner gloss in_article "
                          "source score sent")
Prop = namedtuple("Prop", "i subject predicate object ev_start ev_end ev_quote")

# the span types the rows are built from -- the loader fetches only these
FACT_SPAN_TYPES = ("Money", "Count", "Program", "Organization", "Country", "Location",
                   "Person", "Role", "WeaponSystem", "Platform", "Product", "Equipment")

# one row per label, except Key person (two people at one company is common)
ROW_CAP = {"Key person": 2}
ROW_ORDER = ["Deal value", "Investment", "Budget", "Quantity", "Customer", "Supplier",
             "Counterparty", "Rival", "Programme", "System", "Key person"]
# rows whose value is a NAME: one name under two labels (Defcomm acquired / Defcomm the
# product, 'EyePulse project' / 'EyePulse') is one fact, so these dedupe on name tokens
NAME_ROWS = {"Customer", "Supplier", "Counterparty", "Rival", "Programme", "System", "Key person"}

_STOP = {"the", "and", "of", "for", "a", "an", "de", "du", "la", "le", "des", "der", "die"}
# words that name a KIND of organisation, not one organisation -- never an anchor
_GENERIC = {"ltd", "limited", "inc", "corp", "corporation", "co", "company", "plc", "gmbh",
            "sa", "ag", "llc", "pvt", "private", "nigam", "group", "systems", "system",
            "defence", "defense", "technologies", "technology", "industries", "industry",
            "aerospace", "ministry", "army", "navy", "force", "forces", "air", "command",
            "government", "govt", "department", "dept", "military", "authority", "royal",
            "national", "international", "state", "federal", "agency", "office", "bureau",
            "services", "service", "holdings", "international", "global", "us", "uk", "usa",
            "indian", "american", "russian", "british", "german", "french", "australian",
            "chinese", "japanese", "korean", "israeli", "italian", "spanish", "polish",
            "canadian", "ukrainian", "united", "states", "kingdom", "republic"}


def _fold(s):
    """Case- and accent-insensitive text with 'U.S.' -> 'us' so an abbreviation
    anchors the same way its expansion does."""
    s = unicodedata.normalize("NFKD", _html.unescape(str(s or "")))
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r"\bu\.s\.", "us", s)


def _word_in(tok, hay):
    return re.search(r"(?<![^\W_])" + re.escape(tok) + r"(?![^\W_])", hay) is not None


def anchor_tokens(company):
    """(tokens, mode). Distinctive tokens ('lockheed', 'gdynia') anchor on ANY hit;
    a name made only of generic words ('The Army', 'US Army') anchors only when
    ALL of its words are present, because 'army' alone matches every army."""
    toks = re.findall(r"[^\W_]+", _fold(company))
    distinct = [t for t in toks if len(t) >= 3 and t not in _GENERIC and t not in _STOP]
    if distinct:
        return distinct, "any"
    return [t for t in toks if t not in _STOP], "all"


def anchored(company, *hays):
    """Is the company named in the given text(s)? A short distinctive token ('port'
    of 'Port of Gdynia Authority') is not enough on its own -- it needs a long one
    ('gdynia') or every distinctive token present."""
    toks, mode = anchor_tokens(company)
    if not toks:
        return False
    hay = _fold(" ".join(h or "" for h in hays))
    hits = [t for t in toks if _word_in(t, hay)]
    if mode == "all":
        return len(hits) == len(toks)
    return any(len(t) >= 5 for t in hits) or len(hits) == len(toks)


def _quoted_in(span, props):
    """The propositions whose evidence sentence contains the span AND shows its exact
    text at that offset. Returns (props, reason-if-none)."""
    inside, out = False, []
    for p in props:
        if p.ev_start is None or p.ev_end is None or not p.ev_quote:
            continue
        if p.ev_start <= span.start_c and span.end_c <= p.ev_end:
            inside = True
            a, b = span.start_c - p.ev_start, span.end_c - p.ev_start
            if p.ev_quote[a:b] == span.text:
                out.append(p)
    if out:
        return out, None
    return [], ("misaligned" if inside else "unquoted")


def _anchor_prop(company, span, props):
    """The first quoting proposition that ties the span to the company: the company is
    in its subject/object, or the span's own in_article names the company."""
    quoting, why = _quoted_in(span, props)
    if not quoting:
        return None, why
    for p in quoting:
        if anchored(company, p.subject, p.object) or anchored(company, span.in_article):
            return p, None
    return None, "unanchored"


def _role_text(span, p=None):
    return " ".join(x or "" for x in (span.in_article, span.gloss,
                                       p.predicate if p else "", p.object if p else ""))


# --- redundancy with the headline ------------------------------------------------------------
# nouns that name a KIND of thing; sharing one with the headline is not sharing a name
_PRODUCT_NOUNS = {"system", "systems", "program", "programme", "project", "class", "series",
                  "missile", "missiles", "aircraft", "vehicle", "vehicles", "radar", "radars",
                  "drone", "drones", "ship", "ships", "frigate", "frigates", "submarine",
                  "submarines", "tank", "tanks", "boat", "boats", "platform", "platforms",
                  "solution", "solutions", "product", "products", "capability",
                  "capabilities", "service", "services", "technology", "technologies",
                  "main", "battle", "new", "modern", "advanced", "combat", "defence",
                  "defense", "military", "naval", "air", "land", "sea", "ground", "unmanned",
                  "uav", "uavs", "uas", "gun", "guns", "shell", "shells", "ammunition",
                  "helicopter", "helicopters", "satellite", "satellites", "contract",
                  "order", "programm", "programma", "programu", "programme", "portfolio",
                  "usv", "usvs", "ugv", "ugvs", "autonomous", "procurement", "european",
                  "media", "state", "controlled", "interceptor", "interceptors", "launcher",
                  "launchers", "munition", "munitions", "weapon", "weapons", "sensor",
                  "sensors", "network", "networks", "fleet", "prototype", "prototypes"}
# words that name a KIND of organisation ('Suppliers', 'the company', 'officials')
_ORG_GENERIC = {"supplier", "suppliers", "partner", "partners", "customer", "customers",
                "contractor", "contractors", "subcontractor", "subcontractors", "companies",
                "firm", "firms", "official", "officials", "authorities", "consortium",
                "startup", "startups", "manufacturer", "manufacturers", "vendor", "vendors",
                "prime", "primes", "member", "members", "allies", "ally", "nation", "nations"}


def _stem(t):
    """'ccas' and 'cca', 'frigates' and 'frigate' are the same word for the headline test."""
    return t[:-1] if len(t) > 2 and t.endswith("s") and not t.endswith("ss") else t


def _name_tokens(text):
    out = []
    for t in re.findall(r"[^\W_]+", _fold(text)):
        if (len(t) >= 4 or re.search(r"\d", t)) and t not in _GENERIC and t not in _STOP \
                and t not in _PRODUCT_NOUNS and _stem(t) not in _PRODUCT_NOUNS \
                and t not in _ORG_GENERIC:
            out.append(_stem(t))
    return out


def in_title(value, title):
    """The headline already names it: the whole value, or any distinctive word of it
    ('Gripen E' under a 'Gripen F' headline, 'Stinger systems' under 'replace Stinger')."""
    ft = _fold(title)
    if not ft:
        return False
    if _fold(value) in ft:
        return True
    title_toks = {_stem(t) for t in re.findall(r"[^\W_]+", ft)}
    return any(t in title_toks for t in _name_tokens(value))


# --- Money ---------------------------------------------------------------------------
_MONEY_CONTRACT = re.compile(r"\b(contract(?!or)|award|order|deal|agreement|purchas|procur|acqui|"
                             r"bought|buy|won|win|secur|tender|framework|call-off)", re.I)
_MONEY_INVEST = re.compile(r"\b(invest|commit)", re.I)
_MONEY_BUDGET = re.compile(r"\b(budget|request|allocat|fund|appropriat|spend|ask)", re.I)
# a unit cost or a company's own financial metric is not the value of a deal
_MONEY_VETO = re.compile(r"\b(each|apiece|per unit|per (missile|aircraft|vehicle|round|shell|"
                         r"system|ship|drone|interceptor)|unit (cost|price)|cost (of )?(each|per)|"
                         r"revenue|sales|turnover|profit|earnings|ebit\w*|dividend|margin|"
                         r"backlog|order intake|order book|market cap|valuation|enterprise value|share price|"
                         r"stock|salary|fine|penalt|loss|r&d|research and development|"
                         r"capital expenditure|capex|guidance)", re.I)
# a ceiling or a forecast presented as a figure would be a wrong row
_CEILING = re.compile(r"\b(up to|as much as|maximum|potential|ceiling|could|may|might|"
                      r"estimated|projected|expected|forecast|anticipat)", re.I)


def money_label(span, p):
    role = _role_text(span, p)
    if _MONEY_VETO.search(role):
        return None, "not-a-deal-figure"
    before = p.ev_quote[max(0, span.start_c - p.ev_start - 30):span.start_c - p.ev_start]
    if _CEILING.search(role) or _CEILING.search(before):
        return None, "ceiling"
    # investment before contract: 'the prime contractor has invested $2bn' is an investment
    if _MONEY_INVEST.search(role):
        return "Investment", None
    if _MONEY_CONTRACT.search(role):
        return "Deal value", None
    if _MONEY_BUDGET.search(role):
        return "Budget", None
    return None, "untyped"


# --- Count -----------------------------------------------------------------------------
_COUNT_OK = re.compile(r"\d|\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                       r"twenty|thirty|forty|fifty|sixty|hundred|hundreds|thousand|thousands|"
                       r"dozen|dozens|million)\b", re.I)
_COUNT_VETO = re.compile(r"\b(nation|countr|people|person|soldier|troop|personnel|employee|"
                         r"job|worker|staff|year|month|day|week|percent|%|weight|group|tier|"
                         r"generation|class|kg|pound|tonne|mile|km|metre|meter|hour|minute|"
                         r"identifier|not applicable|not specified)", re.I)
# what may sit between a count and the thing counted for the slice to be one phrase
_CONNECTOR = re.compile(r"^(\s*(of|the|those|these|its|their|more|new|additional|further|"
                        r"extra|such|units|pieces|sets|batches|examples|,|-|–)\s*)*$",
                        re.I)
_PRODUCT_TYPES = ("WeaponSystem", "Platform", "Product", "Equipment")


def count_value(span, p, spans):
    """'11,000 of the missiles' -- the count plus the typed product span it modifies,
    as ONE slice of the quote. A count with no product beside it is a number, not a
    quantity, and is refused."""
    if not _COUNT_OK.search(span.text):
        return None, "not-a-count"
    if _COUNT_VETO.search(_role_text(span)):
        return None, "counts-not-units"
    for t in spans:
        if t.type not in _PRODUCT_TYPES or t.sent != span.sent or t.start_c < span.end_c:
            continue
        gap = p.ev_quote[span.end_c - p.ev_start:t.start_c - p.ev_start]
        if t.start_c - span.end_c > 14 or not _CONNECTOR.match(gap):
            continue
        if t.end_c > p.ev_end:
            continue
        return p.ev_quote[span.start_c - p.ev_start:t.end_c - p.ev_start], None
    return None, "no-product"


# --- Programme / System ------------------------------------------------------------------
_PROG_GENERIC = {"program", "programme", "project", "initiative", "effort", "plan", "defence",
                 "defense", "modernization", "modernisation", "procedure", "contract",
                 "research program", "research programme", "research & development",
                 "research and development", "training", "exercise", "development",
                 "protected mobility", "sustainment"}
# legislation and policy are not programmes, whatever the extractor typed them as
_NOT_A_PROGRAMME = re.compile(r"\b(act|policy|law|bill|notice|regulation|directive)$", re.I)
# ...and the extractor's own reading of the span must say it IS one: 'Naval Power' and
# 'Mission Systems' are typed Program but glossed as business units
_IS_A_PROGRAMME = re.compile(r"\b(program|project|initiative|effort|competition|procurement|"
                             r"acquisition|mission|scheme|plan|campaign|contest|challenge|"
                             r"constellation|framework|tender|requirement|phase|increment)",
                             re.I)
# a business line or a portfolio is not a system
_NOT_A_SYSTEM = re.compile(r"\b(solutions?|capabilit(y|ies)|services?|products?|technolog(y|ies)|"
                           r"portfolio|offerings?|business|programmes?|programs?)$", re.I)
# brackets are NOT stripped: '(CEO)' must not come out as '(CEO'
_PUNCT = "\"'“”‘’«»,.;:@-–— "


def _clean(text):
    return (text or "").strip(_PUNCT)


def _proper(text, span, p):
    """A named thing: an inner capital or a digit ('MQ-9', 'Sgt. Stout', 'Hunter-class'),
    or an initial capital that is NOT the first word of the sentence."""
    if re.search(r"[A-ZА-Я]", text[1:]) or re.search(r"\d", text):
        return True
    return text[:1].isupper() and span.start_c > p.ev_start


def _overlaps_place(span, spans):
    for c in spans:
        if c.type in ("Country", "Location") and c.start_c < span.end_c and span.start_c < c.end_c:
            return True
    return False


def named_value(span, p, title, spans=(), kind="programme", company=None):
    text = _clean(span.text)
    if len(text) < 4 or len(text) > 60:
        return None, "length"
    if text.casefold() in _PROG_GENERIC or not _name_tokens(text):
        return None, "generic"            # 'European defence programmes' names nothing
    if kind == "programme" and (_NOT_A_PROGRAMME.search(text)
                                or not _IS_A_PROGRAMME.search(_role_text(span))):
        return None, "not-a-programme"
    if kind == "system" and (_NOT_A_SYSTEM.search(text) or not _name_tokens(text)):
        return None, "generic"
    if kind == "system" and company is not None \
            and all(t in anchor_tokens(company)[0] for t in _name_tokens(text)):
        return None, "is-company"         # 'KNDS platform' names the maker, not a system
    if "gliner" not in (span.source or "") or (span.score or 0) < 0.4:
        return None, "low-score"
    if not _proper(text, span, p):
        return None, "not-a-name"
    if in_title(text, title):
        return None, "in-title"
    if kind == "system" and _overlaps_place(span, spans):
        return None, "demonym"        # 'American drones' is a country, not a system
    return text, None


# --- Counterparty ------------------------------------------------------------------------
# the OTHER party bought or sold something -> Customer / Supplier by which side the name is on.
# A strong verb counts wherever it stands; a weak one ('delivers', 'supplies') only in the
# span's own in_article, because "delivers interoperability with NATO" has the same
# predicate as "delivers radars to NATO" and only the extractor's reading of the org
# tells them apart.
_PURCHASE_STRONG = re.compile(r"\b(award|contract|order|select|purchas|procur|acqui|buy|bought|"
                              r"sell|sold|commission|tender|licen|export)", re.I)
_PURCHASE_WEAK = re.compile(r"\b(suppl|deliver|receiv|provider|won|win|secur|framework|"
                            r"customer|buyer|client)", re.I)
# a tie that is not (yet) a purchase -> Counterparty, whoever they are
_PARTNER = re.compile(r"\b(partner|team|collaborat|joint|memorandum|mou|agree|sign|deal|"
                      r"letter of intent|loi|cooperat|consortium|venture|owns?\b)", re.I)


def _tie_kind(p, span):
    ia = span.in_article or ""
    both = " ".join((p.predicate or "", ia))
    if _PURCHASE_STRONG.search(both) or _PURCHASE_WEAK.search(ia):
        return "purchase"
    if _PARTNER.search(both):
        return "partner"
    return None
_RIVAL = re.compile(r"\b(compet\w*|rival\w*|versus|against|contender|challenger)\b", re.I)
_BUYER_FALLBACK = re.compile(r"\b(ministry|ministr\w+|government|govt|armed forces?|"
                             r"defen[cs]e forces?|air force|army|navy|marines?|coast guard|"
                             r"national guard|pentagon|department of|command|agency|police|"
                             r"military|bundeswehr|forces)\b", re.I)


def _strip_places(span, spans):
    """The org text with any overlapping Country/Location span removed -- 'Dutch suppliers'
    minus 'Dutch' leaves no name at all."""
    text = span.text
    for c in spans:
        if c.type in ("Country", "Location") and c.start_c < span.end_c and span.start_c < c.end_c:
            a, b = max(c.start_c, span.start_c) - span.start_c, min(c.end_c, span.end_c) - span.start_c
            text = text[:a] + " " * (b - a) + text[b:]
    return text


def counterparty(company, title, span, p, spans, is_buyer=None):
    """The OTHER party of a deal proposition: the span names it, the proposition names both
    it and the company, and the predicate (or the span's own in_article) is a deal. The
    label says Customer/Supplier only for a PURCHASE and only when the name says which side
    is the buyer; every other tie is a Counterparty."""
    text = _clean(span.text)
    # 'Suppliers', 'the company' -- a kind of organisation, not one. (Not _name_tokens:
    # buyers are named BY generic words -- 'Israeli Defense Ministry', 'US Army' -- and
    # must pass, so only the org-kind words disqualify here.)
    named = _strip_places(span, spans)
    kind_only = all(t in _ORG_GENERIC or t in _STOP or t in _ORG_SUFFIX
                    for t in re.findall(r"[^\W_]+", _fold(named)))
    if len(text) < 3 or kind_only or not re.search(r"[A-ZА-Я]", named):
        return None, None, "not-a-name"
    if anchored(company, text) or _fold(text) in _fold(company) or _fold(company) in _fold(text):
        return None, None, "is-company"
    if "gliner" not in (span.source or "") or (span.score or 0) < 0.5:
        return None, None, "low-score"
    if not anchored(company, p.subject, p.object):
        return None, None, "unanchored"
    if _fold(text) not in _fold(p.subject) and _fold(text) not in _fold(p.object):
        return None, None, "not-in-proposition"
    if in_title(text, title):
        return None, None, "in-title"
    if _RIVAL.search(span.in_article or ""):
        return "Rival", text, None          # the extractor says they compete; that is the tie
    kind = _tie_kind(p, span)

    def buyer(n):
        return bool(_BUYER_FALLBACK.search(n or "")) or bool(is_buyer and is_buyer(n))
    if kind == "purchase":
        if buyer(text):
            return "Customer", text, None
        if buyer(company):
            return "Supplier", text, None
        return "Counterparty", text, None
    if kind == "partner":
        return "Counterparty", text, None
    return None, None, "not-a-deal"


# --- Key person --------------------------------------------------------------------------
_ORG_SUFFIX = {"ltd", "limited", "inc", "corp", "corporation", "co", "company", "plc", "gmbh",
               "sa", "ag", "llc", "pvt", "private", "nigam", "group", "holdings", "the"}


def _core_name(company):
    toks = [t for t in re.findall(r"[^\W_]+", _fold(company)) if t not in _ORG_SUFFIX]
    return " ".join(toks)


def person_value(company, span, p, spans):
    """'Kendy Hau, head of defence' -- a Person span and its adjacent Role span as one slice,
    kept only when the extractor's in_article places the person AT this company by its
    full name: 'adani' alone would put Adani Ports' managing director on an Adani Defence
    card, so a shared group word is not enough here."""
    core = _core_name(company)
    if not core or core not in " ".join(re.findall(r"[^\W_]+", _fold(span.in_article))):
        return None, "unanchored"
    for r in spans:
        if r.type != "Role" or r.sent != span.sent:
            continue
        if not (-3 <= r.start_c - span.end_c <= 3 or -3 <= span.start_c - r.end_c <= 3):
            continue
        lo, hi = min(span.start_c, r.start_c), max(span.end_c, r.end_c)
        if lo < p.ev_start or hi > p.ev_end:
            continue
        val = _clean(p.ev_quote[lo - p.ev_start:hi - p.ev_start])
        if len(val) < 4:
            return None, "length"
        return val, None
    return None, "no-role"


# --- the block ---------------------------------------------------------------------------
def glance_facts(company, title, props, spans, is_buyer=None, refused=None, esc=None):
    """[[label, value, quote], ...] for one card. `refused` (a dict) is incremented per
    '<type>:<reason>' for every candidate span the gates turned away."""
    props = [p if isinstance(p, Prop) else Prop(*p) for p in props]
    spans = [s if isinstance(s, Span) else Span(*s) for s in spans]
    esc = esc or (lambda t: _html.escape(str(t or ""), quote=False))
    refused = refused if refused is not None else {}
    title = _html.unescape(title or "")

    def refuse(kind, why):
        refused[kind + ":" + why] = refused.get(kind + ":" + why, 0) + 1

    found = {}          # label -> [(sortkey, value, quote)]

    def offer(label, key, value, quote):
        found.setdefault(label, []).append((key, value, quote))

    for s in spans:
        if s.type == "Money":
            p, why = _anchor_prop(company, s, props)
            if not p:
                refuse("money", why)
                continue
            label, why = money_label(s, p)
            if not label:
                refuse("money", why)
                continue
            offer(label, (s.start_c,), s.text, p.ev_quote)
        elif s.type == "Count":
            p, why = _anchor_prop(company, s, props)
            if not p:
                refuse("count", why)
                continue
            val, why = count_value(s, p, spans)
            if not val:
                refuse("count", why)
                continue
            offer("Quantity", (s.start_c,), val, p.ev_quote)
        elif s.type == "Program":
            p, why = _anchor_prop(company, s, props)
            if not p:
                refuse("programme", why)
                continue
            val, why = named_value(s, p, title, spans, "programme")
            if not val:
                refuse("programme", why)
                continue
            offer("Programme", (-(s.score or 0), s.start_c), val, p.ev_quote)
        elif s.type in ("WeaponSystem", "Platform", "Product"):
            p, why = _anchor_prop(company, s, props)
            if not p:
                refuse("system", why)
                continue
            val, why = named_value(s, p, title, spans, "system", company)
            if not val:
                refuse("system", why)
                continue
            offer("System", (-(s.score or 0), s.start_c), val, p.ev_quote)
        elif s.type == "Organization":
            # Country spans are NOT candidates: a country in a deal sentence is the
            # buyer's country, the seller's country, or just where the story is set.
            quoting, why = _quoted_in(s, props)
            if not quoting:
                refuse("counterparty", why)
                continue
            got = None
            for p in quoting:
                label, val, why = counterparty(company, title, s, p, spans, is_buyer)
                if label:
                    got = (label, val, p.ev_quote)
                    break
            if not got:
                refuse("counterparty", why)
                continue
            offer(got[0], (-(s.score or 0), s.start_c), got[1], got[2])
        elif s.type == "Person":
            p, why = _anchor_prop(company, s, props)
            if not p:
                refuse("person", why)
                continue
            val, why = person_value(company, s, p, spans)
            if not val:
                refuse("person", why)
                continue
            offer("Key person", (s.start_c,), val, p.ev_quote)

    rows, shown, shown_toks = [], set(), set()
    for label in ROW_ORDER:
        n = 0
        for _key, value, quote in sorted(found.get(label, [])):
            k = _fold(value)
            toks = set(_name_tokens(value)) if label in NAME_ROWS else set()
            if k in shown or (toks and toks & shown_toks):
                continue              # the same name under two labels is one fact
            shown.add(k)
            shown_toks |= toks
            # a slice can straddle a line break in the source; the words are unchanged
            rows.append([label, esc(re.sub(r"\s+", " ", value)), quote])
            n += 1
            if n >= ROW_CAP.get(label, 1):
                break
    return rows


def _demo():
    """Fixtures are REAL sentences from the corpus (the Stinger, Gdynia, Dataminr, Thales,
    Fujitsu, Adani, Astute and Insta articles), including the ones where the number, place
    or person is in the article but does NOT belong to the subject."""
    def sp(i, a, b, text, type_, in_article=None, gloss=None, source="gliner", score=0.9,
           sent=0):
        return Span(i, a, b, text, type_, None, gloss, in_article, source, score, sent)

    # 1. Stinger article, company "The Army": $215M is the Army's budget ask; $4M is what
    #    a missile costs (subject: the missiles) and must never become the Army's figure.
    q1 = ("The Army has asked Congress for $215 million in its fiscal year 2027 budget for "
          "the Stinger replacement along with $713 million for 14 more Sgt. Stout Systems.")
    q2 = ("U.S. air defense missiles — each of which can cost about $4 million — have "
          "been used to shoot down Iranian drones, which cost between $20,000 and $30,000 apiece.")
    props = [Prop(0, "The Army", "asks for", "$215 million in its fiscal year 2027 budget",
                  0, len(q1), q1),
             Prop(1, "U.S. air defense missiles", "have been used to shoot down",
                  "Iranian drones", 1000, 1000 + len(q2), q2)]
    a = q1.index("$215 million")
    b = q1.index("$713 million")
    c = 1000 + q2.index("$4 million")
    d = 1000 + q2.index("$20,000 and $30,000")
    spans = [sp("s1", a, a + 12, "$215 million", "Money",
                "the amount requested for the Stinger replacement", "a unit of currency"),
             sp("s2", b, b + 12, "$713 million", "Money",
                "a specific budget allocation for defense systems", "a unit of currency"),
             sp("s3", c, c + 10, "$4 million", "Money",
                "the cost of each U.S. air defense missile", "a unit of currency", sent=1),
             sp("s4", d, d + 19, "$20,000 and $30,000", "Money",
                "the cost range of Iranian drones", "a unit of currency", sent=1)]
    ref = {}
    rows = glance_facts("The Army", "US Army seeks thousands of new missiles to replace Stinger",
                        props, spans, refused=ref)
    assert rows == [["Budget", "$215 million", q1]], rows
    assert ref == {"money:unanchored": 2}, "the two unit costs are refused, not the Army's" + str(ref)

    # 2. the same article: "14 more Sgt. Stout Systems" is a quantity (count + product as one
    #    slice); a count of nations is not, and the Sgt. Stout is a System only while the
    #    headline does not already say so.
    e = q1.index("14 more")
    f = q1.index("Sgt. Stout Systems")
    spans2 = [sp("c1", e, e + 2, "14", "Count", "the number of Sgt. Stout systems requested",
                 "a number of items"),
              sp("w1", f, f + 18, "Sgt. Stout Systems", "WeaponSystem",
                 "the air defense system the Army wants more of")]
    rows = glance_facts("The Army", "t", props, spans2, refused=ref)
    assert rows == [["Quantity", "14 more Sgt. Stout Systems", q1],
                    ["System", "Sgt. Stout Systems", q1]], rows
    ref2 = {}
    rows = glance_facts("The Army", "Army asks for 14 more Sgt. Stout systems", props, spans2,
                        refused=ref2)
    assert rows == [["Quantity", "14 more Sgt. Stout Systems", q1]], rows
    assert ref2 == {"system:in-title": 1}, ref2
    q3 = "Raytheon leads the 12 nations in the NATO SeaSparrow consortium."
    p3 = [Prop(0, "Raytheon", "leads", "12 nations in the NATO SeaSparrow consortium",
               0, len(q3), q3)]
    g = q3.index("12 nations")
    h = q3.index("NATO SeaSparrow")
    ref3 = {}
    rows = glance_facts("Raytheon", "t", p3,
                        [sp("c", g, g + 10, "12 nations", "Count",
                            "the number of countries in the consortium", "a number"),
                         sp("w", h, h + 15, "NATO SeaSparrow", "WeaponSystem", "a missile")],
                        refused=ref3)
    assert not any(r[0] == "Quantity" for r in rows), rows
    assert ref3.get("count:counts-not-units") == 1, ref3

    # 3. Gdynia: PLN5 billion is what an unnamed private partner will raise -- the port
    #    authority is in the sentence, but the figure is not its deal value.
    q4 = ("The successful private partner will be responsible for designing and constructing "
          "the new container terminal, arranging financing of around PLN5 billion (USD1.31 "
          "billion), and jointly operating the terminal with the Port of Gdynia Authority.")
    p4 = [Prop(0, "The successful private partner", "will jointly operate the terminal with",
               "the Port of Gdynia Authority", 0, len(q4), q4)]
    i = q4.index("PLN5 billion")
    ref4 = {}
    rows = glance_facts("Port of Gdynia Authority", "t", p4,
                        [sp("m", i, i + 12, "PLN5 billion", "Money",
                            "Arranging financing of around PLN5 billion (USD1.31 billion)",
                            "A monetary value")], refused=ref4)
    assert rows == [], rows
    assert ref4 == {"money:untyped": 1}, ref4    # anchored (object names the port), but not a deal

    # 4. Dataminr: the deal value is typed by the span's own in_article even though the
    #    proposition's predicate is "delivers"; a ceiling ("up to") is refused.
    q5 = ("Dataminr won a $318 million contract from the Defense Department for AI-powered "
          "situational awareness technology.")
    p5 = [Prop(0, "Dataminr", "delivers", "AI-powered situational awareness technology",
               0, len(q5), q5)]
    j = q5.index("$318 million")
    rows = glance_facts("Dataminr", "t", p5,
                        [sp("m", j, j + 12, "$318 million", "Money",
                            "the amount of money awarded in the contract")])
    assert rows == [["Deal value", "$318 million", q5]], rows
    q6 = "The framework is valued at up to £8 billion over eight years."
    k = q6.index("£8 billion")
    ref6 = {}
    rows = glance_facts("Ericsson", "t",
                        [Prop(0, "Ericsson", "is a provider for", "the framework", 0, len(q6), q6)],
                        [sp("m", k, k + 10, "£8 billion", "Money",
                            "the value of the framework over eight years")], refused=ref6)
    assert rows == [] and ref6 == {"money:ceiling": 1}, (rows, ref6)
    # a company's own turnover, backlog or R&D spend is not a deal (Thales, Saab)
    q7 = "In 2025, the Group generated sales of €22.1 billion."
    ref7 = {}
    rows = glance_facts("Thales", "t",
                        [Prop(0, "Thales", "generated", "sales of €22.1 billion", 0, len(q7), q7)],
                        [sp("m", 38, 51, "€22.1 billion", "Money",
                            "the Group's total sales in 2025", "a monetary amount")], refused=ref7)
    assert rows == [] and ref7 == {"money:not-a-deal-figure": 1}, (rows, ref7)
    # ...but an acquisition price IS the deal value, 'price' notwithstanding
    q7b = "Leonardo finalised the acquisition of Iveco Defence for a price of €1.6 billion."
    rows = glance_facts("Leonardo", "t",
                        [Prop(0, "Leonardo", "finalised", "the acquisition of Iveco Defence",
                              0, len(q7b), q7b)],
                        [sp("m", q7b.index("€1.6"), q7b.index("€1.6") + 12, "€1.6 billion",
                            "Money", "the acquisition price paid by Leonardo")])
    assert rows == [["Deal value", "€1.6 billion", q7b]], rows

    # 5. a quote that does not show the span at its offset proves nothing
    ref8 = {}
    rows = glance_facts("Dataminr", "t", p5,
                        [sp("m", j + 1, j + 13, "$318 million", "Money",
                            "the amount of money awarded in the contract")], refused=ref8)
    assert rows == [] and ref8 == {"money:misaligned": 1}, (rows, ref8)

    # 6. counterparties: Astute signed WITH Hanwha (Counterparty); the Finnish Defence Forces
    #    signed an agreement with Insta (a tie, not a purchase -> Counterparty, even for a
    #    force); Germany, merely in the sentence where Rheinmetall expects a contract, is not
    #    a party to anything -- and no Country ever is; NATO named as an interoperability
    #    target is not a customer of the network that talks to it.
    q9 = "Astute Systems signed a contract with Hanwha Defence Australia."
    p9 = [Prop(0, "Astute Systems", "signed with", "Hanwha Defence Australia", 0, len(q9), q9)]
    m = q9.index("Hanwha")
    rows = glance_facts("Astute Systems", "t", p9,
                        [sp("o", m, m + 24, "Hanwha Defence Australia", "Organization",
                            "the company Astute Systems signed a contract with", score=0.67),
                         sp("o2", 0, 14, "Astute Systems", "Organization", score=0.96)])
    assert rows == [["Counterparty", "Hanwha Defence Australia", q9]], rows
    q10 = "Insta and the Finnish Defence Forces signed a multi-year agreement."
    p10 = [Prop(0, "Insta and the Finnish Defence Forces", "signed", "multi-year agreement",
                0, len(q10), q10)]
    n = q10.index("Finnish")
    rows = glance_facts("Insta", "t", p10,
                        [sp("o", n, n + 22, "Finnish Defence Forces", "Organization", score=0.7)])
    assert rows == [["Counterparty", "Finnish Defence Forces", q10]], rows
    q11 = "Rheinmetall expects a multibillion-euro contract after Germany canceled the F126."
    p11 = [Prop(0, "Rheinmetall", "expects", "a multibillion-euro contract", 0, len(q11), q11)]
    o = q11.index("Germany")
    ref11 = {}
    rows = glance_facts("Rheinmetall", "t", p11,
                        [sp("o", o, o + 7, "Germany", "Country", score=0.97)], refused=ref11)
    assert rows == [] and ref11 == {}, (rows, ref11)        # never a candidate
    q12 = "The network delivers secure communications and interoperability with NATO C2 systems."
    p12 = [Prop(0, "Elbit Systems' network", "delivers",
                "secure communications and interoperability with NATO C2 systems", 0, len(q12), q12)]
    ref12 = {}
    rows = glance_facts("Elbit Systems", "t", p12,
                        [sp("o", q12.index("NATO"), q12.index("NATO") + 4, "NATO", "Organization",
                            "the alliance whose C2 systems the network interoperates with",
                            score=0.9)], refused=ref12)
    assert rows == [] and ref12 == {"counterparty:not-a-deal": 1}, (rows, ref12)
    # the buyer's card: the maker it awarded is its Supplier; a demonym is not a name; a
    # partner the headline already names is redundant
    q13 = "The Army awarded Raytheon a contract for 350 missiles."
    p13 = [Prop(0, "The Army", "awarded", "Raytheon a contract", 0, len(q13), q13)]
    r = q13.index("Raytheon")
    rows = glance_facts("The Army", "t", p13,
                        [sp("o", r, r + 8, "Raytheon", "Organization", score=0.9)])
    assert rows == [["Supplier", "Raytheon", q13]], rows
    q14 = "Raytheon is also working with key Dutch suppliers to produce Stinger assemblies."
    p14 = [Prop(0, "Raytheon", "is working with", "key Dutch suppliers", 0, len(q14), q14)]
    u = q14.index("Dutch suppliers")
    ref14 = {}
    rows = glance_facts("Raytheon", "t", p14,
                        [sp("o", u, u + 15, "Dutch suppliers", "Organization",
                            "the suppliers Raytheon partners with", score=0.8),
                         sp("k", u, u + 5, "Dutch", "Country", score=0.9)], refused=ref14)
    assert rows == [] and ref14 == {"counterparty:not-a-name": 1}, (rows, ref14)
    ref15 = {}
    rows = glance_facts("Airbus", "Airbus and Saab explore joint fighter development",
                        [Prop(0, "Airbus", "is looking to", "Saab as a preferred partner", 0, 60,
                              "Airbus is increasingly looking to Saab as a preferred partner")],
                        [sp("o", 34, 38, "Saab", "Organization", score=0.95)], refused=ref15)
    assert rows == [] and ref15 == {"counterparty:in-title": 1}, (rows, ref15)

    # 7. a person is a row only when the extractor places them AT this company, by its full
    #    name: Adani Ports' managing director does not belong on the Adani Defence card.
    q16 = "Kendy Hau, head of defence at Fujitsu Australia, said quantum was years away."
    p16 = [Prop(0, "Kendy Hau", "said", "quantum was years away", 0, len(q16), q16)]
    rows = glance_facts("Fujitsu Australia", "t", p16,
                        [sp("p", 0, 9, "Kendy Hau", "Person", "the head of defence at Fujitsu Australia"),
                         sp("r", 11, 26, "head of defence", "Role")])
    assert rows == [["Key person", "Kendy Hau, head of defence", q16]], rows
    ref17 = {}
    rows = glance_facts("Boeing", "t", p16,
                        [sp("p", 0, 9, "Kendy Hau", "Person", "the head of defence at Fujitsu Australia"),
                         sp("r", 11, 26, "head of defence", "Role")], refused=ref17)
    assert rows == [] and ref17 == {"person:unanchored": 1}, (rows, ref17)
    q18 = "Mr Karan Adani, Managing Director, Adani Ports & SEZ, attended the event."
    p18 = [Prop(0, "Mr Karan Adani", "attended", "the event", 0, len(q18), q18)]
    ref18 = {}
    rows = glance_facts("Adani Defence & Aerospace", "t", p18,
                        [sp("p", 3, 14, "Karan Adani", "Person",
                            "the Managing Director of Adani Ports & SEZ who attended"),
                         sp("r", 16, 33, "Managing Director", "Role")], refused=ref18)
    assert rows == [] and ref18 == {"person:unanchored": 1}, (rows, ref18)
    q19 = "@ Matt Warnick, CEO American Rheinmetall"
    p19 = [Prop(0, "Matt Warnick", "is", "CEO of American Rheinmetall", 0, len(q19), q19)]
    rows = glance_facts("Rheinmetall", "t", p19,
                        [sp("p", 0, 14, "@ Matt Warnick", "Person", "the CEO of American Rheinmetall"),
                         sp("r", 16, 19, "CEO", "Role")])
    assert rows == [["Key person", "Matt Warnick, CEO", q19]], rows

    # 8. a programme the headline already names is redundant; a generic word, a bare
    #    3-letter acronym, and an Act of Congress are not programme names
    q20 = "General Atomics will pitch a new drone for the MMA effort."
    p20 = [Prop(0, "General Atomics", "will pitch", "a new drone for the MMA effort", 0, len(q20), q20)]
    t = q20.index("MMA effort")
    mma = "the program for which General Atomics plans to pitch a new drone"
    ref20 = {}
    rows = glance_facts("General Atomics", "General Atomics pitches drone for MMA effort", p20,
                        [sp("g", t, t + 10, "MMA effort", "Program", mma, score=0.75)], refused=ref20)
    assert rows == [] and ref20 == {"programme:in-title": 1}, (rows, ref20)
    ref21 = {}
    rows = glance_facts("General Atomics", "t", p20,
                        [sp("g", t, t + 10, "MMA effort", "Program", mma, score=0.75),
                         sp("g2", t, t + 10, "MMA effort", "Program", mma, score=0.3),
                         sp("g3", t, t + 3, "MMA", "Program", mma, score=0.9),
                         sp("g4", t + 4, t + 10, "effort", "Program", mma, score=0.9)], refused=ref21)
    assert rows == [["Programme", "MMA effort", q20]], rows
    assert ref21 == {"programme:low-score": 1, "programme:length": 1, "programme:generic": 1}, ref21
    # a business unit typed Program is not a programme -- the extractor's own gloss says so
    q20b = "Barbara Borgonovi, president of Naval Power at Raytheon, said the array was installed."
    p20b = [Prop(0, "Barbara Borgonovi", "said", "the array was installed", 0, len(q20b), q20b)]
    y = q20b.index("Naval Power")
    ref20b = {}
    rows = glance_facts("Raytheon", "t", p20b,
                        [sp("g", y, y + 11, "Naval Power", "Program",
                            "the Raytheon business unit Barbara Borgonovi presides over", score=0.8)],
                        refused=ref20b)
    assert rows == [] and ref20b == {"programme:not-a-programme": 1}, (rows, ref20b)
    # plural in the block, singular in the headline: still the headline's word
    q20c = "The Air Force awarded General Atomics contracts to keep building their proposed CCAs."
    p20c = [Prop(0, "The Air Force", "awarded", "General Atomics contracts", 0, len(q20c), q20c)]
    z = q20c.index("CCAs")
    ref20c = {}
    rows = glance_facts("General Atomics", "General Atomics wins Air Force CCA production contract",
                        p20c, [sp("g", z, z + 4, "CCAs", "Program", "the CCA program", score=0.8)],
                        refused=ref20c)
    assert rows == [] and ref20c == {"programme:in-title": 1}, (rows, ref20c)
    # a capitalised kind of organisation is not a name; a rival is labelled as one; one name
    # under two labels ('EyePulse project' / 'EyePulse') is one row
    q20d = "Building a Robust Supply Chain: 10,000 Suppliers support Northrop Grumman."
    p20d = [Prop(0, "10,000 Suppliers", "support", "Northrop Grumman", 0, len(q20d), q20d)]
    ref20d = {}
    rows = glance_facts("Northrop Grumman", "t", p20d,
                        [sp("o", q20d.index("Suppliers"), q20d.index("Suppliers") + 9, "Suppliers",
                            "Organization", "the suppliers in Northrop Grumman's supply chain",
                            score=0.7)], refused=ref20d)
    assert rows == [] and ref20d == {"counterparty:not-a-name": 1}, (rows, ref20d)
    q20e = "The Army will choose between Rheinmetall and U.S. prime General Dynamics Land Systems in 2027."
    p20e = [Prop(0, "The Army", "will choose between", "Rheinmetall and General Dynamics Land Systems",
                 0, len(q20e), q20e)]
    gd = q20e.index("General Dynamics Land Systems")
    rows = glance_facts("Rheinmetall", "t", p20e,
                        [sp("o", gd, gd + 29, "General Dynamics Land Systems", "Organization",
                            "the U.S. prime competing with Rheinmetall for the XM30", score=0.9)])
    assert rows == [["Rival", "General Dynamics Land Systems", q20e]], rows
    q20f = "The collaborative EyePulse project highlighted Daher's expertise; Daher developed EyePulse."
    p20f = [Prop(0, "Daher", "developed", "EyePulse", 0, len(q20f), q20f)]
    e1, e2 = q20f.index("EyePulse project"), q20f.rindex("EyePulse")
    rows = glance_facts("Daher", "t", p20f,
                        [sp("g", e1, e1 + 16, "EyePulse project", "Program", "the project", score=0.8),
                         sp("s", e2, e2 + 8, "EyePulse", "Product", "the demonstrator", score=0.9)])
    assert rows == [["Programme", "EyePulse project", q20f]], rows
    q22 = "NATO allies followed the 2026 Defense Authorization Act into action."
    p22 = [Prop(0, "NATO allies", "followed", "the 2026 Defense Authorization Act", 0, len(q22), q22)]
    v = q22.index("Defense Authorization Act")
    ref22 = {}
    rows = glance_facts("NATO", "t", p22,
                        [sp("g", v, v + 25, "Defense Authorization Act", "Program", score=0.8)],
                        refused=ref22)
    assert rows == [] and ref22 == {"programme:not-a-programme": 1}, (rows, ref22)
    # a portfolio is not a system; the same name under two labels is one row
    q23 = "Elbit Systems is a global leader in the field of ISR & Targeting solutions."
    p23 = [Prop(0, "Elbit Systems", "is a global leader in", "ISR & Targeting solutions", 0, len(q23), q23)]
    w = q23.index("ISR")
    ref23 = {}
    rows = glance_facts("Elbit Systems", "t", p23,
                        [sp("s", w, w + 25, "ISR & Targeting solutions", "Product", score=0.8)],
                        refused=ref23)
    assert rows == [] and ref23 == {"system:generic": 1}, (rows, ref23)
    q24 = "Fincantieri announces the agreement for the acquisition of Defcomm."
    p24 = [Prop(0, "Fincantieri", "announces the agreement for the acquisition of", "Defcomm",
                0, len(q24), q24)]
    x = q24.index("Defcomm")
    rows = glance_facts("Fincantieri", "t", p24,
                        [sp("o", x, x + 7, "Defcomm", "Organization", "the company being acquired", score=0.9),
                         sp("s", x, x + 7, "Defcomm", "Product", score=0.9)])
    assert rows == [["Counterparty", "Defcomm", q24]], rows

    # 9. anchoring: generic-only names need every word; a short token alone is not enough
    assert anchored("The Army", "The Army has asked Congress")
    assert not anchored("US Army", "The Army has asked Congress"), "'us' is missing"
    assert anchored("U.S. Army", "the US Army wants 5,000 missiles")
    assert anchored("Port of Gdynia Authority", "with the Port of Gdynia Authority")
    assert not anchored("Port of Gdynia Authority", "the port hosts an exercise"), "'port' alone"
    assert anchored("Lockheed Martin", "Lockheed has committed $250 million")
    assert not anchored("Insta", "install the radar"), "whole word only"
    assert in_title("Gripen E", "Saab Completes First Flight of Gripen F")
    assert in_title("The ROGUE-Fires", "Oshkosh Defense wins USMC ROGUE-Fires Block 2 order")
    assert not in_title("Bergepanzer 3 Büffel", "Rheinmetall wins Bundeswehr order for 23 armoured recovery vehicles")
    assert not in_title("Skyranger 30", "Rheinmetall faces delays with Bundeswehr order")
    # HTML-escaped values, raw quotes
    q25 = "Saab & Bofors won a SEK 1bn order."
    rows = glance_facts("Saab", "t", [Prop(0, "Saab & Bofors", "won", "a SEK 1bn order", 0, len(q25), q25)],
                        [sp("m", 20, 27, "SEK 1bn", "Money", "the order value")])
    assert rows == [["Deal value", "SEK 1bn", q25]], rows
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo()
