"""Dynamic "At a glance" — the facts THIS article states, read from the article itself.

    python glance_facts.py --demo      # self-check, no database
    python glance_facts.py --report    # what would be extracted, per row, with quotes
    python glance_facts.py --verify    # hard assertions + per-language coverage
    python glance_facts.py --apply     # write into serving.signal_detail.facts

WHY THE FIRST DESIGN WAS THROWN AWAY
------------------------------------
The first version read the six `lens` quotes stored per signal. An audit against all 14
real rows killed it, for reasons worth keeping:

  * The facts the operator wants are IN THE ARTICLE and not in those six quotes. The
    Carl-Gustaf contract "is valid for ten years" appears in no stored row at all. A
    lens-only extractor can only ever produce a thin panel.
  * The lens rows are `claim - "quote"`, and the CLAIM halves contain text that is in no
    source ("Saab delivers orispe", "Ondas Networks is a product"). Treating them as
    evidence makes hallucinated tokens groundable.

So evidence is `extracted.document.text` - the article as fetched - and nothing else.

AND THE LANGUAGE PROBLEM IS NOT A DETECTION PROBLEM
---------------------------------------------------
10 of the 14 rows are not English: Malay 3, Croatian 3, Swedish, German, French,
Lithuanian, Ukrainian. The first design planned to detect script and count non-Latin
misses - which would have been blind to 9 of those 10, since all but Ukrainian are Latin
script. That is this codebase's recurring "a closed keyword list is a language detector"
fault for the fourth time.

It does not need solving. `extracted.document.language` is already populated for every
row by the pipeline. Read the language, pick that language's table, and count coverage
PER LANGUAGE - a language whose rows all come back empty is a table to write, and it is
visible instead of silent.

ENGLISH VALUES, SOURCE-LANGUAGE QUOTES
--------------------------------------
The operator reads English; ten of the fourteen sources do not. So the VALUE is rendered
in English ("460 miljoner kronor" -> "SEK 460 million", "deset godina" -> "ten years")
and the QUOTE is left verbatim in the source language, because the quote is the evidence
and evidence that has been rewritten is no longer evidence - the original figure is still
visible inside it.

Words only, never numbers, and never a currency conversion: SEK 460 million must not
become $44 million, because no source states that and an exchange rate is a fact about
today rather than about the contract. `same_digits()` enforces it - any rendering that
moves a digit is discarded in favour of the original, and --verify fails on it.

A useful side effect: the Swedish and Croatian reports of the SAME Saab contract now
render identically (SEK 460 million / SEK 640 million / ten years / 2026-2029), which is
a free cross-check that the extraction is not language-dependent.

THE RULE
--------
A fact is emitted only when:
  1. its value appears VERBATIM in one sentence of the document, and
  2. that sentence carries a subject anchor from THIS DOCUMENT'S LANGUAGE, and
  3. no vetoing marker (ceiling, negation) applies to it, and
  4. the sentence is stored with the fact, so the operator reads what we read.
"""
import argparse
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DSN = os.environ.get("KSSL_DSN",
                     "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")

