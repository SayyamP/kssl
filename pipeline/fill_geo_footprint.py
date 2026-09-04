"""Fill the geographic footprint from the extraction layer, one entailed sentence at a time.

    python fill_geo_footprint.py --dry            # propose, print, write nothing
    python fill_geo_footprint.py --dry --sample 30
    python fill_geo_footprint.py --apply          # write the proposed rows
    python fill_geo_footprint.py --apply --allow-new-countries
    python fill_geo_footprint.py --demo

WHAT IS MISSING
---------------
`serving.competitors.global_locations` has no writer at all (0 of 42 rows), `hq` is
filled on 11 of 42, and the client's own map footprint is three countries, two of which
are analytical estimates. The client asked for the extracted data to be used to fill it.

THE RULE, STATED ONCE
---------------------
A country mentioned in an article about a company is NOT a footprint. This project
already believed 59% wrong facts once because grounding checked that evidence EXISTED
rather than that it ENTAILED the claim. So a row is written only when ONE sentence, with
the company as its agent, states a PRESENCE relation to the country:

    facility    a plant / factory / production line / shipyard / subsidiary / office
                the company has, operates, opened, built or is based at, IN the country
    production  the company produces / manufactures / assembles IN the country
    delivery    the company delivered / supplied / exported / was contracted TO the
                country, its armed forces or its ministry
    hq          the company is headquartered / has its registered office IN the country

and every row carries the URL and the verbatim sentence, so a reader can check it in one
click. A sentence that co-mentions the two -- an award ceremony in Germany, a trade show
in Paris, an MoU with a Kyrgyz firm, an election in the United States -- is refused with
a named reason, and the refusal counts are printed: a gate that refuses nothing is not
working.

HOW A DOCUMENT IS TIED TO A COMPANY
-----------------------------------
There is no stored document->company link. `serving.company_source` and
`serving.source_registry` are OUTPUTS of enrich_serving.step_sources, produced by
word-boundary matching the company name against titles and proposition subjects
(`company_mentions`). The same join is used here, on the proposition SUBJECT: the
extraction layer already names the agent of every statement, so a statement about
"Rheinmetall" resolves to the rival by its surfaces (name + the alias table the other
writers share), and a person ("Mr. Baba Kalyani") or a product ("Kalyani M4") is not the
company however much it contains the name. On a company's OWN site (source_tiers
MAKER_DOMAINS), a first-person sentence ("we operate 10 facilities across ...") is the
company speaking; that is the one place a pronoun is allowed to resolve.

Sources are graded with the ONE shared bar (engine source_tiers.publishable): the
company's own site or a government publisher stands alone; news needs two independent
domains saying it.

MAP VOCABULARY
--------------
The map plots only the country spellings it has coordinates for -- it refuses rather than
invents a position -- so every country is normalised to the 52 spellings already served,
and a presence in a country the map cannot draw is HELD and listed, never written without
--allow-new-countries.

Ord range: this writer owns geo_presence rows at ord >= 4000 (enrich_serving 1000+,
revive_geo 2000+, discover_geo 3000+) and deletes only its own range.
"""
import argparse
import collections
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
GEO_ORD0 = 4000
CLIENT_ID = "kalyani-strategic-systems"
CLIENT_NAME = "Kalyani Strategic Systems"
MAX_SENT = 600            # a "sentence" longer than this is a page, not a statement
MAX_COUNTRIES = 8         # more than this in one sentence is an index or an export table
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _load_engine_source_tiers():
    """The tier-graded source bar lives in the ENGINE's source_tiers.py; the module next
    to this file with the same name exports tier_of/LABEL. Load the engine copy by path,
    from wherever this file is run: the repo (pipeline/ -> extraction/engine) or the
    container (/app/signals -> /app/engine)."""
    for cand in (HERE.parent / "engine" / "source_tiers.py",
                 HERE.parent / "extraction" / "engine" / "source_tiers.py"):
        if cand.exists():
            spec = importlib.util.spec_from_file_location("engine_source_tiers", str(cand))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError("engine source_tiers.py not found beside %s" % HERE)


_st = _load_engine_source_tiers()
publishable, st_domain, maker_of, tier_of_url = (_st.publishable, _st.domain,
                                                 _st.maker_of, _st.tier)
MAKER_DOMAINS = dict(_st.MAKER_DOMAINS)

try:
    from revive_partners import ALIAS, ALIAS_JV            # noqa: E402
except Exception:                                           # noqa: BLE001
    ALIAS, ALIAS_JV = {}, {}


# ----------------------------------------------------------------------- countries

# The 52 spellings serving.geo_presence holds today, i.e. what the map can draw.
SERVED = [
    "Afghanistan", "Africa", "Argentina", "Armenia", "Australia", "Austria",
    "Bangladesh", "Belgium", "Brazil", "Canada", "China", "Czech Republic", "Denmark",
    "Egypt", "Estonia", "Europe", "Finland", "France", "Germany", "Greece", "Hungary",
    "India", "Indonesia", "Israel", "Italy", "Japan", "Kazakhstan", "Kuwait", "Malaysia",
    "Netherlands", "New Zealand", "Norway", "Pakistan", "Philippines", "Poland", "Qatar",
    "Romania", "Russia", "Saudi Arabia", "Singapore", "South Africa", "South Korea",
    "Spain", "Sri Lanka", "Sweden", "Taiwan", "Thailand", "UAE", "UK", "Ukraine", "USA",
    "Vietnam",
]
REGIONS = {"Europe", "Africa"}
# Recognised so a refusal is counted correctly, but HELD unless --allow-new-countries:
# the map has no coordinates for them and would refuse to plot the row.
NEW_COUNTRIES = [
    "Turkey", "Switzerland", "Mexico", "Chile", "Colombia", "Peru", "Morocco", "Kenya",
    "Nigeria", "Lithuania", "Latvia", "Slovakia", "Portugal", "Ireland", "Serbia",
    "Croatia", "Bulgaria", "Slovenia", "Azerbaijan", "Oman", "Jordan", "Iraq", "Iran",
    "Nepal", "Myanmar", "Brunei", "Ecuador", "Kyrgyzstan", "Luxembourg", "Bahrain",
    "Algeria", "Uganda", "Ethiopia", "Uzbekistan", "Mongolia", "Cyprus", "Iceland",
]
# surface -> canonical. Case-insensitive except the short codes marked in CASED.
SURFACE = {}
CASED = {"US", "UK", "UAE", "ROK", "USA"}


