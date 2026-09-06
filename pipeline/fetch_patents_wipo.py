# -*- coding: utf-8 -*-
"""Real patent records for the Patents tab, from WIPO PATENTSCOPE.

    python fetch_patents_wipo.py --demo     # hermetic: gates only, no network
    python fetch_patents_wipo.py --dry      # fetch, gate, report, write the ledger
    python fetch_patents_wipo.py --apply    # ... and write serving.patent

WHY NOT THE EXISTING FETCHER. fetch_patents.py reads Google Patents, which serves
about four queries from this network and then answers 503 to everything, including
a single query after a long back-off. Its result JSON also carries no
classification code at all, so a CPC filter can be applied but never read back and
checked. Its output, pipeline/fetch_patents.json, holds 90 rows that show what a
title/abstract keyword gate produces: 79 with assignee "not stated", plus "Toy Gun"
and "PNEUMATIC TOY GUN RECOIL DEVICE" filed under Artillery and a solar-energy
patent under UAVs (it came from the query "Solar Industries").

PATENTSCOPE answers without a key, without JavaScript, and prints the IPC, the
applicant, the publication number, the jurisdiction and the date on the result row
itself -- so every gate below runs on data the registry stated, not on data we
inferred. It covers the national collections the roster actually files in: IN, KR,
IL, TR, RU, CN, JP and the European offices.

THE TWO GATES

  ATTRIBUTION is an allow-list and nothing else. A patent belongs to the applicant
  of record -- not the inventor, not a licensee, not the maker of a product, and
  never the company that happened to be queried (fetch_patents.py:154 fills a
  missing assignee with the query term, which is how a record acquires an owner it
  never had). Registry applicants are legal entities, not brands: Nammo files as
  Nammo Talley Inc, Nammo Lapua Oy, Nammo Vanasverken AB, Nammo Raufoss AS and
  Nammo Germany GmbH. A single-token brand matches EXACTLY and never by
  containment, because containment lets Elbit claim Elbit Imaging -- a real,
  unrelated company -- and Adani claim every Adani group entity. An applicant that
  does not resolve is DROPPED and written to the proposal file for a human, never
  stored as "not stated".

  RELEVANCE is classification, never keywords. A keyword list is a language
  detector: a Korean autoloader is F41A 9/49 whatever language its title is in, and
  under PATENTSCOPE the Hindi, Korean, Hebrew and Turkish titles are not translated
  for you. Keywords appear here once, as a DIAGNOSTIC that must find nothing.

AREA is resolved from the patent's own classification, and every stored row lands
in one of the nine areas the client's vocabulary already defines. There is no tenth
area and no "Other": gun-fired ammunition of every calibre, a 155 mm shell body
included, belongs under "Small arms & ammunition".
"""
import argparse
import collections
import http.cookiejar
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
LEDGER = HERE / "fetch_patents_wipo.json"
PROPOSALS = HERE / "fetch_patents_unresolved.json"
DSN = os.environ.get(
    "KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "KSSL-corpus/1.0 (+patent research; contact via repository)"}
BASE = "https://patentscope.wipo.int/search/en/result.jsf?query="
PATENT_ORD0 = 1000          # archived reference rows own 1..26; this writer owns >=1000
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# folding
# --------------------------------------------------------------------------
# NFD then strip combining marks, never NFKD: NFKD decomposes Hangul syllables into
# jamo and a Korean applicant stops matching itself. Legal-form suffixes are a closed
# list fixed by company law in each jurisdiction, which is what separates this from a
# keyword list -- it cannot silently exclude a language, it can only fail to strip a
# suffix, and then the alias simply needs the fuller form.
_SUFFIX = {
    "ltd", "limited", "pvt", "private", "inc", "incorporated", "corp", "corporation",
    "llc", "lllp", "llp", "plc", "gmbh", "mbh", "ag", "kg", "kgaa", "se", "sa", "sas",
    "sarl", "spa", "srl", "nv", "bv", "ab", "oy", "oyj", "as", "asa", "aps", "sp",
    "zoo", "ao", "oao", "ooo", "pao", "zao", "co", "company", "holding", "holdings",
    "group", "industries", "industrie", "systems", "system", "technologies",
    "technology", "defence", "defense", "kabushiki", "kaisha", "gongsi", "jusik",
    "hoesa", "anonim", "sirketi", "sti", "as1",
    # Swedish and Czech legal forms the registry prints in full. "SAAB DYNAMICS
    # AKTIEBOLAG" and "SAAB CZECH S.R.O." are the same two companies as "Saab
    # Dynamics AB" and a Saab s.r.o.; the list failing to hold the spelled-out form
    # is the "it can only fail to strip a suffix" failure the note above predicted.
    # "lp" is here for the same reason: the list held llp and lllp but not the plain
    # limited partnership BAE Systems Land & Armaments files as.
    "aktiebolag", "sro", "lp",
}
# "&" folds to the WORD "and", which then sits between two alias tokens and breaks
# their contiguity: "BAE Systems Land & Armaments L.P." became
# bae/systems/land/AND/armaments, so the alias "BAE Systems Land Armaments" no longer
# appeared as a run and 51 correctly-owned publications were dropped. A connector is
# not part of a name for matching, so it is removed from BOTH sides.
_CONNECT = {"and"}
# WIPO's uppercase applicant index truncates at 30 characters -- 'KRAUSS MAFFEI
# WEGMANN GMBH & C', 'SAAB BOFORS DYNAMICS SWITZERLA' and 'OTOKAR OTOBUES KAROSERI
# SANAYI' are all exactly this long. No alias can equal a cut-off string, so at or
# beyond the cut the LAST leftover token may be a PREFIX of a noise word instead of
# the whole word. Only a leftover is ever forgiven; the alias itself must still
# appear in full and contiguously.
_TRUNC = 30
_COMBINING = dict.fromkeys(
    i for i in range(sys.maxunicode) if unicodedata.combining(chr(i)))


def _tokens(s):
    """Script-preserving token list. NFD then strip marks, never NFKD."""
    s = unicodedata.normalize("NFD", (s or "").strip())
    s = s.translate(_COMBINING)
    s = unicodedata.normalize("NFC", s).casefold()
    s = s.replace("&amp;", " and ").replace("&", " and ")
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    return [t for t in s.split() if t]


def _key(s, strip_suffix=True):
    """Match tokens: connectors dropped, THEN trailing legal forms popped.

    The order matters. Popping first stops at the "and" that "& Co. KG" folds to and
    leaves "gmbh and" welded to the name; dropping the connector first lets the pop
    reach the whole suffix run.
    """
    toks = [t for t in _tokens(s) if t not in _CONNECT]
    if strip_suffix:
        while toks and toks[-1] in _SUFFIX:
            toks.pop()
    return toks


def fold(s, strip_suffix=True):
    """Comparable form of an applicant or alias. Script is preserved.

    Also the family-dedup key for titles, which is why it stays a plain string.
    """
    return " ".join(_key(s, strip_suffix))


# --------------------------------------------------------------------------
# ATTRIBUTION -- the allow-list
# --------------------------------------------------------------------------
# (alias as a registry prints it, comp_id, kind, why). Seeded from the live roster
# and from the applicant strings PATENTSCOPE actually returns. Every entry beyond a
# roster name is a decision, so each one carries its reason.
#
# CLIENT is the client group. Kalyani Strategic Systems holds nothing as applicant;
# the group files as Bharat Forge, so the client's rows arrive through that alias and
# the business-line split (truck forgings vs gun barrels) is made by classification,
# not by the name.
ART = [
    ("Kalyani Strategic Systems", "CLIENT", "self", "the client"),
    ("Bharat Forge", "CLIENT", "subsidiary", "the client's parent; KSSL files under it"),
    ("Kalyani Rafael Advanced Systems", "CLIENT", "jv", "KRAS, the client group's JV"),

    ("Bharat Dynamics", "bharat-dynamics", "self", ""),
    ("Munitions India", "munitions-india", "self", ""),
    ("Premier Explosives", "premier-explosives", "self", ""),
    ("Solar Industries India", "premier-explosives", "self",
     "not on the roster in its own right; nearest tracked energetics rival"),
    ("Larsen and Toubro", "larsen-toubro", "self", ""),
    ("Tata Advanced Systems", "tata-advanced-systems", "self", ""),
    ("Mahindra Defence Systems", "mahindra", "self", ""),
    ("Adani Defence and Aerospace", "adani-defence", "self", ""),
    ("BrahMos Aerospace", "brahmos-aerospace", "self", ""),
    ("PLR Systems", "plr-systems", "self", ""),
    ("SSS Defence", "sss-defence", "self", ""),
    ("Advanced Weapons and Equipment India", "aweil", "legal_variant", "AWEIL in full"),

    ("Rheinmetall", "rheinmetall", "self", ""),
    ("Rheinmetall Waffe Munition", "rheinmetall", "subsidiary", ""),
    ("Rheinmetall Air Defence", "rheinmetall", "subsidiary", ""),
    ("Rheinmetall Landsysteme", "rheinmetall", "subsidiary", ""),
    ("Diehl Defence", "rheinmetall", "self",
     "Diehl is not a roster row; nearest tracked German munitions rival"),
    ("Diehl BGT Defence", "rheinmetall", "former_name",
     "Diehl Defence's registered name until the 2017 rename; 10 publications"),

    ("KNDS", "knds", "self", ""),
    ("KNDS Deutschland", "knds", "subsidiary", ""),
    ("KNDS France", "knds", "subsidiary", ""),
    ("Krauss Maffei Wegmann", "knds", "subsidiary", "KMW, the German half of KNDS"),
    ("Nexter Systems", "nexter", "self", "the roster keeps Nexter separate from KNDS"),
    ("Nexter Munitions", "nexter", "subsidiary", ""),
    ("Giat Industries", "nexter", "former_name", "Nexter's name until 2006"),

    ("BAE Systems", "bae-systems", "self", ""),
    ("BAE Systems Land Armaments", "bae-systems", "subsidiary", ""),
    ("BAE Systems Bofors", "bae-systems", "subsidiary", ""),
    ("British Aerospace", "bae-systems", "former_name",
     "BAE's name until the 1999 Marconi merger; the registry still prints it"),
    ("Lockheed Martin", "lockheed-martin", "self", ""),
    ("General Dynamics", "general-dynamics", "self", ""),
    ("General Dynamics Ordnance and Tactical Systems", "general-dynamics",
     "subsidiary", "the remainder is a business-line name, so it needs its own row"),
    ("General Dynamics Land Systems", "general-dynamics", "subsidiary", ""),
    ("Raytheon", "raytheon", "self", "the roster keeps Raytheon separate from RTX"),
    ("Raytheon Technologies", "rtx", "former_name", "RTX's name until 2023"),
    ("RTX", "rtx", "self", ""),
    ("Oshkosh Defense", "oshkosh-defense", "self", ""),
    ("Oshkosh", "oshkosh-defense", "self", ""),
    ("AeroVironment", "aerovironment", "self", ""),
    ("Anduril Industries", "anduril", "self", ""),
    ("SIG Sauer", "sig-sauer", "self", ""),

    ("MBDA", "mbda", "self", ""),
    ("MBDA France", "mbda", "subsidiary", ""),
    ("MBDA Deutschland", "mbda", "subsidiary", ""),
    ("MBDA UK", "mbda", "subsidiary", ""),
    ("Saab", "saab", "self", ""),
    ("Saab Bofors Dynamics", "saab", "subsidiary", ""),
    ("Saab Dynamics", "saab", "subsidiary", ""),
    ("Saab Barracuda", "saab", "subsidiary",
     "the signature-management arm; a business line, so it needs its own row"),
    ("Patria", "patria", "self", ""),
    # Patria's three operating companies. "Patria" is a single-token brand and a
    # Latin word, so it matches exactly and never by containment -- which means every
    # subsidiary has to be written out, exactly as Nammo's five are. 27 publications.
    ("Patria Land", "patria", "subsidiary", ""),
    ("Patria Land Armament", "patria", "subsidiary", ""),
    ("Patria Vammas", "patria", "subsidiary", "the Vammas gun works"),
    ("Nammo", "nammo", "self", ""),
    ("Nammo Raufoss", "nammo", "subsidiary", ""),
    ("Nammo Lapua", "nammo", "subsidiary", ""),
    ("Nammo Talley", "nammo", "subsidiary", ""),
    ("Nammo Vanasverken", "nammo", "subsidiary", ""),
    ("Nammo Germany", "nammo", "subsidiary", ""),
    ("Kongsberg Defence and Aerospace", "kongsberg", "subsidiary", ""),
    ("Kongsberg Gruppen", "kongsberg", "self", ""),
    # LEONARDO IS NOT IDV'S PARENT, AND WAS LISTED HERE AS IF IT WERE.
    #
    # Iveco Defence Vehicles is Iveco Group's defence arm -- Iveco is its own row on
    # the roster -- and Leonardo S.p.A. is a separate Italian prime that is not on
    # the roster at all. The two firms share a JV (Leonardo Rheinmetall Military
    # Vehicles) and nothing else. Querying "Leonardo" and filing the results under
    # `idv` attributed one company's patents to another, which is the exact failure
    # this module's attribution gate exists to stop: an applicant of record is the
    # owner, and a JV partner is not.
    ("Iveco Defence Vehicles", "idv", "self", ""),
    ("Iveco", "iveco", "self", ""),
    ("Otokar Otomotiv ve Savunma Sanayi", "otokar", "self", ""),
    ("Otokar Otobues Karoseri Sanayi", "otokar", "former_name",
     "Otokar's name before the 2005 rename, spelled as WIPO's index prints it "
     "(oe for the Turkish o-umlaut) and cut off at the index's 30 characters"),
    ("Otokar", "otokar", "self", ""),
    ("Supacat", "supacat", "self", ""),
    ("Roshel", "roshel", "self", ""),
    # Huta Stalowa Wola stood here mapped to `paramount-group`, with a note saying it
    # was "kept out unless it is added". The note was not the code: an ART entry IS
    # the allow-list, so every HSW patent would have been stored as Paramount's. HSW
    # is a Polish state manufacturer and Paramount is South African. It belongs in
    # the proposal file with the other unresolved applicants, which is where an
    # applicant that resolves to nothing already goes.

    ("Elbit Systems", "elbit-systems", "self", ""),
    ("Elbit Systems Land", "elbit-systems", "subsidiary", ""),
    ("Elbit Systems Land and C4I", "elbit-systems", "subsidiary",
     "the merged land-and-C4I company; 'c4i' is a business line, so containment "
     "will not reach it from 'Elbit Systems Land' and it needs its own row"),
    ("Israel Aerospace Industries", "israel-aerospace-industries", "self", ""),
    ("Rafael Advanced Defense Systems", "rafael-advanced-defense-systems", "self", ""),
    ("UVision Air", "uvision-air", "self", ""),
    ("Israel Weapon Industries", "iwi", "self", ""),

    ("Hanwha Aerospace", "hanwha-aerospace", "self", ""),
    ("Hanwha Corporation", "hanwha-aerospace", "subsidiary",
     "the explosives and MLRS arm of the same group"),
    ("Hanwha Techwin", "hanwha-aerospace", "former_name", "renamed 2018"),
    ("Hanwha Defense", "hanwha-aerospace", "former_name", "merged in 2022"),
    ("Poongsan", "poongsan", "self", ""),
    ("Poongsan Corporation", "poongsan", "self", ""),
    # CROSS-SCRIPT ALIASES ARE NOT TRANSLITERATIONS WE PERFORMED.
    #
    # Each one below is a string PATENTSCOPE returned in reply to an APPLICANT-field
    # query for the Latin name -- PA:(Poongsan) answers with 주식회사 풍산 because
    # WIPO's own applicant index holds both forms for that record. The registry is
    # asserting the link; we are recording what it asserted. We never romanise a name
    # ourselves and never infer one, and an unlisted non-Latin applicant is dropped
    # and proposed like any other.
    ("주식회사 풍산", "poongsan", "transliteration",
     "returned by PA:(Poongsan) -- WIPO's applicant index holds both forms"),
    ("풍산", "poongsan", "transliteration", "the same, without the corporate prefix"),
    ("한화에어로스페이스 주식회사", "hanwha-aerospace", "transliteration",
     "returned by PA:(Hanwha)"),
    ("주식회사 한화", "hanwha-aerospace", "transliteration", "returned by PA:(Hanwha)"),
    ("한화시스템 주식회사", "hanwha-aerospace", "transliteration", "Hanwha Systems"),
    ("한화디펜스 주식회사", "hanwha-aerospace", "transliteration",
     "returned by PA:(Hanwha Techwin) -- Hanwha Defense, merged in 2022; the Latin "
     "'Hanwha Defense' is already an entry above and shares no token with this"),

    ("Kalashnikov Concern", "kalashnikov", "self", ""),
    ("Концерн Калашников", "kalashnikov", "transliteration", "the Cyrillic form"),
    ("Ижевский машиностроительный завод", "kalashnikov", "former_name",
     "Izhmash, the name it filed under before 2013"),
    ("Norinco", "norinco", "self", ""),
    ("China North Industries", "norinco", "legal_variant", "NORINCO in full"),
    ("Paramount Group", "paramount-group", "self", ""),
]

# A brand of one token is far too weak to match by containment: Saab, Nammo, Patria
# (a Latin word), Rafael (a given name), Elbit, Adani, Otokar, MBDA, KNDS, Norinco,
# Poongsan, Supacat, Roshel, Kongsberg, Anduril. These match EXACTLY, and every
# subsidiary of them is an explicit row above. This is the whole-name rule that the
# spec grounder needed three attempts to get right, applied to attribution.
# AN ALIAS IS REGISTERED IN BOTH FOLDED FORMS, NOT ONLY THE STRIPPED ONE.
#
# fold() was applied to the alias as well as to the applicant, so "Diehl Defence" --
# an alias written out precisely because the brand alone is too weak -- was stored as
# the one-token "diehl", "BAE Systems" as "bae", "Israel Weapon Industries" as
# "israel weapon". A one-token alias then falls under the strict rule below that every
# leftover be GEOGRAPHIC, and "defence" is a business word, not a place. The alias the
# author wrote was silently replaced by a weaker one and then refused for being weak.
#
# Both forms are kept: the stripped one so "Hanwha Corporation" still answers a bare
# "HANWHA", the unstripped one so "Diehl Defence" is still available as itself.
_BY_FOLD = {}
for _alias, _cid, _kind, _why in ART:
    for _strip in (True, False):
        _f = fold(_alias, _strip)
        if _f:
            _BY_FOLD.setdefault(_f, (_cid, _alias, _kind))
# Longest alias first, so "Iveco Defence Vehicles" is tried before "Iveco" and
# "Elbit Systems Land and C4I" before "Elbit Systems". Dict order is insertion order,
# which put the answer at the mercy of the order rows happen to appear in ART.
_ALIAS_SEQ = sorted(((af.split(), v) for af, v in _BY_FOLD.items()),
                    key=lambda kv: -len(kv[0]))


def _noise(tok, truncated_tail=False):
    """Is this leftover token noise -- a legal form, a place, or an initial?

    A single character is an initialism fragment, never a business line: "L.P.",
    "(I.W.I.)" and "A.S." fold to l/p, i/w/i and a/s, and each of those refused a
    company its own registry names as itself.
    """
    if tok in _GEO or tok in _SUFFIX:
        return True
    if len(tok) == 1:
        return True
    if truncated_tail and len(tok) >= 3:
        return any(w.startswith(tok) for w in _NOISE_WORDS)
    return False


def resolve(applicant):
    """-> (comp_id, matched_alias) or (None, None). Allow-list only, no guessing."""
    raw = (applicant or "").strip()
    ftoks = _key(raw)
    if not ftoks:
        return None, None
    hit = _BY_FOLD.get(" ".join(ftoks))
    if hit:
        return hit[0], hit[1]
    # Containment is permitted only for a multi-token alias, only on whole word
    # boundaries, and only when what is left over is legal-form or geographic noise.
    # "General Dynamics Ordnance and Tactical Systems" leaves "ordnance tactical",
    # which is a business line, not noise -- so it needs the explicit row it has.
    truncated = len(raw) >= _TRUNC
    last = len(ftoks) - 1
    for atoks, (cid, alias, _k) in _ALIAS_SEQ:
        # A one-token brand may carry a COUNTRY and nothing else: "Nammo Germany GmbH"
        # is Nammo's German arm, and refusing it lost a real record to the proposal
        # file. The remainder test below still does the work -- "Elbit Imaging" leaves
        # "imaging", "Adani Green Energy" leaves "green energy", and neither is a place,
        # so both stay refused. A brand plus a place is the same brand; a brand plus a
        # business line is a different company until someone says otherwise.
        if len(atoks) == 1 and not all(
                t in _GEO or len(t) == 1 for t in ftoks if t not in atoks):
            continue
        if len(atoks) > len(ftoks):
            continue
        for i in range(len(ftoks) - len(atoks) + 1):
            if ftoks[i:i + len(atoks)] == atoks:
                rest = [(j, t) for j, t in enumerate(ftoks)
                        if not i <= j < i + len(atoks)]
                if all(_noise(t, truncated and j == last) for j, t in rest):
                    return cid, alias
    return None, None


_GEO = {
    "usa", "us", "america", "american", "uk", "gb", "britain", "british", "france",
    "french", "germany", "german", "deutschland", "india", "indian", "israel",
    "israeli", "korea", "korean", "japan", "japanese", "china", "chinese", "italy",
    "italia", "italian", "spain", "espana", "sweden", "sverige", "swedish", "norway",
    "norge", "finland", "suomi", "poland", "polska", "turkiye", "turkey", "russia",
    "canada", "australia", "south", "north", "africa", "europe", "european",
    "international", "global", "worldwide", "of", "the", "and", "for",
    # Saab files from both: "SAAB BOFORS DYNAMICS SWITZERLAND LTD" and
    # "SAAB CZECH S.R.O." are Saab's Swiss and Czech arms and were refused because
    # the list of places did not name their places.
    "switzerland", "swiss", "czech", "czechia", "suisse", "schweiz",
}

# Words a truncated tail is allowed to be a prefix of. Places and legal forms only --
# never a brand or a business line, so a cut-off string can lose its suffix but can
# never acquire an owner.
_NOISE_WORDS = _GEO | _SUFFIX


# --------------------------------------------------------------------------
# RELEVANCE -- classification, and the nine areas
# --------------------------------------------------------------------------
# An IPC symbol as PATENTSCOPE prints it: "F42B 5/00", "F41A 9/49", "C06B 25/34".
IPC_RX = re.compile(r"\b([A-H])\s?(\d{2})\s?([A-Z])\s?(\d{1,4})\s*/\s*(\d{2,6})\b")


def ipc_parts(sym):
    """'F42B 5/00' -> ('F42B', 5). The main group is what the area rules read."""
    m = IPC_RX.search(sym or "")
    if not m:
        return None, None
    return "%s%s%s" % (m.group(1), m.group(2), m.group(3)), int(m.group(4))


# Vetoes. These win even when a core class is also present, because they name what
# the record IS: an airgun, a target, a training simulator, civil blasting, a toy.
# F41B is where "PNEUMATIC TOY GUN RECOIL DEVICE" and "Toy Gun" live.
VETO = [("F41B", None), ("F41J", None), ("F41A", 33), ("F42D", None),
        ("A63H", None), ("A63F", None), ("E21B", None), ("E21C", None)]

# The nine areas are the client's vocabulary, exactly as ui_config PATENTS.techAreas
# spells them. A tenth area is not created and there is no "Other": a row whose
# classification lands nowhere is refused, counted, and left in the ledger.
A_LOITER = "Loitering munitions"
A_GUIDED = "Guided artillery / precision fires"
A_MBRL = "Rocket artillery (MBRL)"
A_ARMOUR = "Armour & protected mobility"
A_SMALL = "Small arms & ammunition"
A_AD = "Air defence & C-UAS"
A_MISSILE = "Missiles & seekers"
A_ENERGET = "Energetics & propellants"
A_UAV = "UAV / ISR platforms"
AREAS = [A_LOITER, A_GUIDED, A_MBRL, A_ARMOUR, A_SMALL, A_AD, A_MISSILE,
         A_ENERGET, A_UAV]


def area_of(codes):
    """Resolve the area from the record's own classification. First rule wins.

    Ordered most-specific first, because a loitering munition is classified as both
    an aircraft and a warhead and would otherwise land under whichever class was
    read first.

    Gun-fired ammunition of every calibre lands in "Small arms & ammunition",
    including a 155 mm shell body. The vocabulary has one ammunition area and this
    is it; splitting artillery ammunition out would need a tenth area that the UI
    does not have and the client has not asked for.
    """
    cls = set()
    grp = set()
    for c in codes:
        k, g = ipc_parts(c)
        if k:
            cls.add(k)
            grp.add((k, g))

    def has(k, *groups):
        return (k in cls) if not groups else any((k, g) in grp for g in groups)

    uav = has("B64U") or has("B64C", 39) or has("B64D") or has("G05D", 1)
    weapon = any(k.startswith("F41") or k.startswith("F42") for k in cls)

    if uav and weapon:
        return A_LOITER                                  # an aircraft that is a weapon
    if has("F41H", 11, 13) or has("F41G", 5) or has("H04K"):
        return A_AD
    if has("F41G", 7, 9) or has("F42B", 15) or has("F02K", 9):
        return A_MISSILE
    if has("F41F", 3):
        return A_MBRL
    if has("F41H", 1, 5, 7, 12) or has("F41H"):
        return A_ARMOUR
    if has("F41G") or has("F41F", 1) or has("F42B", 10):
        return A_GUIDED                                  # aiming, fire control, guided shells
    if has("F41A") or has("F41C") or has("F42B") or has("F42C") or has("B21K", 21):
        return A_SMALL                                   # ALL gun-fired ammunition
    if has("C06B") or has("C06D") or has("C06C"):
        return A_ENERGET
    if uav:
        return A_UAV
    return None


def relevant(codes):
    """-> (ok, reason). Classification decides; a veto beats a core class."""
    parsed = [ipc_parts(c) for c in codes]
    parsed = [(k, g) for k, g in parsed if k]
    if not parsed:
        return False, "no classification"
    for vk, vg in VETO:
        for k, g in parsed:
            if k == vk and (vg is None or g == vg):
                return False, "civil veto (%s)" % vk
    # C06B 47 is ANFO / emulsion / water-gel: mining, not defence, and it is the one
    # energetics group that must not carry a record on its own.
    core = []
    for k, g in parsed:
        if k == "C06B" and g == 47:
            continue
        if k in ("F41A", "F41C", "F41F", "F41G", "F41H", "F42B", "F42C",
                 "C06B", "C06D", "C06C", "F02K", "B64U"):
            core.append((k, g))
    if not core:
        return False, "not defence-classified"
    return True, ""


# The keyword list appears exactly once in this file, and it is a DIAGNOSTIC: after a
# run it must match nothing. If it ever matches, the classification gate has a hole --
# it is not there to close one.
JUNK_RX = re.compile(
    r"\b(toy|airsoft|paintball|hunting rifle|sport(ing)? (gun|arm)|fluid end|"
    r"wellbore|frac(king)?|solar (energy|panel|cell))\b", re.I)


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------
ROW_RX = re.compile(r'data-mt-ipc="([^"]*)"(.*?)(?=data-mt-ipc="|$)', re.S)
NUM_RX = re.compile(r'ps-patent-result--title--patent-number">([^<]+)<')
TITLE_RX = re.compile(r'needTranslation-title"[^>]*>.*?</span>([^<]*)<', re.S)
CTR_RX = re.compile(r'ctr-pubdate">\s*<span[^>]*>([A-Z]{2})</span>.*?'
                    r'ColumnPubDate"[^>]*>([\d.]+)<', re.S)
APP_RX = re.compile(r'Applicant\s*</span>\s*<span[^>]*>(.*?)</span>\s*</span>', re.S)
IPCLINK_RX = re.compile(r'symbol=([A-H]\d{2}[A-Z]\d{6,})')
TAG_RX = re.compile(r"<[^>]+>")
# The record's stable id, in the href of the number the parser already reads:
#   <a href="detail.jsf;jsessionid=...?docId=PH290880599&amp;_cid=...">
# It is the only durable handle PATENTSCOPE prints. Without it the module could
# neither link to a record nor ask the registry anything further about one.
DOCID_RX = re.compile(r'href="(detail\.jsf[^"]*?docId=([A-Za-z0-9_]+)[^"]*)"')
ABSTRACT_RX = re.compile(r'ps-patent-result--abstract"[^>]*>(.*?)</div>', re.S)
# HOW MANY THERE ACTUALLY ARE. PATENTSCOPE prints the true total on the page and the
# harvest never read it, so ten rows per query looked like the whole answer:
# PA:(Poongsan) AND IC:(F42B) says "60 results" and returned 10.
TOTAL_RX = re.compile(r'results-count">\s*([\d,  ]+?)\s*results?\s*<', re.I)
PAGENO_RX = re.compile(r'pageNumber">(\d+)</span>')
VIEWSTATE_RX = re.compile(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"')
# The paginator's next link is an <a> while it is live and a <span> once it is
# disabled on the last page, so requiring the <a> is also the stop condition.
NEXTLINK_RX = re.compile(r'<a id="([A-Za-z0-9_:]+)"[^>]*js-paginator-next')
# detail.jsf's bibliographic block. Labelled fields, one label span then one value
# span, which is where Application Date, Publication Kind, Grant Number and Grant
# Date live -- none of which the result row prints.
BIBLIO_RX = re.compile(
    r'ps-biblio-field--label"><span[^>]*>([^<]+)</span>\s*</span>\s*'
    r'<span class="ps-field--value ps-biblio-field--value">([^<]*)<', re.S)
# The detail page answers a cold request with a shell that reloads itself. That is
# not the record, and storing what it parses out of one would be storing nothing.
SHELL_RX = re.compile(r"setTimeout\(function\(\)\{location\.reload\(\);\}")


def _text(s):
    return re.sub(r"\s+", " ", TAG_RX.sub(" ", s or "")).strip()


def ipc_symbol(sym):
    """WIPO's fixed-width symbol -> the printed form. F42B0033020700 -> F42B 33/0207.

    The subgroup is SIX digits, not two. Reading sym[8:10] turned F42B 1/032 into
    F42B 1/03 -- a real subgroup, a different one, and one the area rules could
    therefore read as something the record is not.
    """
    sub = sym[8:14].rstrip("0")
    if not sub:
        sub = "00"
    elif len(sub) < 2:
        sub += "0"
    return "%s %d/%s" % (sym[:4], int(sym[4:8]), sub)


def parse_total(html):
    """-> the registry's own count of matching records, or None if it did not print one."""
    m = TOTAL_RX.search(html or "")
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(1))
    return int(digits) if digits else None


def parse_results(html):
    """-> [record]. Every field comes off the result row the registry rendered."""
    out = []
    for ipc_attr, blob in ROW_RX.findall(html):
        num = NUM_RX.search(blob)
        app = APP_RX.search(blob)
        ctr = CTR_RX.search(blob)
        ttl = TITLE_RX.search(blob)
        did = DOCID_RX.search(blob)
        abst = ABSTRACT_RX.search(blob)
        codes = [ipc_attr] if ipc_attr else []
        for sym in IPCLINK_RX.findall(blob):
            codes.append(ipc_symbol(sym))
        out.append({
            "no": _text(num.group(1)) if num else "",
            "title": _text(ttl.group(1)) if ttl else "",
            "applicant": _text(app.group(1)) if app else "",
            "country": ctr.group(1) if ctr else "",
            "pub_date": ctr.group(2) if ctr else "",
            "ipc": sorted(set(c for c in codes if ipc_parts(c)[0])),
            "doc_id": did.group(2) if did else "",
            "detail_href": did.group(1).replace("&amp;", "&") if did else "",
            # The abstract was on the result row all along and was thrown away:
            # all 1,157 stored rows carry abstract=None.
            "abstract": _text(abst.group(1)) if abst else "",
        })
    return out


def parse_detail(html):
    """-> {label: value} from detail.jsf, or {} if this is the reload shell.

    An empty dict means NOT MEASURED. It must never become "filed" or a zero.
    """
    if not html or SHELL_RX.search(html):
        return {}
    out = {}
    for lab, val in BIBLIO_RX.findall(html):
        out.setdefault(_text(lab), _text(val))
    return out


class Session(object):
    """A cookie session. PATENTSCOPE is stateful and a stateless GET gets nothing.

    result.jsf answers a cold GET, but detail.jsf answers it with a reload shell and
    the paginator is a JSF postback against a ViewState that only exists inside a
    session. Both were unreachable through urlopen(), which is why grant status was
    "one request away" and never made.
    """

    def __init__(self, timeout=60, pause=3.0):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self.timeout = timeout
        self.pause = pause
        self.requests = 0

    def get(self, url, referer=None):
        hdrs = dict(UA)
        if referer:
            hdrs["Referer"] = referer
        req = urllib.request.Request(url, headers=hdrs)
        self.requests += 1
        with self.op.open(req, timeout=self.timeout) as r:
            return r.geturl(), r.read().decode("utf-8", "replace")

    def post_ajax(self, url, source, viewstate, form="resultListForm", referer=None):
        data = [("javax.faces.partial.ajax", "true"),
                ("javax.faces.source", source),
                ("javax.faces.partial.execute", source),
                ("javax.faces.partial.render", "results-container"),
                (source, source), (form, form),
                ("javax.faces.ViewState", viewstate)]
        hdrs = dict(UA)
        hdrs["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        hdrs["Faces-Request"] = "partial/ajax"
        hdrs["X-Requested-With"] = "XMLHttpRequest"
        hdrs["Referer"] = referer or url
        req = urllib.request.Request(
            url, data=urllib.parse.urlencode(data).encode(), headers=hdrs,
            method="POST")
        self.requests += 1
        with self.op.open(req, timeout=self.timeout) as r:
            return r.read().decode("utf-8", "replace")


def fetch(query, timeout=60, session=None):
    """One result page. Kept for callers that only want the first ten rows."""
    url = BASE + urllib.parse.quote(query, safe="")
    if session is not None:
        return session.get(url)[1]
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_pages(query, session, max_pages=1, pause=3.0, log=None):
    """-> (rows, total, pages_read). Follows the paginator when asked to.

    PAGING IS OFF BY DEFAULT (max_pages=1) because it changes harvest volume by a
    large multiple -- PA:(Poongsan) AND IC:(F42B) is 60 records where the harvest
    stored 10 -- and that is an operator's decision, not a silent one. What is NOT
    optional is reporting `total`, so a truncated query is visible either way.
    """
    url = BASE + urllib.parse.quote(query, safe="")
    cur, html = session.get(url)
    total = parse_total(html)
    rows, seen_ids, pages = [], set(), 0
    while True:
        pages += 1
        for r in parse_results(html):
            key = r.get("doc_id") or r.get("no")
            if key in seen_ids:
                continue
            seen_ids.add(key)
            r["result_url"] = cur
            rows.append(r)
        if pages >= max_pages:
            break
        vs = VIEWSTATE_RX.search(html)
        nxt = NEXTLINK_RX.search(html)
        if not (vs and nxt):
            break                       # last page: the next link is a disabled span
        time.sleep(pause)
        try:
            reply = session.post_ajax(cur, nxt.group(1), vs.group(1), referer=cur)
        except Exception as e:
            if log:
                log("      ! paging stopped at page %d: %s" % (pages, str(e)[:50]))
            break
        red = re.search(r'<redirect url="([^"]+)"', reply)
        if red:
            # The first postback of a session syncs the view and answers with a
            # redirect rather than the rows; the rows are on the URL it names.
            time.sleep(pause)
            cur, html = session.get(
                "https://patentscope.wipo.int" + red.group(1).replace("&amp;", "&"),
                referer=cur)
        else:
            html = reply                # later postbacks answer with the rows inline
        if not parse_results(html):
            break
    return rows, total, pages


def fetch_detail(row, session, pause=3.0):
    """-> (fields, error). Fields come from detail.jsf; {} means not measured.

    The link is followed EXACTLY as the result row printed it -- jsessionid, _cid and
    a Referer -- because detail.jsf served a bare docId= a reload shell and then, on
    the retry, a captcha. This is also why the fetch is per-record and paced.
    """
    href = row.get("detail_href")
    if not href:
        return {}, "no detail link on the result row"
    url = "https://patentscope.wipo.int/search/en/" + href
    try:
        _, html = session.get(url, referer=row.get("result_url"))
    except Exception as e:
        return {}, str(e)[:80]
    fields = parse_detail(html)
    if not fields:
        return {}, "registry served no bibliographic block (shell or challenge)"
    return fields, None


# One query per (company, classification block). This spreads the harvest across the
# areas instead of taking the first page of one huge result set -- which on
# Rheinmetall would be ten fuze patents and nothing else. It is a sampling strategy,
# not a census: see fetch_pages and the `truncated` tally that harvest() reports.
BLOCKS = ["F41A", "F41C", "F41F", "F41G", "F41H", "F42B", "F42C", "C06B", "B64U"]


def iso(d):
    """PATENTSCOPE prints 09.03.2020."""
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", (d or "").strip())
    return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1)) if m else None