# ── per-language vocabulary ───────────────────────────────────────────────────
# Written from the ACTUAL sentences in these 14 documents, not from a phrasebook. The
# comment on each line is the sentence it was taken from, so a later reader can tell a
# word that earns its place from one that was guessed.
LANG = {
    "en": {
        "unit": r"million|billion|bn\b|trillion",
        # "worth 460 million" / "order ... worth"
        "anchor": r"order|contract|deal|purchase|procure|award|worth|tender|buy",
        "ceiling": r"up to|maximum|estimated|potential|option|ceiling|framework|as much as",
        "negate": r"does not constitute|not (?:a|an) (?:final|firm)|no (?:firm )?order|"
                  r"has not (?:been )?(?:signed|placed)|would (?:be|serve)|if (?:the )?agreement",
        "qty_noun": r"units?|systems?|vehicles?|rounds?|aircraft|helicopters?|radars?|"
                    r"rifles?|guns?|tanks?|drones?|missiles?|launchers?",
        "term": r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)[\s-](years?|months?)",
        "term_anchor": r"contract|agreement|framework|valid|term|period",
        "deliver": r"deliver\w*|deliveries|in service|entry into service",
    },
    "sv": {
        # "Ordervärdet är 460 miljoner kronor och leveranser är planerade 2026-2029"
        "unit": r"miljoner|miljarder",
        "anchor": r"order|ordervärdet|kontrakt|avtal|värde|beställning\w*|upphandling",
        # "optioner på ytterligare beställningar till ett värde av upp till 640 miljoner"
        "ceiling": r"option\w*|upp till|ytterligare|maximalt|potentiell\w*",
        "negate": r"inte (?:en|ett) (?:slutlig|fast)|ingen order",
        "qty_noun": r"enheter|system|fordon|granatgevär|radar\w*|robotar",
        "term": r"(\d+|ett|två|tre|fyra|fem|sex|sju|åtta|nio|tio)\s*(år|månader)",
        "term_anchor": r"kontrakt|avtal|löper|giltig",
        "deliver": r"leverans\w*|levereras",
    },
    "hr": {
        # "Vrijednost narudžbe iznosi 460 milijuna SEK"
        "unit": r"milijuna|milijardi|milijun\w*",
        "anchor": r"narudžb\w*|ugovor\w*|vrijednost\w*|nabav\w*|kupnj\w*",
        # "potencijalne opcije ukupne vrijednosti do 640 milijuna SEK"
        "ceiling": r"opcij\w*|do\b|potencijaln\w*|najviše|ukupne vrijednosti",
        "negate": r"nije (?:konačn|potpisan)\w*|nema narudžbe",
        "qty_noun": r"radar\w*|sustav\w*|vozil\w*|komad\w*|jedinic\w*",
        "term": r"(\d+|jedn\w+|dvije|tri|četiri|pet|šest|sedam|osam|devet|deset)\s*(godin\w*|mjesec\w*)",
        "term_anchor": r"ugovor\w*|vrijedi|razdoblj\w*",
        # "isporuke su planirane za razdoblje od 2026. do 2029. godine"
        "deliver": r"isporuk\w*|isporučen\w*",
    },
    "ms": {
        "unit": r"juta|bilion|trilion",
        "anchor": r"pesanan|kontrak|nilai|perolehan|belian|tender",
        "ceiling": r"sehingga|maksimum|potensi|pilihan|anggaran",
        "negate": r"belum (?:dimuktamadkan|ditandatangani)|bukan pesanan",
        "qty_noun": r"unit|sistem|kenderaan|pesawat|radar|senjata",
        "term": r"(\d+)\s*(tahun|bulan)",
        "term_anchor": r"kontrak|perjanjian|tempoh|sah",
        "deliver": r"penghantaran|dihantar|diserahkan",
    },
    "de": {
        "unit": r"Millionen|Milliarden|Mio\.?|Mrd\.?",
        "anchor": r"Auftrag\w*|Vertrag\w*|Wert|Bestellung\w*|Beschaffung\w*|Kauf",
        "ceiling": r"bis zu|Option\w*|maximal|voraussichtlich|potenziell",
        "negate": r"kein\w* (?:fester )?Auftrag|noch nicht (?:unterzeichnet|erteilt)",
        "qty_noun": r"Einheiten|Systeme|Fahrzeuge|Flugzeuge|Radare|Waffen",
        "term": r"(\d+|ein|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)\s*(Jahre?n?|Monate?n?)",
        "term_anchor": r"Vertrag\w*|Laufzeit|gültig",
        "deliver": r"Lieferung\w*|geliefert|Auslieferung\w*",
    },
    "fr": {
        "unit": r"millions?|milliards?",
        "anchor": r"commande\w*|contrat\w*|valeur|marché\w*|achat\w*|acquisition\w*",
        "ceiling": r"jusqu'à|option\w*|maximum|estimé\w*|potentiel\w*",
        "negate": r"n'est pas (?:une )?commande (?:ferme|finale)|pas encore signé",
        "qty_noun": r"unités|systèmes|véhicules|avions|radars|armes",
        "term": r"(\d+|un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix)\s*(ans?|mois)",
        "term_anchor": r"contrat|accord|durée|valable",
        "deliver": r"livraison\w*|livré\w*",
    },
    "lt": {
        "unit": r"milijon\w*|milijard\w*|mln\.?",
        "anchor": r"užsakym\w*|sutart\w*|vert[ėe]\w*|pirkim\w*",
        "ceiling": r"iki|opcij\w*|maksimal\w*|galim\w*",
        "negate": r"n[ėe]ra (?:galutin|pasirašyt)\w*",
        "qty_noun": r"vienet\w*|sistem\w*|transporto priemon\w*|radar\w*",
        "term": r"(\d+)\s*(met\w*|m[ėe]nes\w*)",
        "term_anchor": r"sutart\w*|galioja|laikotarp\w*",
        "deliver": r"pristat\w*|tiekim\w*",
    },
    "uk": {
        "unit": r"млн|мільйон\w*|млрд|мільярд\w*",
        "anchor": r"замовлен\w*|контракт\w*|вартіст\w*|закупівл\w*|придбан\w*",
        "ceiling": r"до\b|опці\w*|максимум|потенційн\w*|орієнтовн\w*",
        "negate": r"не є (?:остаточн|підписан)\w*|немає замовлення",
        "qty_noun": r"одиниц\w*|систем\w*|машин\w*|установ\w*|радар\w*",
        "term": r"(\d+)\s*(рок\w*|років|місяц\w*)",
        "term_anchor": r"контракт\w*|дію|термін",
        "deliver": r"постач\w*|поставк\w*",
    },
}

