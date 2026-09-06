"""Re-publish archived matchups ONLY as far as the corpus can carry them.

    python revive_matchups.py --dry        # report, write nothing
    python revive_matchups.py --apply
    python revive_matchups.py --demo

The archive holds 507 matchups. Every one carries a spec table; almost none carry
a source for the numbers in it. Re-publishing them as-is would put unsourced
values on screen, which is the one thing this project has decided it will not do.

So each row is rebuilt rather than copied:

  * a SPEC entry survives only if its number appears in a document we hold,
    within PROXIMITY characters of a mention of the product it describes. That
    is deliberately a proximity rule and not a document-level one: "40" occurs in
    every artillery article ever written, and "the document mentions CAESAR and
    also contains 40" is not evidence that CAESAR's range is 40 km.
  * an ADVANTAGE bullet survives only if its own content words are stated.
  * `edge` and `verdict` are RECOMPUTED from what survived. Copying a verdict
    that was written about ten specs onto the two that could be grounded would
    be the worst outcome of the three.
  * `srcs` is written from the documents actually used, so every surviving number
    has a URL behind it.

A row whose pairing itself cannot be grounded is not written at all.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _superseded import refuse_if_superseded  # noqa: E402
refuse_if_superseded(__file__)   # this copy is superseded; see the module
import argparse
import collections
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from source_tiers import domain as st_domain, publishable  # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
PROXIMITY = 400        # chars between the product mention and its number
# enrich_serving.py ALREADY owns 9000+ for the matchups it derives from cards.
# Sharing that range made this script's delete-first wipe those 6 rows -- the same
# two-writers-one-id-space fault that hit serving.tender. Revived rows own 20000+,
# and each writer deletes only its own range.
MATCHUP_ID0 = 20000
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GENERIC = {
    "system", "systems", "vehicle", "vehicles", "gun", "guns", "howitzer", "howitzers",
    "tank", "tanks", "missile", "missiles", "rifle", "rifles", "drone", "drones", "uav",
    "uas", "artillery", "ammunition", "armoured", "armored", "protected", "protective",
    "mounted",
    "towed", "self", "propelled", "main", "battle", "light", "heavy", "series", "new",
    "the", "and", "for", "with", "class", "mark", "type", "group", "defence", "defense",
    "limited", "ltd", "inc", "gmbh", "systems", "aerospace", "industries", "technologies",
    # Product NAMES that are only a category noun. A page about any sniper rifle
    # matches a product called "Sniper", and an EV charging station's "weight |
    # approximately 80 kg" was sourcing a carbine's weight through the word
    # "protective". A name that names a class cannot identify a member of it.
    "sniper", "carbine", "pistol", "revolver", "mortar", "radar", "launcher",
    "truck", "trailer", "boat", "vessel", "helmet", "rocket", "bomb", "grenade",
}
STOPWORDS = {"leads", "on", "in", "this", "a", "an", "of", "to", "is", "are", "its",
             "and", "or", "with", "for", "by", "from", "at", "as", "that", "than",
             "more", "less", "higher", "lower", "established", "maker", "house"}


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def product_of(name):
    """"KNDS · CAESAR 6x6" -> "CAESAR 6x6".

    The maker is NOT the product. Grounding on "knds" let a Brazilian article about
    Elbit's ATMOS source CAESAR's calibre, and a brahmos.com gallery URL source the
    MArG's -- because those pages mention the company somewhere and contain "155"
    somewhere. Only the model name may identify the thing being measured."""
    parts = re.split(r"[·|]", name or "")
    return parts[-1].strip() if len(parts) > 1 else (name or "").strip()


def designators(name):
    """Tokens specific enough to identify a product.

    Hyphens are NOT split on: "RCH-155", "ALS-50" and "AK-203" are single model
    names, and splitting them produced "rch"/"als"/"ak" (too short) plus a bare
    number (not discriminating), so 191 rows lost both sides of the comparison.

    A token qualifies when it is a letters+digits model code ("rch-155", "6x6"),
    a word of 4+ letters, or a SHORT ALL-CAPS ACRONYM in the original casing
    ("MGS", "MPV", "PzH") -- acronyms are how this domain names things."""
    out = []
    for raw in re.split(r"[\s/,()·]+", (name or "").strip()):
        raw = raw.strip(".:;")
        t = norm(raw)
        if not t or t in GENERIC or len(t) < 2:
            continue
        if not any(ch.isalpha() for ch in t):
            continue                                   # bare "155" discriminates nothing
        has_digit = any(ch.isdigit() for ch in t)
        acronym = len(raw) >= 2 and raw.isupper() and raw.isalpha()
        mixed_caps = len(raw) >= 3 and raw[0].isupper() and any(c.isupper() for c in raw[1:])
        if has_digit or len(t) >= 4 or acronym or mixed_caps:
            out.append(t)
    return out


def numbers(value):
    """The numeric tokens a spec value asserts. '40+ (55 guided)' -> ['40','55']."""
    if value is None:
        return []
    return [n for n in re.findall(r"\d[\d,.]*", str(value).replace(",", "")) if n]


def load_docs(cur):
    """-> [(document_id, url, normalised_text)]. Normalised once; this is the hot loop.

    Reads the extracted store AND the staged corpus. Grounding a spec needs the
    document TEXT, not its propositions, so a freshly fetched page can source a
    claim before Layer A has run over it -- and Layer A takes hours. The document
    is one we hold and can cite either way; the extraction adds spans, not
    authority."""
    cur.execute("select document_id, url, text from extracted.document where text is not null")
    docs = [(d, u, norm(t)) for d, u, t in cur.fetchall()]
    have = {d for d, _u, _t in docs}
    staged = 0
    for p in (HERE / "corpus").glob("doc_*.json"):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if r.get("document_id") in have or not r.get("text"):
            continue
        docs.append((r["document_id"], r.get("url", ""), norm(r["text"])))
        staged += 1
    if staged:
        print("  (+%d staged doc(s) not yet through Layer A)" % staged)
    return docs


def one_per_domain(hits):
    """-> one representative URL per distinct publisher, in stable order."""
    out, seen = [], set()
    for h in hits:
        url = h[1]
        d = st_domain(url)
        if d and d not in seen:
            seen.add(d)
            out.append(url)
    return out


TABLE_PROXIMITY = 1400     # ...but a specification table is all one product
# Must equal EDGE_DEADBAND in frontend/src/lib/edge.js. Two definitions of "level"
# put a stored verdict and the gauge above it in direct contradiction.
PARITY_DEADBAND = 0.03


def _same_table(text, a, b):
    """Are these two offsets inside ONE uninterrupted flattened table?

    trafilatura renders an infobox as a run of pipe-delimited cells, and the
    product is named once at the top of it -- so the mass row of the ATAGS
    infobox sits 471 characters from the only mention of ATAGS and lost to a
    400-character rule, even though a spec table is the best evidence there is.
    Extending the reach unconditionally would let one infobox source the next
    one's numbers, so the run must be unbroken: a stretch of prose between the
    two (a gap with no cell separator) means they are different tables.
    """
    lo, hi = min(a, b), max(a, b)
    seg = text[lo:hi]
    if seg.count("|") < 4:
        return False
    return max((len(g) for g in seg.split("|")), default=0) <= 160


RIVALS = set()          # every distinctive product name in the catalogue
RIVAL_WINDOW = 200


def name_surfaces(name):
    """How a product name is written: "bharat 52" and "bharat-52"."""
    n = norm(name or "")
    if len(n) < 6 or " " not in n:
        return []
    return [n, n.replace(" ", "-")]


def index_rivals(tokens, names=()):
    """Remember the distinctive product names, so a number can be refused when a
    DIFFERENT product is the thing being described right next to it.

    A page listing India's loitering munitions mentions Trinetra somewhere and
    states Nagastra's range in the next paragraph; proximity to a mention is not
    the same as being about it. Only distinctive tokens take part -- rejecting on
    a word like "bharat" would refuse most of the corpus."""
    RIVALS.clear()
    RIVALS.update(t for t in tokens if len(t) >= 4 and DF.get(t, 1.0) <= COMMON)
    # Whole product names count too, whatever their tokens' frequency. "bharat" is
    # far too common to reject on -- but "bharat-52" is not, and a sentence reading
    # "could offer the 13-ton bharat-52" published that weight as the Dhanush's.
    for nm in names or ():
        RIVALS.update(name_surfaces(nm))
    return RIVALS


def _rival_beside(text, j, own, spans):
    """Is a DIFFERENT product named closer to this number than our own is?

    Rejecting on any rival within the window was too blunt -- a specification page
    names related systems constantly, and it cost a third of the sourced values.
    What actually disqualifies a number is another product standing between it and
    us: then the sentence is about them, not about us."""
    if not RIVALS or not spans:
        return False
    mine = min(abs(p - j) for p in spans)
    lo = max(0, j - RIVAL_WINDOW)
    w = text[lo: j + RIVAL_WINDOW]
    for t in RIVALS:
        if t in own:
            continue
        i = w.find(t)
        while i != -1:
            if _word_at(w, t, i) and abs((lo + i) - j) < mine:
                return True
            i = w.find(t, i + 1)
    return False


def _number_at(text, n, i):
    """Is this a whole number, or the middle of a bigger one?

    "41" was found inside "341 km" -- a road distance a gun was towed in Sikkim --
    and published as the Bharat 52's firing range across six comparisons. A digit
    or a decimal point on either side means this is not that number."""
    before = text[i - 1] if i else " "
    after = text[i + len(n)] if i + len(n) < len(text) else " "
    if before == "[" and after == "]":
        return False        # "[40][41]" is a footnote marker, not a measurement
    # A thousands separator does not end a number: "13" inside "13,000 kg" is not
    # thirteen of anything, and it grounded a 13-tonne gun against a 13,000 kg one.
    if after == "," and text[i + len(n) + 1: i + len(n) + 4].isdigit():
        return False
    return not (before.isdigit() or before in ".,") and not (after.isdigit() or after == ".")


def _near(text, j, spans):
    """Is this offset close to a mention -- or in the same specification table?"""
    return any(abs(j - p) <= PROXIMITY or
               (abs(j - p) <= TABLE_PROXIMITY and _same_table(text, j, p))
               for p in spans)


def _word_at(text, term, i):
    """Is the hit at i a whole word? "dron" inside "squadrons" is not a mention."""
    before = text[i - 1] if i else " "
    after = text[i + len(term)] if i + len(term) < len(text) else " "
    return not (before.isalnum() or after.isalnum())


# How ordinary a name token is in THIS corpus. "bharat" is in 9.5% of the documents
# (Bharat Forge, Bharat Electronics, the country); "caesar" is in 1.2%. That
# difference is the whole question of whether a token can identify a product by
# itself, and it is measurable rather than a matter of opinion.
DF = {}
COMMON = 0.04


def index_df(docs, tokens):
    """Fill DF for the tokens we are about to match on. Once, over the corpus."""
    n = float(len(docs)) or 1.0
    for tok in {t for t in tokens if t and tok_ok(t)}:
        if tok in DF:
            continue
        DF[tok] = sum(1 for _d, _u, t in docs if tok in t) / n
    return DF


def tok_ok(t):
    return len(t) >= 2


def _config(p):
    """A configuration suffix rather than a name: "6x6", "2000", "52"."""
    return p.isdigit() or re.fullmatch(r"\d+x\d+", p) is not None


def mention_spans(text, ds, name=None, maker=None):
    """Character positions where THE PRODUCT is mentioned.

    A product name must be matched WHOLE, not by its most common token. "Bharat 52"
    reduces to the designator "bharat", which appears in most of an Indian defence
    corpus (Bharat Forge, Bharat Electronics, Bharat Dynamics, the country itself),
    and anchoring on it let a Tejas fighter-jet article and a company home page
    "corroborate" the Bharat 52's rate of fire. So when the name has more than one
    part, every part must appear close together before this counts as a mention."""
    parts = [p for p in re.split(r"[\s/,()·-]+", norm(name or "")) if p] if name else []
    parts = [p for p in parts if p not in GENERIC and len(p) >= 2]
    if len(parts) >= 2:
        pos = []
        # Anchor on the RAREST part, and require the rest of the name only when that
        # anchor is too ordinary to identify the product alone. Demanding the whole
        # name unconditionally cost more than it saved: no article writes "CAESAR
        # 6x6", so the name matched ZERO documents and the product vanished from
        # Positioning entirely -- while "Bharat 52" still needs both halves, because
        # "bharat" on its own is most of an Indian defence corpus.
        # Scan on the longest NON-configuration part -- that is the model name. The
        # rarest part of "CAESAR 6x6" is "6x6", which appears in no document at all,
        # so anchoring on rarity looked for a token that is never written; the
        # longest part of "PzH 2000" is the number.
        core = [p for p in parts if not _config(p)] or parts
        anchor = max(core, key=len)
        others = [p for p in parts if p != anchor]
        # Drop the rest of the name only when the rest is a CONFIGURATION suffix that
        # sources routinely omit ("6x6", "2000", "52") AND the anchor is distinctive
        # enough to stand alone. Relaxing on rarity alone let a Shahed-136 article
        # source the K9 Thunder's range through the word "thunder".
        whole = not (all(_config(p) for p in others) and DF.get(anchor, 1.0) <= COMMON)
        i = text.find(anchor)
        while i != -1 and len(pos) < 200:
            if _word_at(text, anchor, i):
                window = text[max(0, i - 45): i + len(anchor) + 45]
                if not whole or all(p in window for p in parts):
                    pos.append(i)
            i = text.find(anchor, i + 1)
        return pos
    if not parts and maker:
        # The whole name is a category noun -- "Sniper", "CQB Carbine". It cannot
        # identify a product on its own (a page about any sniper rifle would match),
        # so 65 rows were dropped outright for having no designator. But the MAKER
        # beside the noun does identify it: "Kalyani ... sniper rifle" is about this
        # product, and that is how the trade press writes about it.
        nouns = [p for p in re.split(r"[\s/,()·-]+", norm(name)) if len(p) >= 3]
        mt = [t for t in designators(maker) if DF.get(t, 1.0) <= COMMON]
        pos = []
        for m in mt:
            i = text.find(m)
            while i != -1 and len(pos) < 200:
                if _word_at(text, m, i):
                    window = text[max(0, i - 70): i + len(m) + 70]
                    if any(n in window for n in nouns):
                        pos.append(i)
                i = text.find(m, i + 1)
        return sorted(pos)

    # Single-token name: match on the name's own surviving token, not on the raw
    # designator list. "Protective Carbine" filters down to one part because
    # "protective" is generic -- but the designator list still carried it, so a
    # page about protective helmets counted as a mention of the carbine.
    pos = []
    for d in (parts[:1] if parts else ds):
        i = text.find(d)
        while i != -1 and len(pos) < 200:
            if _word_at(text, d, i):
                pos.append(i)
            i = text.find(d, i + 1)
    return pos


# How a unit is actually written on a page. The archive stores "t"; a spec sheet
# writes "tonnes". Matching the stored form as a SUBSTRING was worse than useless:
# the unit "t" occurs inside "the", "at" and "system", so every 3+ digit value with
# a tonne unit was accepted next to any word at all.
UNIT_FORMS = {
    "t": ("t", "tonne", "tonnes", "ton", "tons"),
    "kg": ("kg", "kgs", "kilogram", "kilograms"),
    "km": ("km", "kilometre", "kilometres", "kilometer", "kilometers"),
    "m": ("m", "metre", "metres", "meter", "meters"),
    "mm": ("mm", "millimetre", "millimetres"),
    "hp": ("hp", "bhp", "horsepower"),
    "kw": ("kw", "kilowatt", "kilowatts"),
    "rds": ("rds", "rd", "rounds", "round", "rpm"),
    "km/h": ("km/h", "kmph", "kph"),
    "lb": ("lb", "lbs", "pound", "pounds"),
}


# Surfaces longest-first, so "km/h" is not read as "km" and "mm" is not read as "m".
_UNIT_SURFACES = None


def unit_at(text, end):
    """The unit ACTUALLY WRITTEN after this number in the source document.

    This is the only place the unit of a value can be established. The archive
    stores the K9 Thunder's weight as the bare string "47" and the ATAGS's as
    "18 t"; comparing those two numbers made a 47-tonne self-propelled gun the
    LIGHTER machine by a factor of 383. The source says "combat weight of over 47
    tonnes", and that sentence is what decides the unit."""
    global _UNIT_SURFACES
    if _UNIT_SURFACES is None:
        pairs = [(f, k) for k, fs in UNIT_FORMS.items() for f in fs]
        _UNIT_SURFACES = sorted(pairs, key=lambda p: -len(p[0]))
    tail = text[end: end + 20]
    for f, key in _UNIT_SURFACES:
        if re.match(r"[\s\-]{0,3}" + re.escape(f) + r"(?![a-z0-9])", tail):
            return key
    return ""