def harvest(companies, pause=3.0, log=print, max_pages=1, session=None,
            detail=True):
    """-> (rows, unresolved, stats).

    stats carries what the run cannot honestly leave unsaid: how many queries were
    issued, how many FAILED, and how many were truncated by the page limit. A run
    whose every query errored used to be indistinguishable from a run that found
    nothing, and the caller then deleted the tab with it.
    """
    sess = session or Session(pause=pause)
    seen, rows, unresolved = set(), [], {}
    stats = {"queries": 0, "ok": 0, "failed": 0, "truncated": 0,
             "seen_total": 0, "read": 0, "detail_ok": 0, "detail_missing": 0,
             "detail_stopped": False}
    for alias, cid in companies:
        for blk in BLOCKS:
            q = "PA:(%s) AND IC:(%s)" % (alias, blk)
            stats["queries"] += 1
            try:
                got, total, pages = fetch_pages(q, sess, max_pages=max_pages,
                                                pause=pause, log=log)
            except Exception as e:
                stats["failed"] += 1
                log("   ! %-34s %-6s %s" % (alias[:33], blk, str(e)[:44]))
                time.sleep(pause * 2)
                continue
            stats["ok"] += 1
            stats["read"] += len(got)
            if total is not None:
                stats["seen_total"] += total
                if total > len(got):
                    stats["truncated"] += 1
            kept, fresh = 0, []
            for r in got:
                who, matched = resolve(r["applicant"])
                if not who:
                    u = unresolved.setdefault(r["applicant"], {
                        "applicant": r["applicant"], "n": 0,
                        "queried_as": alias, "sample_ipc": r["ipc"][:3]})
                    u["n"] += 1
                    continue
                if r["no"] in seen:
                    continue
                seen.add(r["no"])
                row = dict(r, comp_id=who, matched_alias=matched, query=q)
                rows.append(row)
                fresh.append(row)
                kept += 1
            log("   %-34s %-6s %2d of %-5s rows (%d pg), %2d attributed"
                % (alias[:33], blk, len(got),
                   "?" if total is None else total, pages, kept))
            # ENRICH NOW, WHILE THIS RESULT PAGE IS STILL THE SESSION'S CURRENT VIEW.
            # The detail link the row printed carries a jsessionid and a per-page
            # conversation id (_cid); following it after eighty more queries is
            # following a link into a conversation the server has moved on from.
            #
            # The cost is that a detail fetch moves the session off the result view,
            # so with --pages > 1 a later query may find no paginator and read one
            # page. That degrades to reading LESS, never to reading wrong, and it is
            # visible: the log prints "N of TOTAL rows (P pg)" and stats["truncated"]
            # counts it. If a full census is what is wanted, run --no-detail with
            # --pages, then a second pass for status.
            if detail and not stats["detail_stopped"]:
                enrich(fresh, sess, pause=pause, log=log, stats=stats)
            time.sleep(pause)
    return rows, unresolved, stats