# Currency is NOT per-language: the symbol or ISO code is what makes an amount MONEY, and
# "34 juta tong" (34 million barrels, in the Malay Diego Garcia article) is exactly what
# happens without it. A unit word alone is never enough.
CURRENCY = (r"(?:[$€£₹]|\b(?:USD|EUR|GBP|INR|SEK|NOK|DKK|CHF|JPY|CNY|AUD|RM|UAH|PLN)\b"
            r"|\b(?:kronor|kronur|kr|crore|lakh|euros?|dollars?|dolar\w*|eurų|євро|грн"
            r"|Euro|rupees?)\b)")
AMOUNT = r"\d[\d\s.,]*"


def norm(s):
    """NFKC, entity-free, whitespace-collapsed. Case is PRESERVED."""
    s = unicodedata.normalize("NFKC", s or "")
    s = (s.replace("&amp;", "&").replace("&nbsp;", " ")
           .replace("&ldquo;", '"').replace("&rdquo;", '"')
           .replace("&#39;", "'").replace("&quot;", '"'))
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"[‘’]", "'", s)
    return re.sub(r"\s+", " ", s).strip()


def squash(s):
    """For comparison only: the characters that carry meaning."""
    return re.sub(r"[^0-9a-zЀ-ӿ]+", "", (s or "").lower())


# ── sentence splitting ────────────────────────────────────────────────────────
# The traps, all present in these 14 documents:
#   "$2.3 billion"                 a period inside a number
#   "od 2026. do 2029. godine"     Croatian writes a period after every year
#   "U.S. Department of State"     initialisms
#   "Mio." / "mln." / "Mrd."       abbreviated units
ABBR = re.compile(r"(?:^|\s)(?:[A-ZÅÄÖÜ]|Mio|Mrd|mln|No|Nr|St|Dr|Mr|Ms|vs|approx"
                  r"|etc|inc|Inc|Ltd|Co)$")
BOUND = re.compile(r"[.!?]+[\s ]+")
NEXT_OK = re.compile(r"[\"'(\[]?[A-ZÅÄÖÜÉÈÀÂÎÔÛ"
                     r"ŠĐČĆŽА-ЯЄІЇҐ 0-9]")