def _add(canon, *surfaces):
    SURFACE[canon.lower()] = canon
    for s in surfaces:
        SURFACE[s if s in CASED else s.lower()] = canon


for _c in SERVED + NEW_COUNTRIES:
    _add(_c)
_add("USA", "united states", "united states of america", "u.s.", "u.s.a.", "US")
_add("UK", "united kingdom", "great britain", "britain", "u.k.")
_add("UAE", "united arab emirates")
_add("South Korea", "republic of korea", "korea", "ROK")
_add("Czech Republic", "czechia")
_add("Netherlands", "the netherlands", "holland")
_add("Russia", "russian federation")
_add("Vietnam", "viet nam")
_add("Turkey", "turkiye")
# türkiye written with its umlaut
_add("Turkey", "türkiye")

_forms = sorted(SURFACE, key=len, reverse=True)
_ci = [re.escape(f) for f in _forms if f not in CASED]
_cs = [re.escape(f) for f in _forms if f in CASED]
# "korea" must not match inside "North Korea"; "africa" not inside "South Africa" (handled
# by longest-first alternation) nor "african" (word boundary).
COUNTRY_RX = re.compile(
    r"(?<![\w-])(?:(?<!north )(?<!North )(?:" + "|".join(_ci) + r"))(?![\w-])", re.I)
COUNTRY_CASED_RX = re.compile(r"(?<![\w.-])(?:" + "|".join(_cs) + r")(?![\w-])")

DEMONYM = {
    "indian": "India", "american": "USA", "british": "UK", "german": "Germany",
    "french": "France", "swedish": "Sweden", "norwegian": "Norway", "finnish": "Finland",
    "danish": "Denmark", "dutch": "Netherlands", "belgian": "Belgium", "polish": "Poland",
    "ukrainian": "Ukraine", "russian": "Russia", "italian": "Italy", "spanish": "Spain",
    "greek": "Greece", "hellenic": "Greece", "hungarian": "Hungary", "romanian": "Romania",
    "czech": "Czech Republic", "estonian": "Estonia", "austrian": "Austria",
    "israeli": "Israel", "saudi": "Saudi Arabia", "emirati": "UAE", "qatari": "Qatar",
    "kuwaiti": "Kuwait", "egyptian": "Egypt", "south african": "South Africa",
    "australian": "Australia", "japanese": "Japan", "south korean": "South Korea",
    "korean": "South Korea", "taiwanese": "Taiwan", "thai": "Thailand",
    "malaysian": "Malaysia", "singaporean": "Singapore", "indonesian": "Indonesia",
    "philippine": "Philippines", "filipino": "Philippines", "vietnamese": "Vietnam",
    "pakistani": "Pakistan", "bangladeshi": "Bangladesh", "sri lankan": "Sri Lanka",
    "afghan": "Afghanistan", "kazakh": "Kazakhstan", "canadian": "Canada",
    "brazilian": "Brazil", "argentine": "Argentina", "argentinian": "Argentina",
    "chinese": "China", "swiss": "Switzerland", "turkish": "Turkey", "mexican": "Mexico",
    "u.s.": "USA", "us": "USA", "uk": "UK",
}
_dem = sorted(DEMONYM, key=len, reverse=True)
# A demonym counts only when it qualifies an armed force / ministry (a delivery target)
# or a facility noun ("Swiss subsidiary", "British factories"). "German company" and
# "US-based AM General" are the nationality of ANOTHER organisation and match neither.
FORCE_WORD = (r"(?:army|navy|air force|armed forces|defence forces|defense forces|"
              r"self-defense forces|ministry of defen[cs]e|defen[cs]e ministry|"
              r"department of defen[cs]e|mod\b|military|marine corps|marines|"
              r"coast guard|government|special forces|border guard|police|"
              r"land forces|naval forces|air forces)")
DEMONYM_FORCE_RX = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(d) for d in _dem) + r")\s+(?:royal\s+)?"
    + FORCE_WORD, re.I)
NAMED_FORCE = {
    "bundeswehr": "Germany", "royal navy": "UK", "royal air force": "UK",
    "british army": "UK", "u.s. army": "USA", "us army": "USA", "u.s. navy": "USA",
    "us navy": "USA", "u.s. air force": "USA", "us air force": "USA",
    "u.s. marine corps": "USA", "us marine corps": "USA", "usmc": "USA",
    "pentagon": "USA", "department of defense": "USA", "hellenic army": "Greece",
    "hellenic navy": "Greece", "idf": "Israel", "fmv": "Sweden", "dga": "France",
    "baainbw": "Germany", "japan self-defense forces": "Japan", "adf": "Australia",
    "indian mod": "India", "ministry of defence of india": "India",
}
NAMED_FORCE_RX = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(k) for k in sorted(NAMED_FORCE, key=len,
                                                              reverse=True))
    + r")(?![\w-])", re.I)
COUNTRY_POSSESSIVE_FORCE_RX = re.compile(
    r"(?<![\w-])([A-Z][A-Za-z .]{2,24}?)(?:'s|’s)\s+(?:royal\s+)?" + FORCE_WORD, re.I)

# ----------------------------------------------------------------------- relations

FACILITY_LP = (r"plants?|factory|factories|production (?:sites?|lines?|facilit(?:y|ies)|"
               r"units?|bases?|hubs?|plants?|centres?|centers?)|manufacturing (?:sites?|"
               r"facilit(?:y|ies)|units?|hubs?|bases?|plants?|centres?|centers?|"
               r"operations?)|assembly (?:lines?|plants?|facilit(?:y|ies)|sites?)|"
               r"shipyards?|foundr(?:y|ies)|forge|forging (?:plants?|facilit(?:y|ies))|"
               r"works|munitions? (?:plants?|facilit(?:y|ies))|"
               r"(?:aluminium|aluminum|steel|casting|forging|machining) operations")