# If the registry starts refusing detail pages -- it answers a cold or impatient
# request with a reload shell and then a picture captcha -- stop asking. Every
# remaining record then stores status='unknown', which is true, instead of spending
# thousands of requests to learn nothing.
DETAIL_GIVE_UP = 8


def enrich(rows, session, pause=3.0, log=print, stats=None):
    """Ask the registry what the result row does not print: is it GRANTED, and when
    was it actually FILED.

    Only rows that will survive the classification gate are asked about, so the extra
    requests are bounded by what the run would store, not by what it read.
    """
    want = [r for r in rows if relevant(r.get("ipc") or [])[0]]
    run = 0
    for r in want:
        fields, err = fetch_detail(r, session, pause=pause)
        r["detail"] = fields or None
        r["detail_error"] = err
        if stats is not None:
            stats["detail_ok" if fields else "detail_missing"] += 1
        if fields:
            run = 0
        else:
            run += 1
            log("      ! detail %-14s %s" % ((r.get("doc_id") or "")[:14], err[:56]))
            if run >= DETAIL_GIVE_UP and stats is not None:
                stats["detail_stopped"] = True
                log("      ! %d detail requests failed in a row: no longer asking. "
                    "The rest of this run stores status=%r."
                    % (run, ST_UNKNOWN))
                break
        time.sleep(pause)
    return rows


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
# Jurisdiction-shaped publication numbers. A record whose number does not match its
# own jurisdiction's grammar is refused: an invented identifier is exactly what the
# archived 26 rows carried (22 of them, "IN-2024-EST01 (est)"), and it is the one
# thing that must never render as a patent record.
NUMBER_RX = re.compile(r"^(?:[A-Z]{2})?[\d][\dA-Z/\-.]{3,24}$")