def sentences(text):
    """Split into sentences without breaking the four things that break splitters here.

    A fixed-width lookbehind cannot express "not after an abbreviation", so the boundary
    is proposed by the regex and then VETOED by looking at what precedes it:
      "$2.3 billion"              a period between digits
      "od 2026. do 2029. godine"  Croatian puts a period after every year
      "U.S. Department of State"  initialisms
      "Mio." / "mln." / "Mrd."    abbreviated units
    Each of those is present in these 14 documents; each would otherwise cut a value
    away from the anchor that makes it meaningful.
    """
    t = norm(text)
    out, start = [], 0
    for m in BOUND.finditer(t):
        head = t[start:m.start()]
        tail = t[m.end():]
        if not tail or not NEXT_OK.match(tail):
            continue
        # NOTE: there is deliberately NO "don't split after a digit" rule.
        # A decimal never reaches here - BOUND requires whitespace after the period, and
        # "$2.3 billion" has none. Croatian year ordinals are already handled by NEXT_OK,
        # because "od 2026. do 2029." is followed by a LOWERCASE word. Vetoing every
        # post-digit break as well merged two Swedish sentences into one, and the option
        # ceiling in the second half then re-labelled the order value in the first:
        # "Ordervardet ar 460 miljoner kronor" was published as an option.
        if ABBR.search(head[-6:]):
            continue
        seg = head.strip()
        if len(seg) >= 12:
            out.append(seg)
            start = m.end()
    last = t[start:].strip()
    if len(last) >= 12:
        out.append(last)
    return out


# ── extractors ────────────────────────────────────────────────────────────────
def _money_hits(sent):
    """Every (value, span) in a sentence that is an AMOUNT OF MONEY."""
    out = []
    for rx in (CURRENCY + r"\s?(" + AMOUNT + r")\s?(?:%s)?",
               r"(" + AMOUNT + r")\s?(?:%s)\s?" + CURRENCY):
        pass
    # one pattern, both orders: currency may lead ("$2.3 billion") or trail
    # ("460 miljoner kronor"), and the unit word sits between or after the number.
    pat = re.compile(
        r"(?:" + CURRENCY + r"\s*(" + AMOUNT + r")(?:\s*(?:%s))?"
        r"|(" + AMOUNT + r")\s*(?:%s)?\s*" + CURRENCY + r")", re.I)
    return out, pat


def money_pattern(units):
    return re.compile(
        r"(?:" + CURRENCY + r"\s*" + AMOUNT + r"(?:\s*(?:" + units + r"))?"
        r"|" + AMOUNT + r"\s*(?:" + units + r")\s*" + CURRENCY +
        r"|" + AMOUNT + r"\s*(?:" + units + r")?\s*" + CURRENCY + r")", re.I)


def near(rx, sent, at, before=45, after=25):
    """Is a marker within reach of position `at`, rather than merely in the sentence?

    Sentence-local grounding on its own is too loose, and the first run of this
    extractor proved it - both of these were real false positives:

      "Vrijednost narudzbe iznosi 460 milijuna SEK, a isporuke ... do 2029. godine"
        -> Croatian `do` ("until") sits 60 characters away, attached to the DELIVERY
           window, and re-labelled a firm order value as an option ceiling.
      "union agreements that guarantee ... jobs ... for ten years"
        -> the anchor `agreements` is 100 characters from `ten years` and is about
           employment, not the contract's term.

    A marker earns its veto by being next to the value it modifies.
    """
    lo, hi = max(0, at - before), min(len(sent), at + after)
    return bool(re.search(rx, sent[lo:hi], re.I))


# Markers strong enough to speak for a whole sentence regardless of distance: they
# describe the AMOUNT itself, not some other number nearby.
STRONG_CEILING = re.compile(
    "potential|maximum estimated|estimated value|up to|as much as|ceiling"
    "|potencijaln|ukupne vrijednosti|opcij"
    "|optioner|upp till|potentiell"
    "|potenziell|bis zu|potentiel|jusqu|potensi|потенційн", re.I)

# Speculation. A projected or unofficial schedule is not a delivery window.
SPECULATIVE = re.compile(
    "unofficial|projected|expected|anticipat|could |may |might|proposal|proposed"
    "|planned to be|possible|speculat", re.I)



def has(rx, sent):
    return bool(re.search(rx, sent, re.I))


