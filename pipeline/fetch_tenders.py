"""Live-tender feed for the KSSL demo's Tender Pipeline tab.

Pulls OPEN procurement notices from three public procurement APIs (never news articles),
keeps only tenders inside KSSL's product portfolio, and upserts them into
serving.tender with origin='pipeline' (the serving_live.tender view the UI reads).

    python fetch_tenders.py           # fetch + write
    python fetch_tenders.py --dry     # fetch + report, no DB writes
    python fetch_tenders.py --demo    # parser/mapper asserts only, no network, no DB

SOURCES (each optional-graceful — one failing source is counted, not fatal):
  * SAM.gov Get Opportunities v2 (US DoD solicitations). API keys are read at RUNTIME
    from ../../TendPro/.env (SAM_API_KEYS / SAM_API_KEY) and rotated on HTTP 429 the way
    TendPro's pull_sam_us.py does. Keys are never printed or persisted anywhere.
  * TED v3 search API (EU) — CPV division 35 defence families (35300000 weapons/ammo,
    35400000 military vehicles, 35500000 warships, 35600000 military aircraft/UAV),
    English titles preferred.
  * GeM India — bidplus.gem.gov.in search-bids JSON API filtered server-side to
    Ministry of Defence (pull_gem_india.py: public, no login, no captcha).
  * CPPP India — the captcha-free "latest active tenders" pagers on eprocure.gov.in
    (same stateless ?page=N feeds pull_cppp_live.py relies on; the search form is
    captcha'd, these listings are not). Bounded top-up scan.
  * CanadaBuys (Canada) — the daily open-tender-notice CSV. Filtered by BUYER to National
    Defence / Defense nationale (both official languages) rather than by keyword. The feed
    only lists notices still open for bidding, so every kept row is live. Keyless.
  * ProZorro (Ukraine) — the open feed exposes procurementMethodType, and defence procedures
    carry a '.defense' suffix, so defence is filtered BEFORE any detail fetch. Keyless.
    Measured 2026-08-31: currently yields zero, see the note at PROZORRO_PAGES.
  * Find a Tender (UK) — OCDS release packages, no key. UK MOD notices band on the CPV code
    through the same CPV_MAP that TED uses, not on English keywords.

CAPS: --cap / --per-source. The 100/40 defaults were demo caps and SAM and TED were hitting
them exactly, so the pipeline was capped rather than exhausted. --only runs named sources.

KSSL FILTER: word-boundary keyword match (no term under 4 chars) on title+issuer text,
or PSC/CPV code prefix, mapped to exactly ONE of the 9 KSSL_CATS categories from
reference_dataset.json. Unmappable rows are skipped and counted. Recency: posted within
~120 days OR future deadline.

WRITER contract (serving.tender): id is a source-prefixed stable text id
('sam_<noticeId>' / 'ted_<pub>' / 'cppp_<ref>'); absence is NULL, never '';
ON CONFLICT (id) DO UPDATE on the mutable fields; ord renumbered per run over
origin='pipeline' rows by deadline ascending (soonest first, no-deadline last).
Reference rows and every other table are untouched.
"""

import os
import argparse
import csv
import html as _html
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent          # KSSL_Deploy
WORKSPACE = REPO.parent     # mallery
DSN = os.environ.get("KSSL_DSN", "host=127.0.0.1 port=5460 dbname=kssl user=postgres password=kssl")
TENDPRO_ENV = WORKSPACE / "TendPro" / ".env"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")

TOTAL_CAP = 100          # quality over volume, across all sources
PER_SOURCE_CAP = 40
RECENT_DAYS = 120

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- categories

def kssl_cats():
    ref = json.loads((REPO / "reference_dataset.json").read_text(encoding="utf-8"))
    return ref["KSSL_CATS"]


CAT_ARTY = "Artillery"
CAT_AMMO = "Ammunition"
CAT_SA = "Small Arms"
CAT_AV = "Protected & Armoured Vehicles"
CAT_MRO = "Armoured Vehicle MRO"
CAT_NAVY = "Marine / Naval"
CAT_UAV = "UAVs & Drones"
CAT_MSL = "Missiles & Air Defence"
CAT_FORGE = "Precision Components & Forgings"

# Ordered: first matching category wins (one category per tender). Ammunition sits before
# Artillery so "155mm howitzer ammunition" files under Ammunition; Naval before Artillery
# so "naval gun" is Marine / Naval. Every term is >= 4 chars, matched on word boundaries;
# spaces/hyphens in a phrase match any whitespace/hyphen run.
CAT_RULES = [
    (CAT_MSL, ["missile", "missiles", "air defence", "air defense", "surface-to-air",
               "anti-tank guided", "manpads", "guided rocket"]),
    (CAT_UAV, ["drone", "drones", "anti-drone", "counter-uas", "rpas", "unmanned aerial",
               "unmanned aircraft", "unmanned combat", "quadcopter", "loitering munition",
               "remotely piloted aircraft"]),
    (CAT_NAVY, ["naval", "warship", "warships", "frigate", "corvette", "shipborne",
                "torpedo", "torpedoes"]),
    # bare "cartridge" matched heater/printer/filter cartridges on GeM — ammo needs the
    # phrase or a calibre next to it
    (CAT_AMMO, ["ammunition", "munitions", "mortar", "mortars", "grenade", "grenades",
                "projectile", "projectiles", "propellant", "warhead", "warheads",
                "fuze", "fuzes", "cartridge case", "cartridge cases", "ball cartridge",
                "blank cartridge"]),
    (CAT_ARTY, ["artillery", "howitzer", "howitzers", "155mm", "155 mm", "105mm", "105 mm",
                "130mm", "130 mm", "gun system", "field gun", "mounted gun", "towed gun",
                "cannon", "cannons"]),
    (CAT_SA, ["rifle", "rifles", "carbine", "carbines", "pistol", "pistols", "revolver",
              "machine gun", "small arms", "sniper", "firearm", "firearms"]),
    # a bare calibre with no weapon word ("5.56mm ball", "7.62mm links") reads as ammo;
    # ranked BELOW Small Arms so "7.62mm rifle" stays a rifle
    (CAT_AMMO, ["5.56mm", "5.56 mm", "7.62mm", "7.62 mm", "12.7mm", "12.7 mm"]),
    # bare "armoured/armor" matched "5th Armored Brigade Turf Replacement" (a base
    # construction job) — armour needs its noun
    (CAT_AV, ["armoured vehicle", "armoured vehicles", "armored vehicle", "armored vehicles",
              "armoured platform", "armored platform", "armoured personnel", "armored personnel",
              "armoured fighting", "armored fighting", "armoured recovery", "armored recovery",
              "armoured car", "armored car", "armour plate", "armor plate", "armour plates",
              "armor plates", "up-armoured", "up-armored", "battle tank", "combat vehicle",
              "tracked vehicle", "mine protected", "bulletproof"]),
    (CAT_FORGE, ["forging", "forgings", "forged", "precision component",
                 "precision components", "precision machining", "machined component",
                 "machined components", "crankshaft", "crankshafts"]),
]
# A defence word next to a services job is a LOCATION, not a portfolio match:
# "Drone Power Wash Service - VA Medical Center" (UAVs), "Lease of Portable Toilets ...
# US Naval Base", "Custodial Services ... Naval Hospital" and "Academic Instructor and
# Tutor services ... Naval Service Training Command" were all shown with KSSL
# categories (audit H2).
#   HARD  -- can never be a goods buy, veto outright.
#   SOFT  -- veto UNLESS the title also names goods or MRO work, so "M134D Miniguns,
#            ... Spare Part Kits and Installation/Training Services" and "Repair and
#            maintenance services of military vehicles" survive.
SERVICE_HARD = ["custodial", "janitorial", "housekeeping", "toilet", "toilets",
                "latrine", "latrines", "tutor", "tutors", "tutoring", "instructor",
                "instructors", "academic", "tuition", "catering", "landscaping",
                "groundskeeping", "grounds maintenance", "pest control",
                "snow removal", "lawn care", "mowing", "laundry", "dormitory"]
SERVICE_SOFT = ["service", "services", "cleaning", "wash", "washing", "facilities",
                "refuse collection", "waste collection"]
# what a real procurement of goods (or of MRO work) says it is buying
SUBSTANCE = ["supply", "supplies", "delivery", "deliveries", "procurement",
             "purchase", "acquisition", "spare", "spares", "kit", "kits", "part",
             "parts", "round", "rounds", "cartridge", "cartridges", "repair",
             "maintenance", "overhaul", "refurbishment", "modernization",
             "modernisation", "upgrade", "manufacture", "production"]

# Overhaul/repair of armoured vehicles is its own category; checked before the plain
# armoured-vehicle rule.
MRO_WORK = ["overhaul", "repair", "maintenance", "refurbishment", "refurbish", "spares",
            "reset of", "upgrade"]