# THREE STATES, NOT TWO.
#
# Every one of the 1,157 stored rows says status="filed", granted=None, because the
# gate wrote those two constants for every record it ever saw. That is not a
# measurement, it is a default -- and it is wrong: of three records sampled from the
# registry, all three were GRANTED (US 20180364015 -> grant 10254091, kind B2,
# 09.04.2019). "granted = 0 patents" was an artefact of never asking.
#
# So a record is GRANTED when detail.jsf named a grant, FILED when detail.jsf was
# read and named none, and UNKNOWN when detail.jsf was not read. Unknown is a real
# answer and must render as one; it is not filed and it is not zero.
ST_GRANTED, ST_FILED, ST_UNKNOWN = "granted", "filed", "unknown"
DETAIL_URL = "https://patentscope.wipo.int/search/en/detail.jsf?docId=%s"


def status_of(detail):
    """-> (status, granted_date, grant_no, kind). detail is parse_detail's dict."""
    if not detail:
        return ST_UNKNOWN, None, None, None
    gno = (detail.get("Grant Number") or "").strip() or None
    gdate = iso(detail.get("Grant Date"))
    kind = (detail.get("Publication Kind") or "").strip() or None
    if gno or gdate:
        return ST_GRANTED, gdate, gno, kind
    return ST_FILED, None, None, kind