def extract(text, lang):
    """[(label, value, quote)] for one document. Order is FIXED, not confidence-ranked."""
    tab = LANG.get(lang)
    if not tab:
        return [], "no table for language %r" % lang
    money = money_pattern(tab["unit"])
    found, seen_money = {}, set()

    for sent in sentences(text):
        # ---- money: order value vs option/ceiling ----
        for m in money.finditer(sent):
            val = norm(m.group(0))
            strong = bool(STRONG_CEILING.search(sent))
            # An ORDER value needs an order to belong to. A CEILING does not: "the
            # $2.3 billion figure represents the maximum estimated value of the full
            # package" names what the amount is without using the word order, and
            # refusing it left the Norway row - the article the operator opened - with
            # no money fact at all. Adding "value" to the generic anchor instead would
            # have published "secondary markets valued at EUR 1 billion" as an order.
            if not strong and not has(tab["anchor"], sent):
                continue
            ceiling = strong or near(tab["ceiling"], sent, m.start())
            negated = has(tab["negate"], sent)
            key = squash(val)
            if key in seen_money:
                continue
            seen_money.add(key)
            # AUDIT FIX: the Norway row states "$2.3 billion" with anchor "purchase" and
            # is NOT an order - the same article says the approval "does not constitute a
            # final Norwegian order" and calls the figure "the maximum estimated value".
            # A ceiling or a negation anywhere in the sentence routes the amount away
            # from Order value; it never silently becomes one.
            label = "Order value" if not (ceiling or negated) else "Option / ceiling"
            found.setdefault(label, (val, sent))

        # ---- quantity ----
        for m in re.finditer(r"(?<![\w-])(\d[\d,]*)\s+((?:[\w/-]+\s+){0,3}?(?:%s))"
                             % tab["qty_noun"], sent, re.I):
            n = m.group(1)
            # AUDIT FIX: "FV-014 LM" yielded Quantity "014 LM", and "155-mm" is a
            # calibre. A digit run preceded by a hyphen or followed by a calibre unit is
            # a designation, not a count.
            if re.search(r"[-–/]\s*$", sent[:m.start(1)]):
                continue
            if re.match(r"\s*-?\s*(mm|мм|cm|kg|km)\b", sent[m.end(1):], re.I):
                continue
            if n.startswith("0"):
                continue
            # "the Bell 412 helicopters" is a model, not 412 aircraft. A number
            # directly after a Capitalised word is part of a designation - Bell 412,
            # Block 70, Mk 44 - and publishing it as a quantity is the same class of
            # error as "014 LM". A count is introduced by an ordinary word.
            prev = re.search(r"([\w'-]+)\s+$", sent[:m.start(1)])
            if prev and prev.group(1)[:1].isupper():
                continue
            found.setdefault("Quantity", (norm(m.group(0)), sent))

        # ---- contract term ----
        m = re.search(tab["term"], sent, re.I)
        if m and near(tab["term_anchor"], sent, m.start(), before=40, after=40):
            found.setdefault("Contract term", (norm(m.group(0)), sent))

        # ---- delivery window ----
        # A RANGE only. The bare-year fallback this replaces produced four false
        # positives out of five hits - a product-launch year, an agreement year and a
        # half-stated window ("2026" out of "between 2026 and 2027") - because any
        # article using the word "delivery" also contains a year somewhere.
        if has(tab["deliver"], sent) and not SPECULATIVE.search(sent):
            m = re.search(r"((?:19|20)\d\d)[.]?\s*(?:[-–]|\bto\b|\bi\b|\bdo\b"
                          r"|\boch\b|\bund\b|\bet\b|\bhingga\b|\bir\b|та)"
                          r"\s*((?:19|20)\d\d)", sent, re.I)
            if m:
                found.setdefault("Delivery", (norm(m.group(0)), sent))


    order = ["Order value", "Option / ceiling", "Quantity", "Contract term", "Delivery"]
    return [(k, found[k][0], found[k][1]) for k in order if k in found], ""


