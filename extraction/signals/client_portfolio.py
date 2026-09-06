"""The client's OWN product portfolio, as the client supplied it.

    python client_portfolio.py --xlsx <workbook>   # parse the client's workbook -> portfolio/kssl_portfolio.json
    python client_portfolio.py --demo              # hermetic asserts, no DB
    python client_portfolio.py --dry               # what --apply would write to serving.client_product
    python client_portfolio.py --apply             # write serving.client_product (origin='reference')

NOT portfolio.py. That sibling module (merged from wt2-relevance the same day) is the
relevance gate's view of the same workbook: positive ANCHORS per serving tag and the
heading-to-tag join for signals. This one is the matchup writer's view: the rows
themselves, bullet for bullet, and the rules for when a bullet may stand as KSSL's side
of a comparison. _demo() checks the two category maps agree, so they cannot drift apart.

WHY THIS FILE EXISTS
--------------------
Two acceptance items were blocked on one fact: the corpus holds no source for KSSL's
own specifications. revive_matchups.py grounds every number in a document we hold,
and for the KSSL side of a comparison there was nothing to hold -- so 160 served
matchups carried a competitor value and a blank where KSSL's should be (MD 11), and
"KSSL advantages" was empty (MD 10). On 2026-09-05 the client sent their master
product-specification workbook ("for portfolio reference though not complete i think
but enough to start"). This module is that workbook, made usable by the matchup
writer -- and nothing else. It does not decide pairings, it does not score, and it
never fills a value the workbook does not state.

TWO ID SPACES, NEVER JOINED ON A LABEL
--------------------------------------
The workbook's Category column and the dashboard's category vocabulary look alike and
are not the same thing. The workbook says "Protected Vehicles" and "Armoured Vehicles -
MRO"; the dashboard says "Protected & Armoured Vehicles" (catKey pav) and "Armoured
Vehicle MRO" (mro). The workbook has no "Missiles & Air Defence" heading and lists
MRSAM missile subsystems under Ammunition. FILE_CATEGORY and PRODUCT_CLASS below are
the explicit map; the file heading is kept verbatim on every row so the map can be
audited, and nothing anywhere compares a display label to a display label. This
project has already lost an entire layer to exactly that join (see
[[one-company-two-id-spaces]]).

WHAT A VALUE HAS TO SURVIVE BEFORE IT REACHES A MATCHUP
-------------------------------------------------------
  1. the product must be named in the workbook -- by an explicit alias, because the
     archive writes "KSSL · M4" and the workbook writes "Kalyani M4"; a name that is
     ambiguous in the workbook ("MArG 155" against five MaRG variants) is resolved
     only by the archive row's OWN calibre statement, and refused otherwise;
  2. the product's class (from the map above) must equal the matchup's catKey;
  3. within artillery and small arms the two products must share a bore: a 105 mm
     gun's range is not a figure to put beside a 155 mm gun's;
  4. the matchup label must have a RECIPE for that class -- a list of the workbook
     keys that mean the same measurement, and the keys that look alike and do not
     (a UAV's "communication link range" is not its flight range);
  5. the bullet must not sit under a hedged sub-heading ("Publicly indexed ST-500-type
     technical table associated with...") or in the "Programme / status context";
  6. a single figure gets a number; a range, a compound ("2+4"), a set of variant
     values or a composite label with no unit on record gets TEXT ONLY and no number,
     so the front end draws chips, never bars;
  7. the row's Sources column must clear the same credibility bar the corpus path
     applies (engine/source_tiers.publishable): the maker or a government publisher,
     or two independent domains.

Every refusal is counted by reason in REFUSALS, and revive_matchups prints the count.
If that number is ever zero the checks are not running.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "portfolio" / "kssl_portfolio.json"
DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
CLIENT = "Kalyani Strategic Systems"
CLIENT_ID = "KSSL"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _engine_tiers():
    """engine/source_tiers.py, loaded BY PATH.

    signals/source_tiers.py is the trust-tier table (how much a claim weighs);
    engine/source_tiers.py is the publishability rule (maker / government / two
    independent domains). They share a filename, and `from source_tiers import
    publishable` from this directory finds the wrong one -- which is why
    revive_matchups.py could not be imported in the deployed image on 2026-09-05."""
    p = HERE.parent / "engine" / "source_tiers.py"
    spec = importlib.util.spec_from_file_location("engine_source_tiers", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TIERS = _engine_tiers()
publishable, st_domain = TIERS.publishable, TIERS.domain


# ---------------------------------------------------------------------------
# category map: the workbook's heading -> the dashboard's (label, catKey)
# ---------------------------------------------------------------------------
# Keys are the workbook's headings VERBATIM. Values are (KSSL_CATS label, CAT_KEY
# key) from reference_dataset.json, and _demo() checks they still exist there.
FILE_CATEGORY = {
    "Artillery":               ("Artillery", "art"),
    "Ammunition":              ("Ammunition", "ammo"),
    "Small Arms":              ("Small Arms", "sa"),
    # The dashboard has ONE vehicles tag for what the workbook splits into
    # "Protected Vehicles" and the MRO line -- and it also has a separate MRO tag
    # that the workbook's MRO heading is the honest match for.
    "Protected Vehicles":      ("Protected & Armoured Vehicles", "pav"),
    "Armoured Vehicles - MRO": ("Armoured Vehicle MRO", "mro"),
    "Marine / Naval":          ("Marine / Naval", "naval"),
    "UAVs & Drones":           ("UAVs & Drones", "uav"),
}

# Rows whose class is NOT the heading the client filed them under. Keyed by the
# workbook product name (slugged, see product_id()). None means "no dashboard
# category exists for this": an unmanned GROUND vehicle is not a drone, and the
# workbook's own note on the ECARS row says so.
PRODUCT_CLASS = {
    "mrsam-missile-subsystems-integration-kits": ("Missiles & Air Defence", "msl"),
    "spike-atgm-sub-assemblies":                 ("Missiles & Air Defence", "msl"),
    "counter-uas-c-uas-mobile-system":           ("Missiles & Air Defence", "msl"),
    "ecars-enhanced-collaborative-autonomous-rover-system": (None, None),
}

# "Precision Components & Forgings" (pc) is a dashboard tag with NO workbook heading.
# That is a fact about the workbook the client called incomplete, not about the
# portfolio, and this module records it rather than inferring anything from it.
UNMAPPED_SERVING_TAGS = ("Missiles & Air Defence", "Precision Components & Forgings")

# ---------------------------------------------------------------------------
# product aliases: archive `bf` product name -> workbook product_id(s)
# ---------------------------------------------------------------------------
# The archive names products the way the trade press does; the workbook names them
# the way the catalogue does. A list means a GROUP: the value is accepted only when
# every member states it identically (a portfolio-level statement), which is what
# "Shell forgings" against four effect-type rows sharing one calibre range is.
ALIASES = {
    "ATAGS":              ["atags"],
    "Bharat 45":          ["bharat-45"],
    "Bharat 52":          ["bharat-52"],
    "Bharat ULH":         ["bharat-ulh-155-39"],
    "Garuda 105":         ["garuda-105-v2"],
    # The archive's MArG 155 states 155/39, 18 t, 18 rds Zone 5, 4x4 on every row,
    # and the workbook's MaRG 155-BR row is the only MaRG that states all four; its
    # own note reads "MArG 155-BR is the earlier/public 155/39-cal 4x4 MArG
    # configuration". ALIAS_GUARD still checks each archive row's calibre.
    "MArG 155":           ["marg-155-br"],
    "M4":                 ["kalyani-m4"],
    "Maverick":           ["kalyani-maverick"],
    "ATC":                ["armoured-troops-carrier"],
    "LBPV":               ["light-bullet-proof-vehicle"],
    "LTV":                ["light-tactical-vehicle"],
    "MPV":                ["mine-protected-vehicle"],
    "ULSV":               ["ultra-light-strike-vehicle"],
    "CQB Carbine":        ["cqb-carbine-f90"],
    "Protective Carbine": ["protective-carbine-5-56-30-mm"],
    "Sniper":             ["sniper-rifles-t-5000m"],
    "Bharat 150":         ["bharat-150-uav"],
    "Naval Guns":         ["naval-guns"],
    "Shell forgings":     ["high-explosive-he-artillery-shells", "illuminating-artillery-shells",
                           "incendiary-artillery-shells", "smoke-artillery-shells"],
    # Not in the workbook at all (the client said it is incomplete): Bayonet, Cleaver,
    # Omega, MRAUV. They stay on the corpus path and are reported, not guessed.
}
# archive product -> (archive label, regex its kv must match) before the alias holds
ALIAS_GUARD = {
    "MArG 155": ("Calibre", r"(^|\D)39(\D|$)"),
}

# ---------------------------------------------------------------------------
# recipes: (catKey, archive label) -> what workbook keys mean that measurement
# ---------------------------------------------------------------------------
# keys:     regex the bullet KEY must fully match (case-folded)
# exclude:  regex that, matching the key or value, refuses the bullet with `why`
# unit:     the unit the number is read in (None: text only, never a number)
# numeric:  False -> text only even when a figure is present, with `why`
# compose:  optional (prefix, regex) pairs assembled into one text value
# choose:   "max" takes the largest figure among candidates (a maximum range);
#           default prefers a single figure over a range, then file order
_HEDGE = r"future|under-development|ramjet|aspirational|claims|variant|parent|comparable|not confirmed|related|lineage|titanium|steel variant|later/lighter|indexed"
RECIPES = {
    ("art", "Calibre"): dict(keys=r"calibre", unit="mm", first=True),
    ("art", "Weight"): dict(keys=r"(system|total|all-up|complete system) weight|weight|complete system",
                            unit="t", exclude=(_HEDGE + r"|gun weight|gun-only", "hedged or component weight")),
    ("art", "Max range"): dict(keys=r".*(firing|maximum|max|reported|effective|conventional).*range.*|range with .*|erfb.*|standard ammunition|rocket-assisted projectile.*|maximum / extended-range firing|maximum range with .*",
                               unit="km", choose="max",
                               exclude=(_HEDGE + r"|direct-fire|link|communication", "a claimed, direct-fire or link range is not the gun's maximum range")),
    ("art", "Crew"): dict(keys=r"crew( accommodation)?", unit="count"),
    ("art", "Rate of fire"): dict(keys=r"(burst|intense|sustained|maximum|normal) rate( of fire)?|rate of fire",
                                  unit=None, numeric=False,
                                  why="rate-of-fire measures differ: burst / intense / sustained figures are not a rounds-per-minute rate",
                                  compose=(("burst ", (r"burst rate( of fire)?",)), ("sustained ", (r"sustained rate( of fire)?",)))),
    ("art", "Loading"): dict(keys=r"(ammunition )?handling|loading system", unit=None),
    ("art", "Mobility"): dict(keys=r"self-propelled speed|(maximum )?towing speed( on blacktop)?", unit=None,
                              compose=(("SP ", (r"self-propelled speed",)),
                                       ("tow ", (r"towing speed", r"maximum towing speed", r"towing speed on blacktop")))),
    # Combat weight is the vehicle as it fights. A kerb weight (unladen) and a
    # "maximum GVW" (the chassis rating -- the MPV's 30 tonnes) are different numbers
    # under similar words, so they are refused as "states nothing", not read as it.
    ("pav", "Combat weight"): dict(keys=r"combat weight.*|combat / gross weight|gvm|gvw", unit="t",
                                   exclude=(_HEDGE, "hedged provenance in the workbook")),
    # `keys` decide the NUMBER (power, in hp); `extra` bullets may only join the text.
    ("pav", "Power / speed"): dict(keys=r"engine power|engine", unit="hp",
                                   extra=r"burst speed|speed|maximum/burst speed|burst / maximum stated speed",
                                   compose=(("", (r"engine power", r"engine")),
                                            ("", (r"burst speed", r"maximum/burst speed", r"burst / maximum stated speed", r"speed"))),
                                   exclude=(_HEDGE, "hedged provenance in the workbook")),
    ("pav", "Protection"): dict(keys=r"protection class|ballistic protection|protection|stanag protection", unit=None),
    ("pav", "Crew / pax"): dict(keys=r"crew / troop capacity|crew capacity|capacity|carrying capacity|troop capacity|crew", unit="count",
                                exclude=(_HEDGE + r"|alternate", "hedged or alternate configuration")),
    ("pav", "Configuration"): dict(keys=r"configuration|drive layout|layout|drive", unit=None),
    ("sa", "Calibre"): dict(keys=r"calibre|cartridge|published calibre options", unit="mm", first=True),
    ("sa", "Effective range"): dict(keys=r"effective (firing )?range", unit="m"),
    ("sa", "Weight"): dict(keys=r"weight(,| -)? (carbine|weapon) only|weight without (magazine|ammunition box)|weight|mass", unit="kg",
                           exclude=(r"magazine weight|box|full magazine|with full", "loaded-magazine or box weight is not the weapon's weight")),
    ("sa", "Barrel"): dict(keys=r"barrel length( options)?|barrel options", unit="mm"),
    ("sa", "Action"): dict(keys=r"operating principle|action", unit=None),
    ("uav", "Range"): dict(keys=r"(operational |flight |mission )?range", unit="km",
                           exclude=(r"communication|link|control|surveillance|demonstrated", "a communication-link or demonstrated-mission distance is not the flight range")),
    ("uav", "Endurance"): dict(keys=r"(minimum battery |battery )?endurance", unit="h"),
    ("uav", "Payload / ceiling"): dict(keys=r"(demonstrated )?payload( capacity)?", unit="kg",
                                       extra=r"designed operating altitude",
                                       compose=(("", (r"demonstrated payload", r"payload capacity", r"payload")),
                                                ("", (r"designed operating altitude",)))),
    ("uav", "MTOW"): dict(keys=r"maximum take-off weight", unit="kg"),
    ("uav", "Class"): dict(keys=r"configuration|type", unit=None),
    ("naval", "Weight / dia"): dict(keys=r"calibre", unit=None, numeric=False, join_all=True,
                                    why="the workbook states a calibre; the label's unit on record is kg, and a bore is not a weight"),
    ("naval", "Type"): dict(keys=r"type|system type", unit=None),
    ("ammo", "Calibre"): dict(keys=r"(publicly stated |published )?calibre range.*", unit="mm"),
    ("ammo", "Type"): dict(keys=r"product form|ammunition effect / family", unit=None),
}

# How a number in the workbook is read into the base unit revive_matchups compares
# in. Mass in kg, length in m, power in hp, time in h -- the same quantities and
# sizes as revive_matchups.BASE where both have them.
_UNITS = {
    "mm": ("length", 0.001), "m": ("length", 1.0), "km": ("length", 1000.0),
    "kg": ("mass", 1.0), "t": ("mass", 1000.0), "tonne": ("mass", 1000.0), "tonnes": ("mass", 1000.0),
    "hp": ("power", 1.0), "kw": ("power", 1.34102),
    "h": ("time", 1.0), "hr": ("time", 1.0), "hours": ("time", 1.0), "min": ("time", 1 / 60.0), "minutes": ("time", 1 / 60.0),
    "count": ("count", 1.0),
}
# The imperial surfaces the client's own pages write ("508 mm (20 in)", "8 lb") were
# missing, so those values came back with NO unit at all and could not be compared
# against a metric one. Adding them here is safe in a way adding them to
# revive_matchups.UNIT_FORMS would not be: this regex is asked only about a workbook
# CELL, where the token sits beside its number, never about document prose, where
# "in" is an English word. `_UNITS` deliberately does NOT gain them, so Fit.side
# behaves exactly as before -- a unit it cannot size is refused, as it always was.
_UNIT_RX = re.compile(r"(?<![a-z])(mm|km/h|km|kg|tonnes|tonne|t|m/s|mph|m|cm|ft|"
                      r"inches|inch|in|lbs|lb|hp|kw|hr|hours|h|minutes|min)(?![a-z])")

REFUSALS = collections.Counter()


class Refusal(object):
    __slots__ = ("why",)

    def __init__(self, why):
        self.why = why
        REFUSALS[why] += 1

    def __repr__(self):
        return "Refusal(%r)" % self.why


# ---------------------------------------------------------------------------
# parsing the workbook
# ---------------------------------------------------------------------------
BULLET = "•"
_DASH_ONLY = re.compile(r"^[—–\-\s]*$")
_URL = re.compile(r"https?://[^\s<>\"]+")
_NOTE_SEP = re.compile(r"\s+—\s+")          # " -- " with an em dash


def slug(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


product_id = slug


def _bullets(cell):
    """-> [{k, v, note, ctx}] from one workbook cell.

    Lines that start with a bullet are entries; any other non-empty line is a
    sub-heading that applies to the entries after it ("Programme / status context:",
    "DRDO-published parameters:"). A cell holding only a dash is EMPTY, and stays so."""
    out, ctx = [], None
    for raw in (cell or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(BULLET):
            ctx = line.rstrip(":").strip()
            continue
        body = line[len(BULLET):].strip()
        if _DASH_ONLY.match(body):
            continue
        note = None
        parts = _NOTE_SEP.split(body, maxsplit=1)
        if len(parts) == 2:
            body, note = parts[0].strip(), parts[1].strip()
        k, v = None, body
        m = re.match(r"^([^:]{1,70}?):\s+(.+)$", body)
        if m and not m.group(1).startswith("http"):
            k, v = m.group(1).strip(), m.group(2).strip()
        out.append({"k": k, "v": v, "note": note, "ctx": ctx})
    return out


def _urls(cell):
    seen, out = set(), []
    for u in _URL.findall(cell or ""):
        u = u.rstrip(".,;)")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_workbook(path, sheet="Master Database"):
    """-> {"_meta": {...}, "rows": [...]}. Needs openpyxl; run locally, commit the JSON."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[sheet]
    rows, ord_ = [], 0
    for i, r in enumerate(ws.iter_rows(values_only=True)):
        if i == 0 or not any(r):
            continue
        cat, name, specs, feats, srcs = (list(r) + [None] * 5)[:5]
        cat, name = (cat or "").strip(), (name or "").strip()
        if not cat or not name:
            continue
        ord_ += 1
        rows.append(_row(ord_, cat, name, specs, feats, srcs))
    return {"_meta": {"source_file": os.path.basename(path), "sheet": sheet,
                      "supplied_by": "client", "supplied_on": "2026-09-05",
                      "client_note": "for portfolio reference though not complete i think but enough to start",
                      "rows": len(rows)},
            "rows": rows}