def record_url(row):
    """The registry record, not a full-text search for a number without a country.

    result.jsf?query=FP:(2010239639) is a SEARCH for a bare number with no country
    prefix and no kind code: of 14 stored links resolved live, 12 did not return the
    record at all. detail.jsf?docId= is the record, and the docId was in the html the
    parser already had in hand.
    """
    did = (row.get("doc_id") or "").strip()
    if did:
        return DETAIL_URL % urllib.parse.quote(did, safe="")
    return None


def gate(rows):
    """-> (kept, refusals). Every check is a shape, never `is not None`."""
    kept, refusals = [], {}

    def refuse(why, r):
        refusals.setdefault(why, []).append(r.get("no") or r.get("applicant"))

    for r in rows:
        if not r.get("comp_id"):
            refuse("owner not on the roster", r)
            continue
        no = (r.get("no") or "").strip()
        if not no or not NUMBER_RX.match(no.replace(" ", "")) or "est" in no.lower():
            refuse("malformed publication number", r)
            continue
        ok, why = relevant(r.get("ipc") or [])
        if not ok:
            refuse(why, r)
            continue
        a = area_of(r["ipc"])
        if not a:
            refuse("classified, but outside the nine areas", r)
            continue
        title = (r.get("title") or "").strip()
        if len(title) < 3:
            refuse("no title", r)
            continue
        if JUNK_RX.search(title):
            # The diagnostic fired, which means the classification gate has a hole.
            refuse("DIAGNOSTIC: junk title passed the code gate", r)
            continue
        d = iso(r.get("pub_date"))
        if not d:
            refuse("no publication date", r)
            continue
        ctry = (r.get("country") or "").strip()
        if len(ctry) != 2:
            refuse("no jurisdiction", r)
            continue
        # `d` IS THE PUBLICATION DATE AND WAS STORED AS THE FILING DATE.
        #
        # The result row prints one date and it is the publication date. It went into
        # `filed`, which the UI renders as "Filed <date>", overstating the age of the
        # invention by as much as two and a half years -- the Poongsan detonator was
        # filed 05.10.2018 and published 09.03.2020. The two are now separate fields
        # and `filed` is filled only by the registry's own "Application Date".
        detail = r.get("detail") or {}
        status, gdate, gno, kind = status_of(detail)
        filed = iso(detail.get("Application Date"))
        kept.append({
            "no": no, "title": title, "assignee": r["applicant"],
            "comp_id": r["comp_id"],
            "status": status, "filed": filed, "granted": gdate,
            "published": d, "grant_no": gno, "pub_kind": kind,
            "doc_id": (r.get("doc_id") or "") or None,
            "country": ctry, "ipc": r["ipc"],
            "abstract": (r.get("abstract") or "").strip() or None, "area": a,
            # threat is not measured here and stays null; relev records what the gate
            # actually proved -- the record carries a core defence classification.
            "threat": None, "relev": "CORE",
            "url": record_url(r),
            "p": r.get("matched_alias"),
        })

    # ONE INVENTION IS ONE FILING.
    #
    # A single invention is published in several offices, and PATENTSCOPE returns each
    # publication as its own row -- the Poongsan detonator-assembly system came back as
    # a PH application, a PH publication, an IL grant, an EP grant and a US application,
    # five rows for one thing. Left alone the tab reads "Poongsan: 210 patents" when the
    # honest number is a fraction of that, which is the patent form of counting two
    # pages of one outlet as two witnesses.
    #
    # Without a family identifier (PATENTSCOPE does not print one on the result row)
    # the test is the same owner and the same folded title. Publication dates are NOT
    # part of the key: the offices publish years apart -- the Poongsan detonator ran
    # 2018 in the EPO and the USPTO and 2020 in the Philippines -- so bucketing by date
    # splits the family it is meant to join. The span is measured and reported instead,
    # so a title collision across a decade would be visible rather than assumed away.
    #
    # THE KEEPER WAS ALWAYS THE WRONG ONE. The old test for a grant was a kind code on
    # the publication number -- re.search("[AB]\\d?$", no) -- and no number the parser
    # produces carries one: all 1,157 stored numbers have none, so the branch never
    # fired and the keeper was always group[0], the EARLIEST publication, which is
    # systematically the application rather than the grant. Grant status is now a
    # measured field, so the keeper is the row the registry says is granted.
    fam, order = {}, []
    for r in kept:
        key = (r["comp_id"], fold(r["title"]))
        if key not in fam:
            fam[key] = []
            order.append(key)
        fam[key].append(r)
    out = []
    for key in order:
        group = sorted(fam[key], key=lambda x: x["published"] or "")
        keep = group[0]
        for g in group:
            if g["status"] == ST_GRANTED or re.search(r"[AB]\d?$", g["no"]):
                keep = g
                break
        kept_no = keep["no"]          # captured BEFORE the copy: dict(keep) is a new
        keep = dict(keep)             # object, so `is not keep` would count the keeper
        if len(group) > 1:            # itself among the publications it collapsed
            keep["p"] = "%s (1 of %d publications)" % (keep.get("p") or "", len(group))
            refusals.setdefault("same invention, another office", []).extend(
                g["no"] for g in group if g["no"] != kept_no)
        out.append(keep)
    return out, refusals


def regate(rows):
    """Re-check every stored row against the CURRENT allow-list.

    The ledger never shrinks, which is the right rule for a harvest -- and the wrong
    one for a mistake. Two entries in ART were false ownership claims: "Leonardo"
    filed under `idv`, and Huta Stalowa Wola under `paramount-group`. Rows harvested
    before those were removed would otherwise sit in the ledger forever, because a
    union merge has no way to know an old row is now inadmissible.

    So the allow-list is applied again to what is already stored, and a row whose
    assignee no longer resolves -- or resolves to a different company -- is dropped
    rather than kept on the strength of having once been accepted.
    """
    keep, dropped = [], []
    for r in rows:
        cid, _alias = resolve(r.get("assignee") or "")
        if cid and cid == r.get("comp_id"):
            keep.append(r)
        else:
            dropped.append((r.get("assignee"), r.get("comp_id"), cid))
    return keep, dropped