MRO_SUBJECT = ["armoured vehicle", "armoured vehicles", "armored vehicle", "armored vehicles",
               "armoured personnel", "armored personnel", "armoured fighting", "armored fighting",
               "armoured recovery", "armored recovery", "battle tank", "combat vehicle",
               "tracked vehicle"]


def _rx(term):
    parts = [re.escape(p) for p in re.split(r"[\s-]+", term.strip()) if p]
    return re.compile(r"\b" + r"[\s-]+".join(parts) + r"\b", re.I)


_COMPILED = [(cat, [_rx(t) for t in terms]) for cat, terms in CAT_RULES]
_SVC_HARD = [_rx(t) for t in SERVICE_HARD]
_SVC_SOFT = [_rx(t) for t in SERVICE_SOFT]
_SUBSTANCE = [_rx(t) for t in SUBSTANCE]


def service_veto(text):
    """True when the notice buys a SERVICE that merely happens next to a defence word."""
    if any(r.search(text) for r in _SVC_HARD):
        return True
    if any(r.search(text) for r in _SVC_SOFT):
        return not any(r.search(text) for r in _SUBSTANCE)
    return False
_MRO_WORK = [_rx(t) for t in MRO_WORK]
_MRO_SUBJ = [_rx(t) for t in MRO_SUBJECT]

# SAM.gov PSC (classificationCode) prefixes -> category. Longest prefix wins.
PSC_MAP = [
    ("1005", CAT_SA),        # guns through 30mm
    ("1010", CAT_ARTY), ("1015", CAT_ARTY), ("1020", CAT_ARTY), ("1025", CAT_ARTY),
    ("1055", CAT_ARTY),      # launchers, rocket & pyrotechnic
    ("1550", CAT_UAV),       # unmanned aircraft
    ("2350", CAT_AV),        # combat, assault & tactical vehicles
    ("13", CAT_AMMO),        # 13xx ammunition & explosives
    # 141x-144x are guided missiles and their components/launchers. 1450 (guided
    # missile handling and servicing EQUIPMENT) is deliberately absent: generic shop
    # hardware files there, and "SWITCH, ENET, 8 POR" arrived as a KSSL missile
    # opportunity through it (audit H2).
    ("1410", CAT_MSL), ("1420", CAT_MSL), ("1425", CAT_MSL), ("1427", CAT_MSL),
    ("1430", CAT_MSL), ("1440", CAT_MSL),
]

# CPV prefixes -> category. Longest prefix wins; a prefix mapped to None is a
# DELIBERATE exclusion, not a gap. The 356 family was mapped wholesale to UAVs, which
# filed manned trainers (Hawk Mk51 spares, 3564x), fighter aircraft (3561x) and
# navigation satellites (3563x, "EGNOS-NEXT") as drone opportunities (audit H2).
CPV_MAP = [
    ("347112", CAT_UAV),     # non-piloted aircraft (transport-equipment division)
    ("50630", CAT_MRO),      # repair and maintenance services of military vehicles
    ("35613", CAT_UAV),      # unmanned aerial vehicles
    ("35322", CAT_MSL),      # anti-aircraft
    ("3531", CAT_SA),        # miscellaneous weapons
    ("3532", CAT_SA),        # firearms
    ("3533", CAT_AMMO),      # ammunition
    ("3534", CAT_AMMO),      # parts of firearms and ammunition
    ("3541", CAT_AV),        # armoured combat vehicles
    ("3542", CAT_FORGE),     # parts of military vehicles
    ("3561", None),          # MANNED military aircraft -- no KSSL category
    ("3562", CAT_MSL),       # missiles
    ("3563", None),          # military spacecraft / satellites
    ("3564", None),          # military aerospace parts
    ("353", CAT_AMMO),
    ("354", CAT_AV),
    ("355", CAT_NAVY),       # warships
    ("356", None),           # the family head alone proves nothing
]


def _prefix_map(code, table):
    code = (code or "").strip()
    if not code:
        return None
    for pref, cat in sorted(table, key=lambda x: -len(x[0])):
        if code.startswith(pref):
            return cat
    return None


def map_cat(text, psc=None, cpvs=None):
    """One KSSL category or None (skip). Keywords first, then PSC/CPV code prefixes.
    A services job is vetoed before either: the defence word in it is an address."""
    text = text or ""
    if service_veto(text):
        return None
    if any(r.search(text) for r in _MRO_SUBJ) and any(r.search(text) for r in _MRO_WORK):
        return CAT_MRO
    for cat, rxs in _COMPILED:
        if any(r.search(text) for r in rxs):
            return cat
    if psc:
        cat = _prefix_map(psc, PSC_MAP)
        if cat:
            return cat
    for c in (cpvs or []):
        cat = _prefix_map(str(c), CPV_MAP)
        if cat:
            return cat
    return None


# --------------------------------------------------------------------------- helpers

def nn(s):
    """Text-column discipline: absence is NULL, never ''."""
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s or None


def fmt_deadline(dt):
    """datetime -> the human string the UI's countdown parser reads ('15 Sep 2026')."""
    return f"{dt.day} {dt.strftime('%b %Y')}"


def recent_enough(posted_dt, deadline_dt, today=None):
    today = today or date.today()
    if deadline_dt and deadline_dt.date() >= today:
        return True
    if posted_dt and (today - posted_dt.date()).days <= RECENT_DAYS:
        return True
    return False