def _row(ord_, cat, name, specs, feats, srcs):
    pid = product_id(name)
    if cat not in FILE_CATEGORY:
        raise ValueError("workbook heading %r is not in FILE_CATEGORY -- map it explicitly" % cat)
    label, key = PRODUCT_CLASS.get(pid, FILE_CATEGORY[cat])
    return {"product_id": pid, "ord": ord_, "name": name, "file_category": cat,
            "cat": label, "catKey": key,
            "specs": _bullets(specs), "features": _bullets(feats), "sources": _urls(srcs)}


def load(path=DATA):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d["rows"]


def load_db(cur):
    """The same rows from serving.client_product, or [] if the table is absent/empty."""
    cur.execute("select to_regclass('serving.client_product')")
    if cur.fetchone()[0] is None:
        return []
    cur.execute('select product_id, ord, name, file_category, cat, "catKey", specs, features, '
                "sources from serving.client_product order by ord")
    cols = ["product_id", "ord", "name", "file_category", "cat", "catKey", "specs", "features", "sources"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# reading a value
# ---------------------------------------------------------------------------
def _figure(v, first=False):
    """-> (number, unit_written, kind) for a value that states ONE figure.

    kind is "single", "bound" ("<15", "up to 6", "~16", "38+"), "range" ("6-8",
    "15-16"), "compound" ("2+4", "4+2+2") or "multi" (several different figures in
    one value: "336 kW / 465 hp, 1,627 Nm"). Only single and bound get a number.
    `first` is for calibres, where "155 mm / 52 calibre" means the bore comes first."""
    s = (v or "").strip().lower().replace(",", "")
    s = s.replace("–", "-").replace("—", "-").replace("×", "x")
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if not nums:
        return None, "", "text"
    if re.search(r"\d\s*[+]\s*\d", s):
        return None, "", "compound"
    if re.search(r"\d\s*-\s*\d", s) or re.search(r"\d\s*(to|or)\s+\d", s):
        return None, "", "range"
    if len(set(nums)) > 1 and not first:
        return None, "", "multi"
    m = _UNIT_RX.search(s)
    unit = m.group(1) if m else ""
    kind = "bound" if re.search(r"^[<>~]|under|up to|minimum|maximum|more than|\d\s*\+", s) else "single"
    return float(nums[0]), unit, kind


def _base(n, unit):
    q = _UNITS.get(unit)
    if n is None or not q:
        return None, None
    return n * q[1], q[0]


def _key(b):
    return (b.get("k") or "").strip().lower()


def _hedged(b):
    ctx = (b.get("ctx") or "").lower()
    return bool(ctx) and not ctx.startswith("drdo-published")


class Fit(object):
    """One archive product resolved against the workbook."""

    def __init__(self, name, rows, catkey, bore=None):
        self.name, self.rows, self.catkey, self.bore = name, rows, catkey, bore

    @property
    def sources(self):
        out, seen = [], set()
        for r in self.rows:
            for u in r["sources"]:
                if u not in seen:
                    seen.add(u)
                    out.append(u)
        return out

    def _candidates(self, recipe):
        """Bullets matching the recipe in EVERY member row (a group is a consensus)."""
        kx = re.compile("^(%s)$" % recipe["keys"])
        xx = re.compile("^(%s)$" % recipe["extra"]) if recipe.get("extra") else None
        ex = recipe.get("exclude")
        per = []
        for r in self.rows:
            cand = []
            for b in r["specs"]:
                k = _key(b)
                if not k or not (kx.match(k) or (xx and xx.match(k))):
                    continue
                if _hedged(b):
                    REFUSALS["bullet under a hedged sub-heading in the workbook"] += 1
                    continue
                if ex and re.search(ex[0], k + " " + (b["v"] or "").lower() + " " + (b.get("note") or "").lower()):
                    REFUSALS[ex[1]] += 1
                    continue
                cand.append(b)
            per.append(cand)
        if len(per) == 1:
            return per[0]
        # group: keep a bullet only if every member states the same key and value
        first = per[0]
        agreed = []
        for b in first:
            if all(any(_key(o) == _key(b) and (o["v"] or "").strip() == (b["v"] or "").strip() for o in others)
                   for others in per[1:]):
                agreed.append(b)
        return agreed

    def side(self, label, unit, archive_kv=None):
        """-> dict(kv, n, unit, base, urls, why, tier, key) or Refusal."""
        recipe = RECIPES.get((self.catkey, label))
        if not recipe:
            return Refusal("no recipe for label %r in class %r" % (label, self.catkey))
        cands = self._candidates(recipe)
        if not cands:
            return Refusal("workbook states nothing for %r" % label)
        ok, why, tier, _n = publishable(self.sources, CLIENT)
        if not ok:
            return Refusal("row sources do not clear the credibility bar (%s)" % why)
        composed = self._compose(recipe, cands)
        text_only = recipe.get("unit") is None or recipe.get("numeric") is False
        if text_only:
            if recipe.get("numeric") is False:
                REFUSALS[recipe["why"]] += 1
            kv = composed or (" / ".join(c["v"] for c in cands) if recipe.get("join_all") else cands[0]["v"])
            return self._value(kv, None, None, cands, why, tier)
        if label in ("Power / speed",) and not (unit or "").strip():
            REFUSALS["composite label with no unit on record: the archive figure could be power or speed"] += 1
            return self._value(composed or cands[0]["v"], None, None, cands, why, tier)
        # only the recipe's own keys may carry the number; `extra` bullets are text
        kx = re.compile("^(%s)$" % recipe["keys"])
        figs = [(b, _figure(b["v"], recipe.get("first", False))) for b in cands if kx.match(_key(b))]
        want_q = _UNITS[recipe["unit"]][0]
        # A figure has to be WRITTEN in the label's quantity to count: "Engine:
        # 6-cylinder turbo diesel" holds a 6 and no unit, and it is not 6 hp.
        singles = [(b, f) for b, f in figs
                   if f[2] in ("single", "bound")
                   and (want_q == "count" or _UNITS.get(f[1], (None,))[0] == want_q)]
        if not singles:
            if any(f[2] in ("single", "bound") for _b, f in figs):
                REFUSALS["figure is not written in the label's quantity (%s)" % want_q] += 1
            else:
                kinds = sorted(set(f[2] for _b, f in figs)) or ["text"]
                REFUSALS["value is a %s, no single figure" % "/".join(kinds)] += 1
            return self._value(composed or cands[0]["v"], None, None, cands, why, tier)
        if recipe.get("choose") == "max":
            b, f = max(singles, key=lambda bf: _base(bf[1][0], bf[1][1] or recipe["unit"])[0] or 0)
        else:
            vals = [f[0] for _b, f in singles]
            spread = (max(vals) - min(vals)) / (sum(vals) / len(vals)) if sum(vals) else 0.0
            if spread > 0.03 and label not in ("Calibre",):
                # Six T-5000M variants, six weights: no single figure describes the rifle.
                REFUSALS["several variant figures in the workbook, no single figure"] += 1
                return self._value(composed or cands[0]["v"], None, None, cands, why, tier)
            # "<3 kg" and "3.05 kg" agree within the parity deadband; the stated
            # figure beats the bound.
            b, f = next(((b, f) for b, f in singles if f[2] == "single"), singles[0])
        n, wu, kind = f
        u = wu if wu in _UNITS else recipe["unit"]
        if recipe["unit"] == "count":
            u = "count"
        if u == "km/h" or (recipe["unit"] != "count" and _UNITS.get(u, (None,))[0] != _UNITS[recipe["unit"]][0]):
            REFUSALS["unit in the workbook is not the label's quantity"] += 1
            return self._value(composed or b["v"], None, None, cands, why, tier)
        # The workbook's own key travels with the figure -- "18 tonnes (system weight)",
        # "30 tonnes (maximum gvw)" -- so a reader sees WHAT was measured, not just how much.
        kv = composed or b["v"]
        if not composed and b["k"] and b["k"].strip().lower() != label.lower():
            kv = "%s (%s)" % (b["v"], b["k"].strip().lower())
        return self._value(kv, n, u, cands, why, tier, key=b["k"])

    def _compose(self, recipe, cands):
        """Join one bullet per part, trying each part's key patterns in priority order:
        "Engine power: 465 hp" before "Engine: 6-cylinder turbo-diesel, 336 kW / 465 hp"."""
        comp = recipe.get("compose")
        if not comp:
            return None
        parts = []
        for prefix, patterns in comp:
            for rx in patterns:
                rxc = re.compile("^(%s)$" % rx)
                hit = next((b for b in cands if rxc.match(_key(b))), None)
                if hit:
                    parts.append(prefix + hit["v"])
                    break
        return ", ".join(parts) if parts else None

    def _value(self, kv, n, u, cands, why, tier, key=None):
        base, q = _base(n, u) if n is not None else (None, None)
        return {"kv": kv, "n": n, "unit": u, "base": (base, q), "urls": self.sources,
                "why": "stated in KSSL's own portfolio (client-supplied workbook); " + why,
                "tier": tier, "key": key or (cands[0].get("k") if cands else None),
                "bullets": [c["v"] for c in cands]}

    # -- MD 10: advantages -------------------------------------------------------
    _CLASSIFY = re.compile(r"^(type|vehicle type|system type|platform( family| lineage| / model family)?|configuration|"
                           r"mission type|vehicle class|platform context|design lineage|public product identity)$")
    _SKIP_NOTE = re.compile(r"lineage|not treated|not an accepted|parent|secondary source", re.I)
    # The compiler's own remarks about the workbook ("treated as separate developmental
    # context rather than silently merged...") are not capabilities of the product.
    _EDITORIAL = re.compile(r"treated as|rather than|do not assume|should not be|not located|"
                            r"not confirmed|reviewed sources|referenced workbook|consolidated file", re.I)

    def advantages(self, limit=6):
        """Capability bullets from the workbook's Features column, each attributed to
        the row's own source. Classification rows ("Type: towed howitzer") and the
        "Programme / status context" block are not capabilities and are skipped."""
        out, seen = [], set()
        for r in self.rows:
            src = _primary_source(r["sources"])
            if not src:
                continue
            for b in r["features"]:
                if _hedged(b) and not (b.get("ctx") or "").lower().startswith("drdo"):
                    continue
                k = _key(b)
                if k and self._CLASSIFY.match(k):
                    continue
                if b.get("note") and self._SKIP_NOTE.search(b["note"]):
                    continue
                v = (b["v"] or "").strip()
                if self._EDITORIAL.search(v):
                    continue
                if v.lower() in ("yes", "available", "provided", "supported", "listed as feature"):
                    text = b["k"]
                elif v.lower() == "optional":
                    continue
                elif k:
                    text = "%s: %s" % (b["k"], v)
                else:
                    text = v
                text = re.sub(r"\.$", "", text.strip())
                norm = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
                if not norm or norm in seen or len(text) < 6:
                    continue
                seen.add(norm)
                out.append('%s <a class="adv-src" href="%s" target="_blank" rel="noopener">%s</a>'
                           % (_esc(text), src, st_domain(src)))
                if len(out) >= limit:
                    return out
        return out


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_CLIENT_DOMAINS = ("kssl.in", "kssl.co.in", "bharatforge.com", "bharatforge.eu", "kalyanistrategic.com")


def _primary_source(urls):
    for u in urls:
        d = st_domain(u)
        if any(d == c or d.endswith("." + c) for c in _CLIENT_DOMAINS):
            return u
    return urls[0] if urls else None


def _bore(v):
    """The bore in mm from a calibre as written. An imperial calibre is a decimal
    fraction of an inch (".338 LM", ".50 BMG"): read as 338 mm it would still refuse
    a 5.56 mm carbine, for the wrong reason and by a wrong number."""
    m = re.search(r"(\.\d+|\d+(?:\.\d+)?)\s*(?:mm)?", (v or "").replace(",", ""))
    if not m:
        return None
    tok = m.group(1)
    return round(float(tok) * 25.4, 2) if tok.startswith(".") else float(tok)


def match(bf, catkey, archive_specs, rows):
    """-> Fit or Refusal for one archive matchup's KSSL side.

    `bf` is the archive's product ("KSSL · M4" or "M4"); `archive_specs` the archive
    row's own spec list, consulted for the alias guard and the bore check."""
    name = re.split(r"[·|]", bf or "")[-1].strip()
    ids = ALIASES.get(name)
    if not ids:
        return Refusal("product not in the workbook")
    guard = ALIAS_GUARD.get(name)
    by_id = {r["product_id"]: r for r in rows}
    fit_rows = [by_id[i] for i in ids if i in by_id]
    if len(fit_rows) != len(ids):
        return Refusal("alias points at a product_id the workbook does not hold")
    classes = set(r["catKey"] for r in fit_rows)
    if classes != {catkey}:
        return Refusal("product class %s differs from the matchup class %s" % (sorted(classes), catkey))
    kv_of = {s.get("l"): s.get("kv") for s in (archive_specs or []) if s.get("l")}
    if guard:
        lab, rx = guard
        if not re.search(rx, kv_of.get(lab) or ""):
            return Refusal("alias guard: the archive row does not state the variant the alias resolves to")
    fit = Fit(name, fit_rows, catkey)
    if catkey in ("art", "sa"):
        own = fit.side("Calibre", "mm")
        comp = _bore(next((s.get("cv") for s in (archive_specs or []) if s.get("l") == "Calibre"), None))
        mine = own["n"] if isinstance(own, dict) else None
        if mine is not None and comp is not None and abs(mine - comp) > 0.01:
            fit.bore = (mine, comp)
    return fit


def kssl_side(fit, label, unit, archive_kv=None):
    """The one call revive_matchups makes per spec row. Applies the bore rule.

    UNCHANGED, ON PURPOSE. Widening this to a per-field rule was tried and reverted:
    test_client_portfolio's Garuda 105 case is the reason. A 105 mm gun weighs a third
    of a 155 mm gun, `Weight` is hi=False, and letting the lighter one through here
    would have SCORED a class difference as a KSSL lead -- the exact fault
    positioning_gate exists to stop. A figure this rule refuses is not lost: spec_join
    still puts KSSL's published value on the panel as its own stated value, with no
    number attached to it, so it can be read and cannot decide anything."""
    if fit.bore and label != "Calibre":
        return Refusal("bore differs (%g vs %g mm): not a like-for-like pairing" % fit.bore)
    return fit.side(label, unit, archive_kv)


# ---------------------------------------------------------------------------
# writing serving.client_product
# ---------------------------------------------------------------------------
def write_db(rows, dsn=DSN, apply=False):
    import psycopg2
    from psycopg2.extras import Json
    con = psycopg2.connect(dsn)
    cur = con.cursor()
    cur.execute("select to_regclass('serving.client_product')")
    if cur.fetchone()[0] is None:
        raise SystemExit("serving.client_product does not exist -- run the migrate role first")
    cur.execute("select count(*) from serving.client_product where origin='reference'")
    before = cur.fetchone()[0]
    print("serving.client_product: %d reference row(s) now, %d to write" % (before, len(rows)))
    if not apply:
        print("(dry run -- nothing written)")
        con.close()
        return
    # This module is the ONLY writer of these rows, and they are the client's own
    # statement: replaced whole, never merged, so a row the client removed does not
    # linger. origin='reference' because the enrich pass must never rebuild them.
    cur.execute("delete from serving.client_product where origin='reference'")
    for r in rows:
        cur.execute("""insert into serving.client_product
                         (product_id, ord, name, file_category, cat, "catKey", specs, features,
                          sources, origin)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'reference')""",
                    (r["product_id"], r["ord"], r["name"], r["file_category"], r["cat"],
                     r["catKey"], Json(r["specs"]), Json(r["features"]), Json(r["sources"])))
    con.commit()
    con.close()
    print("applied: %d row(s) written" % len(rows))


def inventory(rows):
    """Per category: products, products with any spec bullet, recurring spec keys."""
    by = collections.OrderedDict()
    for r in rows:
        c = by.setdefault(r["file_category"], {"n": 0, "specs": 0, "keys": collections.Counter(),
                                                "cat": r["cat"], "catKey": r["catKey"]})
        c["n"] += 1
        if r["specs"]:
            c["specs"] += 1
        for b in r["specs"]:
            if b["k"] and not _hedged(b):
                c["keys"][_key(b)] += 1
    return by


def _demo():
    rows = load()
    assert len(rows) == 59, len(rows)
    # the map is keyed by the WORKBOOK's headings and only those
    assert set(r["file_category"] for r in rows) == set(FILE_CATEGORY)
    ref = json.loads((HERE.parent / "reference_dataset.json").read_text(encoding="utf-8"))
    for label, key in list(FILE_CATEGORY.values()) + [v for v in PRODUCT_CLASS.values() if v[0]]:
        assert label in ref["KSSL_CATS"] and ref["CAT_KEY"][label] == key, (label, key)
    empty = [r for r in rows if not r["specs"]]
    assert len(empty) == 16, len(empty)
    # Two views of one workbook must not carry two joins. portfolio.py (the relevance
    # gate) maps each heading to the serving TAGS it may anchor; this module maps it to
    # the ONE class a product may be compared in. Every class here must be one of the
    # tags there, or the two files have started to disagree about the same heading.
    try:
        import portfolio as relevance
    except ImportError:                       # older checkout without the gate
        relevance = None
    if relevance is not None:
        for heading, (label, _key) in FILE_CATEGORY.items():
            tags = relevance.FILE_CATEGORY_TO_TAG.get(heading)
            assert tags and label in tags, (heading, label, tags)
        assert set(relevance.FILE_CATEGORY_TO_TAG) == set(FILE_CATEGORY)
    print("ok - %d rows, %d without specifications, %d refusal reasons live"
          % (len(rows), len(empty), len(REFUSALS)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", help="parse the client's workbook and write portfolio/kssl_portfolio.json")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dsn", default=DSN)
    a = ap.parse_args()
    if a.xlsx:
        d = parse_workbook(a.xlsx)
        DATA.parent.mkdir(exist_ok=True)
        txt = json.dumps(d, ensure_ascii=False, indent=1)
        assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", txt), "control byte in the parsed workbook"
        io.open(DATA, "w", encoding="utf-8", newline="\n").write(txt + "\n")
        inv = inventory(d["rows"])
        for c, v in inv.items():
            print("%-24s -> %-32s %2d products, %2d with specs; keys: %s"
                  % (c, "%s (%s)" % (v["cat"], v["catKey"]), v["n"], v["specs"],
                     ", ".join("%s x%d" % kv for kv in v["keys"].most_common(8))))
        print("wrote %s (%d rows)" % (DATA, len(d["rows"])))
    elif a.demo:
        _demo()
    else:
        write_db(load(), a.dsn, apply=a.apply)