def merge_ledger(new):
    """Union-merge, keyed by number. The ledger never shrinks: a partial run once
    overwrote a full one and cost 10,548 rows."""
    old = []
    if LEDGER.exists():
        try:
            old = json.load(io.open(LEDGER, encoding="utf-8"))
        except Exception:
            old = []
    by = {r["no"]: r for r in old if isinstance(r, dict) and r.get("no")}
    for r in new:
        by[r["no"]] = r
    out = sorted(by.values(), key=lambda r: (r.get("comp_id") or "", r.get("no") or ""))
    if len(out) < len(old):
        raise SystemExit("refusing to shrink the ledger: %d -> %d" % (len(old), len(out)))
    stale = sum(1 for r in out if "published" not in r)
    if stale:
        print("  WARNING: %d of %d ledger rows predate the grant-status fix. Their"
              " `filed` is the PUBLICATION date and their status='filed' was never"
              " measured. Run --repair-ledger, or re-harvest them, before --load."
              % (stale, len(out)))
    json.dump(out, io.open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


# Columns beyond the original seventeen. Each is written only if the database has it,
# so this file runs against a schema that has had the migration and one that has not.
OPTIONAL_COLS = ("comp_id", "published", "grant_no", "pub_kind", "doc_id")


def write_db(rows):
    # A TOTALLY FAILED RUN MUST NOT SPEAK FOR THE CORPUS.
    #
    # This function DELETEs the whole pipeline range before it inserts. write_db([])
    # therefore deletes the entire Patents tab and inserts nothing -- and `kept` is []
    # whenever every query errored, which is one network outage away. The caller's
    # guard for this ran only when `kept` was non-empty, i.e. never in the case it was
    # written for. The refusal belongs here, next to the DELETE.
    if not rows:
        raise SystemExit(
            "refusing to write 0 rows: this would DELETE every pipeline patent and "
            "insert nothing. An empty result is a failed run, not an empty registry.")
    import psycopg2
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT coalesce(max(ord), 0) FROM serving.patent "
                "WHERE origin = 'reference'")
    top = cur.fetchone()[0]
    if top >= PATENT_ORD0:
        raise SystemExit("reference rows reach ord=%d; this writer's range starts at %d"
                         % (top, PATENT_ORD0))
    # THE ATTRIBUTION IS THE ANSWER; DO NOT MAKE THE DASHBOARD GUESS IT AGAIN.
    # Every row here reached this point by resolving its applicant of record against
    # the allow-list above -- Korean, Hebrew and German surfaces included. Dropping
    # comp_id left the frontend re-deriving it by matching Latin word tokens, which
    # loses every Korean applicant and Krauss-Maffei Wegmann.
    #
    # THE PROBE READ THE WRONG RELATION. It asked information_schema about
    # serving_live.patent -- the VIEW -- and then INSERTed into serving.patent, the
    # TABLE. Run only the ALTER half of a migration and the column exists on the table
    # while the probe says it does not, so every comp_id is silently dropped on the
    # way in. What may be written is decided by the table; what the dashboard can read
    # is decided by the view, and they are now reported separately.
    cur.execute("SELECT table_schema, column_name FROM information_schema.columns"
                " WHERE table_name = 'patent' AND table_schema IN"
                " ('serving', 'serving_live') AND column_name = ANY(%s)",
                (list(OPTIONAL_COLS),))
    found = set(cur.fetchall())
    have = [c for c in OPTIONAL_COLS if ("serving", c) in found]
    missing = [c for c in OPTIONAL_COLS if c not in have]
    if missing:
        print("  serving.patent is missing %s; run db/migrations/"
              "2026-09-06_patent_grant_status.sql (and _patent_comp_id.sql) or these"
              " fields are dropped on the way in" % ", ".join(missing))
    blind = [c for c in have if ("serving_live", c) not in found]
    if blind:
        print("  serving.patent HAS %s but the serving_live view does not expose it:"
              " the value will be written and the dashboard will not see it. The view"
              " enumerates its columns; CREATE OR REPLACE VIEW it." % ", ".join(blind))
    cur.execute("DELETE FROM serving.patent WHERE origin = 'pipeline' AND ord >= %s",
                (PATENT_ORD0,))
    base = ["ord", "assignee_ord", '"no"', "title", "assignee", "status", "filed",
            "granted", "country", "ipc", "abstract", "area", "threat", "relev",
            "url", "p"]
    cols = ", ".join(base + list(have) + ["origin"])
    marks = ", ".join(["%s"] * (len(base) + len(have)) + ["'pipeline'"])
    for i, r in enumerate(rows):
        vals = [PATENT_ORD0 + i, i, r["no"], r["title"], r["assignee"], r["status"],
                r["filed"], r["granted"], r["country"], json.dumps(r["ipc"]),
                r["abstract"], r["area"], r["threat"], r["relev"], r["url"], r["p"]]
        vals += [r.get(c) for c in have]
        cur.execute("INSERT INTO serving.patent (%s) VALUES (%s)" % (cols, marks),
                    tuple(vals))
    conn.commit()
    return len(rows)


# --------------------------------------------------------------------------
# MARKUP THE REGISTRY REALLY SERVES.
#
# Both fixtures are cut from live PATENTSCOPE pages for PA:(Poongsan) AND IC:(F42B)
# on 2026-09-06 -- the result list and the detail page for docId=PH290880599 -- with
# the IPC tooltip tables and the unread middle of the row elided and nothing altered.
# A parser test written against invented markup tests the invention.
RESULT_ROW_FIXTURE = u'''\
<span class="results-count">60 results</span>
<td data-mt-ipc="F42B 5/00">
<div class="ps-patent-result--first-row">
<div class="ps-patent-result--title">
<span class="notranslate ps-patent-result--title--record-number">1.</span>\
<a href="detail.jsf;jsessionid=53BEAEEB3DBE20BDD5AE0F91EA55D0E9.wapp2nA?\
docId=PH290880599&amp;_cid=P20-MTQ14K-26087-1" onclick="" target="_self">\
<span class="notranslate ps-patent-result--title--patent-number">1/2018/000299\
</span></a><span class="ps-patent-result--title--title content--text-wrap">\
<span class="trans-section needTranslation-title" lang="en">\
<span class="trans-control"></span>SYSTEM FOR ASSEMBLING DETONATOR OF PROJECTILE\
</span></span>
</div>
<div class="ps-patent-result--title--ctr-pubdate"><span class="notranslate">PH</span>
<span class="notranslate">-</span><span id="resultListForm:resultTable:0:\
resultListTableColumnPubDate" class="notranslate">09.03.2020</span>
</div>
</div>
<span class="ps-field--value ps-patent-result--ipc notranslate">\
<a href="https://www.wipo.int/ipcpub/?symbol=F42B0005000000&amp;menulang=en&amp;\
lang=en" target="_blank">F42B 5/00</a>\
<a href="https://www.wipo.int/ipcpub/?symbol=F42B0033020700&amp;menulang=en&amp;\
lang=en" target="_blank">F42B 33/0207</a></span>
<span class="ps-field ps-field--is-layout--inline ">
<span class="ps-field--label notranslate">
Applicant
</span>
<span class="ps-field--value ps-patent-result--applicant notranslate">\
POONGSAN CORPORATION
</span>
</span>
<div id="resultListForm:resultTable:0:j_idt2422" class="ui-outputpanel ui-widget \
ps-patent-result--abstract"><span class="trans-section needTranslation-biblio" \
lang="en"><span class="trans-control"></span>The present invention relates to a \
system for combining a detonator of a projectile.</span></div>
'''

DETAIL_FIXTURE = u'''\
<div class="ps-field ps-biblio-field ">
<span class="ps-field--label ps-biblio-field--label">\
<span class="trans-nc-detail-label">Application Number</span>
</span>
<span class="ps-field--value ps-biblio-field--value">1/2018/000299
</span>
</div>
<div class="ps-field ps-biblio-field ">
<span class="ps-field--label ps-biblio-field--label">\
<span class="trans-nc-detail-label">Application Date</span>
</span>
<span class="ps-field--value ps-biblio-field--value">05.10.2018
</span>
</div>
<div class="ps-field ps-biblio-field ">
<span class="ps-field--label ps-biblio-field--label">\
<span class="trans-nc-detail-label">Publication Date</span>
</span>
<span class="ps-field--value ps-biblio-field--value">09.03.2020
</span>
</div>
<div class="ps-field ps-biblio-field ">
<span class="ps-field--label ps-biblio-field--label">\
<span class="trans-nc-detail-label">Grant Number</span>
</span>
<span class="ps-field--value ps-biblio-field--value">1/2018/000299
</span>
</div>
<div class="ps-field ps-biblio-field ">
<span class="ps-field--label ps-biblio-field--label">\
<span class="trans-nc-detail-label">Grant Date</span>
</span>
<span class="ps-field--value ps-biblio-field--value">28.04.2023
</span>
</div>
<div class="ps-field ps-biblio-field ">
<span class="ps-field--label ps-biblio-field--label">\
<span class="trans-nc-detail-label">Publication Kind</span>
</span>
<span class="ps-field--value ps-biblio-field--value">B1
</span>
</div>
'''


