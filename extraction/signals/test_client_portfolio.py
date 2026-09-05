"""The client's workbook may fill the KSSL side of a comparison ONLY where it states
the same measurement for the same class of product.

    python3 test_client_portfolio.py

Two acceptance items depend on this module (MD 11 spec comparison, MD 10 KSSL
advantages), and both are places where a value that exists but does not mean what the
row claims is worse than a blank. So the second half of this file is refusals: the
figures the workbook holds that must NOT reach a matchup, each for a stated reason.

No DB, no network -- the committed portfolio JSON and inline archive rows only.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import client_portfolio as pf                                                # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = pf.load()
fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("  FAIL", what)


def fit(bf, catkey, specs=()):
    return pf.match(bf, catkey, list(specs), ROWS)


def side(bf, catkey, label, unit, specs=()):
    f = fit(bf, catkey, specs)
    assert isinstance(f, pf.Fit), (bf, f)
    return pf.kssl_side(f, label, unit)


# ---- 1. the workbook, as parsed ---------------------------------------------------
check(len(ROWS) == 59, "59 products in the Master Database sheet")
empty = [r["name"] for r in ROWS if not r["specs"]]
check(len(empty) == 16, "16 rows have an em-dash for specifications and stay EMPTY: %d" % len(empty))
check("MRSAM Missile Subsystems & Integration Kits" in empty, "MRSAM row is one of the empties")
check(all(r["sources"] for r in ROWS), "every row carries at least one source URL")
by_id = {r["product_id"]: r for r in ROWS}
check(by_id["mrsam-missile-subsystems-integration-kits"]["catKey"] == "msl",
      "MRSAM filed under Ammunition in the workbook maps to the msl class, by explicit override")
check(by_id["ecars-enhanced-collaborative-autonomous-rover-system"]["catKey"] is None,
      "a ground rover under 'UAVs & Drones' maps to NO class rather than to drones")
check(by_id["armoured-personnel-carrier"]["catKey"] == "pav" and by_id["mro-armoured-vehicles"]["catKey"] == "mro",
      "Protected Vehicles -> pav, Armoured Vehicles - MRO -> mro (two workbook headings, two tags)")
check("Protected & Armoured Vehicles" not in pf.FILE_CATEGORY,
      "the dashboard LABEL is never a key of the category map (the file heading is)")
# a sources cell written "KSSL official: https://..." yields the URL, not the label
check(all(u.startswith("http") for r in ROWS for u in r["sources"]), "sources are bare URLs")
# sub-headings inside a cell are kept as context, never as bullets
ltv = by_id["light-tactical-vehicle"]
gvm = [b for b in ltv["specs"] if (b["k"] or "").lower() == "gvm"]
check(gvm and gvm[0]["ctx"] and "indexed" in gvm[0]["ctx"].lower(),
      "LTV's GVM bullet carries the 'Publicly indexed ST-500-type table' hedge as its context")

# ---- 2. product resolution --------------------------------------------------------
check(isinstance(fit("KSSL · ATAGS", "art"), pf.Fit), "ATAGS resolves by alias")
check(isinstance(fit("KSSL · Bayonet", "uav"), pf.Refusal), "Bayonet is not in the workbook: refused, not guessed")
check(isinstance(fit("KSSL · ATAGS", "pav"), pf.Refusal), "an artillery product against a vehicle matchup is refused")
g52 = fit("KSSL · MArG 155", "art", [{"l": "Calibre", "cv": "155/52", "kv": "155mm / 52 Cal"}])
check(isinstance(g52, pf.Refusal), "MArG 155 alias is guarded: an archive row saying 52 cal does not resolve to the 39-cal 155-BR")
g39 = fit("KSSL · MArG 155", "art", [{"l": "Calibre", "cv": "155/52", "kv": "155mm / 39 Cal"}])
check(isinstance(g39, pf.Fit) and g39.rows[0]["product_id"] == "marg-155-br", "...and a 39-cal row does")

# ---- 3. values the workbook supports ---------------------------------------------
w = side("KSSL · ATAGS", "art", "Weight", "kg")
check(isinstance(w, dict) and w["base"] == (18000.0, "mass"), "ATAGS system weight 18 tonnes -> 18000 kg base: %r" % (w,))
check(isinstance(w, dict) and any("kssl.in" in u for u in w["urls"]), "...cited to the row's own kssl.in source")
check(isinstance(w, dict) and w["tier"] == "official", "...at the official tier (maker or government publisher)")
r = side("KSSL · ATAGS", "art", "Max range", "km")
check(isinstance(r, dict) and r["base"] == (48074.0, "length"), "ATAGS max range takes the 48.074 km ERFB/HE-BB figure: %r" % (r and r.get("kv"),))
check(isinstance(r, dict) and "80" not in (r["kv"] or ""), "...and never the 'future ramjet 60-80 km class claims' bullet")
c = side("KSSL · ATAGS", "art", "Calibre", "mm")
check(isinstance(c, dict) and c["n"] == 155.0, "ATAGS calibre 155 mm")
crew = side("KSSL · ATAGS", "art", "Crew", "")
check(isinstance(crew, dict) and crew["n"] is None and "6" in crew["kv"], "ATAGS crew '6-8 personnel' is a RANGE: text shown, no number")
g = side("KSSL · Garuda 105", "art", "Crew", "")
check(isinstance(g, dict) and g["n"] == 4.0, "Garuda crew: the single-figure bullet (4) beats the range (3-5): %r" % (g,))
m4 = side("KSSL · M4", "pav", "Combat weight", "kg")
check(isinstance(m4, dict) and m4["base"] == (16000.0, "mass"), "M4 combat weight ~16 tonnes -> 16000 kg: %r" % (m4 and m4.get("kv"),))
hp = side("KSSL · M4", "pav", "Power / speed", "hp")
check(isinstance(hp, dict) and hp["n"] == 465.0 and "140" in hp["kv"], "M4 power 465 hp with the speed in the text: %r" % (hp and hp.get("kv"),))
pl = side("KSSL · Bharat 150", "uav", "Payload / ceiling", "kg")
check(isinstance(pl, dict) and pl["n"] == 20.0, "Bharat 150 demonstrated payload 20 kg: %r" % (pl,))
mt = side("KSSL · Bharat 150", "uav", "MTOW", "kg")
check(isinstance(mt, dict) and mt["n"] == 150.0, "Bharat 150 MTOW 150 kg")
sh = side("KSSL · Shell forgings", "ammo", "Calibre", "")
check(isinstance(sh, dict) and "70" in sh["kv"] and "155" in sh["kv"] and sh["n"] is None,
      "Shell forgings: the four shell rows AGREE on 70-155 mm, shown as text, a range gets no number: %r" % (sh,))
pc = side("KSSL · Protective Carbine", "sa", "Weight", "kg")
check(isinstance(pc, dict) and pc["n"] == 3.05 and pc["kv"] == "3.05 kg (mass)",
      "carbine weight: KSSL's '<3 kg' and DRDO's '3.05 kg' agree within 3%%; the stated figure beats the bound: %r" % (pc and pc.get("kv"),))
b52 = side("KSSL · Bharat 52", "art", "Weight", "kg")
check(isinstance(b52, dict) and b52["base"] == (15000.0, "mass"), "Bharat 52 '<15 tonnes / 15 tonnes (catalogue figure)' -> 15000 kg: %r" % (b52 and b52.get("kv"),))
ld = side("KSSL · Bharat 52", "art", "Loading", "")
check(isinstance(ld, dict) and "ALAS" in ld["kv"] and ld["n"] is None, "Bharat 52 loading is text (ALAS)")
mob = side("KSSL · Bharat 52", "art", "Mobility", "")
check(isinstance(mob, dict) and "21" in mob["kv"] and "80" in mob["kv"], "Bharat 52 mobility composed from SP and towing speed: %r" % (mob and mob.get("kv"),))

# every accepted value cites only URLs the row itself lists
for v in (w, r, c, m4, hp, pl, sh, pc):
    if isinstance(v, dict):
        check(all(any(u in row["sources"] for row in ROWS) for u in v["urls"]), "value cites a URL from the workbook's Sources column")

# ---- 4. refusals: figures that exist and must NOT be compared ----------------------
n0 = sum(pf.REFUSALS.values())
rng = side("KSSL · Bharat 150", "uav", "Range", "km")
check(isinstance(rng, pf.Refusal), "Bharat 150 'communication link range 50-200 km' is NOT a flight range: %r" % (rng,))
rof = side("KSSL · ATAGS", "art", "Rate of fire", "")
check(isinstance(rof, dict) and rof["n"] is None and "burst" in rof["kv"].lower(),
      "burst/sustained artillery rates are text only against a rds/min figure: %r" % (rof,))
ltvw = side("KSSL · LTV", "pav", "Combat weight", "kg")
check(isinstance(ltvw, pf.Refusal), "LTV GVM 12,000 kg sits under a hedged 'indexed ST-500-type table' heading: refused: %r" % (ltvw,))
mpv = side("KSSL · MPV", "pav", "Combat weight", "kg")
check(isinstance(mpv, pf.Refusal), "MPV 'Maximum GVW: 30 tonnes' is a chassis rating, not a combat weight: refused: %r" % (mpv,))
check(pf._bore(".338/.408") == 8.59 and pf._bore("5.56x45") == 5.56 and pf._bore("155/52") == 155.0,
      "an imperial calibre is read as a fraction of an inch, in mm")
snip = fit("KSSL · CQB Carbine", "sa", [{"l": "Calibre", "cv": ".338 LM", "kv": "5.56x45mm"}])
check(isinstance(snip, pf.Fit) and snip.bore == (5.56, 8.59), "a 5.56 carbine against a .338 rifle: bores differ (5.56 vs 8.59 mm): %r" % (snip and snip.bore,))
ps = side("KSSL · M4", "pav", "Power / speed", "")
check(isinstance(ps, dict) and ps["n"] is None, "a composite label with no unit on record gets text, never a number")
nav = side("KSSL · Naval Guns", "naval", "Weight / dia", "kg")
check(isinstance(nav, dict) and nav["n"] is None and "57" in nav["kv"] and "127" in nav["kv"],
      "naval gun calibres are shown as text under a kg label, not compared as weights: %r" % (nav,))
sn = side("KSSL · Sniper", "sa", "Weight", "kg")
check(isinstance(sn, dict) and sn["n"] is None, "T-5000M: six variant weights -> no single figure: %r" % (sn,))
bore = fit("KSSL · Garuda 105", "art", [{"l": "Calibre", "cv": "155/52", "kv": "105mm / 37 Cal"}])
check(isinstance(bore, pf.Fit) and bore.bore is not None, "Garuda 105 against a 155 mm rival: bore mismatch recorded")
bw = pf.kssl_side(bore, "Weight", "kg") if isinstance(bore, pf.Fit) else None
check(isinstance(bw, pf.Refusal) and "bore" in bw.why, "...so its weight is refused for that pairing")
bc = pf.kssl_side(bore, "Calibre", "mm") if isinstance(bore, pf.Fit) else None
check(isinstance(bc, dict) and bc["n"] == 105.0, "...while the calibre itself is still shown, so the mismatch is visible")
apc = side("KSSL · ATC", "pav", "Crew / pax", "")
check(isinstance(apc, dict) and apc["n"] is None, "ATC '12-14 crew members' is a range: text only")
none = side("KSSL · ATAGS", "art", "Autonomy / EW", "")
check(isinstance(none, pf.Refusal) and "no recipe" in none.why, "a label with no recipe in this class is refused, not improvised")
check(sum(pf.REFUSALS.values()) - n0 >= 8, "refusals are COUNTED: %d new" % (sum(pf.REFUSALS.values()) - n0))
# a Refusal is never mistaken for a value
check(not isinstance(rng, dict), "a refusal is not a dict a caller could store")

# ---- 5. MD 10: advantages from the Features column ----------------------------------
adv = fit("KSSL · ATAGS", "art").advantages()
check(1 <= len(adv) <= 6, "ATAGS: between 1 and 6 capability bullets: %d" % len(adv))
check(all('href="https://www.kssl.in/' in a for a in adv), "each bullet is attributed to the row's own kssl.in source")
check(not any(a.lower().startswith("type:") for a in adv), "a 'Type:' classification row is not an advantage")
check(any("Automatic Ammunition Handling" in a for a in adv), "the AHS capability is one of them")
check(not any("307 guns" in a or "Armenia" in a for a in adv), "programme/status context is not a capability")
sn_adv = fit("KSSL · Sniper", "sa").advantages()
check(not any("lineage" in a.lower() for a in sn_adv), "a design-lineage note is not an advantage")
ng_adv = fit("KSSL · Naval Guns", "naval").advantages()
check(ng_adv and not any("rather than" in a for a in ng_adv), "the workbook compiler's own remark is not a capability")
sf_adv = fit("KSSL · Shell forgings", "ammo").advantages()
check(sf_adv == [], "shell rows whose features are all programme/status context yield NO advantage")
sim = [r for r in ROWS if r["product_id"] == "simha-4x4"][0]
check(isinstance(pf.Fit("Simha", [sim], "pav").side("Combat weight", "kg"), pf.Refusal),
      "Simha 4x4 (trials phase, weight not disclosed) fills nothing")
# a product whose ONLY sources are trade press does not clear the bar even if it states a figure
fake = {"product_id": "x", "name": "X", "catKey": "art", "sources": ["https://idrw.org/a"],
        "specs": [{"k": "Calibre", "v": "155 mm", "note": None, "ctx": None}], "features": []}
check(isinstance(pf.Fit("X", [fake], "art").side("Calibre", "mm"), pf.Refusal),
      "a single uncorroborated news source does not publish a figure")

# ---- 6. hygiene ------------------------------------------------------------------
for fn in ("client_portfolio.py", "test_client_portfolio.py", os.path.join("portfolio", "kssl_portfolio.json")):
    raw = open(os.path.join(HERE, fn), "rb").read()
    check(not re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", raw), "%s holds no control byte" % fn)
meta = json.load(open(os.path.join(HERE, "portfolio", "kssl_portfolio.json"), encoding="utf-8"))["_meta"]
check(meta["rows"] == 59 and meta["supplied_by"] == "client", "the JSON records where it came from")

if fails:
    print("\n%d failure(s)" % len(fails))
    sys.exit(1)
print("ok - portfolio: 59 rows, 16 empty, values only where the workbook states the same measurement; "
      "%d refusal(s) across %d reason(s)" % (sum(pf.REFUSALS.values()), len(pf.REFUSALS)))