def parse_iso_day(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# Where SAM keys come from, in order. TendPro/.env is preferred so the authoring workspace keeps
# using the single copy it already maintains; the in-repo file is the fallback that makes the
# pipeline work for a collaborator who has cloned this branch and nothing else.
SAM_KEY_FILES = [TENDPRO_ENV, HERE / "tender_keys.env"]


def load_sam_keys():
    """SAM keys from the first key file that yields any. Values are never printed or persisted."""
    for path in SAM_KEY_FILES:
        keys = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip().strip('"').strip("'")
        except OSError:
            continue
        raw = keys.get("SAM_API_KEYS") or keys.get("SAM_API_KEY") or ""
        found = [k.strip() for k in raw.split(",") if k.strip()]
        if found:
            return found
    return []


_CT_SEG = re.compile(r"\s+[‒–—\-]\s+")


def clean_title(title, country=None):
    """One readable, consistent tender title from the raw feed text. The portals write
    it three different ways -- TED as 'Country - CPV label - buyer's own ref/foreign
    title', GeM with a '- GEM/2026/B/...' suffix, CanadaBuys with a 'W8472-225864 '
    solicitation prefix -- and some are ALL CAPS. The specific notice number stays in
    the id and the source link; the title is for reading. Never invents words."""
    t = _html.unescape(str(title or "")).strip()
    parts = [p.strip() for p in _CT_SEG.split(t) if p.strip()]
    # TED 'Country - CPV label - ...': the CPV label is the clean English description;
    # the tail is the buyer's internal reference or a foreign-language title -> drop it.
    if country and parts and parts[0].lower() == country.lower():
        parts = parts[1:]
        if len(parts) >= 2:
            parts = parts[:1]
    t = " - ".join(parts) if parts else t
    # leading CanadaBuys solicitation code 'W8472-225864 ' FIRST, so its internal hyphen
    # is never mistaken for a separator by the reference strips below.
    t = re.sub(r"^\s*[A-Z]{1,3}\d{2,}[-–—]\d{3,}\w*\s+", "", t)
    # trailing solicitation / reference codes
    t = re.sub(r"(?i)\s*[-–—]\s*GEM/\S+.*$", "", t)
    t = re.sub(r"(?i)\s*[-–—]\s*DAT\s*\d+.*$", "", t)
    t = re.sub(r"(?i)\s*[-–—]\s*(Marche|Marché)\s+public.*$", "", t)
    t = re.sub(r"(?i)\s*[-–—]\s*N[°º]\s*\S+.*$", "", t)
    # ' - 6003105378-BAAINBw' (space-surrounded dash ONLY -- never a hyphen inside a code)
    t = re.sub(r"\s+[-–—]\s+\d{6,}[-–—\w]*.*$", "", t)
    # ALL-CAPS listing -> Title Case
    letters = [c for c in t if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7:
        t = t.title()
    t = re.sub(r"\s+", " ", t).strip(" -–—·")
    return t[:100] or _html.unescape(str(title or ""))


def make_row(tid, title, issuer, country, cat, url, src_label, status,
             deadline_dt=None, deadline_raw=None, posted_dt=None, value=None, qty=None):
    deadline = fmt_deadline(deadline_dt) if deadline_dt else nn(deadline_raw)
    return {
        "id": tid, "title": clean_title(title, country), "issuer": nn(issuer), "country": nn(country),
        "cat": cat, "value": nn(value), "qty": nn(qty), "deadline": deadline,
        "dl": None, "reqNote": None, "req": [], "matches": [], "lean": None,
        "leanTxt": None, "status": status, "url": nn(url), "urlKind": "tender",
        "srcs": [{"label": src_label, "url": nn(url) or ""}], "stage": None,
        "_deadline_dt": deadline_dt, "_posted_dt": posted_dt,
    }


_TITLE_SEG = re.compile(r"\s+[\u2013\u2014-]\s+")


def norm_title(title):
    """TED titles read 'Country - CPV label - real title'; the first two segments are
    boilerplate, so two notices for one procurement differ only in publication number."""
    parts = [x.strip() for x in _TITLE_SEG.split(str(title or "")) if x.strip()]
    body = " ".join(parts[2:]) if len(parts) >= 3 else " ".join(parts)
    return re.sub(r"[^a-z0-9]+", " ", body.lower()).strip()


def dedupe_rows(rows):
    """One procurement, one row: same buyer + same normalised title. Two TED notices
    for the same Portuguese GNR buy and two for the same Norwegian framework were both
    listed (audit H2). Keeps the first (the caller sorts soonest-deadline first)."""
    out, seen = [], set()
    for r in rows:
        key = (re.sub(r"[^a-z0-9]+", " ", (r.get("issuer") or "").lower()).strip(),
               norm_title(r.get("title")))
        if key[1] and key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


class Tally:
    def __init__(self):
        self.fetched = 0
        self.kept = 0
        self.skipped = {}
        self.error = None

    def skip(self, reason):
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


# --------------------------------------------------------------------------- SAM.gov

SAM_BASE = "https://api.sam.gov/opportunities/v2/search"

# The DoD department filter is not airtight -- notices from civilian parents come back
# in the same pages. Without a defence word of their own they are somebody else's
# facilities work (audit H2).
NON_DEFENCE_PARENTS = [
    "veterans affairs", "commerce", "homeland security", "health and human services",
    "agriculture", "education", "transportation", "interior", "justice",
    "housing and urban development", "social security", "environmental protection",
]
DEFENCE_WORDS = [
    "weapon", "weapons", "ammunition", "ammo", "munition", "munitions", "artillery",
    "howitzer", "missile", "missiles", "armoured", "armored", "armour", "armor",
    "military", "combat", "naval", "warship", "torpedo", "rifle", "rifles", "pistol",
    "firearm", "firearms", "small arms", "drone", "drones", "unmanned", "cartridge",
    "cartridges", "projectile", "grenade", "propellant", "explosive", "mortar",
    "battle tank", "gunnery", "sniper", "carbine", "minigun", "miniguns",
]
_NON_DEF = [_rx(t) for t in NON_DEFENCE_PARENTS]
_DEF_WORDS = [_rx(t) for t in DEFENCE_WORDS]


def non_defence_notice(parent, title):
    """A civilian department's notice, with nothing defence about it."""
    if not any(r.search(parent or "") for r in _NON_DEF):
        return False
    return not any(r.search(title or "") for r in _DEF_WORDS)


def sam_row(o):
    nid = o.get("noticeId")
    title = (o.get("title") or "").strip()
    parent = (o.get("fullParentPathName") or "").split(".")[0].strip()
    issuer = parent.title() or None
    if non_defence_notice(parent, title):
        return None, "non-defence agency"
    cat = map_cat(title, psc=o.get("classificationCode"))
    if not cat:
        return None, "unmappable"
    posted = parse_iso_day(o.get("postedDate"))
    deadline = parse_iso_day(o.get("responseDeadLine"))
    if not recent_enough(posted, deadline):
        return None, "stale"
    status = "open" if str(o.get("active", "")).lower() == "yes" else "closed"
    url = o.get("uiLink") or f"https://sam.gov/opp/{nid}/view"
    return make_row(f"sam_{nid}", title, issuer, "United States", cat, url, "SAM.gov",
                    status, deadline_dt=deadline, posted_dt=posted), None


def fetch_sam(cap, tally, client_factory):
    keys = load_sam_keys()
    if not keys:
        tally.error = ("no SAM keys in any of: "
                       + ", ".join(str(p) for p in SAM_KEY_FILES))
        return []
    print(f"[sam] {len(keys)} API key(s) loaded (values not shown)")
    rows, ki = [], 0
    today = date.today()
    with client_factory(timeout=90) as c:
        # Newest windows first; each 6-day DoD window stays under SAM's 1000-record page.
        for w in range(0, 8):
            if len(rows) >= cap:
                break
            w_to = today - timedelta(days=6 * w)
            w_from = today - timedelta(days=6 * (w + 1) + 1)
            qp = {"api_key": keys[ki], "ptype": "o", "limit": 1000, "offset": 0,
                  "deptname": "DEPT OF DEFENSE",
                  "postedFrom": w_from.strftime("%m/%d/%Y"),
                  "postedTo": w_to.strftime("%m/%d/%Y")}
            for attempt in range(len(keys) + 1):
                r = c.get(SAM_BASE, params=qp)
                if r.status_code == 429 and ki + 1 < len(keys):
                    ki += 1
                    qp["api_key"] = keys[ki]
                    print(f"[sam] key throttled -> rotating to key {ki + 1}/{len(keys)}")
                    continue
                break
            if r.status_code != 200:
                tally.error = f"HTTP {r.status_code}: {r.text[:120]}"
                break
            for o in r.json().get("opportunitiesData", []):
                if len(rows) >= cap:
                    break
                tally.fetched += 1
                row, why = sam_row(o)
                if row is None:
                    tally.skip(why)
                else:
                    rows.append(row)
                    tally.kept += 1
            time.sleep(1.0)
    return rows


# --------------------------------------------------------------------------- TED EU

TED_BASE = "https://api.ted.europa.eu/v3/notices/search"
TED_FIELDS = ["publication-number", "notice-title", "publication-date", "buyer-name",
              "buyer-country", "classification-cpv", "main-classification-proc",
              "deadline-receipt-tender-date-lot", "notice-type", "links"]
ISO3 = {"AUT": "Austria", "BEL": "Belgium", "BGR": "Bulgaria", "HRV": "Croatia",
        "CYP": "Cyprus", "CZE": "Czech Republic", "DNK": "Denmark", "EST": "Estonia",
        "FIN": "Finland", "FRA": "France", "DEU": "Germany", "GRC": "Greece",
        "HUN": "Hungary", "IRL": "Ireland", "ITA": "Italy", "LVA": "Latvia",
        "LTU": "Lithuania", "LUX": "Luxembourg", "MLT": "Malta", "NLD": "Netherlands",
        "POL": "Poland", "PRT": "Portugal", "ROU": "Romania", "SVK": "Slovakia",
        "SVN": "Slovenia", "ESP": "Spain", "SWE": "Sweden", "NOR": "Norway",
        "ISL": "Iceland", "LIE": "Liechtenstein", "CHE": "Switzerland",
        "GBR": "United Kingdom", "UKR": "Ukraine"}


def i18n(v):
    """TED text fields are {'eng': [...]} maps (or lists/strings). Prefer English."""
    if isinstance(v, dict):
        for lang in ("eng", "ENG", "en"):
            if v.get(lang):
                return "; ".join(v[lang]) if isinstance(v[lang], list) else str(v[lang])
        for val in v.values():
            if val:
                return "; ".join(val) if isinstance(val, list) else str(val)
        return ""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return str(v or "")


def link_of(links, pub):
    if isinstance(links, dict):
        for kind in ("html", "pdf", "xml"):
            block = links.get(kind)
            if isinstance(block, dict):
                for u in block.values():
                    if u:
                        return u
    return f"https://ted.europa.eu/en/notice/-/detail/{pub}"


def ted_row(n):
    pub = str(n.get("publication-number") or "")
    title = i18n(n.get("notice-title"))
    cpv = n.get("classification-cpv") or []
    if not isinstance(cpv, list):
        cpv = [cpv]
    main = n.get("main-classification-proc") or []
    if not isinstance(main, list):
        main = [main]
    # Band on the notice's MAIN CPV, never on whichever of its CPVs happens to map
    # first: a Latvian school's sports-goods buy carried a 35x code somewhere in its
    # list and was shown as Ammunition (audit H2). Title keywords still come first
    # inside map_cat -- they read the same notice, not a neighbouring one.
    main_cpv = str((main or cpv or [""])[0])
    cat = map_cat(title, cpvs=[main_cpv])
    if not cat:
        return None, "main CPV outside the KSSL portfolio"
    posted = parse_iso_day(str(n.get("publication-date") or "")[:10])
    deadline = parse_iso_day(i18n(n.get("deadline-receipt-tender-date-lot"))[:10])
    if not recent_enough(posted, deadline):
        return None, "stale"
    ntype = i18n(n.get("notice-type")).lower()
    if ntype.startswith("can") or "award" in ntype:
        status = "awarded"
    elif deadline and deadline.date() < date.today():
        status = "closed"
    else:
        status = "open"
    country = ISO3.get((i18n(n.get("buyer-country")) or "")[:3].upper())
    return make_row(f"ted_{pub}", title, i18n(n.get("buyer-name")), country, cat,
                    link_of(n.get("links"), pub), "TED (EU)", status,
                    deadline_dt=deadline, posted_dt=posted), None


def fetch_ted(cap, tally, client_factory):
    since = (date.today() - timedelta(days=RECENT_DAYS)).strftime("%Y%m%d")
    query = (f"classification-cpv IN (35300000 35400000 35500000 35600000) "
             f"AND publication-date>={since} SORT BY publication-date DESC")
    rows, token = [], None
    with client_factory(timeout=90, headers={"User-Agent": UA}) as c:
        for page in range(8):
            body = {"query": query, "fields": TED_FIELDS, "limit": 250,
                    "scope": "ALL", "paginationMode": "ITERATION"}
            if token:
                body["iterationNextToken"] = token
            r = c.post(TED_BASE, json=body)
            if r.status_code != 200:
                if page == 0 and not token:
                    # fall back to the proven single-division query
                    query = ("classification-cpv IN (35000000) "
                             "SORT BY publication-date DESC")
                    r = c.post(TED_BASE, json={"query": query, "fields": TED_FIELDS,
                                               "limit": 250, "scope": "ALL",
                                               "paginationMode": "ITERATION"})
                if r.status_code != 200:
                    tally.error = f"HTTP {r.status_code}: {r.text[:150]}"
                    break
            d = r.json()
            notices = d.get("notices") or []
            if not notices:
                break
            token = d.get("iterationNextToken")
            for n in notices:
                if len(rows) >= cap:
                    break
                tally.fetched += 1
                row, why = ted_row(n)
                if row is None:
                    tally.skip(why)
                else:
                    rows.append(row)
                    tally.kept += 1
            if len(rows) >= cap or not token:
                break
            time.sleep(0.5)
    return rows


# --------------------------------------------------------------------------- India
# Two proven captcha-free routes (cralwer/scripts + TendPro):
#   * GeM bidplus search-bids JSON API, server-side filtered to Ministry of Defence
#     (pull_gem_india.py: "no login, no captcha — those are only for bidding")
#   * CPPP latest-active pagers on eprocure.gov.in (pull_cppp_live.py), scanned bounded —
#     the newest pages are dominated by coal/construction, so this is a top-up, not the spine.

GEM_BASE = "https://bidplus.gem.gov.in"


def _first(v):
    return v[0] if isinstance(v, list) and v else (v if not isinstance(v, list) else "")


def gem_row(b):
    bid_id = _first(b.get("b_id")) or b.get("id")
    bid_no = _first(b.get("b_bid_number")) or ""
    item = _first(b.get("b_category_name")) or _first(b.get("bd_category_name")) or ""
    dept = _first(b.get("ba_official_details_deptName")) or ""
    cat = map_cat(item)
    if not cat:
        return None, "unmappable"
    start = parse_iso_day(_first(b.get("final_start_date_sort")))
    end = parse_iso_day(_first(b.get("final_end_date_sort")))
    if not recent_enough(start, end):
        return None, "stale"
    qty = _first(b.get("b_total_quantity"))
    qty = f"{qty} units" if qty not in (None, "", 0) else None
    issuer = f"Ministry of Defence — {dept}" if dept else "Ministry of Defence"
    title = f"{item} — {bid_no}" if bid_no else item
    return make_row(f"gem_{bid_id}", title, issuer, "India", cat,
                    f"{GEM_BASE}/showbidDocument/{bid_id}", "GeM (India MoD)", "open",
                    deadline_dt=end, posted_dt=start, qty=qty), None


def gem_csrf(c):
    r = c.get(f"{GEM_BASE}/all-bids")
    m = re.search(r'name="csrf_bd_gem_nk"[^>]*value="([^"]+)"', r.text) \
        or re.search(r'csrf_bd_gem_nk["\']?\s*[:=]\s*["\']([^"\']+)', r.text)
    return m.group(1) if m else None


def fetch_gem(cap, tally, client_factory):
    rows = []
    with client_factory(timeout=60, headers={"User-Agent": UA}, follow_redirects=True) as c:
        tok = gem_csrf(c)
        if not tok:
            tally.error = "no CSRF token on /all-bids — GeM layout changed"
            return rows
        retried = False
        page = 1
        while len(rows) < cap and page <= 40:
            payload = {"searchType": "ministry-search", "ministry": "Ministry of Defence",
                       "buyerState": "", "organization": "", "department": "",
                       "bidEndFromMin": "", "bidEndToMin": "", "page": page}
            try:
                r = c.post(f"{GEM_BASE}/search-bids",
                           data={"payload": json.dumps(payload), "csrf_bd_gem_nk": tok},
                           headers={"Referer": f"{GEM_BASE}/advance-search"})
                if r.status_code in (419, 403) and not retried:
                    tok, retried = gem_csrf(c), True
                    continue
                docs = r.json().get("response", {}).get("response", {}).get("docs", [])
            except Exception as ex:
                if retried:
                    tally.error = f"page {page}: {type(ex).__name__}"
                    break
                tok, retried = gem_csrf(c), True
                time.sleep(2)
                continue
            if not docs:
                break
            for b in docs:
                if len(rows) >= cap:
                    break
                tally.fetched += 1
                row, why = gem_row(b)
                if row is None:
                    tally.skip(why)
                else:
                    rows.append(row)
                    tally.kept += 1
            page += 1
            time.sleep(0.4)
    return rows


CPPP_BASE = "https://eprocure.gov.in/cppp/latestactivetendersnew"
CPPP_FEEDS = [("cpppdata", "CPPP (eprocure.gov.in)"), ("gemdata", "GeM via CPPP")]
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_HREF = re.compile(r'href="([^"]+)"')
_TAG = re.compile(r"<[^>]+>")


def _txt(s):
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub(" ", s))).strip()