# ── rendering the value in English ─────────────────────────────────────
# The operator reads English; the sources are Swedish, Croatian, Malay, French, German,
# Lithuanian and Ukrainian. So the VALUE is rendered in English while the QUOTE stays
# verbatim in the source language, because the quote is the evidence and evidence that
# has been rewritten is no longer evidence.
#
# This translates WORDS ONLY - the unit ("miljoner" -> "million"), the currency name
# ("kronor" -> "SEK"), a spelled-out number ("tio" -> "ten"), a counted noun ("pesawat"
# -> "aircraft"). It NEVER converts: SEK 460 million does not become $44 million, because
# no source states that figure and an exchange rate is a fact about today, not about the
# contract. `same_digits` below enforces exactly that - a rendering that changes any
# digit is discarded and the original is kept.
EN_UNIT = {
    "miljoner": "million", "miljarder": "billion",
    "milijuna": "million", "milijun": "million", "milijardi": "billion",
    "juta": "million", "bilion": "billion", "trilion": "trillion",
    "millionen": "million", "milliarden": "billion", "mio": "million", "mrd": "billion",
    "millions": "million", "million": "million", "milliards": "billion",
    "milliard": "billion", "billion": "billion", "bn": "billion",
    "milijon": "million", "milijonu": "million", "milijardu": "billion", "mln": "million",
    "млн": "million", "млрд": "billion",
    "мільйонів": "million",
}
EN_CURRENCY = {
    "kronor": "SEK", "kronur": "SEK", "kr": "SEK",
    "euros": "EUR", "euro": "EUR", "eurų": "EUR", "євро": "EUR",
    "dollars": "USD", "dollar": "USD", "dolar": "USD", "грн": "UAH",
    "rupees": "INR",
}
EN_NUMWORD = {
    "ett": "one", "två": "two", "tre": "three", "fyra": "four", "fem": "five",
    "sex": "six", "sju": "seven", "åtta": "eight", "nio": "nine", "tio": "ten",
    "jedna": "one", "dvije": "two", "četiri": "four", "pet": "five",
    "šest": "six", "sedam": "seven", "osam": "eight", "devet": "nine",
    "deset": "ten",
    "ein": "one", "zwei": "two", "drei": "three", "vier": "four", "fünf": "five",
    "sechs": "six", "sieben": "seven", "acht": "eight", "neun": "nine", "zehn": "ten",
    "un": "one", "deux": "two", "trois": "three", "quatre": "four", "cinq": "five",
    "sept": "seven", "huit": "eight", "neuf": "nine", "dix": "ten",
}
EN_PERIOD = {
    "år": "years", "månader": "months",
    "godina": "years", "godine": "years", "mjeseci": "months",
    "jahre": "years", "jahren": "years", "monate": "months", "monaten": "months",
    "ans": "years", "an": "year", "mois": "months",
    "tahun": "years", "bulan": "months",
    "metų": "years", "metai": "years", "mėnesių": "months",
    "років": "years", "місяців": "months",
}
EN_NOUN = {
    "pesawat": "aircraft", "kenderaan": "vehicles", "senjata": "weapons",
    "unit": "units", "sistem": "systems",
    "radara": "radars", "radar": "radars", "vozila": "vehicles", "komada": "units",
    "sustava": "systems", "jedinica": "units",
    "granatgevär": "launchers", "fordon": "vehicles", "enheter": "units",
    "fahrzeuge": "vehicles", "flugzeuge": "aircraft", "einheiten": "units",
    "véhicules": "vehicles", "avions": "aircraft", "unités": "units",
}


ISO_CUR = {"USD", "EUR", "GBP", "INR", "SEK", "NOK", "DKK", "CHF", "JPY", "CNY",
           "AUD", "RM", "UAH", "PLN"}
SYMBOL_CUR = {"$", "€", "£", "₹"}


def same_digits(a, b):
    """Both strings carry exactly the same numerals, in the same order."""
    return re.findall(r"\d", a or "") == re.findall(r"\d", b or "")


def _word_en(w):
    k = w.lower().strip(".,")
    for table in (EN_UNIT, EN_CURRENCY, EN_NUMWORD, EN_PERIOD, EN_NOUN):
        if k in table:
            return table[k]
    return None


def to_english(label, value, lang):
    """The value as an English reader would write it, or the original if it cannot be.

    Money is re-ordered as well as translated: "460 miljoner kronor" is written
    "SEK 460 million", because an English reader expects the currency in front. A symbol
    currency is already in front and is left alone ("$2.3 billion").
    """
    if lang == "en":
        return value
    words = value.split()
    cur = num = unit = None
    rest = []
    for w in words:
        k = w.lower().strip(".,")
        if w.upper() in ISO_CUR:
            # already an ISO code in the source ("640 milijuna SEK") - keep it as-is
            cur = w.upper()
        elif w in SYMBOL_CUR:
            cur = w
        elif k in EN_CURRENCY:
            cur = EN_CURRENCY[k]
        elif k in EN_UNIT:
            unit = EN_UNIT[k]
        elif re.fullmatch(r"[\d][\d\s.,]*", w):
            num = w.strip(".,")
        else:
            rest.append(w)
    if num and (cur or unit) and label in ("Order value", "Option / ceiling"):
        out = " ".join(x for x in (cur, num, unit) if x)
    else:
        out = " ".join(_word_en(w) or w for w in words)
    out = re.sub(r"\s+", " ", out).strip()
    # A rendering that changes a digit is not a rendering, it is a new claim.
    return out if out and same_digits(out, value) else value