def demo():
    """Hermetic self-check: the gates, on the failures they exist to stop."""
    f = 0

    def ck(name, ok, d=""):
        nonlocal f
        print("  %-62s %s%s" % (name, "PASS" if ok else "FAIL", "  " + str(d) if d else ""))
        if not ok:
            f += 1

    ck("a subsidiary resolves to its group",
       resolve("Nammo Talley, Inc.")[0] == "nammo")
    ck("so does one in another script's jurisdiction",
       resolve("Nammo Vanäsverken AB")[0] == "nammo")
    ck("a single-token brand does NOT match by containment",
       resolve("Elbit Imaging Ltd")[0] is None, resolve("Elbit Imaging Ltd"))
    ck("nor does a person who shares a brand's name",
       resolve("Rafael Gomez")[0] is None)
    ck("an unrelated group company is not absorbed",
       resolve("Adani Green Energy Limited")[0] is None)
    ck("a one-token brand plus a COUNTRY is that brand's national arm",
       resolve("Nammo Germany GmbH")[0] == "nammo")
    ck("but a one-token brand plus a business line still is not",
       resolve("Elbit Imaging Ltd")[0] is None and
       resolve("Adani Green Energy")[0] is None and
       resolve("Saab Automobile AB")[0] is None)
    ck("an inventor is never an owner",
       resolve("Mark A. Skidmore")[0] is None and resolve("Robert Willhelm")[0] is None)
    ck("a former name resolves to the company that has it now",
       resolve("Hanwha Techwin Co., Ltd.")[0] == "hanwha-aerospace")
    ck("the client group resolves to CLIENT, never to a rival",
       resolve("Bharat Forge Limited")[0] == "CLIENT")
    ck("an unknown applicant is dropped, not guessed",
       resolve("Some Unlisted Kabushiki Kaisha")[0] is None)
    ck("an empty applicant is dropped",
       resolve("")[0] is None)

    ck("a toy gun is vetoed however it is classified",
       relevant(["F41B 11/00", "F41A 9/00"])[0] is False)
    ck("a target is vetoed", relevant(["F41J 5/00"])[0] is False)
    ck("civil blasting is vetoed", relevant(["F42D 1/00"])[0] is False)
    ck("mining emulsion alone is not defence",
       relevant(["C06B 47/14"])[0] is False)
    ck("an oil-and-gas fluid end never had a class to pass",
       relevant(["F04B 53/16"])[0] is False)
    ck("a gun breech is in scope", relevant(["F41A 9/49"])[0] is True)
    ck("a fuze is in scope", relevant(["F42C 11/00"])[0] is True)

    ck("155 mm shell body -> Small arms & ammunition",
       area_of(["F42B 12/20", "B21K 21/06"]) == A_SMALL)
    ck("a gun autoloader -> Small arms & ammunition",
       area_of(["F41A 9/49"]) == A_SMALL)
    ck("an armed UAV -> Loitering munitions",
       area_of(["B64U 10/00", "F42B 12/00"]) == A_LOITER)
    ck("an unarmed UAV -> UAV / ISR platforms",
       area_of(["B64U 10/16"]) == A_UAV)
    ck("a missile seeker -> Missiles & seekers",
       area_of(["F41G 7/22"]) == A_MISSILE)
    ck("an MBRL launcher -> Rocket artillery (MBRL)",
       area_of(["F41F 3/04"]) == A_MBRL)
    ck("armour plate -> Armour & protected mobility",
       area_of(["F41H 5/04"]) == A_ARMOUR)
    ck("a propellant composition -> Energetics & propellants",
       area_of(["C06B 25/34"]) == A_ENERGET)
    ck("every area returned is one of the client's nine",
       all(area_of(c) in AREAS or area_of(c) is None
           for c in ([["F41A 9/49"], ["C06B 25/34"], ["B64U 10/16"], ["F41H 5/04"]])))
    ck("a class outside the vocabulary returns no area",
       area_of(["H04N 5/33"]) is None)

    # THE FIXTURES ARE SHAPES THE PARSER PRODUCES.
    #
    # These rows used to carry "US9182199B2" -- a kind-coded number that no result row
    # PATENTSCOPE serves ever contains: all 1,157 harvested numbers are bare. So the
    # grant-preference branch below was being exercised on a shape that cannot occur,
    # and the branch that actually ran in production (there is no kind code, so keep
    # the earliest) was never tested at all. Every number here is copied from a real
    # result page, and grant status now arrives where it really arrives: from detail.
    kept, ref = gate([
        {"comp_id": "nammo", "no": "IN-2024-EST01", "ipc": ["F42B 12/00"],
         "title": "Invented", "pub_date": "01.01.2024", "country": "IN",
         "applicant": "Nammo", "doc_id": "IN000000001"},
        {"comp_id": None, "no": "20180364015", "ipc": ["F42B 12/00"],
         "title": "Real but unowned", "pub_date": "20.12.2018", "country": "US",
         "applicant": "Someone Else", "doc_id": "US235210071"},
        {"comp_id": "nammo", "no": "2010239639", "ipc": ["F42B 12/20"],
         "title": "Mine defeat system", "pub_date": "08.09.2011", "country": "AU",
         "applicant": "Nammo Talley, Inc.", "matched_alias": "Nammo Talley",
         "doc_id": "AU215066611",
         "detail": {"Application Date": "05.10.2010", "Publication Kind": "A1"}},
    ])
    ck("an invented identifier is refused", len(kept) == 1, sorted(ref))
    ck("an unattributable record is refused",
       "owner not on the roster" in ref)
    ck("the surviving row carries a real area",
       kept and kept[0]["area"] == A_SMALL)
    ck("the surviving row's url is the RECORD, not a full-text search for a number",
       kept and kept[0]["url"] == DETAIL_URL % "AU215066611", kept and kept[0]["url"])
    ck("the publication date is stored as the publication date",
       kept and kept[0]["published"] == "2011-09-08")
    ck("`filed` is the registry's Application Date, not the publication date",
       kept and kept[0]["filed"] == "2010-10-05", kept and kept[0]["filed"])
    ck("a record the registry named no grant for is `filed`, and granted stays empty",
       kept and kept[0]["status"] == ST_FILED and kept[0]["granted"] is None)

    # THE HONEST UNKNOWN. A record whose detail page was never read has no filing date
    # and no grant status, and must not be given the old defaults instead.
    k3, _ = gate([
        {"comp_id": "poongsan", "no": "1020180041275", "ipc": ["F42B 5/00"],
         "title": "Unasked", "pub_date": "17.04.2018", "country": "KR",
         "applicant": "POONGSAN CORPORATION", "doc_id": "KR217798612"}])
    ck("a record never asked about is `unknown`, never `filed`",
       k3 and k3[0]["status"] == ST_UNKNOWN, k3 and k3[0]["status"])
    ck("and it carries NO filing date rather than a borrowed one",
       k3 and k3[0]["filed"] is None and k3[0]["published"] == "2018-04-17")
    ck("status_of distinguishes granted, filed and unknown",
       status_of({"Grant Number": "10254091", "Grant Date": "09.04.2019",
                  "Publication Kind": "B2"})[0] == ST_GRANTED and
       status_of({"Publication Kind": "A1"})[0] == ST_FILED and
       status_of({})[0] == ST_UNKNOWN)
    ck("a granted record carries the grant DATE, not a bare flag",
       status_of({"Grant Number": "10254091",
                  "Grant Date": "09.04.2019"})[1] == "2019-04-09")

    ck("a cross-script applicant the registry itself returned resolves",
       resolve("주식회사 풍산")[0] == "poongsan")
    ck("an unlisted non-Latin applicant is still dropped",
       resolve("주식회사 삼성전자")[0] is None)

    # ATTRIBUTION: the exact applicant strings PATENTSCOPE returned and the harvest
    # dropped. Each one is a line of pipeline/fetch_patents_unresolved.json.
    ck("an alias is not itself stripped down to a weaker alias",
       resolve("DIEHL DEFENCE GMBH & CO KG")[0] == "rheinmetall",
       resolve("DIEHL DEFENCE GMBH & CO KG"))
    ck("'&' does not break the alias into two non-adjacent halves",
       resolve("BAE Systems Land & Armaments L.P.")[0] == "bae-systems")
    ck("an initialism leftover is noise, not a business line",
       resolve("ISRAEL WEAPON INDUSTRIES (I.W.I.) LTD.")[0] == "iwi")
    ck("a 30-character truncated applicant still resolves",
       resolve("KRAUSS MAFFEI WEGMANN GMBH & C")[0] == "knds" and
       resolve("SAAB BOFORS DYNAMICS SWITZERLA")[0] == "saab")
    ck("but truncation does not become a licence to guess",
       resolve("KRAUSS MAFFEI WEGMANN GMBH & CATERPILLAR")[0] is None and
       resolve("HUTA STALOWA WOLA SPOLKA AKCYJNA")[0] is None)
    ck("a spelled-out legal form is still a legal form",
       resolve("SAAB DYNAMICS AKTIEBOLAG")[0] == "saab")
    ck("a business line is still not the parent",
       resolve("General Dynamics , Pomona Division")[0] is None and
       resolve("ELBIT SYSTEMS C4I AND CYBER LTD.")[0] is None)
    ck("a state institute is not the group it is named after",
       resolve("NO.213 INSTITUTE OF CHINA NORTH INDUSTRIES GROUP CORPORATION")[0]
       is None)

    # PARSING, on markup lifted from a live result page and a live detail page.
    got = parse_results(RESULT_ROW_FIXTURE)
    ck("the parser reads one row out of a result page", len(got) == 1, len(got))
    ck("and takes the docId the row has always carried",
       got and got[0]["doc_id"] == "PH290880599", got and got[0].get("doc_id"))
    ck("and the abstract it used to throw away",
       got and got[0]["abstract"].startswith("The present invention relates"),
       got and (got[0]["abstract"] or "")[:30])
    ck("and the number, applicant, jurisdiction and date",
       got and got[0]["no"] == "1/2018/000299" and got[0]["country"] == "PH"
       and got[0]["pub_date"] == "09.03.2020"
       and got[0]["applicant"] == "POONGSAN CORPORATION", got and got[0])
    ck("the registry's own result total is read, so truncation is visible",
       parse_total(RESULT_ROW_FIXTURE) == 60, parse_total(RESULT_ROW_FIXTURE))
    ck("a six-digit IPC subgroup is not cut down to a different real subgroup",
       ipc_symbol("F42B0001032000") == "F42B 1/032" and
       ipc_symbol("F42B0033020700") == "F42B 33/0207" and
       ipc_symbol("F42B0005000000") == "F42B 5/00" and
       ipc_symbol("F41A0009100000") == "F41A 9/10", ipc_symbol("F42B0001032000"))

    d = parse_detail(DETAIL_FIXTURE)
    ck("the detail page yields the four fields the result row never prints",
       d.get("Application Date") == "05.10.2018" and
       d.get("Grant Number") == "1/2018/000299" and
       d.get("Grant Date") == "28.04.2023" and
       d.get("Publication Kind") == "B1", d)
    ck("the reload shell is not mistaken for a record",
       parse_detail("<html><script>setTimeout(function(){location.reload();}, 0);"
                    "</script></html>") == {})
    ck("and an empty detail is `unknown`, which is the point of having the state",
       status_of(parse_detail(""))[0] == ST_UNKNOWN)

    many = [{"comp_id": "poongsan", "no": n, "ipc": ["F42B 5/00"],
             "title": "System for assembling detonator of projectile",
             "pub_date": d, "country": c, "applicant": "POONGSAN CORPORATION",
             "doc_id": "X" + n.replace("/", ""), "detail": det}
            for n, d, c, det in [
                ("1/2018/000299", "09.03.2020", "PH", None),
                ("12018000299", "09.03.2020", "PH", None),
                ("3312545", "25.04.2018", "EP", None),
                ("20180364015", "20.12.2018", "US",
                 {"Grant Number": "10254091", "Grant Date": "09.04.2019",
                  "Publication Kind": "B2", "Application Date": "21.08.2018"})]]
    k2, r2 = gate(many)
    ck("one invention published in four offices stores once", len(k2) == 1, len(k2))
    ck("the collapsed publications are counted, not silently dropped",
       "same invention, another office" in r2 and len(r2["same invention, another office"]) == 3)
    ck("the surviving row says how many publications it stands for",
       k2 and "1 of 4 publications" in (k2[0]["p"] or ""), k2 and k2[0]["p"])
    ck("the keeper is the GRANT, not the earliest publication",
       k2 and k2[0]["no"] == "20180364015" and k2[0]["status"] == ST_GRANTED,
       k2 and (k2[0]["no"], k2[0]["status"]))

    # A LEDGER WRITTEN BEFORE ANY OF THIS MUST STOP ASSERTING WHAT IT NEVER MEASURED.
    old = [{"no": "2010239639", "filed": "2011-09-08", "status": "filed",
            "granted": None, "url": "https://patentscope.wipo.int/search/en/"
                                    "result.jsf?query=FP%3A%282010239639%29"}]
    fixed, changed = repair_ledger(old)
    ck("an old row's publication date moves to `published` and is not lost",
       changed == 1 and fixed[0]["published"] == "2011-09-08")
    ck("its unmeasured `filed` and `status` become empty and unknown",
       fixed[0]["filed"] is None and fixed[0]["status"] == ST_UNKNOWN)
    ck("its FP:() search link, which mostly does not resolve, is dropped",
       fixed[0]["url"] is None)
    ck("repairing an already-repaired ledger changes nothing",
       repair_ledger(fixed)[1] == 0)

    print("\n%s" % ("all checks passed" if not f else "%d FAILED" % f))
    return 1 if f else 0