# What each unit is, and its size in the base unit of that quantity. Two figures can
# only be compared once they are the same quantity in the same unit.
BASE = {"kg": ("mass", 1.0), "t": ("mass", 1000.0), "lb": ("mass", 0.45359237),
        "m": ("length", 1.0), "km": ("length", 1000.0), "mm": ("length", 0.001),
        "hp": ("power", 1.0), "kw": ("power", 1.34102),
        "km/h": ("speed", 1.0), "rds": ("rate", 1.0)}


def to_base(n, unit):
    """-> (value_in_base_unit, quantity) or (None, None) if the unit is unknown."""
    q = BASE.get((unit or "").strip())
    if not q:
        return None, None
    try:
        return float(str(n).replace(",", "")) * q[1], q[0]
    except (TypeError, ValueError):
        return None, None


def _other_unit(text, end, unit):
    """Is a DIFFERENT unit written immediately after this number?

    "the marg 39 has a 22-tonne all-up weight, and it carries 18 rounds" sourced a
    weight of 18 tonnes, because "weight" sits within a few characters of the 18.
    A number that states its own unit is not available for another measurement."""
    u = norm(unit).strip()
    if not u:
        return False                    # no unit claimed: nothing to conflict with
    tail = text[end: end + 20]
    for key, forms in UNIT_FORMS.items():
        if key == u or u in forms:
            continue
        for f in forms:
            if re.match(r"[\s\-]{0,3}" + re.escape(f) + r"(?![a-z0-9])", tail):
                return True
    return False