FACILITY_SV = (r"mro (?:facilit(?:y|ies)|centres?|centers?|hubs?)|maintenance (?:"
               r"facilit(?:y|ies)|centres?|centers?|hubs?|depots?)|service (?:centres?|"
               r"centers?|hubs?)|support (?:centres?|centers?|hubs?)|repair (?:facilit(?:y|"
               r"ies)|centres?|centers?)|depots?|training (?:centres?|centers?|academy)")
FACILITY_PT = r"joint venture|\bjv\b"
FACILITY_OF = (r"subsidiar(?:y|ies)|offices?|branch(?: office)?|headquarters|"
               r"head office|registered office|r&d (?:centres?|centers?|facilit(?:y|ies))|"
               r"engineering (?:centres?|centers?)|design (?:centres?|centers?)|"
               r"technology (?:centres?|centers?)|innovation (?:centres?|centers?)|"
               r"campus|premises|sites?|facilit(?:y|ies)|presence|footprint|"
               r"operations?|entity|affiliate|unit")
FACILITY_RX = re.compile(r"(?<![\w-])(?:(?P<lp>" + FACILITY_LP + r")|(?P<sv>" + FACILITY_SV
                         + r")|(?P<pt>" + FACILITY_PT + r")|(?P<of>" + FACILITY_OF
                         + r"))(?![\w-])", re.I)
# "Swiss subsidiary", "British factories": a demonym qualifying a facility noun
DEMONYM_FACILITY_RX = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(d) for d in _dem) + r")\s+(?:" + FACILITY_LP + "|"
    + FACILITY_SV + "|" + FACILITY_PT + "|" + FACILITY_OF + r")(?![\w-])", re.I)
PRESENCE_VERB_RX = re.compile(
    r"\b(?:has|have|had|having|operat(?:es|e|ed|ing)|runs?|running|owns?|owned|"
    r"open(?:s|ed|ing)?|inaugurat(?:es|ed|ion)|establish(?:es|ed|ing|ment)|set(?:s|ting)? up|"
    r"found(?:ed|ing)|commission(?:ed|s|ing)|buil(?:t|ds|ding)|construct(?:ed|s|ing|ion)|"
    r"commenced construction|broke ground|ground-?breaking|acquir(?:ed|es|ing)|"
    r"expand(?:ed|s|ing)|expansion|maintain(?:s|ed)|employ(?:s|ed|ing)|based|"
    r"headquartered|located|houses?|housed|manufactur(?:es|ed|ing)|produc(?:es|ed|ing)|"
    r"assembl(?:es|ed|ing)|makes|completed|cater(?:s|ed|ing)?|serv(?:es|ed|ing)|"
    r"invest(?:s|ed|ing)?|added|adds|spread|across|through)\b", re.I)
PROD_RX = re.compile(
    r"\b(?:produc(?:e|es|ed|ing|tion)|manufactur(?:e|es|ed|ing)|assembl(?:e|es|ed|ing|y)|"
    r"buil(?:d|ds|t|ding)|ma(?:de|kes|king)|fabricat(?:e|es|ed|ing)|forg(?:e|es|ed|ing))\b",
    re.I)
EXPORT_RX = re.compile(
    r"\b(?:deliver(?:s|ed|y|ies|ing)?|suppl(?:y|ies|ied|ying)|export(?:s|ed|ing)?|"
    r"shipp?(?:ed|ing)|handed over|hands over|sold|sale|sales|order(?:s|ed)?|"
    r"contract(?:s|ed)?|awarded|selected|inducted|induction|procured|purchased|bought|"
    r"customers?|in service with|operated by|fielded|dispatch(?:es|ed)|"
    r"provid(?:es|ed|ing)|agreement to supply)\b", re.I)
HQ_RX = re.compile(r"\b(?:headquarter(?:s|ed)|head office|registered office|"
                   r"principal office|corporate office|based)\b", re.I)
# The country must be the OBJECT of a place preposition (facility / production / hq)
# or a direction preposition (delivery). Between the preposition and the country only
# list glue ("five countries: India, United States,"), a city or a compass word may
# stand -- "in Zalaegerszeg, western Hungary" is in Hungary; "to all major networks
# across the world including US" is not a delivery to the US.
PLACE_PREP = r"(?:in|at|across|throughout|within|near|outside|into)"
DIR_PREP = r"(?:to|for|into|from|with|by)"
GLUE_TOKEN = (r"(?:the|and|or|both|also|its|our|their|five|four|six|three|two|seven|eight|"
              r"nine|ten|\d+|countries|country|markets?|regions?|nations?|such|as|key|"
              r"principal|including|namely|like|of|western|eastern|northern|southern|"
              r"central|north|south|east|west|new|state|province|region|city|"
              r"[A-Z][\w'’.-]*|,|:|;|–|-)")
GLUE_RX = re.compile(r"^(?:\s*" + GLUE_TOKEN + r")*\s*$")

# Refusals.
NEG_RX = re.compile(r"\b(?:not|no|never|cancel(?:led|ed|s)?|withdr(?:ew|awn|aws)|denied|"
                    r"rejected|refus(?:ed|es)|halted|suspended|closed|closing|shut down|"
                    r"divest(?:ed|s|ing|ment)?|ceased|scrapped|sever(?:ed|s))\b", re.I)
INTENT_RX = re.compile(
    r"\b(?:plans?|planning|aims?|aiming|intends?|intention|propos(?:es|ed|al)|"
    r"letter of intent|loi|mou|memorandum of understanding|in talks|explor(?:e|es|ing)|"
    r"consider(?:s|ing)|could|may|might|would|expected|expects?|is set to|set to|"
    r"potential|offer(?:s|ed)?|bid|bidding|tender|pitch(?:ed|es)?|seeks?|seeking|hopes?|"
    r"looking to|eyes|eyeing|mulls?|envisag(?:es|ed)|target(?:s|ing)|planned|upcoming|"
    r"future|would-be|prospective|study|feasibility|proposal|will (?:be )?(?:build|"
    r"establish|set up|construct|open|produce|manufacture|invest))\b", re.I)