def repair_ledger(rows):
    """-> (rows, changed). Undo the two false constants on rows harvested before the
    registry was ever asked about them.

    Every row in a ledger written by the old gate says filed=<the PUBLICATION date>
    and status="filed", and neither was measured. The publication date is not lost --
    it moves to `published`, where it was always true -- and `filed` and `status`
    become empty and "unknown", which is what they actually are. The url is dropped
    where it is the old FP:(number) full-text search, because that link mostly does
    not resolve to the record and there is no docId on an old row to replace it with.

    This does not invent anything and does not guess. It is the only way a row
    harvested before the fix can stop asserting something the registry never said.
    """
    changed = 0
    out = []
    for r in rows:
        r = dict(r)
        if "published" not in r:
            r["published"] = r.get("filed")
            r["filed"] = None
            r["status"] = ST_UNKNOWN
            r["granted"] = None
            r.setdefault("grant_no", None)
            r.setdefault("pub_kind", None)
            r.setdefault("doc_id", None)
            if "result.jsf?query=FP" in (r.get("url") or ""):
                r["url"] = None
            changed += 1
        out.append(r)
    return out, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated comp_id filter")
    # A harvest of 82 applicant names takes the better part of an hour at a polite
    # pause. --load publishes the ledger a completed harvest already wrote, so a
    # deploy never has to re-query the registry to put the same rows on the screen.
    ap.add_argument("--load", action="store_true",
                    help="write the existing ledger to serving.patent, no network")
    ap.add_argument("--pause", type=float, default=3.0)
    # PAGING CHANGES HARVEST VOLUME BY A LARGE MULTIPLE, so it is opt-in and capped.
    # One query, PA:(Poongsan) AND IC:(F42B), is 60 records against the 10 a single
    # page returns; the whole grid is 82 names x 9 blocks.
    ap.add_argument("--pages", type=int, default=1,
                    help="result pages per query (default 1 = the old behaviour; "
                         "the registry's own total is reported either way)")
    ap.add_argument("--no-detail", dest="detail", action="store_false",
                    help="skip detail.jsf; every record then stores status=unknown "
                         "with no filing date, which is honest but much less useful")
    ap.add_argument("--repair-ledger", action="store_true",
                    help="report what repair_ledger() would change in the ledger")
    ap.add_argument("--write", action="store_true",
                    help="with --repair-ledger, actually rewrite the ledger file")
    a = ap.parse_args()
    if a.demo:
        return demo()
    if a.repair_ledger:
        rows = json.load(io.open(LEDGER, encoding="utf-8"))
        fixed, changed = repair_ledger(rows)
        print("%d of %d ledger rows were written by the old gate" % (changed, len(rows)))
        print("  filed  -> published, and filed becomes empty (it was never measured)")
        print("  status -> %r (it was the constant %r)" % (ST_UNKNOWN, ST_FILED))
        print("  url    -> empty where it is the FP:() search that does not resolve")
        if not a.write:
            print("\nnothing written. Re-run with --repair-ledger --write to apply.")
            print("NOTE: after applying, --load will publish empty Filed dates and")
            print("status='unknown' for every un-re-harvested row. The frontend must")
            print("be able to render that before this reaches the tab.")
            return 0
        json.dump(fixed, io.open(LEDGER, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\nrewrote %s" % LEDGER.name)
        return 0
    if a.load:
        rows = json.load(io.open(LEDGER, encoding="utf-8"))
        if not rows:
            raise SystemExit("the ledger is empty; refusing to publish it")
        stale = sum(1 for r in rows if "published" not in r)
        if stale:
            print("  WARNING: %d of %d rows predate the grant-status fix: their"
                  " `filed` is the publication date and their status='filed' was a"
                  " constant, not a measurement. --repair-ledger reports the fix."
                  % (stale, len(rows)))
        # THE ALLOW-LIST IS APPLIED AGAIN ON THE WAY OUT, not only on the way in.
        # A row harvested under an ART entry that has since been found wrong is still
        # in the ledger -- the union merge has no way to know it is now inadmissible.
        # 11 Leonardo S.p.A. patents were stored as IDV's before that entry was
        # removed, and this is what takes them off the tab.
        rows, stale = regate(rows)
        if stale:
            print("dropped %d row(s) the allow-list no longer admits" % len(stale))
            json.dump(rows, io.open(LEDGER, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        n = write_db(rows)
        print("wrote %d rows from the ledger to serving.patent (%d companies)"
              % (n, len(set(r.get("comp_id") for r in rows))))
        return 0

    want = set(x.strip() for x in a.only.split(",") if x.strip())
    companies = [(alias, cid) for alias, cid, kind, _ in ART
                 if kind in ("self", "subsidiary", "former_name", "legal_variant", "jv")
                 and (not want or cid in want)]
    print("querying %d applicant names x %d classification blocks, %d page(s) each"
          % (len(companies), len(BLOCKS), a.pages))
    rows, unresolved, stats = harvest(companies, pause=a.pause, max_pages=a.pages,
                                      detail=a.detail)
    print("\n%d attributed records" % len(rows))

    # A RUN THAT FAILED IS NOT A RUN THAT FOUND NOTHING.
    #
    # harvest() swallows a failed query so one dead host does not end the harvest,
    # which means a total outage looked exactly like an empty registry -- and the
    # empty result then went on to DELETE the tab. Say so, and stop.
    print("queries: %d issued, %d ok, %d failed" %
          (stats["queries"], stats["ok"], stats["failed"]))
    if stats["ok"] == 0:
        raise SystemExit("every query failed; this run knows nothing about the "
                         "registry and must not be allowed to speak for it")
    if stats["failed"]:
        print("   %d queries errored; their companies are UNDER-counted in this run"
              % stats["failed"])
    # THE REGISTRY'S OWN TOTAL vs WHAT WE READ. A per-rival count on the tab is a
    # count of what this grid sampled, not of the register.
    print("registry reported %d matching records across the ok queries; %d rows read"
          % (stats["seen_total"], stats["read"]))
    if stats["truncated"]:
        print("   %d of %d queries were TRUNCATED by --pages %d. Per-company patent"
              " counts on the tab are a floor, not a total."
              % (stats["truncated"], stats["ok"], a.pages))
    if a.detail:
        print("detail.jsf: %d records answered, %d did not (those store status=%r)"
              % (stats["detail_ok"], stats["detail_missing"], ST_UNKNOWN))

    kept, refusals = gate(rows)
    print("%d stored, %d refused" % (len(kept), sum(len(v) for v in refusals.values())))
    for why, xs in sorted(refusals.items(), key=lambda kv: -len(kv[1])):
        print("   %4d  %s" % (len(xs), why))
    if not refusals:
        print("   WARNING: nothing was refused. A gate that never refuses is not running.")

    json.dump(sorted(unresolved.values(), key=lambda u: -u["n"]),
              io.open(PROPOSALS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n%d unresolved applicants -> %s" % (len(unresolved), PROPOSALS.name))

    # WHAT GOES TO THE DASHBOARD IS THE LEDGER, NOT THIS RUN.
    #
    # write_db DELETEs the whole pipeline range before inserting, so applying this
    # run's `kept` would delete every company the run did not query. `--only nammo`
    # with --apply would have left the tab holding nammo alone. This is the same
    # fault that once took a harvest from 10,548 rows to 0: a partial run allowed
    # to speak for the whole corpus.
    ledger = kept
    if kept:
        ledger = merge_ledger(kept)
        ledger, stale = regate(ledger)
        if stale:
            print("\n  %d stored row(s) no longer pass the allow-list:" % len(stale))
            seen = set()
            for who, was, now in stale:
                k = (who, was)
                if k in seen:
                    continue
                seen.add(k)
                print("    %-46s was %-18s now %s" % ((who or "")[:46], was, now))
            json.dump(ledger, io.open(LEDGER, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        print("ledger: %s (%d rows, %d companies)"
              % (LEDGER.name, len(ledger),
                 len(set(r.get("comp_id") for r in ledger))))
        st = collections.Counter(r.get("status") for r in ledger)
        print("   status: %s" % ", ".join("%s=%d" % kv for kv in st.most_common()))
    if a.apply:
        if not kept:
            raise SystemExit("this run stored 0 records; refusing to --apply")
        n = write_db(ledger)
        print("wrote %d rows to serving.patent (ord >= %d)" % (n, PATENT_ORD0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