# What the same measurement is CALLED elsewhere. An infobox writes "mass" where the
# archive's column says "Combat weight", and "effective firing range" where it says
# "Max range" -- so the label test rejected values that were sitting in a labelled
# specification table, which is the most reliable evidence there is.
LABEL_SYN = {
    "weight": ("mass", "gvw", "gvm", "laden", "kerb", "curb", "all-up"),
    "combat": ("gvm", "gvw"),
    "crew": ("detachment", "crewmen", "operators"),
    "pax": ("passengers", "seats", "seating", "occupants", "personnel", "capacity"),
    "range": ("firing range", "reach"),
    "power": ("engine", "output", "horsepower", "bhp"),
    "speed": ("velocity", "kmph", "km/h"),
    "rate": ("rpm", "rounds per minute"),
    "fire": ("rpm", "rounds per minute"),
    "endurance": ("flight time", "duration", "autonomy", "loiter"),
    "payload": ("carrying capacity", "useful load"),
    "ceiling": ("altitude",),
    "calibre": ("caliber",),
    "caliber": ("calibre",),
    "mobility": ("configuration", "drive"),
}


def label_words(label):
    """The label's own words plus the words a source is likely to use instead."""
    out = []
    for w in re.split(r"[^a-z0-9/]+", norm(label)):
        if len(w) > 2:
            out.append(w)
            out.extend(LABEL_SYN.get(w, ()))
    return out


def unit_follows(text, end, unit):
    """Is the unit written as a WHOLE WORD right after the number?"""
    u = norm(unit).strip()
    if not u:
        return False
    tail = text[end: end + 20]
    for f in UNIT_FORMS.get(u, (u,)):
        if re.match(r"[\s\-]{0,3}" + re.escape(f) + r"(?![a-z0-9])", tail):
            return True
    return False


def compound_forms(value):
    """The literal multi-number forms a compound value asserts: "6-8", "2+9".

    A claim of "3-4" crew is not evidenced by a table reading "3-5", and "2+9" is
    not evidenced by a bare 2 next to the word "personnel" -- but that is exactly
    what decomposing a compound value into its separate numbers allowed. So a
    compound is looked for as a compound."""
    v = norm(str(value or ""))
    out = []
    for m in re.findall(r"\d[\d.,]*\s*[-+/]\s*\d[\d.,]*", v):
        out.append(m)
        squeezed = re.sub(r"\s+", "", m)
        if squeezed != m:
            out.append(squeezed)
    return out


def stated_with_context(text, j, n, unit, label, strict=False, require_unit=False):
    """A bare number is not a measurement. Require the number to be followed by its
    UNIT, or to sit close to the words of its own spec label -- otherwise "40"
    anywhere in an artillery article "proves" a 40 km range."""
    lab = label_words(label)
    if _other_unit(text, j + len(n), unit):
        return False
    if unit_follows(text, j + len(n), unit):
        # "18 tonnes" is not a bare number even though 18 is short: the unit IS the
        # context, and refusing it was why every combat weight failed to ground.
        return True
    if require_unit or (unit and norm(unit)):
        # A value that CLAIMS a unit must be found with it. "5 rds/min" was sourced
        # to a page whose only 5 sat near the word "rate"; a source stating a rate
        # of fire writes the rounds.
        return False
    if strict:
        # A short number with no unit needs its label RIGHT THERE, not merely in the
        # paragraph -- "crew 3", never a bare 3.
        if not lab:
            return False
        near = text[max(0, j - 32): j + 32]
        return any(w in near for w in lab)
    if lab:
        near = text[max(0, j - 90): j + 90]
        if any(w in near for w in lab):
            return True
    return False