CONTRACT_RX = re.compile(r"\b(?:awarded|contract(?:s|ed)?|order(?:ed|s)?|signed a|purchas|"
                         r"agreement to supply|inducted|delivered|handed over)\b", re.I)
MOU_RX = re.compile(r"\b(?:mou|loi|memorandum|letter of intent)\b", re.I)
EVENT_RX = re.compile(
    r"\b(?:exhibition|expo|exposition|trade fair|trade show|tradeshow|air ?show|"
    r"defen[cs]e show|pavilion|booth|stand|showcas\w*|display(?:ed|s|ing)?|unveil\w*|"
    r"debut\w*|eurosatory|dsei|idex|defexpo|aero india|mspo|ausa|farnborough|"
    r"paris air show|le bourget|dubai airshow|lima|indo ?defence|sitdef|fidae|adex|"
    r"land forces|avalon|euronaval|milipol|idef|sofex|isdef|hannover messe|bidec|edex|"
    r"shot show|sedec|saha expo|summit|forum|conference|ceremony|awards?|honou?r\w*|"
    r"conferred|medal|visit(?:ed|s|ing)?|delegation|meeting|met with|talks|dateline|"
    r"seminar|webinar|symposium|festival|carnival|gala|dinner)\b", re.I)
BIO_RX = re.compile(r"\b(?:university|degree|alumni|alumnus|born|graduat\w*|ambassador|"
                    r"prime minister|president of|minister|parliament|election\w*|"
                    r"embassy|consul\w*|his excellency|chairman of the|order of merit)\b",
                    re.I)
# A country name immediately owning or qualifying an organisation is that
# organisation's nationality, not this company's location.
NOT_LOCATIVE_AFTER_RX = re.compile(
    r"^(?:'s|’s|-based|-headquartered|-owned|based|headquartered)\b", re.I)
ORG_WORD_AFTER_RX = re.compile(
    r"^\s+(?:compan(?:y|ies)|firm|group|manufacturer|giant|contractor|supplier|"
    r"shipbuilder|conglomerate|start-?up|partner|arms|defen[cs]e (?:company|firm|"
    r"contractor|major|giant))\b", re.I)
# case-sensitive on purpose: "US" the country is not "us" the pronoun
FIRST_PERSON_RX = re.compile(r"\b(?:[Ww]e|[Oo]ur|us|[Tt]he [Cc]ompany|[Tt]he [Gg]roup|"
                             r"[Tt]he [Cc]ompany's)\b")
PERSON_SUBJECT_RX = re.compile(r"^(?:mr|ms|mrs|dr|shri|smt|prof|lt|col|gen|maj|capt)\b\.?",
                               re.I)
NOT_COMPANY_SUBJECT_RX = re.compile(
    r"\b(?:vehicle|tank|howitzer|gun|missile|drone|uav|school|foundation|hospital|"
    r"award|m4|maverick|light tank|atags|bharat 52|rifle|aircraft|radar|ship|frigate|"
    r"engine|platform|programme|program)\b|\d", re.I)

KIND_LABEL = {"lp": "Manufacturing / production", "sv": "Service / MRO",
              "pt": "Joint venture", "ex": "Delivery / contract",
              "of": "Subsidiary / office", "hq": "Headquarters"}
# What the map's activity codes can honestly carry. A subsidiary or an office is a
# corporate presence the map has no code for (its fallback text reads "Service/MRO"),
# so those reach the Profile's global_locations and, for the client, its own 'bf' band.
MAP_CODE = {"lp": "lp", "sv": "sv", "pt": "pt", "ex": "ex"}
# What counts as a LOCATION for the Profile field (a delivery target is a market).
LOCATION_KINDS = {"lp", "sv", "pt", "of", "hq"}


class Verdict:
    __slots__ = ("country", "kind", "ok", "reason", "city")

    def __init__(self, country, kind, ok, reason, city=None):
        self.country, self.kind, self.ok, self.reason, self.city = (
            country, kind, ok, reason, city)

    def __repr__(self):
        return "Verdict(%s, %s, %s, %r)" % (self.country, self.kind, self.ok, self.reason)


def no_control_chars():
    """A regex written through a shell heredoc has had its \\b collapse into a literal
    0x08 byte repeatedly in this codebase; it compiles and never matches."""
    src = Path(__file__).read_text(encoding="utf-8")
    bad = [(i, hex(ord(c))) for i, line in enumerate(src.splitlines(), 1) for c in line
           if ord(c) < 32 and c != "\t"]
    assert not bad, "control characters in source: %s" % bad[:5]


def find_countries(sentence):
    """-> [(start, end, canon, form)] non-overlapping, in order. form:
       name    the country written out ("India", "the United States")
       force   its armed force / ministry ("Indian Army", "Bundeswehr", "Poland's MoD")
       facadj  a demonym qualifying a facility noun ("Swiss subsidiary")"""
    taken = []
    out = []

    def free(a, b):
        return all(b <= s or a >= e for s, e, _c, _f in taken)

    for m in NAMED_FORCE_RX.finditer(sentence):
        if free(m.start(), m.end()):
            hit = (m.start(), m.end(), NAMED_FORCE[m.group(1).lower()], "force")
            taken.append(hit)
    for m in DEMONYM_FORCE_RX.finditer(sentence):
        if free(m.start(), m.end()):
            taken.append((m.start(), m.end(), DEMONYM[m.group(1).lower()], "force"))
    for m in COUNTRY_POSSESSIVE_FORCE_RX.finditer(sentence):
        canon = SURFACE.get(m.group(1).strip().lower()) or SURFACE.get(m.group(1).strip())
        if canon and free(m.start(), m.end()):
            taken.append((m.start(), m.end(), canon, "force"))
    for m in DEMONYM_FACILITY_RX.finditer(sentence):
        if free(m.start(), m.end()):
            taken.append((m.start(), m.end(), DEMONYM[m.group(1).lower()], "facadj"))
    for rx in (COUNTRY_RX, COUNTRY_CASED_RX):
        for m in rx.finditer(sentence):
            key = m.group(0)
            canon = SURFACE.get(key) if key in CASED else SURFACE.get(key.lower())
            if canon and free(m.start(), m.end()):
                taken.append((m.start(), m.end(), canon, "name"))
    out = sorted(taken)
    return out