def cppp_date(s):
    """'09-Aug-2026 03:46 PM' -> datetime(2026,8,9) (the listing's only date format)."""
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", (s or "").strip())
    if not m:
        return None
    try:
        return datetime.strptime("-".join(m.groups()), "%d-%b-%Y")
    except ValueError:
        return None


def cppp_parse(t):
    """Proven layout-agnostic row parser (from TendPro pull_cppp_live.py): anchor on the
    cell holding the detail link, because the gem feed has one column fewer.

        cppp: [Sl, Published, Closing, Opening, <a>Title</a>/Ref/TenderId, Org, Corrig]
        gem:  [Sl, Published, Closing, <a>GEM/2026/B/nnn</a>/value, Item desc, Org, ...]
    """
    out = []
    for r in _ROW.findall(t):
        cells = _TD.findall(r)
        if len(cells) < 6:
            continue
        li = next((i for i, c in enumerate(cells) if _HREF.search(c)), None)
        if li is None or li < 3:
            continue
        link = _HREF.search(cells[li])
        blob = _txt(cells[li])
        anchor = _txt(cells[li][:cells[li].find("</a>")])
        bits = [b.strip() for b in blob.split("/") if b.strip()]
        gem = li == 3
        out.append({
            "published": cppp_date(_txt(cells[1])),
            "closing": cppp_date(_txt(cells[2])),
            "title": (_txt(cells[4]) if gem else anchor) or blob,
            "ref": anchor if gem else (bits[-1] if bits else ""),
            "org": _txt(cells[5]),
            "url": link.group(1) if link else "",
        })
    return out


def cppp_row(r, label):
    # Map on the TITLE only: org names ("Armoured Vehicles Nigam Ltd", "Munitions India
    # Ltd") would file their floor-tile and canteen tenders under the portfolio.
    cat = map_cat(r["title"])
    if not cat:
        return None, "unmappable"
    if not recent_enough(r["published"], r["closing"]):
        return None, "stale"
    ref = r["ref"] or r["url"]
    tid = "cppp_" + re.sub(r"[^A-Za-z0-9_.-]", "_", ref)[:60]
    return make_row(tid, r["title"], r["org"], "India", cat, r["url"], label, "open",
                    deadline_dt=r["closing"], posted_dt=r["published"]), None