# ── grounding ─────────────────────────────────────────────────────────────────
def grounded(facts, text):
    """Drop anything whose value is not in its quote, or whose quote is not in the text."""
    body = squash(text)
    out, bad = [], []
    for label, val, quote in facts:
        if squash(val) not in squash(quote):
            bad.append((label, "value not in its own quote"))
            continue
        if squash(quote)[:120] not in body:
            bad.append((label, "quote not in the document"))
            continue
        out.append((label, val, quote))
    return out, bad


# ── database ──────────────────────────────────────────────────────────────────
def rows():
    import psycopg2 as pg
    with pg.connect(DSN, connect_timeout=10) as cx, cx.cursor() as cur:
        cur.execute("select s.id, s.title, s.facts, d.language, d.text "
                    "from serving.signal_detail s "
                    "join extracted.document d on d.document_id = replace(s.id,'pl_','') "
                    "where s.origin='pipeline' order by s.id")
        return cur.fetchall()


def keep_row_facts(existing):
    """The row-level facts stay: Company, Category, Date, Primary lens, Publisher, Stance.
    They are properties of the row and are true regardless of what the article says."""
    return [list(f) for f in (existing or [])]


def report(verify=False):
    per_lang, hard, total = {}, [], 0
    for sid, title, facts, lang, text in rows():
        got, note = extract(text, lang)
        got, bad = grounded(got, text)
        st = per_lang.setdefault(lang, {"rows": 0, "with": 0, "facts": 0})
        st["rows"] += 1
        st["facts"] += len(got)
        if got:
            st["with"] += 1
        total += len(got)
        for label, why in bad:
            hard.append((sid, label, why))
        for label, val, _q in got:
            en = to_english(label, val, lang)
            if not same_digits(en, val):
                hard.append((sid, label, "English rendering %r changes a digit of %r"
                             % (en, val)))
        if not verify:
            print("\n%s  [%s]  %s" % (sid[-12:], lang, (title or "")[:66]))
            if note:
                print("    ! %s" % note)
            for label, val, quote in got:
                en = to_english(label, val, lang)
                print("    %-16s %-24s %s" % (
                    label, en[:24], "" if en == val else "(src: %s)" % val[:26]))
                print("        %s" % quote[:150])
            if not got:
                print("    (nothing this article states)")

    print("\n== coverage per language ==")
    print("%-6s %5s %6s %6s" % ("lang", "rows", "with", "facts"))
    silent = []
    for lang in sorted(per_lang):
        st = per_lang[lang]
        print("%-6s %5d %6d %6d" % (lang, st["rows"], st["with"], st["facts"]))
        if st["with"] == 0:
            silent.append(lang)
    print("total dynamic facts: %d" % total)
    if silent:
        # NOT script-gated. A Latin-script language that extracts nothing is exactly the
        # silent failure the audit found; naming it is the whole point.
        print("\nLANGUAGES EXTRACTING NOTHING: %s" % ", ".join(silent))
        print("  a per-language zero is a table to write, not a result")
    if hard:
        print("\nHARD FAILURES: %d" % len(hard))
        for sid, label, why in hard[:20]:
            print("  %s  %-16s %s" % (sid[-12:], label, why))
        return 1
    print("\nno ungrounded facts: every value appears in its quote, "
          "every quote appears in its document")
    return 0