def _mask_countries(sentence, mentions):
    s = list(sentence)
    for a, b, _c, _f in mentions:
        s[a:b] = ["X"] * (b - a)      # keep offsets, hide the names from the glue check
    return "".join(s)


def _prep_before(masked, pos, preps):
    """The nearest preposition of the given class before pos with only glue between."""
    rx = re.compile(r"\b" + preps + r"\b", re.I)
    best = None
    for m in rx.finditer(masked[:pos]):
        gap = masked[m.end():pos].replace("X", "Xx")
        if GLUE_RX.match(gap):
            best = m
    return best


def locative(sentence, masked, a, b):
    """-> (place_ok, dir_ok, why_not) for a country NAME at [a,b)."""
    after = sentence[b:b + 24]
    if NOT_LOCATIVE_AFTER_RX.match(after) or ORG_WORD_AFTER_RX.match(after):
        return False, False, "nationality of another organisation"
    place = _prep_before(masked, a, PLACE_PREP) is not None
    direc = _prep_before(masked, a, DIR_PREP) is not None
    if not (place or direc):
        return False, False, "country is not the object of a place or delivery preposition"
    return place, direc, ""


def _owner_before(sentence, pos, agent_rx, other_rx, agent_positions):
    """Does the facility noun at pos belong to THIS company? Own name / its / our
    before it, and not another known organisation's possessive nearer."""
    back = sentence[max(0, pos - 110):pos]
    if other_rx is not None:
        om = None
        for m in other_rx.finditer(back):
            om = m
        if om is not None and re.match(r"(?:'s|’s)\b", back[om.end():om.end() + 2]):
            am = None
            for m in agent_rx.finditer(back):
                am = m
            if am is None or am.start() < om.start():
                return False
    if re.search(r"\b(?:its|our|the company's|the group's|their)\b", back, re.I):
        return True
    if agent_rx.search(back):
        return True
    return any(p < pos for p in agent_positions)


def gate(sentence, agent_rx, own_site=False, other_rx=None, polarity=None):
    """-> [Verdict] one per country mention in this sentence.

    `agent_rx` matches this company's surfaces; `own_site` allows first-person on the
    company's own pages; `other_rx` matches every OTHER known organisation so a rival's
    plant is not filed under this company."""
    s = " ".join((sentence or "").split())
    if not s or len(s) > MAX_SENT:
        return [Verdict(None, None, False, "not a sentence (empty or page-length)")]
    mentions = find_countries(s)
    if not mentions:
        return []
    if len({c for _a, _b, c, _f in mentions}) > MAX_COUNTRIES:
        return [Verdict(c, None, False, "list of countries, not a statement")
                for _a, _b, c, _f in mentions]
    agent_pos = [m.start() for m in agent_rx.finditer(s)]
    if not agent_pos:
        if own_site and FIRST_PERSON_RX.search(s):
            agent_pos = [m.start() for m in FIRST_PERSON_RX.finditer(s)]
        else:
            return [Verdict(c, None, False, "company is not the agent of this sentence")
                    for _a, _b, c, _f in mentions]
    if polarity == "negative" or NEG_RX.search(s):
        return [Verdict(c, None, False, "negated or withdrawn") for _a, _b, c, _f in mentions]
    if BIO_RX.search(s):
        return [Verdict(c, None, False, "biographical, diplomatic or ceremonial context")
                for _a, _b, c, _f in mentions]
    intent = INTENT_RX.search(s)
    if intent and (MOU_RX.search(s) or not CONTRACT_RX.search(s)):
        return [Verdict(c, None, False, "intent or future plan, not a presence (%s)"
                        % intent.group(0).lower()) for _a, _b, c, _f in mentions]
    masked = _mask_countries(s, mentions)
    out = []
    for a, b, canon, form in mentions:
        win = s[max(0, a - 90):b + 90]
        ev = EVENT_RX.search(win)
        if ev:
            out.append(Verdict(canon, None, False, "exhibition, event or venue context (%s)"
                               % ev.group(0).lower()))
            continue
        before = s[max(0, a - 110):a]
        if form == "force":
            if EXPORT_RX.search(s):
                out.append(Verdict(canon, "ex", True, "delivery/contract to the country's forces"))
            else:
                out.append(Verdict(canon, None, False,
                                   "armed force named without a delivery or contract relation"))
            continue
        if form == "facadj":
            fm = FACILITY_RX.search(s[a:b])
            kind = fm.lastgroup if fm else "of"
            if _owner_before(s, a, agent_rx, other_rx, agent_pos) or FIRST_PERSON_RX.search(before):
                out.append(Verdict(canon, kind, True, "facility of the company in the country"))
            else:
                out.append(Verdict(canon, None, False, "facility belongs to another organisation"))
            continue
        place, direc, why = locative(s, masked, a, b)
        if why:
            out.append(Verdict(canon, None, False, why))
            continue
        # headquarters -- of the company itself, not of a subsidiary or a unit
        if (place and HQ_RX.search(before[-70:])
                and not re.search(r"subsidiar|division|\bunit\b|branch|affiliate|arm\b",
                                  before, re.I)):
            pm = _prep_before(masked, a, PLACE_PREP)
            city = s[pm.end():a].strip(" ,:;") if pm else ""
            city = city if re.fullmatch(r"[A-Z][\w'’.-]*(?:[ ,]+[A-Z][\w'’.-]*){0,3},?",
                                        city) else ""
            out.append(Verdict(canon, "hq", True, "headquarters stated in the country",
                               (city + ", " + canon) if city else canon))
            continue
        # a facility noun the company owns, sited in the country
        if place:
            # the nearest facility noun before the country: within 110 characters, or
            # further back when only list glue separates them ("10 manufacturing
            # facilities spread across five countries: India, United States, ...")
            fm = fpos = None
            lo = max(0, a - 220)
            for m in FACILITY_RX.finditer(s[lo:a]):
                abs_pos = lo + m.start()
                gap = re.sub(r"\b(?:spread|located|sited|situated|across|in|at|throughout)\b",
                             "", masked[abs_pos + len(m.group(0)):a])
                if a - abs_pos <= 110 or GLUE_RX.match(gap):
                    fm, fpos = m, abs_pos
            if fm is not None:
                if (_owner_before(s, fpos, agent_rx, other_rx, agent_pos)
                        and (PRESENCE_VERB_RX.search(s) or re.search(r"(?:'s|’s)\s", before))):
                    kind = fm.lastgroup
                    out.append(Verdict(canon, kind, True,
                                       "%s of the company in the country" % fm.group(0).lower()))
                    continue
                out.append(Verdict(canon, None, False, "facility belongs to another organisation"))
                continue
            pv = None
            for m in PROD_RX.finditer(before):
                pv = m
            if pv is not None and (agent_pos[0] < a - (len(before) - pv.start())
                                   or re.search(r"\bby\b", s[b:b + 40], re.I)
                                   and agent_rx.search(s[b:b + 80])):
                out.append(Verdict(canon, "lp", True, "produces in the country"))
                continue
        if direc:
            xm = None
            for m in EXPORT_RX.finditer(before):
                xm = m
            if xm is not None and agent_pos[0] <= a:
                pm = _prep_before(masked, a, DIR_PREP)
                if pm and pm.group(0).lower() in ("from", "by") and not re.search(
                        r"\b(?:order|contract|awarded|selected|procured|purchased|bought)\w*\b",
                        before, re.I):
                    out.append(Verdict(canon, None, False,
                                       "country is the source, not the destination"))
                    continue
                out.append(Verdict(canon, "ex", True, "delivery/contract into the country"))
                continue
        out.append(Verdict(canon, None, False,
                           "no presence relation stated (co-occurrence only)"))
    return out