def fetch_cppp(cap, tally, client_factory):
    """Bounded top-up scan: the newest CPPP pages are mostly coal/construction, so this
    walks a fixed window per feed and keeps whatever maps; zero kept is an honest result."""
    rows, seen, errs = [], set(), 0
    with client_factory(timeout=45, follow_redirects=True, verify=False,
                        headers={"User-Agent": UA}) as c:
        for seg, label in CPPP_FEEDS:
            for page in range(1, 31):
                if len(rows) >= cap:
                    break
                parsed = None
                for attempt in range(2):        # transient h2 resets happen; retry once
                    try:
                        parsed = cppp_parse(c.get(f"{CPPP_BASE}/{seg}?page={page}").text)
                        break
                    except Exception as ex:
                        errs += 1
                        tally.error = f"{seg} page {page}: {type(ex).__name__}"
                        time.sleep(1.5)
                if parsed is None:
                    if errs > 6:
                        return rows
                    continue
                if not parsed:
                    break
                for r in parsed:
                    tally.fetched += 1
                    row, why = cppp_row(r, label)
                    if row is None:
                        tally.skip(why)
                    elif row["id"] in seen:
                        tally.skip("duplicate ref")
                    elif len(rows) < cap:
                        seen.add(row["id"])
                        rows.append(row)
                        tally.kept += 1
                time.sleep(0.3)
    return rows


# --------------------------------------------------------------------------- Canada (CanadaBuys)
#
# CanadaBuys has no query API; it publishes ONE daily CSV of tender notices that are still open
# for bidding. That property is why this lane is worth having: every kept row is live and
# biddable, with no recency guessing. Keyless, no login.
#
# Defence is filtered by BUYER, not by keyword: a notice is kept when the contracting entity or
# the end-user entity is National Defence. The portfolio mapper then still has to place it in a
# KSSL category, so "DND buys office chairs" is fetched and then dropped as unmappable.

CANADA_CSV = ("https://canadabuys.canada.ca/opendata/pub/"
              "openTenderNotice-ouvertAvisAppelOffres.csv")
CA_ENTITY = "contractingEntityName-nomEntitContractante-eng"
CA_ENDUSER = "endUserEntitiesName-nomEntitesUtilisateurFinal-eng"
# Both official languages: the same field carries "Department of National Defence" and
# "Ministere de la Defense nationale" depending on the notice.
CA_DEFENCE = re.compile(r"(?i)national\s+defen[cs]e|defen[cs]e\s+nationale|\bDND\b|"
                        r"canadian\s+armed\s+forces|forces\s+armees")


def canada_row(row):
    def g(k):
        return (row.get(k) or "").strip()

    buyer, enduser = g(CA_ENTITY), g(CA_ENDUSER)
    if not CA_DEFENCE.search(buyer + " " + enduser):
        return None, "not a defence buyer"
    title = g("title-titre-eng")
    if not title:
        return None, "no title"
    # Description is included in the mapper's text: CanadaBuys titles are often a bare
    # solicitation number, where the description carries the actual commodity.
    cat = map_cat(title + " " + g("tenderDescription-descriptionAppelOffres-eng"))
    if not cat:
        return None, "unmappable"
    closing = parse_iso_day(g("tenderClosingDate-appelOffresDateCloture"))
    posted = parse_iso_day(g("publicationDate-datePublication"))
    if not recent_enough(posted, closing):
        return None, "stale"
    ref = g("referenceNumber-numeroReference") or g("solicitationNumber-numeroSollicitation")
    if not ref:
        return None, "no reference"
    url = g("noticeURL-URLavis-eng") or f"https://canadabuys.canada.ca/en/tender-opportunities?ref={ref}"
    tid = "ca_" + re.sub(r"[^A-Za-z0-9_.-]", "_", ref)[:60]
    return make_row(tid, title, buyer or enduser, "Canada", cat, url,
                    "CanadaBuys (PSPC)", "open",
                    deadline_dt=closing, posted_dt=posted), None


def fetch_canada(cap, tally, client_factory):
    rows, seen = [], set()
    with client_factory(timeout=90, follow_redirects=True, verify=False,
                        headers={"User-Agent": UA}) as c:
        r = c.get(CANADA_CSV)
        r.raise_for_status()
        # The feed is UTF-8 with a BOM; csv must not inherit it into the first column name.
        text = r.text.lstrip("﻿")
    for rec in csv.DictReader(io.StringIO(text)):
        tally.fetched += 1
        row, why = canada_row(rec)
        if row is None:
            tally.skip(why)
        elif row["id"] in seen:
            tally.skip("duplicate reference")
        elif len(rows) < cap:
            seen.add(row["id"])
            rows.append(row)
            tally.kept += 1
    return rows


# --------------------------------------------------------------------------- Ukraine (ProZorro)
#
# ProZorro marks defence procedures in the procurement method itself: aboveThresholdUA.defense,
# simple.defense and friends all carry a '.defense' suffix. Asking the feed for that one field
# means defence is filtered BEFORE any detail fetch, so this walks thousands of notices while
# hydrating only the few dozen that matter. Keyless.

PROZORRO_FEED = "https://public-api.prozorro.gov.ua/api/2.5/tenders"
# MEASURED 2026-08-31: 4,000 consecutive notices carried ZERO '.defense' procedures - the recent
# feed is aboveThreshold / priceQuotation / reporting / belowThreshold / esco only. Ukraine's
# defence buying is not on the open feed at present. The lane is kept because it costs one page
# to find out and will resume the moment those procedures reappear, but the scan is bounded to
# 1,000 notices rather than 4,000: paying 40 requests a run for a measured zero is waste.
PROZORRO_PAGES = 10


def prozorro_row(t):
    title = (t.get("title") or "").strip()
    if not title:
        return None, "no title"
    buyer = ((t.get("procuringEntity") or {}).get("name") or "").strip()
    cpvs = [((i.get("classification") or {}).get("id") or "")
            for i in (t.get("items") or [])
            if ((i.get("classification") or {}).get("scheme") or "") == "CPV"]
    # Ukrainian titles will not match an English keyword list, so the CPV code is the primary
    # signal here and the title is only a fallback. Without this the whole lane would keep
    # nothing but the occasional English-titled notice - the language-detector failure again.
    cat = map_cat(title + " " + (t.get("description") or ""), cpvs=[c for c in cpvs if c])
    if not cat:
        return None, "unmappable"
    period = t.get("tenderPeriod") or {}
    deadline = parse_iso_day(period.get("endDate"))
    posted = parse_iso_day(period.get("startDate") or t.get("dateModified"))
    if not recent_enough(posted, deadline):
        return None, "stale"
    tid_pub = t.get("tenderID") or t.get("id")
    val = t.get("value") or {}
    amount = val.get("amount")
    return make_row("ua_" + re.sub(r"[^A-Za-z0-9_.-]", "_", str(tid_pub))[:60],
                    title, buyer, "Ukraine", cat,
                    f"https://prozorro.gov.ua/tender/{tid_pub}",
                    "ProZorro (Ukraine)", "open",
                    deadline_dt=deadline, posted_dt=posted,
                    value=(f"{amount:,.0f} {val.get('currency')}"
                           if isinstance(amount, (int, float)) and amount else None)), None


def fetch_prozorro(cap, tally, client_factory):
    rows, seen = [], set()
    url, params = PROZORRO_FEED, {"descending": "1", "limit": "100",
                                  "opt_fields": "procurementMethodType,status"}
    with client_factory(timeout=60, follow_redirects=True, verify=False,
                        headers={"User-Agent": UA}) as c:
        for _ in range(PROZORRO_PAGES):
            if len(rows) >= cap:
                break
            r = c.get(url, params=params)
            if r.status_code != 200:
                tally.error = f"feed HTTP {r.status_code}"
                break
            data = r.json()
            batch = data.get("data") or []
            if not batch:
                break
            for stub in batch:
                tally.fetched += 1
                if ".defense" not in (stub.get("procurementMethodType") or ""):
                    tally.skip("not a defence procedure")
                    continue
                try:
                    dr = c.get(f"{PROZORRO_FEED}/{stub['id']}")
                    if dr.status_code != 200:
                        tally.skip(f"detail HTTP {dr.status_code}")
                        continue
                    row, why = prozorro_row((dr.json() or {}).get("data") or {})
                except Exception as ex:
                    tally.skip(f"detail {type(ex).__name__}")
                    continue
                if row is None:
                    tally.skip(why)
                elif row["id"] in seen:
                    tally.skip("duplicate tender id")
                elif len(rows) < cap:
                    seen.add(row["id"])
                    rows.append(row)
                    tally.kept += 1
            nxt = (data.get("next_page") or {}).get("uri")
            if not nxt:
                break
            url, params = nxt, None
            time.sleep(0.15)
    return rows


# --------------------------------------------------------------------------- UK (Find a Tender)
#
# Find a Tender is the post-Brexit OJEU replacement and publishes OCDS release packages with no
# key. CPV codes travel in the release, so notices are banded with the same CPV_MAP that TED
# uses - UK MOD notices land in the portfolio on the code, not on English keywords.

UK_FTS = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
UK_PAGES = 12