def value_forms(value, unit):
    """-> [(number_string, unit)] the source might plausibly have written.

    The archive normalises to one unit and the world does not: combat weight is
    stored "12000 kg" while every spec sheet says "12 t", so the literal 12000
    never appears and the most directional field in the dataset grounded zero
    times. Only exact, lossless conversions are offered -- 12500 kg becomes
    12.5 t, never a rounded 12."""
    out = []
    u = (unit or "").strip().lower()
    # The VALUE's own unit beats the column's. The column said "kg" while the value
    # read "10-25 t", so 25 was converted as if it were kilograms and the search
    # went looking for 25 kg of armoured vehicle.
    # km/h must be tried BEFORE km, or a towed speed of "80 km/h" is read as 80 km
    # and sourced to a firing range of 80 km on the same page.
    m = re.search(r"\d\s*(km/h|kmph|kph|kg|kilograms?|t|tonnes?|tons?|km|kilometres?|"
                  r"m|metres?|mm|hp|kw|rds?)\b", str(value or "").lower())
    if m:
        w = m.group(1)
        u = {"kilogram": "kg", "kilograms": "kg", "tonne": "t", "tonnes": "t",
             "ton": "t", "tons": "t", "kilometre": "km", "kilometres": "km",
             "metre": "m", "metres": "m", "rd": "rds"}.get(w, w)
    for n in numbers(value):
        out.append((n, u))
        if n.isdigit() and len(n) > 3:
            out.append(("{:,}".format(int(n)), u))   # the page writes "12,000"
        try:
            x = float(n)
        except ValueError:
            continue
        if u == "kg" and x >= 1000:
            t = x / 1000.0
            out.append((("%g" % t), "t"))
            out.append((("%g" % t), "tonne"))
        elif u in ("t", "tonne", "tonnes"):
            out.append((str(int(x * 1000)), "kg"))
        elif u == "m" and x >= 1000:
            out.append((("%g" % (x / 1000.0)), "km"))
        elif u == "km":
            out.append((str(int(x * 1000)), "m"))
    seen, ded = set(), []
    for n, uu in out:
        if (n, uu) not in seen:
            seen.add((n, uu))
            ded.append((n, uu))
    return ded


def ground_value(docs, ds, value, unit="", label="", max_domains=5, name=None,
                 maker=None):
    """-> [(document_id, url, offset)] for EVERY document that states this value near
    a mention of the PRODUCT, in a context that makes it that measurement.

    Returns all of them, not the first: whether a number may be shown depends on
    HOW MANY INDEPENDENT sources state it, so stopping at the first hit would
    throw away the evidence the decision is made on."""
    forms = value_forms(value, unit)
    hits, doms = [], set()
    if not ds or not forms:
        return hits
    # A compound claim ("6-8", "2+9", "3+8-10") is evidenced by the compound, or by
    # a component that carries its own unit -- never by one of its numbers sitting
    # near the label, which matched a different figure entirely.
    lits = compound_forms(value)
    compound = len(numbers(value)) >= 2
    own = set(ds) | {p for p in re.split(r"[\s/,()·-]+", norm(name or "")) if p}
    own.update(name_surfaces(name))
    for did, url, text in docs:
        spans = mention_spans(text, ds, name, maker)
        if not spans:
            continue
        found = False
        for lit in lits:
            j = text.find(lit)
            while j != -1 and not found:
                if (_number_at(text, lit, j) and _near(text, j, spans)
                        and not _rival_beside(text, j, own, spans)):
                    hits.append((did, url, j, lit, unit_at(text, j + len(lit))))
                    doms.add(st_domain(url))
                    found = True
                j = text.find(lit, j + 1)
            if found:
                break
        if found:
            if len(doms) >= max_domains:
                break
            continue
        for n, u in forms:
            # A one- or two-digit number matches almost any document, so it is only
            # accepted when its own LABEL is adjacent -- "crew 3", never a bare 3.
            strict = len(n) < 3
            j = text.find(n)
            while j != -1 and not found:
                if (_number_at(text, n, j) and _near(text, j, spans)
                        and not _rival_beside(text, j, own, spans)
                        and stated_with_context(text, j, n, u, label, strict,
                                                require_unit=compound)):
                    # The unit the SOURCE wrote, not the one the archive stored --
                    # that is what makes the two sides comparable.
                    hits.append((did, url, j, n, unit_at(text, j + len(n)) or u))
                    doms.add(st_domain(url))
                    found = True
                j = text.find(n, j + 1)
            if found:
                break
        if len(doms) >= max_domains:
            break
    return hits


