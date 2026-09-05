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
}
_COMBINING = dict.fromkeys(
    i for i in range(sys.maxunicode) if unicodedata.combining(chr(i)))


def fold(s):
    """Comparable form of an applicant or alias. Script is preserved."""
    s = unicodedata.normalize("NFD", (s or "").strip())
    s = s.translate(_COMBINING)
    s = unicodedata.normalize("NFC", s).casefold()
    s = s.replace("&amp;", " and ").replace("&", " and ")
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    toks = [t for t in s.split() if t]
    while toks and toks[-1] in _SUFFIX:
        toks.pop()
    return " ".join(toks)


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
    ("Patria", "patria", "self", ""),
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
_BY_FOLD = {}
for _alias, _cid, _kind, _why in ART:
    _BY_FOLD.setdefault(fold(_alias), (_cid, _alias, _kind))


def resolve(applicant):
    """-> (comp_id, matched_alias) or (None, None). Allow-list only, no guessing."""
    f = fold(applicant)
    if not f:
        return None, None
    hit = _BY_FOLD.get(f)
    if hit:
        return hit[0], hit[1]
    # Containment is permitted only for a multi-token alias, only on whole word
    # boundaries, and only when what is left over is legal-form or geographic noise.
    # "General Dynamics Ordnance and Tactical Systems" leaves "ordnance and tactical",
    # which is a business line, not noise -- so it needs the explicit row it has.
    ftoks = f.split()
    for af, (cid, alias, _k) in _BY_FOLD.items():
        atoks = af.split()
        # A one-token brand may carry a COUNTRY and nothing else: "Nammo Germany GmbH"
        # is Nammo's German arm, and refusing it lost a real record to the proposal
        # file. The remainder test below still does the work -- "Elbit Imaging" leaves
        # "imaging", "Adani Green Energy" leaves "green energy", and neither is a place,
        # so both stay refused. A brand plus a place is the same brand; a brand plus a
        # business line is a different company until someone says otherwise.
        if len(atoks) == 1 and not all(t in _GEO for t in ftoks if t not in atoks):
            continue
        if len(atoks) > len(ftoks):
            continue
        for i in range(len(ftoks) - len(atoks) + 1):
            if ftoks[i:i + len(atoks)] == atoks:
                rest = ftoks[:i] + ftoks[i + len(atoks):]
                if all(t in _GEO or t in _SUFFIX for t in rest):
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
}


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


def _text(s):
    return re.sub(r"\s+", " ", TAG_RX.sub(" ", s or "")).strip()


def parse_results(html):
    """-> [record]. Every field comes off the result row the registry rendered."""
    out = []
    for ipc_attr, blob in ROW_RX.findall(html):
        num = NUM_RX.search(blob)
        app = APP_RX.search(blob)
        ctr = CTR_RX.search(blob)
        ttl = TITLE_RX.search(blob)
        codes = [ipc_attr] if ipc_attr else []
        for sym in IPCLINK_RX.findall(blob):
            # F42B0005000000 -> F42B 5/00
            codes.append("%s %d/%02d" % (sym[:4], int(sym[4:8]), int(sym[8:10])))
        out.append({
            "no": _text(num.group(1)) if num else "",
            "title": _text(ttl.group(1)) if ttl else "",
            "applicant": _text(app.group(1)) if app else "",
            "country": ctr.group(1) if ctr else "",
            "pub_date": ctr.group(2) if ctr else "",
            "ipc": sorted(set(c for c in codes if ipc_parts(c)[0])),
        })
    return out


def fetch(query, timeout=60):
    url = BASE + urllib.parse.quote(query, safe="")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# One query per (company, classification block). Ten rows come back per query without
# paging, so this spreads the harvest across the areas instead of taking the first ten
# of one huge result set -- which on Rheinmetall would be ten fuze patents and nothing
# else.
BLOCKS = ["F41A", "F41C", "F41F", "F41G", "F41H", "F42B", "F42C", "C06B", "B64U"]


def iso(d):
    """PATENTSCOPE prints 09.03.2020."""
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", (d or "").strip())
    return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1)) if m else None