def uk_row(rel):
    tender = rel.get("tender") or {}
    title = (tender.get("title") or "").strip()
    if not title:
        return None, "no title"
    buyer = ((rel.get("buyer") or {}).get("name") or "").strip()
    cpvs = []
    main = (tender.get("classification") or {})
    if (main.get("scheme") or "").upper().startswith("CPV") and main.get("id"):
        cpvs.append(str(main["id"]))
    for item in (tender.get("items") or []):
        cl = item.get("classification") or {}
        if (cl.get("scheme") or "").upper().startswith("CPV") and cl.get("id"):
            cpvs.append(str(cl["id"]))
    cat = map_cat(title + " " + (tender.get("description") or ""), cpvs=cpvs)
    if not cat:
        return None, "unmappable"
    period = tender.get("tenderPeriod") or {}
    deadline = parse_iso_day(period.get("endDate"))
    posted = parse_iso_day(rel.get("date") or period.get("startDate"))
    if not recent_enough(posted, deadline):
        return None, "stale"
    ocid = rel.get("ocid") or rel.get("id")
    if not ocid:
        return None, "no ocid"
    return make_row("uk_" + re.sub(r"[^A-Za-z0-9_.-]", "_", str(ocid))[:60],
                    title, buyer, "United Kingdom", cat,
                    f"https://www.find-tender.service.gov.uk/Notice/{ocid}",
                    "Find a Tender (UK)", "open",
                    deadline_dt=deadline, posted_dt=posted), None


def fetch_uk(cap, tally, client_factory):
    rows, seen = [], set()
    frm = (date.today() - timedelta(days=RECENT_DAYS)).isoformat()
    url = f"{UK_FTS}?limit=100&updatedFrom={frm}T00:00:00"
    with client_factory(timeout=60, follow_redirects=True, verify=False,
                        headers={"User-Agent": UA, "Accept": "application/json"}) as c:
        for _ in range(UK_PAGES):
            if len(rows) >= cap:
                break
            r = c.get(url)
            if r.status_code != 200:
                tally.error = f"HTTP {r.status_code}"
                break
            pkg = r.json()
            releases = pkg.get("releases") or []
            if not releases:
                break
            for rel in releases:
                tally.fetched += 1
                row, why = uk_row(rel)
                if row is None:
                    tally.skip(why)
                elif row["id"] in seen:
                    tally.skip("duplicate ocid")
                elif len(rows) < cap:
                    seen.add(row["id"])
                    rows.append(row)
                    tally.kept += 1
            nxt = ((pkg.get("links") or {}).get("next"))
            if not nxt:
                break
            url = nxt
            time.sleep(0.2)
    return rows


# --------------------------------------------------------------------------- DB writer

UPSERT_COLS = ["id", "ord", "title", "issuer", "country", "cat", "value", "qty",
               "deadline", "dl", "reqNote", "req", "matches", "lean", "leanTxt",
               "status", "url", "urlKind", "srcs", "stage", "origin"]
MUTABLE = ["title", "issuer", "country", "cat", "value", "qty", "deadline", "status",
           "url", "srcs", "ord"]


def ensure_text_id(cur):
    """serving.tender.id was integer in the seeded schema; source-prefixed stable ids
    need text. One-time in-place migration; the dependent serving_live.tender view is
    recreated exactly as db/schema_serving_live.sql defines it."""
    cur.execute("SELECT data_type FROM information_schema.columns WHERE table_schema='serving' "
                "AND table_name='tender' AND column_name='id'")
    (dtype,) = cur.fetchone()
    if dtype == "text":
        return False
    cur.execute("DROP VIEW IF EXISTS serving_live.tender")
    cur.execute("ALTER TABLE serving.tender ALTER COLUMN id TYPE text USING id::text")
    cur.execute("CREATE OR REPLACE VIEW serving_live.tender AS "
                "SELECT * FROM serving.tender WHERE origin = 'pipeline'")
    return True


def write_db(rows):
    import psycopg2
    from psycopg2.extras import Json

    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    cur = conn.cursor()
    migrated = ensure_text_id(cur)

    sets = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in MUTABLE)
    cols = ", ".join(f'"{c}"' for c in UPSERT_COLS)
    ph = ", ".join(["%s"] * len(UPSERT_COLS))
    sql = (f"INSERT INTO serving.tender ({cols}) VALUES ({ph}) "
           f"ON CONFLICT (id) DO UPDATE SET {sets}, updated_at = now() "
           f"WHERE serving.tender.origin = 'pipeline'")
    for i, r in enumerate(rows):
        vals = []
        for c in UPSERT_COLS:
            if c == "ord":
                vals.append(i)
            elif c == "origin":
                vals.append("pipeline")
            elif c in ("req", "matches", "srcs"):
                vals.append(Json(r[c]))
            else:
                vals.append(r[c])
        cur.execute(sql, vals)

    # Renumber ord over ALL pipeline rows (this run + survivors of earlier runs):
    # deadline ascending, soonest first, no-deadline last.
    cur.execute("SELECT id, deadline FROM serving.tender WHERE origin='pipeline'")
    def key(row):
        m = re.match(r"(\d{1,2}) ([A-Za-z]{3}) (\d{4})$", row[1] or "")
        if m:
            try:
                return (0, datetime.strptime(" ".join(m.groups()), "%d %b %Y"), row[0])
            except ValueError:
                pass
        return (1, datetime.max, row[0])
    for ordv, (tid, _) in enumerate(sorted(cur.fetchall(), key=key)):
        cur.execute("UPDATE serving.tender SET ord=%s WHERE id=%s AND origin='pipeline'",
                    (ordv, tid))
    cur.execute("SELECT count(*) FROM serving.tender WHERE origin='pipeline'")
    (total,) = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return migrated, total


# --------------------------------------------------------------------------- demo