def apply():
    import psycopg2 as pg
    n = 0
    with pg.connect(DSN, connect_timeout=10) as cx:
        for sid, title, facts, lang, text in rows():
            got, _ = extract(text, lang)
            got, _bad = grounded(got, text)
            if not got:
                continue
            base = keep_row_facts(facts)
            have = {str(f[0]).lower() for f in base}
            # dynamic facts lead: they are what makes this article different from the
            # last one. The row-level four follow, unchanged.
            # Ground on the SOURCE wording (grounded() already did), then publish the
            # English rendering. The quote stays in the source language on purpose: it
            # is the evidence, and the operator can see the original figure inside it.
            dyn = [[l, to_english(l, v, lang), q]
                   for l, v, q in got if l.lower() not in have]
            with cx.cursor() as cur:
                cur.execute("update serving.signal_detail set facts=%s::jsonb, "
                            "updated_at=now() where id=%s",
                            (json.dumps(dyn + base), sid))
            n += 1
        cx.commit()
    print("wrote dynamic facts onto %d rows" % n)


def demo():
    # sentence splitting must survive all four traps
    ss = sentences("The deal is worth $2.3 billion. Isporuke od 2026. do 2029. godine. "
                   "The U.S. Department of State approved it. Next one here.")
    assert any("2.3 billion" in s for s in ss), ss
    assert any("2026. do 2029" in s for s in ss), "Croatian year ordinals must not split"
    assert any("U.S. Department" in s for s in ss), "initialism must not split"

    # money needs a CURRENCY, not just a unit word: "34 juta tong" is barrels of oil
    got, _ = extract("Kapasiti 34 juta tong menjadikan kontrak ini penting.", "ms")
    assert not [g for g in got if g[0].startswith("Order")], got

    # Swedish order value, from the real article
    got, _ = extract("Ordervärdet är 460 miljoner kronor och leveranser är planerade "
                     "2026-2029.", "sv")
    d = dict((g[0], g[1]) for g in got)
    assert "Order value" in d and "460" in d["Order value"], got
    assert "Delivery" in d and d["Delivery"] == "2026-2029", got

    # ...and the option ceiling is NOT an order value
    got, _ = extract("Saab har tecknat kontrakt som omfattar optioner på ytterligare "
                     "beställningar till ett värde av upp till 640 miljoner kronor.", "sv")
    d = dict((g[0], g[1]) for g in got)
    assert "Order value" not in d, "an option ceiling must never be published as an order"
    assert "Option / ceiling" in d, got

    # the Norway row: anchored, verbatim, quoted - and still not an order
    got, _ = extract("The US Department of State approved Norway's potential $2.3 billion "
                     "purchase of 21 UH-60M helicopters.", "en")
    d = dict((g[0], g[1]) for g in got)
    assert "Order value" not in d, "'potential' must route the amount to the ceiling"
    assert d.get("Quantity", "").startswith("21"), got

    # designations and calibres are not quantities
    got, _ = extract("Rheinmetall demonstrated the FV-014 LM missiles at the test range.", "en")
    assert "Quantity" not in dict((g[0], g[1]) for g in got), got

    # grounding rejects a value that is not in its own quote
    ok, bad = grounded([("Order value", "999", "the order is worth 460")], "the order is worth 460")
    assert not ok and bad, (ok, bad)
    ok, bad = grounded([("Order value", "460", "the order is worth 460")], "the order is worth 460")
    assert ok and not bad

    # a language with no table returns nothing, and SAYS so
    got, note = extract("something", "zz")
    assert not got and "no table" in note
    # English rendering: words only, never the numbers, never a conversion
    assert to_english("Order value", "460 miljoner kronor", "sv") == "SEK 460 million"
    assert to_english("Option / ceiling", "640 milijuna SEK", "hr") == "SEK 640 million"
    assert to_english("Contract term", "tio år", "sv") == "ten years"
    assert to_english("Contract term", "deset godina", "hr") == "ten years"
    assert to_english("Quantity", "66 pesawat", "ms") == "66 aircraft"
    assert to_english("Order value", "$2.3 billion", "en") == "$2.3 billion"
    assert to_english("Delivery", "2026-2029", "sv") == "2026-2029"
    # an untranslatable word survives rather than being dropped
    assert "Carl-Gustaf" in to_english("Quantity", "12 Carl-Gustaf enheter", "sv")
    # and nothing may alter a digit
    assert same_digits("SEK 460 million", "460 miljoner kronor")
    assert not same_digits("SEK 44 million", "460 miljoner kronor")
    print("demo ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo()
    elif a.apply:
        apply()
    elif a.verify:
        sys.exit(report(verify=True))
    else:
        sys.exit(report())