# ----------------------------------------------------------------------- companies

SHORT = {
    "elbit-systems": ["Elbit"], "hanwha-aerospace": ["Hanwha", "Hanwha Defense", "Hanwha Defence"],
    "lockheed-martin": ["Lockheed"], "israel-aerospace-industries": ["IAI"],
    "rafael-advanced-defense-systems": ["Rafael", "Rafael Advanced Defence Systems"],
    "bae-systems": ["BAE"], "general-dynamics": ["GDLS", "General Dynamics Land Systems"],
    "tata-advanced-systems": ["TASL"], "bharat-dynamics": ["BDL"],
    "brahmos-aerospace": ["BrahMos"], "adani": ["Adani Defence & Aerospace",
                                                "Adani Defence and Aerospace", "Adani Defense"],
    "mahindra": ["Mahindra Defence Systems", "Mahindra Defense"],
    "aweil": ["Advanced Weapons and Equipment India"],
    "munitions-india": ["Munitions India Limited"], "oshkosh-defense": ["Oshkosh"],
    "rtx": ["Raytheon", "RTX Corporation", "Raytheon Technologies"],
    "knds": ["KNDS Deutschland", "KNDS France", "Krauss-Maffei Wegmann", "KMW", "Nexter"],
    "idv": ["Iveco Defence Vehicles", "Iveco Defense Vehicles"],
    "rheinmetall": ["American Rheinmetall", "Rheinmetall AG"],
    "kongsberg": ["Kongsberg Defence & Aerospace", "Kongsberg Defence and Aerospace"],
    "paramount-group": ["Paramount"], "kalashnikov": ["Kalashnikov Concern"],
    "norinco": ["China North Industries"], "uvision-air": ["UVision"],
    "sss-defence": ["SSS Defense"], "anduril": ["Anduril Industries"],
    "iveco": ["Iveco Defence Vehicles"], "otokar": ["Otokar Otomotiv"],
    CLIENT_ID: ["Kalyani Strategic Systems", "Kalyani Strategic Systems Limited",
                "Kalyani Strategic Systems Ltd", "KSSL", "Kalyani Group", "Bharat Forge",
                "Bharat Forge Limited", "Bharat Forge Ltd", "Kalyani Rafael Advanced Systems",
                "Kalyani Technologies", "Kalyani Mobility"],
}
# Own web domains beyond the engine's MAKER_DOMAINS, by company id.
OWN_DOMAINS = {CLIENT_ID: ["bharatforge.com", "kalyanistrategic.com", "kalyanigroup.com"]}


def surfaces_of(cid, name):
    out = [name] + list(SHORT.get(cid, ())) + list(ALIAS.get(cid, ())) + list(ALIAS_JV.get(cid, ()))
    return sorted({s.strip() for s in out if s and len(s.strip()) >= 3}, key=len, reverse=True)


def rx_of(surfaces):
    parts = []
    for s in surfaces:
        parts.append(re.escape(s) if (len(s) <= 5 and s.isupper()) else "(?i:%s)" % re.escape(s))
    return re.compile(r"(?<![\w-])(?:" + "|".join(parts) + r")(?![\w-])")


def own_domains(cid, name, site):
    doms = set(OWN_DOMAINS.get(cid, ()))
    if site:
        doms.add(st_domain(site))
    for d, who in MAKER_DOMAINS.items():
        if _st._same_org(who, name):
            doms.add(d)
    return {d for d in doms if d}


def is_company_subject(subject):
    s = (subject or "").strip()
    if not s or PERSON_SUBJECT_RX.match(s) or NOT_COMPANY_SUBJECT_RX.search(s):
        return False
    return True


# ----------------------------------------------------------------------- corpus

def load_companies(cur):
    cur.execute("""SELECT comp_id, ord, name, dir, hq, site FROM serving.competitors
                    WHERE origin='pipeline' ORDER BY ord""")
    comps = [{"cid": r[0], "ord": r[1], "name": r[2], "dir": r[3], "hq": r[4],
              "site": r[5]} for r in cur.fetchall()]
    # the client is not a competitor and is never in the pipeline roster; it goes first
    comps.insert(0, {"cid": CLIENT_ID, "ord": 0, "name": CLIENT_NAME, "dir": "client",
                     "hq": None, "site": "https://www.bharatforge.com/"})
    return comps


def split_sentences(text):
    for raw in re.split(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])|[\n\r]+|\s{3,}", text or ""):
        s = " ".join(raw.split())
        if 20 <= len(s) <= MAX_SENT:
            yield s