def demo():
    cats = set(kssl_cats())
    used = {c for c, _ in CAT_RULES} | {CAT_MRO} | {c for _, c in PSC_MAP} \
        | {c for _, c in CPV_MAP}
    assert (used - {None}) <= cats, f"mapper targets outside KSSL_CATS: {used - cats}"
    assert None in {c for _, c in CPV_MAP}, \
        "a CPV prefix mapped to None is a DELIBERATE exclusion, not a gap"
    for _, terms in CAT_RULES:
        assert all(len(t.replace(" ", "")) >= 4 for t in terms), "term under 4 chars"

    # keyword mapping: one category, specific before general, word boundaries
    assert map_cat("Supply of 155mm howitzer ammunition") == CAT_AMMO
    assert map_cat("Procurement of towed howitzers") == CAT_ARTY
    assert map_cat("Overhaul of armoured personnel carriers") == CAT_MRO
    assert map_cat("Armoured recovery vehicle") == CAT_AV
    assert map_cat("Counter-UAS detection system") == CAT_UAV
    assert map_cat("Naval gun mount spares") == CAT_NAVY
    assert map_cat("Anti-tank guided missile launchers") == CAT_MSL
    assert map_cat("Die forging of crankshafts") == CAT_FORGE
    assert map_cat("Sniper rifle telescopic sights") == CAT_SA
    assert map_cat("Office furniture and stationery") is None
    assert map_cat("cartridge type heater for RH furnace") is None
    assert map_cat("7.62mm ball cartridge cases") == CAT_AMMO
    assert map_cat("Ambulance services") is None            # 'arm' must not match inside words
    assert map_cat("5th Armored Brigade Turf Replacement") is None
    assert map_cat("ARMOR PLATE") == CAT_AV
    assert map_cat("Business cards printing") is None       # no sub-4-char 'bus' style terms

    # audit H2 (a): a defence word next to a services job is an ADDRESS, not a match
    assert map_cat("Drone Power Wash Service - VA Medical Center") is None
    assert map_cat("Lease of Portable Toilets at US Naval Base") is None
    assert map_cat("Custodial Services for Naval Hospital Camp Lejeune") is None
    assert map_cat("Academic Instructor and Tutor services, Naval Service Training "
                   "Command") is None
    assert map_cat("GOCO Aircraft/Ground Fuel Services") is None
    assert map_cat("Natural Resource Technical Services Throughout the Naval "
                   "Facilities Engineering Systems Command") is None
    # ... but a goods buy that also carries services stays
    assert not service_veto("Commercially available M134D Miniguns, Mounts, Support "
                            "Equipment, Spare Part Kits and Installation/Training "
                            "Services"), "a goods buy survives its trailing services"
    assert map_cat("Sniper rifles, spare parts and installation services") == CAT_SA
    assert map_cat("7.62mm Rifle Cleaning Kits") == CAT_SA, "'cleaning' + goods stays"
    assert map_cat("Repair and maintenance services of military vehicles",
                   cpvs=["50630000"]) == CAT_MRO, "MRO is a KSSL category, not a veto"
    # audit H2 (b): the 356 family is not one category
    assert map_cat("Lot 3", cpvs=["35613000"]) == CAT_UAV, "unmanned aerial vehicles"
    assert map_cat("Hawk Mk51, Mk51A ja Mk66 -suku", cpvs=["35641000"]) is None, \
        "manned-trainer aerospace spares are not a drone opportunity"
    assert map_cat("Beschaffung von Betriebsstoff", cpvs=["35611000"]) is None, \
        "fighter aircraft are outside the portfolio"
    assert map_cat("EGNOS-NEXT: system of systems engineering", cpvs=["35631000"]) \
        is None, "navigation satellites are not UAVs"
    assert map_cat("Panzerabwehr weit", cpvs=["35622000"]) == CAT_MSL
    assert map_cat("AM Suministro de tres sistemas", cpvs=["35322000"]) == CAT_MSL, \
        "anti-aircraft is air defence, not small arms"
    assert map_cat("Sporta inventara iegade", cpvs=["37400000"]) is None
    assert map_cat("GIS framework agreement", cpvs=["72300000"]) is None
    assert map_cat("PolBln 331_26 EU 25 Drohnen", cpvs=["34711200"]) == CAT_UAV
    assert map_cat("Small RPAS Below 25kg with Hands-on Training") == CAT_UAV, \
        "RPAS is how several European notices spell a drone"
    # audit H2: 1450 is guided-missile SERVICING equipment; generic hardware lives there
    assert map_cat("SWITCH, ENET, 8 POR", psc="1450") is None
    assert map_cat("Sealed lot 42", psc="1410") == CAT_MSL
    # audit H2 (d): a civilian department with nothing defence in the title
    assert non_defence_notice("VETERANS AFFAIRS, DEPARTMENT OF", "Grounds Upkeep")
    assert non_defence_notice("COMMERCE, DEPARTMENT OF", "Office relocation")
    assert not non_defence_notice("COMMERCE, DEPARTMENT OF", "Rifle Kit"), \
        "a defence word of its own keeps the notice"
    assert not non_defence_notice("DEPT OF DEFENSE", "Anything at all")
    # audit H2: one procurement, one row
    assert norm_title("Portugal \u2013 Firearms \u2013 Proc. 15/DPIE/2025 - Gas") == \
        norm_title("Portugal \u2013 Miscellaneous weapons \u2013 Proc. 15/DPIE/2025 - Gas"), \
        "the country and CPV-label segments are boilerplate"
    dd = dedupe_rows([
        {"issuer": "Forsvaret", "title": "Norway \u2013 Data \u2013 GIS framework agreement"},
        {"issuer": "Forsvaret", "title": "Norway \u2013 Software \u2013 GIS framework agreement"},
        {"issuer": "Bundeswehr", "title": "Germany \u2013 Ammunition \u2013 Patronen"},
    ])
    assert len(dd) == 2, "same buyer + same procurement is one row"
    # code fallbacks
    assert map_cat("Sealed lot 42", psc="1305") == CAT_AMMO
    assert map_cat("Rahmenvereinbarung", cpvs=["35412000"]) == CAT_AV
    assert map_cat("Lot 3", cpvs=["35613000"]) == CAT_UAV
    assert map_cat("Lot 3", cpvs=["30192000"]) is None

    # discipline: absence is NULL, never ''
    assert nn("") is None and nn("  ") is None and nn(" x ") == "x"
    assert fmt_deadline(datetime(2026, 9, 15)) == "15 Sep 2026"
    assert fmt_deadline(datetime(2026, 9, 5)) == "5 Sep 2026"
    assert parse_iso_day("2026-09-15T14:00:00-05:00") == datetime(2026, 9, 15)
    assert parse_iso_day("bogus") is None
    today = date(2026, 8, 24)
    assert recent_enough(datetime(2026, 8, 1), None, today)
    assert recent_enough(None, datetime(2026, 9, 1), today)
    assert not recent_enough(datetime(2025, 1, 1), datetime(2025, 2, 1), today)

    # CPPP parser: both feed layouts (proven fixture rows from pull_cppp_live.py)
    row = ('<tr><td>11.</td><td>08-Aug-2026 06:55 PM</td><td>19-Aug-2026 05:00 PM</td>'
           '<td>20-Aug-2026 11:00 AM</td><td><a href="https://eprocure.gov.in/cppp/tendersfullview/X">'
           'Repair of armoured vehicles at depot.</a>/WCL wa4350/2026_ARM_363367_1</td>'
           '<td>Ministry of Defence</td><td>--</td></tr>')
    r = cppp_parse(row)[0]
    assert r["ref"] == "2026_ARM_363367_1" and r["org"] == "Ministry of Defence"
    assert r["published"] == datetime(2026, 8, 8) and r["closing"] == datetime(2026, 8, 19)
    t, why = cppp_row(r, "CPPP")
    assert why is None or why == "stale"  # date-relative; mapping must succeed
    assert map_cat(r["title"]) == CAT_MRO
    grow = ('<tr><td>1.</td><td>19-Jun-2026 12:24 PM</td><td>15-Sep-2026 01:00 PM</td>'
            '<td><a href="https://eprocure.gov.in/cppp/gemtendersfullview/ZZZ">GEM/2026/B/7619530</a>/3480000</td>'
            '<td>Supply of drone payloads</td>'
            '<td>South Eastern Coalfields Limited</td><td>--</td></tr>')
    g = cppp_parse(grow)[0]
    assert g["ref"] == "GEM/2026/B/7619530" and g["title"].startswith("Supply of drone")
    gt, gwhy = cppp_row(g, "GeM via CPPP")
    if gt:
        assert gt["id"] == "cppp_GEM_2026_B_7619530" and gt["cat"] == CAT_UAV
        assert gt["deadline"] == "15 Sep 2026" and gt["url"].endswith("/ZZZ")

    # TED helpers
    assert i18n({"eng": ["Ammunition supply"], "fra": ["x"]}) == "Ammunition supply"
    assert i18n({"deu": ["Munitionslieferung"]}) == "Munitionslieferung"
    assert link_of({"html": {"ENG": "https://x/y"}}, "1-2026") == "https://x/y"
    assert link_of(None, "1-2026").endswith("/detail/1-2026")
    n = {"publication-number": "500123-2026",
         "notice-title": {"eng": ["Supply of 155mm artillery ammunition"]},
         "publication-date": "2026-08-10+02:00", "buyer-name": {"eng": ["Ministry of Defence"]},
         "buyer-country": ["POL"], "classification-cpv": ["35330000"],
         "deadline-receipt-tender-date-lot": ["2026-10-01+02:00"],
         "notice-type": "cn-standard", "links": {"html": {"ENG": "https://ted.europa.eu/x"}}}
    tr, why = ted_row(n)
    assert why is None and tr["id"] == "ted_500123-2026" and tr["cat"] == CAT_AMMO
    assert tr["country"] == "Poland" and tr["status"] in ("open", "closed")
    bad = dict(n, **{"classification-cpv": ["30192000"],
                     "main-classification-proc": ["30192000"],
                     "notice-title": {"eng": ["Office paper and toner supplies"]}})
    assert ted_row(bad)[0] is None, "an office-supplies notice is not a defence notice"
    kw_only = dict(n, **{"classification-cpv": ["30192000"],
                         "main-classification-proc": ["30192000"]})
    assert ted_row(kw_only)[0] is not None,         "a notice whose own TITLE says 155mm artillery ammunition is still admitted"
    # the MAIN CPV bands the notice, not whichever of its CPVs maps first
    mixed = dict(n, **{"notice-title": {"eng": ["Latvia - Sports goods and equipment - "
                                               "Sporta inventara iegade"]},
                       "classification-cpv": ["37400000", "35330000"],
                       "main-classification-proc": ["37400000"]})
    assert ted_row(mixed)[0] is None, \
        "a school's sports-goods buy is not Ammunition (audit H2)"
    manned = dict(n, **{"notice-title": {"eng": ["Finland - Structure spare parts - "
                                                "Hawk Mk51 tukisopimus"]},
                        "classification-cpv": ["35641000", "35600000"],
                        "main-classification-proc": ["35641000"]})
    assert ted_row(manned)[0] is None, \
        "manned-trainer spares are not a UAV opportunity"

    # GeM row shaping (field names from pull_gem_india.py's search-bids response)
    b = {"b_id": [7654321], "b_bid_number": ["GEM/2026/B/999"],
         "b_category_name": ["7.62mm Rifle Cleaning Kits"], "b_total_quantity": [500],
         "ba_official_details_deptName": ["Indian Army"],
         "final_start_date_sort": ["2026-08-01 10:00:00"],
         "final_end_date_sort": ["2026-09-30 15:00:00"]}
    gr, gwhy2 = gem_row(b)
    assert gwhy2 is None and gr["id"] == "gem_7654321" and gr["cat"] == CAT_SA
    assert gr["qty"] == "500 units" and gr["country"] == "India"
    assert gr["issuer"] == "Ministry of Defence — Indian Army"
    assert gr["deadline"] == "30 Sep 2026" and gr["url"].endswith("/showbidDocument/7654321")
    assert gem_row({"b_id": [1], "b_category_name": ["Office Chairs"],
                    "final_end_date_sort": ["2099-01-01 00:00:00"]}) == (None, "unmappable")

    # SAM row shaping
    o = {"noticeId": "abc123", "title": "M119A3 Howitzer Recoil Parts",
         "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY", "active": "Yes",
         "postedDate": "2026-08-15", "responseDeadLine": "2026-09-20T17:00:00-04:00",
         "classificationCode": "1015", "uiLink": "https://sam.gov/opp/abc123/view"}
    sr, why = sam_row(o)
    assert why is None and sr["id"] == "sam_abc123" and sr["cat"] == CAT_ARTY
    assert sr["country"] == "United States" and sr["status"] == "open"
    assert sr["deadline"] == "20 Sep 2026" and sr["value"] is None and sr["dl"] is None
    assert sr["req"] == [] and sr["srcs"][0]["label"] == "SAM.gov"
    # ---- Canada: the filter is the BUYER, and it has to work in both official languages ----
    fut = (date.today() + timedelta(days=30)).isoformat()
    ca_base = {"title-titre-eng": "Supply of 155mm Artillery Ammunition",
               "tenderClosingDate-appelOffresDateCloture": fut,
               "publicationDate-datePublication": date.today().isoformat(),
               "referenceNumber-numeroReference": "cb-721-999",
               "noticeURL-URLavis-eng": "https://canadabuys.canada.ca/en/x"}
    row, why = canada_row(dict(ca_base, **{CA_ENTITY: "Department of National Defence"}))
    assert row and row["cat"] == CAT_AMMO and row["country"] == "Canada", (row, why)
    assert row["id"] == "ca_cb-721-999", row["id"]
    # French-language buyer name: an English-only test would have passed while the lane silently
    # dropped every francophone notice.
    row, why = canada_row(dict(ca_base, **{CA_ENTITY: "Ministere de la Defense nationale"}))
    assert row, why
    # end-user is DND even though the contracting entity is the central buying agency
    row, why = canada_row(dict(ca_base, **{CA_ENTITY: "Public Services and Procurement Canada",
                                           CA_ENDUSER: "National Defence"}))
    assert row, why
    assert canada_row(dict(ca_base, **{CA_ENTITY: "Parks Canada"}))[1] == "not a defence buyer"
    # a defence buyer buying something outside the portfolio is still dropped
    assert canada_row(dict(ca_base, **{CA_ENTITY: "National Defence",
                                       "title-titre-eng": "Office furniture"}))[1] == "unmappable"

    # ---- ProZorro: Ukrainian titles must band on the CPV CODE, not on English words ----
    ua = {"tenderID": "UA-2026-01-01-000001-a", "id": "abc123",
          "title": "Закупівля 155-мм артилерійських боєприпасів",
          "procuringEntity": {"name": "Міністерство оборони України"},
          "items": [{"classification": {"scheme": "CPV", "id": "35331100-1"}}],
          "tenderPeriod": {"startDate": date.today().isoformat(),
                           "endDate": fut},
          "value": {"amount": 1234567.0, "currency": "UAH"}}
    row, why = prozorro_row(ua)
    assert row and row["country"] == "Ukraine", (row, why)
    assert row["cat"] in set(kssl_cats()), row["cat"]
    assert row["id"] == "ua_UA-2026-01-01-000001-a", row["id"]
    assert row["value"] and "UAH" in row["value"], row["value"]
    # no CPV and a non-English title -> unmappable, not a false positive
    assert prozorro_row(dict(ua, items=[], title="Послуги з прибирання"))[1] == "unmappable"

    # ---- UK Find a Tender: CPV lives on the tender OR its items ----
    uk = {"ocid": "ocds-h6vhtk-0123", "date": date.today().isoformat(),
          "buyer": {"name": "Ministry of Defence"},
          "tender": {"title": "Supply of armoured fighting vehicles",
                     "classification": {"scheme": "CPV", "id": "35410000-3"},
                     "tenderPeriod": {"endDate": fut}}}
    row, why = uk_row(uk)
    assert row and row["country"] == "United Kingdom" and row["id"] == "uk_ocds-h6vhtk-0123", (row, why)
    assert row["cat"] in set(kssl_cats()), row["cat"]
    # classification carried only on an item still bands
    uk2 = {"ocid": "ocds-h6vhtk-0124", "date": date.today().isoformat(),
           "buyer": {"name": "MOD"},
           "tender": {"title": "Framework", "tenderPeriod": {"endDate": fut},
                      "items": [{"classification": {"scheme": "CPV", "id": "35510000-5"}}]}}
    assert uk_row(uk2)[0], uk_row(uk2)[1]
    assert uk_row({"ocid": "x", "date": date.today().isoformat(),
                   "tender": {"title": "Grounds maintenance",
                              "tenderPeriod": {"endDate": fut}}})[1] == "unmappable"

    print("demo ok: 90+ asserts across mapper, service veto, CPV/PSC banding, dedupe, recency "
          "and CPPP/TED/SAM/Canada/ProZorro/UK row shaping")