def harvest(companies, pause=3.0, log=print):
    seen, rows, unresolved = set(), [], {}
    for alias, cid in companies:
        for blk in BLOCKS:
            q = "PA:(%s) AND IC:(%s)" % (alias, blk)
            try:
                html = fetch(q)
            except Exception as e:
                log("   ! %-34s %-6s %s" % (alias[:33], blk, str(e)[:44]))
                time.sleep(pause * 2)
                continue
            got = parse_results(html)
            kept = 0
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
                rows.append(dict(r, comp_id=who, matched_alias=matched, query=q))
                kept += 1
            log("   %-34s %-6s %2d rows, %2d attributed" % (alias[:33], blk, len(got), kept))
            time.sleep(pause)
    return rows, unresolved


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
# Jurisdiction-shaped publication numbers. A record whose number does not match its
# own jurisdiction's grammar is refused: an invented identifier is exactly what the
# archived 26 rows carried (22 of them, "IN-2024-EST01 (est)"), and it is the one
# thing that must never render as a patent record.
NUMBER_RX = re.compile(r"^(?:[A-Z]{2})?[\d][\dA-Z/\-.]{3,24}$")


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
        kept.append({
            "no": no, "title": title, "assignee": r["applicant"],
            "comp_id": r["comp_id"], "status": "filed", "filed": d, "granted": None,
            "country": ctry, "ipc": r["ipc"], "abstract": None, "area": a,
            "threat": None, "relev": "CORE",
            "url": "https://patentscope.wipo.int/search/en/result.jsf?query="
                   + urllib.parse.quote("FP:(%s)" % no, safe=""),
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
    # The keeper is the one whose number looks like a grant, else the earliest, and the
    # count of collapsed publications is recorded on the row rather than discarded.
    fam, order = {}, []
    for r in kept:
        key = (r["comp_id"], fold(r["title"]))
        if key not in fam:
            fam[key] = []
            order.append(key)
        fam[key].append(r)
    out = []
    for key in order:
        group = sorted(fam[key], key=lambda x: x["filed"] or "")
        keep = group[0]
        for g in group:
            if re.search(r"[AB]\d?$", g["no"]):
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
    json.dump(out, io.open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def write_db(rows):
    import psycopg2
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT coalesce(max(ord), 0) FROM serving.patent "
                "WHERE origin = 'reference'")
    top = cur.fetchone()[0]
    if top >= PATENT_ORD0:
        raise SystemExit("reference rows reach ord=%d; this writer's range starts at %d"
                         % (top, PATENT_ORD0))
    cur.execute("DELETE FROM serving.patent WHERE origin = 'pipeline' AND ord >= %s",
                (PATENT_ORD0,))
    for i, r in enumerate(rows):
        cur.execute(
            "INSERT INTO serving.patent (ord, assignee_ord, \"no\", title, assignee,"
            " status, filed, granted, country, ipc, abstract, area, threat, relev,"
            " url, p, origin) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "'pipeline')",
            (PATENT_ORD0 + i, i, r["no"], r["title"], r["assignee"], r["status"],
             r["filed"], r["granted"], r["country"], json.dumps(r["ipc"]),
             r["abstract"], r["area"], r["threat"], r["relev"], r["url"], r["p"]))
    conn.commit()
    return len(rows)


# --------------------------------------------------------------------------
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

    kept, ref = gate([
        {"comp_id": "nammo", "no": "IN-2024-EST01", "ipc": ["F42B 12/00"],
         "title": "Invented", "pub_date": "01.01.2024", "country": "IN",
         "applicant": "Nammo"},
        {"comp_id": None, "no": "US9182199B2", "ipc": ["F42B 12/00"],
         "title": "Real but unowned", "pub_date": "10.11.2015", "country": "US",
         "applicant": "Someone Else"},
        {"comp_id": "nammo", "no": "US9182199B2", "ipc": ["F42B 12/20"],
         "title": "Mine defeat system", "pub_date": "10.11.2015", "country": "US",
         "applicant": "Nammo Talley, Inc.", "matched_alias": "Nammo Talley"},
    ])
    ck("an invented identifier is refused", len(kept) == 1, sorted(ref))
    ck("an unattributable record is refused",
       "owner not on the roster" in ref)
    ck("the surviving row carries a real area",
       kept and kept[0]["area"] == A_SMALL)
    ck("the surviving row's url points at the record, not a bare search",
       kept and "US9182199B2" in urllib.parse.unquote(kept[0]["url"]))

    ck("a cross-script applicant the registry itself returned resolves",
       resolve("주식회사 풍산")[0] == "poongsan")
    ck("an unlisted non-Latin applicant is still dropped",
       resolve("주식회사 삼성전자")[0] is None)

    many = [{"comp_id": "poongsan", "no": n, "ipc": ["F42B 5/00"],
             "title": "System for assembling detonator of projectile",
             "pub_date": d, "country": c, "applicant": "POONGSAN CORPORATION"}
            for n, d, c in [("1/2018/000299", "09.03.2020", "PH"),
                            ("12018000299", "09.03.2020", "PH"),
                            ("3312545B1", "25.04.2018", "EP"),
                            ("20180364015", "20.12.2018", "US")]]
    k2, r2 = gate(many)
    ck("one invention published in four offices stores once", len(k2) == 1, len(k2))
    ck("the collapsed publications are counted, not silently dropped",
       "same invention, another office" in r2 and len(r2["same invention, another office"]) == 3)
    ck("the surviving row says how many publications it stands for",
       k2 and "1 of 4 publications" in (k2[0]["p"] or ""), k2 and k2[0]["p"])

    print("\n%s" % ("all checks passed" if not f else "%d FAILED" % f))
    return 1 if f else 0


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
    a = ap.parse_args()
    if a.demo:
        return demo()
    if a.load:
        rows = json.load(io.open(LEDGER, encoding="utf-8"))
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
    print("querying %d applicant names x %d classification blocks"
          % (len(companies), len(BLOCKS)))
    rows, unresolved = harvest(companies, pause=a.pause)
    print("\n%d attributed records" % len(rows))

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
    if a.apply:
        n = write_db(ledger)
        print("wrote %d rows to serving.patent (ord >= %d)" % (n, PATENT_ORD0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