def ground_phrase(docs, ds, phrase, name=None, maker=None):
    """An advantage bullet survives if its content words are stated near the product."""
    toks = [t for t in re.split(r"[^a-z0-9]+", norm(phrase))
            if t and t not in STOPWORDS and t not in GENERIC and len(t) > 3]
    if len(toks) < 2:
        return None
    for did, url, text in docs:
        spans = mention_spans(text, ds, name, maker)
        if not spans:
            continue
        hit = [t for t in toks if t in text]
        if len(hit) >= max(2, len(toks) // 2):
            return (did, url, 0)
    return None


def _side_base(hits, stored):
    """-> (value in the quantity's base unit, quantity) for one side of a comparison.

    Uses the number and unit the SOURCE wrote. A unitless figure (a crew count) has
    no quantity and keeps whatever the archive stored -- counts are already
    comparable with each other, and only with each other."""
    usable = []
    for h in hits:
        if len(h) < 5 or not h[4]:
            continue
        v, q = to_base(h[3], h[4])
        if v is not None:
            usable.append((v, q, str(h[3])))
    if usable:
        # Prefer the figure the archive itself chose, when a source actually states
        # it: "30-56 km" is stored as 56, and silently switching to the 30 that
        # happened to ground first would quietly restate the rival's reach.
        want = None if stored is None else str(stored).rstrip("0").rstrip(".")
        for v, q, n in usable:
            if want and n.rstrip("0").rstrip(".") == want:
                return v, q
        return usable[0][0], usable[0][1]
    return (stored, "count") if stored is not None else (None, None)


def _wins(s):
    """-> +1 if the CLIENT's figure is the stronger one, -1 for the rival, 0 tied.

    `hi` carries the direction and it is not always "bigger is better": weight,
    combat weight and crew are all hi=False, because a lighter gun served by fewer
    people is the better gun."""
    c, k = s.get("cn"), s.get("kn")
    if c is None or k is None or c == k:
        return 0
    # Below the front end's parity deadband, nobody leads. Treating exact equality as
    # the only tie put a stored verdict ("AWEIL leads on 1 of 1 comparable field")
    # directly above a gauge reading NEAR PARITY on the same dossier: 42 km against
    # 41 km is 2.4%, which is quoting noise, not an advantage. The two numbers on one
    # screen must not come from two different definitions of "level".
    mean = (abs(c) + abs(k)) / 2.0
    if not mean or abs(k - c) / mean < PARITY_DEADBAND:
        return 0
    k_better = (k > c) if s.get("hi") else (k < c)
    return 1 if k_better else -1


def rebuild(row, docs):
    """-> (new_row_fields, report) for one archived matchup."""
    (mid, cat, comp, compby, bf, bfby, specs, adv_c, adv_b,
     country, direction, catkey, anchor) = row
    cds, kds = designators(product_of(comp)), designators(product_of(bf))
    rep = {"id": mid, "comp": comp, "bf": bf,
           "specs_in": len(specs or []), "specs_kept": 0,
           "adv_in": len(adv_c or []) + len(adv_b or []), "adv_kept": 0, "srcs": []}
    # A name that is only a category noun ("Sniper") has no designator of its own,
    # but its MAKER beside the noun still identifies it -- so the row is only
    # abandoned when neither the name nor the maker can carry it.
    if (not cds and not compby) or (not kds and not bfby):
        rep["drop"] = "no designator on one side"
        return None, rep

    used = {}
    kept_specs = []
    rep["specs_weak"] = 0
    for s in (specs or []):
        u, lab = s.get("u") or "", s.get("l") or ""
        hc = ground_value(docs, cds, s.get("cv"), u, lab, name=product_of(comp),
                          maker=compby)
        hk = ground_value(docs, kds, s.get("kv"), u, lab, name=product_of(bf),
                          maker=bfby)
        # A side is SHOWN only if its sources clear the credibility bar: the
        # product's own maker or a government publisher, or two independent
        # domains. A single news mention is not enough to put a number about a
        # real weapon on screen.
        ok_c, why_c, tier_c, n_c = publishable([h[1] for h in hc], compby)
        ok_k, why_k, tier_k, n_k = publishable([h[1] for h in hk], bfby)
        if not ok_c and not ok_k:
            if hc or hk:
                rep["specs_weak"] += 1        # found, but not well enough sourced
            continue
        e = dict(s)
        # Values whose own side failed the bar are blanked rather than shown with
        # a weak citation -- a half-sourced comparison is a misleading one.
        if not ok_c:
            e["cv"], e["cn"] = None, None
        if not ok_k:
            e["kv"], e["kn"] = None, None
        # One URL per DOMAIN. The claim on screen is "N independent sources", so the
        # list under it must be the independent ones -- showing two pages of a single
        # outlet next to that sentence makes a true statement read as a false one.
        # Make the two figures comparable, or refuse to compare them. cn/kn come
        # straight out of the archive in whatever unit each side's source happened to
        # use -- "47" (tonnes) against "18000" (kilograms) -- and the front end
        # subtracts them as bare numbers, so five of the eleven Artillery
        # comparisons on screen were decided by the unit, not by the gun.
        cbase, cq = _side_base(hc, s.get("cn")) if ok_c else (None, None)
        kbase, kq = _side_base(hk, s.get("kn")) if ok_k else (None, None)
        if cbase is not None and kbase is not None and cq == kq:
            e["cn"], e["kn"] = cbase, kbase
        elif ok_c and ok_k and (cq or kq) and cq != kq:
            e["cn"] = e["kn"] = None      # one side's unit is unknown: not comparable
        e["srcC"] = one_per_domain(hc) if ok_c else []
        e["srcK"] = one_per_domain(hk) if ok_k else []
        e["whyC"], e["whyK"] = (why_c if ok_c else None), (why_k if ok_k else None)
        e["tierC"], e["tierK"] = (tier_c if ok_c else None), (tier_k if ok_k else None)
        for h in (hc if ok_c else []) + (hk if ok_k else []):
            used[h[1]] = h[0]
        kept_specs.append(e)
    rep["specs_kept"] = len(kept_specs)

    kc, kb = [], []
    for lst, ds, out, nm, mk in ((adv_c or [], cds, kc, product_of(comp), compby),
                                 (adv_b or [], kds, kb, product_of(bf), bfby)):
        for a in lst:
            g = ground_phrase(docs, ds, a, nm, mk)
            if g:
                out.append(a)
                used[g[1]] = g[0]
    rep["adv_kept"] = len(kc) + len(kb)

    # ARCHIVE THE INCOMPLETE. Positioning exists to compare specifications; a row
    # with no adequately-sourced specification is not a weaker comparison, it is
    # not a comparison. It stays in the archive rather than appearing as an empty
    # panel that reads as "no difference found".
    if not kept_specs:
        weak = rep.get("specs_weak", 0)
        rep["drop"] = ("%d value(s) found but too weakly sourced to show" % weak
                       if weak else "no specification could be sourced at all")
        return None, rep

    # edge and verdict are recomputed from what survived. Two different counts
    # matter and must not be conflated: how many values we SOURCED, and how many
    # are sourced on BOTH sides (only those can be compared at all).
    # Only a DIRECTIONAL field can decide a lead. 155 mm is not "better" than
    # 105 mm, it is a different class of gun -- and counting calibre as a win was
    # most of what the old edge measured. Direction matters too: hi=False on
    # combat weight, weight and crew means LOWER is the stronger figure, so
    # treating bigger as better had the heaviest vehicle winning.
    both = [s for s in kept_specs if s.get("cn") is not None
            and s.get("kn") is not None and s.get("hi") is not None]
    lead_c = sum(1 for s in both if _wins(s) < 0)
    lead_k = sum(1 for s in both if _wins(s) > 0)
    tied = len(both) - lead_c - lead_k
    # An edge of 0 would render as "the rival leads on nothing", which is not the
    # same statement as "there is nothing to compare". Only assert one when a
    # comparison actually separated the two.
    # The stored scale is the one every consumer documents: 0-100 where 50 is
    # parity and BELOW 50 means the CLIENT is behind. Storing the share the
    # COMPETITOR leads on inverted it -- a row where KSSL led every field was
    # stored as 0, which reads as "KSSL behind on everything".
    # One comparable field is not a verdict. Shrink towards parity by n/(n+1), the
    # same confidence factor the front end's own index documents: a single decided
    # field can move the number at most halfway to the rail, instead of printing
    # maximum severity on the thinnest possible evidence.
    # The share is over the DECIDED fields, not every comparable one. Dividing by
    # all of them let ties vote: one field led by the client and three matched came
    # out 25/100 -- the client behind, on a comparison it wins and never loses. A
    # field both machines match on separates nobody. The front end's index uses this
    # same formula, so the stored number and the drawn number are one number.
    dec = lead_c + lead_k
    if dec:
        raw = 100.0 * lead_k / dec
        edge = int(round(50 + (raw - 50) * dec / (dec + 1.0)))
    else:
        edge = None
    who_c, who_k = (compby or comp), (bfby or bf)
    if not both:
        verdict = ("<b>%d value(s) sourced, none comparable on both sides.</b> A gap needs "
                   "the same field published for both products, and the field has to have "
                   "a better and a worse direction -- 155 mm is not better than 105 mm. "
                   "So none is asserted here." % len(kept_specs))
    elif lead_c == 0 and lead_k == 0:
        verdict = ("<b>Level on every comparable field.</b> %d field(s) sourced for both "
                   "products; the values match." % len(both))
    else:
        # Name the leader first: "X leads on 0 of 1, Y on 1" makes the reader do the
        # arithmetic to find out who is ahead.
        (a, na), (b_, nb) = ((who_c, lead_c), (who_k, lead_k)) if lead_c >= lead_k             else ((who_k, lead_k), (who_c, lead_c))
        verdict = ("<b>%s leads on %d of %d comparable field(s)%s.</b> "
                   "Based only on values sourced for both products."
                   % (a, na, len(both),
                      ("; %s on %d" % (b_, nb)) if nb else
                      ("; %d level" % tied if tied else "")))
    srcs = [{"url": u, "label": u.split("//")[-1].split("/")[0]} for u in sorted(used)]
    rep["srcs"] = [s["url"] for s in srcs]
    # The reason states plainly what was and was not carried over, so a reader is
    # never left to assume the missing specs were "not applicable" rather than
    # "we could not source them".
    n_off = sum(1 for s in kept_specs if "official" in (s.get("tierC"), s.get("tierK")))
    reason = ("<b>%s</b> (%s) is compared with KSSL's <b>%s</b> in %s. "
              "%d of the %d specification(s) held for this pairing are shown; each one "
              "is either published by the manufacturer or a government source (%d here), "
              "or stated by at least two independent sources. The other %d are archived "
              "rather than displayed because no source good enough carries them. Every "
              "number below names the page it came from."
              % (product_of(comp), compby or "unknown maker", product_of(bf),
                 cat or "this category", len(kept_specs), len(specs or []), n_off,
                 len(specs or []) - len(kept_specs)))
    det = [["Competitor", compby or comp], ["HQ / origin", country or "not stated"],
           ["Category", cat or "-"], ["KSSL counterpart", product_of(bf)],
           ["Specs shown", "%d of %d held" % (len(kept_specs), len(specs or []))],
           ["Sources", "%d document(s)" % len(srcs)],
           ["Source rule", "manufacturer or government publisher, or two independent "
                           "sources; anything less is archived, not shown"]]
    return {"cat": cat, "anchor": anchor, "comp": comp, "compBy": compby, "bf": bf,
            "bfBy": bfby, "country": country, "dir": direction, "catKey": catkey,
            "specs": kept_specs, "advComp": kc, "advBf": kb, "edge": edge,
            "verdict": verdict, "srcs": srcs, "reason": reason, "det": det,
            "verdictH": "Positioning verdict — %s" % (cat or ""),
            "ks_thin": len(kept_specs) == 0}, rep


def main(apply=False, limit=None):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    docs = load_docs(cur)
    print("corpus: %d document(s)\n" % len(docs))

    cur.execute("""select matchup_id, cat, comp, "compBy", bf, "bfBy", specs,
                          "advComp", "advBf", country, dir, "catKey", anchor
                     from serving.matchup where origin='reference'
                     order by matchup_id""" + (" limit %d" % limit if limit else ""))
    rows = cur.fetchall()

    # Measure how ordinary each name token is BEFORE matching on it -- mention_spans
    # needs to know whether the anchor can identify a product on its own.
    toks = set()
    for r in rows:
        for nm in (r[2], r[4]):
            toks.update(designators(product_of(nm)))
            toks.update(p for p in re.split(r"[\s/,()·-]+", norm(product_of(nm))) if p)
    index_df(docs, toks)
    index_rivals(toks, [product_of(r[2]) for r in rows] + [product_of(r[4]) for r in rows])
    rare = sum(1 for t in toks if DF.get(t, 1.0) <= COMMON)
    print("  name tokens: %d, of which %d distinctive enough to anchor alone\n"
          % (len(toks), rare))

    built, reports = [], []
    for r in rows:
        new, rep = rebuild(r, docs)
        reports.append(rep)
        if new:
            built.append(new)
        if len(reports) % 50 == 0:
            print("  %d/%d examined, %d revivable" % (len(reports), len(rows), len(built)),
                  flush=True)

    spec_in = sum(r["specs_in"] for r in reports)
    spec_out = sum(r["specs_kept"] for r in reports)
    drops = collections.Counter(r.get("drop") for r in reports if r.get("drop"))
    print("\n%d archived matchup(s) examined" % len(rows))
    print("  revivable with evidence : %d" % len(built))
    print("  spec entries %d -> %d grounded (%.1f%%)"
          % (spec_in, spec_out, 100.0 * spec_out / max(spec_in, 1)))
    print("  advantage bullets kept  : %d of %d"
          % (sum(r["adv_kept"] for r in reports), sum(r["adv_in"] for r in reports)))
    for why, n in drops.most_common():
        print("  dropped: %-42s %d" % (why, n))

    top = sorted([r for r in reports if r["specs_kept"]],
                 key=lambda r: -r["specs_kept"])[:10]
    if top:
        print("\nbest-evidenced rows:")
        for r in top:
            print("  %-34s vs %-28s %d spec(s), %d source(s)"
                  % (str(r["comp"])[:34], str(r["bf"])[:28], r["specs_kept"], len(r["srcs"])))

    io.open(HERE / "revive_matchups_report.json", "w", encoding="utf-8").write(
        json.dumps(reports, ensure_ascii=False, indent=1))

    if apply and built:
        cur.execute("delete from serving.matchup where origin='pipeline' and matchup_id >= %s",
                    (MATCHUP_ID0,))
        gone = cur.rowcount
        for i, b in enumerate(built):
            cur.execute("""insert into serving.matchup
                (matchup_id, cat, anchor, comp, "compBy", bf, "bfBy", country, dir,
                 "catKey", specs, "advComp", "advBf", edge, verdict, srcs, reason, det,
                 "verdictH", ks_thin, origin)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        'pipeline')""",
                (MATCHUP_ID0 + i, b["cat"], b["anchor"], b["comp"], b["compBy"], b["bf"],
                 b["bfBy"], b["country"], b["dir"], b["catKey"], json.dumps(b["specs"]),
                 json.dumps(b["advComp"]), json.dumps(b["advBf"]), b["edge"], b["verdict"],
                 json.dumps(b["srcs"]), b["reason"], json.dumps(b["det"]),
                 b["verdictH"], b["ks_thin"]))
        con.commit()
        print("\napplied: %d row(s) replaced %d previous revived row(s)" % (len(built), gone))
    elif apply:
        print("\nnothing to apply")
    else:
        print("\n(dry run -- nothing written)")
    con.close()
    return built, reports


def _demo():
    assert designators("KNDS · CAESAR 6x6") == ["knds", "caesar", "6x6"], \
        designators("KNDS · CAESAR 6x6")
    assert "howitzer" not in designators("155mm towed howitzer")
    assert numbers("40+ (55 guided)") == ["40", "55"]
    assert numbers("155/52") == ["155", "52"] and numbers(None) == []
    assert numbers("13,000 kg") == ["13000"]
    # a designator must discriminate: "155" is the least distinctive token a
    # howitzer name carries, and anchoring on it sourced the MArG's calibre to a
    # Rheinmetall ammunition contract.
    assert designators("MArG 155") == ["marg"]
    assert "6x6" in designators("CAESAR 6x6")
    # short model codes must survive -- these lost BOTH sides before
    assert designators("RCH-155") == ["rch-155"], designators("RCH-155")
    assert "als-50" in designators("ALS-50")
    assert "mgs" in designators("MGS") and "mpv" in designators("MPV")
    assert "pzh" in designators("PzH 2000")
    assert designators("the towed howitzer") == []
    docs = [("d1", "http://x/1", norm(
        "The CAESAR 6x6 has a calibre of 155 mm and a range of 40 km."))]
    g = ground_value(docs, ["caesar"], "155", "mm", "Calibre")
    assert g and g[0][0] == "d1", g
    # the same number with NO unit and no label nearby is not that measurement
    bare = [("d3", "http://x/3", norm("The CAESAR is French. It cost 155 crore in 2019."))]
    assert ground_value(bare, ["caesar"], "155", "mm", "Calibre") == []
    # a number far from any mention of the product is NOT evidence about it
    far = [("d2", "http://x/2", norm("CAESAR is French. " + ("filler word " * 120) + " 999 mm"))]
    assert ground_value(far, ["caesar"], "999", "mm", "Calibre") == []
    # ...and a product the document never names grounds nothing
    assert ground_value(docs, ["archer"], "155", "mm", "Calibre") == []

    # the displayed sources must be one per publisher
    hh = [("a", "https://idrw.org/1", 0), ("b", "https://idrw.org/2", 0),
          ("c", "https://euro-sd.com/3", 0)]
    assert one_per_domain(hh) == ["https://idrw.org/1", "https://euro-sd.com/3"]

    # A multi-part product name must match WHOLE. "Bharat 52" must not be found by
    # "bharat" alone, or every Bharat Forge / Bharat Electronics article sources it.
    bh = [("d9", "http://x/9", norm("Bharat Electronics won a radar order worth 3 crore."))]
    assert mention_spans(bh[0][2], ["bharat"], "Bharat 52") == []
    good = [("da", "http://x/a", norm("The Bharat 52 howitzer has a 155 mm calibre."))]
    assert mention_spans(good[0][2], ["bharat"], "Bharat 52"), "whole name should match"
    # and a token inside a longer word is not a mention
    assert mention_spans(norm("the fighter squadrons flew"), ["dron"], None) == []

    # unit variants: the archive normalises, the world does not
    assert ("12", "t") in value_forms("12000 kg", "kg"), value_forms("12000 kg", "kg")
    assert ("12500", "kg") in value_forms("12.5 t", "t")
    assert ("12.5", "t") in value_forms("12500 kg", "kg")   # lossless only
    assert ("40", "km") in value_forms("40000 m", "m")
    # the VALUE's unit wins over the column's: "10-25 t" is tonnes even in a kg column
    f = value_forms("10-25 t (variant)", "kg")
    assert ("10", "t") in f and ("10000", "kg") in f, f
    assert ("25000", "kg") in f
    # a short number needs its LABEL adjacent, not merely in the paragraph
    tx = norm("The vehicle carries a crew of 3 and was shown in 2024 at the show.")
    assert stated_with_context(tx, tx.find("3"), "3", "", "Crew", strict=True)
    far = norm("Crew training " + ("filler " * 30) + " 3 units were seen")
    assert not stated_with_context(far, far.rfind("3"), "3", "", "Crew", strict=True)

    # ...but a short number with its UNIT written out is not a bare number. Every
    # combat weight in the dataset failed to ground because "18 tonnes" was read as
    # a naked 18, and the label column said "Weight" where the page said "mass".
    ix = norm("| mass | previously, 18 tonnes (18 long tons; 20 short tons).[3]")
    assert stated_with_context(ix, ix.find("18"), "18", "t", "Weight", strict=True)
    rx = norm("effective firing range | 45 km[75]")
    assert stated_with_context(rx, rx.find("45"), "45", "km", "Max range", strict=True)
    cx = norm("| crew | 6-8 |")
    assert stated_with_context(cx, cx.find("6"), "6", "", "Crew / pax", strict=True)
    # the unit must be a WHOLE WORD after the number. "t" as a substring matches
    # "the", which accepted a tonnage next to any word in the language.
    hx = norm("the system carries 12.5 the rest of the day")
    assert not unit_follows(hx, hx.find("12.5") + 4, "t")
    assert unit_follows(norm("weighs 13 t."), 9, "t")
    assert not stated_with_context(norm("some 45 thing"), 5, "45", "", "Max range",
                                   strict=True)
    assert "mass" in label_words("Combat weight") and "crew" in label_words("Crew / pax")
    # a spec table is one product: the name at the top of an infobox reaches the mass
    # row 500 characters below it, but NOT across the prose into the next infobox
    tbl = norm("| atags | | manufacturer | kssl | | produced | 2019 | | mass | 18 tonnes |")
    assert _same_table(tbl, tbl.find("atags"), tbl.find("18"))
    two = norm("| atags | | mass | 18 t | " + ("prose sentence goes here. " * 12)
               + " | mgs | | mass | 30 t |")
    assert not _same_table(two, two.find("atags"), two.rfind("30"))

    # A rare anchor identifies the product without the rest of its name; a common one
    # does not. No source writes "CAESAR 6x6", so the whole-name rule matched zero
    # documents for it -- while "bharat" still cannot stand alone.
    one = norm("The CAESAR howitzer fires a 155 mm shell.")
    cz = [("dz", "http://x/z", one)] + [("d%d" % i, "http://x/%d" % i,
                                         norm("bharat forge news item")) for i in range(60)]
    DF.clear()
    assert mention_spans(one, ["caesar"], "CAESAR 6x6") == []           # no DF yet
    index_df(cz, ["caesar", "6x6", "bharat", "52"])
    assert DF["caesar"] <= COMMON < DF["bharat"], (DF["caesar"], DF["bharat"])
    assert mention_spans(one, ["caesar"], "CAESAR 6x6"), "rare anchor stands alone"
    bz = norm("Bharat Electronics won a radar order worth 3 crore.")
    DF["bharat"] = 0.30                                     # common in this corpus
    assert mention_spans(bz, ["bharat"], "Bharat 52") == []
    # ...and the rest of a name is only droppable when it is a CONFIGURATION suffix.
    # "Thunder" is rare, but it is half of a name, not a suffix -- relaxing on
    # rarity alone let a Shahed-136 article source the K9 Thunder's range.
    DF["thunder"] = 0.001
    assert mention_spans(norm("a thunder of guns was heard"), ["thunder"],
                         "K9 Thunder") == []
    assert mention_spans(norm("the k9 thunder fires 155 mm"), ["thunder"], "K9 Thunder")
    assert _config("6x6") and _config("2000") and not _config("k9")
    DF.clear()
    # a generic product name cannot identify a product
    assert designators("Protective Carbine") == [] and designators("Sniper") == []
    # ...but the MAKER beside that noun does identify it
    DF["kalyani"] = 0.01
    kz = norm("Kalyani Strategic Systems showed its sniper rifle weighing 6.2 kg.")
    assert mention_spans(kz, [], "Sniper", "Kalyani Strategic Systems")
    assert mention_spans(kz, [], "Sniper", "Nexter") == []       # wrong maker
    assert mention_spans(norm("a sniper rifle was shown"), [], "Sniper",
                         "Kalyani Strategic Systems") == []      # maker absent
    DF.clear()
    # a number that states a DIFFERENT unit is not available for this measurement
    mg = norm("the marg 39 has a 22-tonne all-up weight, and it carries 18 rounds")
    assert not stated_with_context(mg, mg.find("18"), "18", "t", "Weight", strict=True)
    assert _other_unit(norm("40 lb payload"), 2, "km")
    assert not _other_unit(norm("40 km range"), 2, "km")
    # THE UNIT COMES FROM THE SOURCE. The archive stores the K9's weight as a bare
    # "47" and the ATAGS's as "18 t"; compared as bare numbers the 47-tonne gun is
    # the lighter one by a factor of 383, and that decided five of the eleven
    # comparisons the Gap Analysis page showed.
    kt = norm("the k9 thunder has a combat weight of over 47 tonnes")
    assert unit_at(kt, kt.find("47") + 2) == "t"
    sp = norm("top speed 85 km/h over 40 km")
    assert unit_at(sp, sp.find("85") + 2) == "km/h", "km/h must not read as km"
    assert unit_at(norm("barrel 8060 mm long"), 12) == "mm", "mm must not read as m"
    assert to_base(47, "t") == (47000.0, "mass")
    assert to_base(18000, "kg") == (18000.0, "mass")
    assert to_base(5, "") == (None, None)
    # a 47-tonne gun is HEAVIER than an 18-tonne one, whatever unit each was stored in
    c, cq = _side_base([("d", "u", 0, "47", "t")], 47)
    k, kq = _side_base([("d", "u", 0, "18", "t")], 18000)
    assert c > k and cq == kq == "mass", (c, k)
    # the archive's own choice within a range wins when a source states it
    rng = [("d", "u", 0, "30", "km"), ("d2", "u2", 0, "56", "km")]
    assert _side_base(rng, 56) == (56000.0, "length"), _side_base(rng, 56)
    assert _side_base(rng, None) == (30000.0, "length")   # nothing stored: first hit
    # crew counts have no unit and stay as counts
    assert _side_base([("d", "u", 0, "5", "")], 5) == (5, "count")
    # nothing grounded, nothing stored: nothing to compare
    assert _side_base([], None) == (None, None)

    # a compound claim must be found as a compound
    assert compound_forms("6-8") == ["6-8"]
    assert "2+9" in compound_forms("2+9") and compound_forms("47") == []
    cw = [("dc", "http://x/c", norm("| atags | | crew | 6-8 | | caliber | 155 mm |"))]
    assert ground_value(cw, ["atags"], "6-8", "", "Crew")
    # ...and "3-4" is NOT evidenced by a table reading "3-5"
    c5 = [("dd", "http://x/d", norm("| atags | | crew | 3-5 | | caliber | 155 mm |"))]
    assert ground_value(c5, ["atags"], "3-4", "", "Crew") == []
    # a value that claims a unit must be found WITH that unit, not merely near its
    # label: "5 rds/min" was sourced to the only 5 on a page, next to the word rate
    rf = [("de", "http://x/e", norm("the m777 rate of fire is compared; a crew of 5 men"))]
    assert ground_value(rf, ["m777"], "5 rds/min", "", "Rate of fire") == []

    # direction: a LIGHTER gun and a SMALLER crew are the stronger figures
    assert _wins({"cn": 18, "kn": 12, "hi": False}) == 1      # client lighter -> client
    assert _wins({"cn": 12, "kn": 18, "hi": False}) == -1
    assert _wins({"cn": 30, "kn": 42, "hi": True}) == 1       # client longer range
    assert _wins({"cn": 155, "kn": 155, "hi": None}) == 0
    # ...and a difference under the parity deadband is not a lead: 42 km vs 41 km is
    # 2.4%, which the gauge already calls level. Two definitions of "level" on one
    # screen is how a verdict came to contradict the number printed beneath it.
    assert _wins({"cn": 42000, "kn": 41000, "hi": True}) == 0
    assert _wins({"cn": 40000, "kn": 41000, "hi": True}) == 0
    assert _wins({"cn": 30000, "kn": 41000, "hi": True}) == 1     # 31% is a real lead

    # a number is not the middle of a bigger number: "41" inside "341 km" was
    # published as the Bharat 52's firing range in six comparisons at once
    sk = [("df", "http://x/f", norm("the bharat 52 gun covered a distance of 341 km "
                                    "in ten days over steep gradients"))]
    assert ground_value(sk, ["bharat"], "41 km", "km", "Max range", name="Bharat 52") == []
    ok41 = [("dg", "http://x/g", norm("the bharat 52 has a maximum range of 41 km"))]
    assert ground_value(ok41, ["bharat"], "41 km", "km", "Max range", name="Bharat 52")
    assert not _number_at(norm("341 km"), "41", 1)
    assert _number_at(norm("41 km"), "41", 0)
    assert not _number_at(norm("problem.[40][41] during the trial"), "41", 13)
    assert not _number_at(norm("a total weight of 13,000 kg"), "13", 18), "grouped number"
    assert _number_at(norm("13,000 kg"), "13,000", 0), "...but the whole one matches"
    # a number sitting beside a DIFFERENT product is not this product's number
    # a whole name is a rival even when its tokens are ordinary words
    assert name_surfaces("Bharat 52") == ["bharat 52", "bharat-52"]
    assert name_surfaces("ATAGS") == []
    DF["bharat"] = 0.30
    index_rivals(["dhanush"], ["Bharat 52"])
    dz = norm("dhanush is compared; india could offer the 13-ton bharat-52 as well")
    assert _rival_beside(dz, dz.find("13"), {"dhanush"}, [dz.find("dhanush")])
    DF.clear()
    RIVALS.clear()
    RIVALS.update(["nagastra", "trinetra"])
    nz = norm("indian loitering munitions include trinetra. the nagastra-1 range is 15 km.")
    sp_t = [nz.find("trinetra")]
    assert _rival_beside(nz, nz.find("15"), {"trinetra"}, sp_t)
    assert not _rival_beside(nz, nz.find("15"), {"trinetra", "nagastra"}, sp_t)
    # ...but a rival merely mentioned FURTHER away does not disqualify our number
    fz = norm("the atags fires to 48 km. the marg is a different system entirely.")
    assert not _rival_beside(fz, fz.find("48"), {"atags"}, [fz.find("atags")])
    RIVALS.clear()
    assert not _number_at(norm("4.2 t"), "2", 2)          # after a decimal point
    # ...and the page's own grouping is still recognised: "12,000" states 12000
    assert ("12,000", "kg") in value_forms("12000 kg", "kg")

    # EVERY source that states the value is returned, not just the first -- the
    # publish decision counts independent domains, so one hit is not enough data.
    two = [("d1", "https://armyrecognition.com/a", norm("CAESAR calibre 155 mm.")),
           ("d2", "https://euro-sd.com/b", norm("The CAESAR has a 155 mm calibre.")),
           ("d3", "https://armyrecognition.com/c", norm("CAESAR, calibre 155 mm."))]
    hits = ground_value(two, ["caesar"], "155", "mm", "Calibre")
    assert len(hits) == 3, hits
    ok, why, _t, n = publishable([h[1] for h in hits], "KNDS")
    assert ok and n == 2, (ok, n)          # 3 pages, 2 independent domains
    # one maker's own page is enough for its OWN product...
    ok2, _w, t2, _n = publishable(["https://knds.com/caesar"], "KNDS")
    assert ok2 and t2 == "official"
    # ...but a lone news mention is not
    assert not publishable(["https://idrw.org/x"], "KNDS")[0]
    print("ok")


if __name__ == "__main__":

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply, a.limit)