def props_for(cur, every_rx):
    """Propositions whose SUBJECT names one of the companies (the extraction layer's own
    agent field), with the evidence sentence.

    Two steps on purpose: the distinct subjects are matched in Python and the rows are
    then fetched by equality. A regex scan of a million subjects in Postgres took ten
    minutes on the production box; this takes seconds."""
    cur.execute("SELECT DISTINCT subject FROM extracted.proposition")
    subjects = [r[0] for r in cur.fetchall() if r[0] and every_rx.search(r[0])]
    if not subjects:
        return []
    cur.execute("""SELECT p.document_id, d.url, p.subject, p.predicate, p.object,
                          p.place_txt, p.polarity, p.modality, p.ev_quote
                     FROM extracted.proposition p
                     JOIN extracted.document d ON d.document_id = p.document_id
                    WHERE p.subject = ANY(%s)""", (subjects,))
    return cur.fetchall()


def docs_on(cur, domains):
    if not domains:
        return []
    pat = "(" + "|".join(re.escape(d) for d in sorted(domains)) + ")"
    cur.execute(r"""SELECT DISTINCT ON (url) document_id, url, text FROM extracted.document
                     WHERE url ~* %s AND text IS NOT NULL ORDER BY url, document_id""",
                (r"^https?://(?:[a-z0-9-]+\.)*" + pat + r"(?:/|$)",))
    return cur.fetchall()


def mine(cur, comps, verbose=True):
    """-> (accepted, refused_counter, held_new) where accepted is
    {cid: {(country, kind): [(url, quote, city, how)]}}"""
    surf = {c["cid"]: surfaces_of(c["cid"], c["name"]) for c in comps}
    rxs = {cid: rx_of(s) for cid, s in surf.items()}
    all_surf = {s for ss in surf.values() for s in ss}
    # every OTHER company's surfaces, so a rival's plant is not this company's
    other_rx = {cid: rx_of([s for o, ss in surf.items() if o != cid for s in ss])
                for cid in surf}
    own_doms = {c["cid"]: own_domains(c["cid"], c["name"], c["site"]) for c in comps}
    accepted = {c["cid"]: {} for c in comps}
    refused = collections.Counter()
    seen = set()
    n_cand = 0

    def consider(cid, url, quote, own_site, polarity=None, how="stated"):
        nonlocal n_cand
        key = (cid, url, quote[:200])
        if key in seen:
            return
        seen.add(key)
        for v in gate(quote, rxs[cid], own_site=own_site, other_rx=other_rx[cid],
                      polarity=polarity):
            n_cand += 1
            if not v.ok:
                refused[v.reason.split(" (")[0]] += 1
                continue
            if v.country in NEW_COUNTRIES:
                refused["held: country spelling not in the map vocabulary"] += 1
                accepted[cid].setdefault(("__new__", v.country), []).append((url, quote, v.city, how))
                continue
            accepted[cid].setdefault((v.country, v.kind), []).append((url, quote, v.city, how))

    # A. the extraction layer: subject -> company, evidence sentence -> gate
    rows = props_for(cur, rx_of(sorted(all_surf)))
    if verbose:
        print("%d proposition(s) whose subject names a roster company" % len(rows))
    for did, url, subj, pred, obj, place, pol, mod, quote in rows:
        if not is_company_subject(subj):
            refused["subject is a person or product, not the company"] += 1
            continue
        for cid in [cid for cid, rx in rxs.items() if rx.search(subj or "")]:
            consider(cid, url, quote or "", st_domain(url) in own_doms[cid], pol,
                     "extraction layer")
    # B. the company's own pages, sentence by sentence (first person allowed)
    for c in comps:
        for did, url, text in docs_on(cur, own_doms[c["cid"]]):
            for s in split_sentences(text):
                if not (COUNTRY_RX.search(s) or COUNTRY_CASED_RX.search(s)
                        or DEMONYM_FORCE_RX.search(s) or NAMED_FORCE_RX.search(s)):
                    continue
                consider(c["cid"], url, s, True, None, "own site")
    if verbose:
        print("%d (sentence, country) candidate(s) judged" % n_cand)
    return accepted, refused


def judge(accepted, comps):
    """-> {cid: [row]} rows that clear the shared source bar, one per (country, kind)."""
    names = {c["cid"]: c["name"] for c in comps}
    out = {}
    weak = collections.Counter()
    for cid, groups in accepted.items():
        rows = []
        for (country, kind), hits in groups.items():
            if country == "__new__":
                continue
            by_dom = {}
            for url, quote, city, how in hits:
                by_dom.setdefault(st_domain(url), (url, quote, city, how))
            ok, why, tier, n = publishable([h[0] for h in by_dom.values()], names[cid])
            if not ok:
                weak["under the source bar: " + why] += 1
                continue
            # cite the official page when there is one
            best = None
            for d, h in by_dom.items():
                if tier_of_url(h[0]) == _st.OFFICIAL and _st._same_org(maker_of(h[0]) or "", names[cid]):
                    best = h
                    break
            url, quote, city, how = best or list(by_dom.values())[0]
            rows.append({"country": country, "kind": kind, "note": quote, "src": url,
                         "srcnote": "%s; %s; %s" % (why, KIND_LABEL[kind], how),
                         "city": city, "n": len(by_dom)})
        if rows:
            out[cid] = sorted(rows, key=lambda r: (r["country"], r["kind"]))
    return out, weak