# --------------------------------------------------------------------------- main

def report(name, tally, rows):
    print(f"\n[{name}] fetched={tally.fetched} kept={tally.kept} "
          f"skipped={sum(tally.skipped.values())}")
    for why, n in sorted(tally.skipped.items(), key=lambda x: -x[1]):
        print(f"    skipped {n}: {why}")
    if tally.error:
        print(f"    SOURCE PROBLEM: {tally.error}")
    if rows:
        r = rows[0]
        print(f"    example: {r['id']} | {r['cat']} | {r['country']} | "
              f"deadline={r['deadline']} | {r['title'][:70]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo", action="store_true", help="parser/mapper asserts, no network")
    ap.add_argument("--dry", action="store_true", help="fetch + report, no DB writes")
    ap.add_argument("--cap", type=int, default=TOTAL_CAP,
                    help="max rows written in total (default %d)" % TOTAL_CAP)
    ap.add_argument("--per-source", type=int, default=PER_SOURCE_CAP,
                    help="max rows kept per source (default %d)" % PER_SOURCE_CAP)
    ap.add_argument("--only", default="",
                    help="comma-separated source names to run (default: all)")
    args = ap.parse_args()
    if args.demo:
        demo()
        return

    import httpx
    import urllib3
    urllib3.disable_warnings()

    cats = set(kssl_cats())
    sources = [("sam", fetch_sam), ("ted", fetch_ted), ("gem", fetch_gem),
               ("cppp", fetch_cppp), ("canada", fetch_canada),
               ("prozorro", fetch_prozorro), ("uk", fetch_uk)]
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        unknown = want - {n for n, _ in sources}
        if unknown:
            ap.error("unknown source(s): %s" % ", ".join(sorted(unknown)))
        sources = [(n, f) for n, f in sources if n in want]
    all_rows, tallies, dead = [], {}, []
    for name, fn in sources:
        tally = Tally()
        tallies[name] = tally
        try:
            rows = fn(args.per_source, tally, httpx.Client)
        except Exception as ex:
            tally.error = tally.error or f"{type(ex).__name__}: {str(ex)[:120]}"
            rows = []
        if tally.error and not rows:
            dead.append(name)
        for r in rows:
            assert r["cat"] in cats, r["cat"]
        all_rows.extend(rows)
        report(name, tally, rows)

    # de-dup across runs of the same id inside one batch, then cap: soonest deadline first
    uniq = {}
    for r in all_rows:
        uniq.setdefault(r["id"], r)
    ordered = sorted(uniq.values(),
                     key=lambda r: (r["_deadline_dt"] is None,
                                    r["_deadline_dt"] or datetime.max, r["id"]))
    final = dedupe_rows(ordered)[:args.cap]
    if len(ordered) != len(dedupe_rows(ordered)):
        print(f"\ndeduped {len(ordered) - len(dedupe_rows(ordered))} notice(s): "
              f"same buyer, same procurement")
    print(f"\nTOTAL kept {len(final)} (cap {args.cap}); "
          f"sources down: {', '.join(dead) if dead else 'none'}")
    if args.dry:
        print("--dry: no DB writes")
        return
    if not final:
        print("nothing to write")
        return
    migrated, total = write_db(final)
    if migrated:
        print("one-time migration applied: serving.tender.id integer -> text "
              "(serving_live.tender view recreated per db/schema_serving_live.sql)")
    print(f"wrote {len(final)} rows -> serving.tender origin='pipeline' "
          f"(table now holds {total} pipeline rows); ord renumbered by deadline")


if __name__ == "__main__":
    main()