def report(rows, refused, weak, accepted, comps, sample=15):
    names = {c["cid"]: c["name"] for c in comps}
    total = sum(len(v) for v in rows.values())
    print("\nPROPOSED: %d footprint row(s) for %d compan(ies)" % (total, len(rows)))
    print("REFUSED : %d candidate (sentence, country) pair(s)" % sum(refused.values()))
    for why, n in refused.most_common():
        print("   %5d  %s" % (n, why))
    if weak:
        print("BELOW THE SOURCE BAR (entailed, but uncorroborated): %d" % sum(weak.values()))
        for why, n in weak.most_common():
            print("   %5d  %s" % (n, why))
    held = {(cid, ct): hits for cid, g in accepted.items()
            for (ct, k), hits in g.items() if ct == "__new__"}
    if held:
        print("HELD: entailed presences in countries the map cannot draw yet:")
        for (cid, _c), hits in sorted(held.items()):
            for url, quote, _city, _how in hits[:2]:
                print("   %-28s %-14s %s" % (names[cid][:28], _c, st_domain(url)))
    hqs = [(names[cid], r) for cid in rows for r in rows[cid] if r["kind"] == "hq"]
    print("\nHQ STATED (fills hq only where it is NULL): %d" % len(hqs))
    for name, r in hqs:
        print("   %-28s %-28s %s" % (name[:28], (r["city"] or r["country"])[:28], st_domain(r["src"])))
    print("\nPER COMPANY:")
    for cid in sorted(rows, key=lambda k: (k != CLIENT_ID, -len(rows[k]))):
        cts = sorted({r["country"] for r in rows[cid]})
        print("   %-32s %2d row(s)  %s" % (names[cid][:32], len(rows[cid]), ", ".join(cts)))
    print("\nSAMPLE (client first):")
    shown = 0
    for cid in sorted(rows, key=lambda k: (k != CLIENT_ID, k)):
        for r in rows[cid]:
            if shown >= sample:
                break
            shown += 1
            print("\n  [%d] %s -> %s (%s)" % (shown, names[cid], r["country"], KIND_LABEL[r["kind"]]))
            print("      src: %s" % r["src"])
            print("      why: %s" % r["srcnote"])
            print("      \"%s\"" % r["note"][:330])


# ----------------------------------------------------------------------- writing

def apply(cur, con, rows, comps, allow_new=False):
    names = {c["cid"]: c for c in comps}
    cur.execute("DELETE FROM serving.geo_presence WHERE origin='pipeline' AND ord >= %s",
                (GEO_ORD0,))
    gone = cur.rowcount
    n_geo = n_gl = n_hq = n_comp = 0
    for ci, cid in enumerate(sorted(rows)):
        c = names[cid]
        cur.execute("SELECT id, hq FROM serving.geo_comp WHERE id=%s", (cid,))
        have = cur.fetchone()
        hq_rows = [r for r in rows[cid] if r["kind"] == "hq" and r["city"]]
        hq = c["hq"] or (hq_rows[0]["city"] if hq_rows else None)
        if not have:
            cur.execute("""INSERT INTO serving.geo_comp (id, ord, name, dir, hq, "isBf", origin)
                           VALUES (%s,%s,%s,%s,%s,%s,'pipeline')""",
                        (cid, GEO_ORD0 + ci, c["name"],
                         "client" if c["dir"] == "client" else "threat", hq,
                         c["dir"] == "client"))
            n_comp += 1
        elif hq and not have[1]:
            cur.execute("UPDATE serving.geo_comp SET hq=%s WHERE id=%s", (hq, cid))
        by_country = {}
        for r in rows[cid]:
            by_country.setdefault(r["country"], []).append(r)
        for k, (country, rs) in enumerate(sorted(by_country.items())):
            for r in rs:
                if r["kind"] == "hq":
                    continue          # the HQ is served through geo_comp.hq, not a band
                code = "bf" if c["dir"] == "client" else MAP_CODE.get(r["kind"])
                if code is None:
                    continue          # office / subsidiary: Profile field only, no map band
                cur.execute("""INSERT INTO serving.geo_presence
                                 (comp_id, comp_ord, country, country_ord, ord, name, c,
                                  val, since, qty, stage, note, src, srcnote, origin)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,NULL,NULL,NULL,NULL,%s,%s,%s,
                                       'pipeline')
                               ON CONFLICT (comp_id, country, ord) DO NOTHING""",
                            (cid, GEO_ORD0 + ci, country, k, GEO_ORD0 + n_geo,
                             KIND_LABEL[r["kind"]], code, r["note"][:1000], r["src"],
                             r["srcnote"][:300]))
                n_geo += cur.rowcount
        if c["dir"] != "client":
            # global_locations is where the company IS -- a plant, an office, a JV, its
            # HQ -- never a market it delivered into: "countries a company was mentioned
            # in" is the fault the Profile page already complained of.
            gl = []
            for country, rs in sorted(by_country.items()):
                rs = [r for r in rs if r["kind"] in LOCATION_KINDS]
                if country in REGIONS or not rs:
                    continue
                r = rs[0]
                gl.append({"value": country, "url": r["src"], "quote": r["note"][:400],
                           "kind": KIND_LABEL[r["kind"]]})
            if gl:
                cur.execute("""UPDATE serving.competitors SET global_locations=%s
                                WHERE comp_id=%s AND origin='pipeline'""",
                            (json.dumps(gl), cid))
                n_gl += cur.rowcount
            if hq and not c["hq"]:
                cur.execute("""UPDATE serving.competitors SET hq=%s
                                WHERE comp_id=%s AND origin='pipeline' AND hq IS NULL""",
                            (hq, cid))
                n_hq += cur.rowcount
    con.commit()
    print("\napplied: %d map row(s) written (replaced %d of this writer's), %d company row(s) "
          "added to the map, global_locations set on %d competitor(s), hq filled on %d"
          % (n_geo, gone, n_comp, n_gl, n_hq))


def main(apply_it=False, sample=15, allow_new=False):
    import psycopg2
    no_control_chars()
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    cur.execute("SET statement_timeout='900s'")
    comps = load_companies(cur)
    print("%d compan(ies): the client + %d pipeline competitor(s)" % (len(comps), len(comps) - 1))
    accepted, refused = mine(cur, comps)
    rows, weak = judge(accepted, comps)
    report(rows, refused, weak, accepted, comps, sample)
    if apply_it:
        apply(cur, con, rows, comps, allow_new)
    else:
        print("\n(dry run -- nothing written)")
    con.close()
    return rows, refused


def _demo():
    no_control_chars()
    from test_geo_footprint import run_all
    run_all()
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--sample", type=int, default=15)
    ap.add_argument("--allow-new-countries", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        main(a.apply, a.sample, a.allow_new_countries)
