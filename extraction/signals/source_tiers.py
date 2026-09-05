"""Trust tier per source: how much weight a claim carries because of WHERE it came from.

THIS IS NOT THE CADENCE TIER
----------------------------
The word `tier` already means two different things in this project and they must
not be confused:

    site_schedules.tier   daily / weekly / monthly -- HOW OFTEN we crawl it
    Source.tier           1 / 2 / 3               -- HOW MUCH a claim from it weighs

This module is the second one. It never decides whether a source is crawled;
`crawl_scheduler.py` does that, from change rate and cost. A tier-3 blog can
break the most important story of the week and still rank first on merit.

WHAT THE TIERS MEAN
-------------------
  1  STANDS ALONE.  The record itself, or reporting good enough to cite without
     a second source. Government and procurement portals, defence organisations,
     a manufacturer about ITSELF, and independent trade press with a named
     newsroom.
  2  CORROBORATE THE NUMBERS.  Real reporting, but with a structural interest or
     a single-nation lens: industry associations, service journals, national
     outlets, specialist magazines without a wire desk.
  3  A LEAD, NOT EVIDENCE.  Aggregators and blogs that republish other people's
     reporting, and state-owned or state-directed outlets. A state outlet is
     often RIGHT about what was announced and unreliable about what it means, so
     it is worth crawling and not worth citing alone.
  0  UNRATED.  Nobody has assessed it. This is a FOURTH state, not a synonym for
     tier 3 -- the same rule this project applies to every unmeasured number.
     Rendering "unassessed" as "low trust" invents a fact about the source.

HOW EACH ASSIGNMENT WAS MADE -- and this is the part to read
------------------------------------------------------------
`BASIS` records why, because the tiers are not all the same kind of claim:

  structural   a fact anyone can check: a .gov/.mil domain, an official service
               organ, a procurement API. Not a judgement.
  ownership    the outlet is owned or directed by a state. A checkable fact
               about ownership, applied as a judgement about independence.
  editorial    MY judgement about how the outlet works: does it have a named
               newsroom, does it publish original reporting, does it carry a
               declared position. This is opinion, held by one model, on one
               day. It is the majority of the file. Argue with it.
  artefact     not a source at all -- see PLATFORM_ARTEFACTS.

Nothing here is measured. Bias is not something this pipeline can measure today,
and a keyword scan that claimed to would be the tenth instance of the failure in
[[closed-keyword-list-is-a-language-detector]]. So it is written down as a
judgement, per source, with a reason, in a file that is easy to edit.

GOVERNMENT SOURCES ARE MISSING
------------------------------
The live catalogue holds 759 sources: 593 manufacturer_ir and 166 trade_press.
There are ZERO gov_primary, tender_portal, think_tank, defence_org and
business_press rows -- the taxonomy has had those categories all along and
nothing has ever been filed under them. Four of the sources catalogued as trade
press are in fact government (see GOV_MISFILED); the rest of tier 1's primary
layer does not exist yet.
"""
from __future__ import annotations

# ── not sources at all ────────────────────────────────────────────────────────
# `registrable_domain()` returns eTLD+1 from a hard-coded suffix list. `net.au`
# and `in.ua` are public suffixes that are NOT in that list, so every site under
# them collapses into one catalogue row -- exactly the failure the function's own
# comment warns about for `gov.my`. blogspot.com and livejournal.com are the same
# shape for a different reason: they are hosting platforms, so the eTLD+1 IS the
# platform. `blogspot.com` currently carries a measured 65 changes/day and holds
# no pages, which is what one row standing in for thousands of blogs looks like.
PLATFORM_ARTEFACTS = {
    "net.au":        "public suffix missing from _MULTI_SUFFIXES - every .net.au site collapses here",
    "in.ua":         "public suffix missing from _MULTI_SUFFIXES - every .in.ua site collapses here",
    "blogspot.com":  "hosting platform; the eTLD+1 is the platform, not a publisher",
    "livejournal.com": "hosting platform; same shape as blogspot.com",
}

# ── catalogued as trade press, actually government ────────────────────────────
GOV_MISFILED = {
    "contracts.mod.uk": "UK MoD contract award bulletin - a procurement record, not press",
    "mindef.gov.sg":    "Singapore Ministry of Defence",
    "defensie.nl":      "Netherlands Ministry of Defence",
    "dvidshub.net":     "US DoD Defense Visual Information Distribution Service",
}

# ── the assignment: domain -> (tier, basis, reason) ───────────────────────────
# basis: structural | ownership | editorial | artefact
TIERS: dict[str, tuple[int, str, str]] = {}


def _add(tier, basis, reason, *domains):
    for d in domains:
        # A domain listed twice would silently take whichever bucket was written
        # last -- the "one value, two writers" failure this project keeps hitting.
        # Fail loudly instead.
        if d in TIERS:
            raise AssertionError("%s assigned twice: %s then %s"
                                 % (d, TIERS[d][:2], (tier, basis)))
        TIERS[d] = (tier, basis, reason)


# --- tier 1, structural: the record itself ------------------------------------
_add(1, "structural", "government or ministry of defence",
     "contracts.mod.uk", "mindef.gov.sg", "defensie.nl", "dvidshub.net")

# --- tier 1, editorial: independent trade press with a newsroom ----------------
_add(1, "editorial", "established defence newsroom, bylined original reporting",
     "janes.com", "defensenews.com", "breakingdefense.com", "aviationweek.com",
     "c4isrnet.com", "defenseone.com", "defensescoop.com", "insidedefense.com",
     "defensedaily.com", "shephardmedia.com", "navalnews.com", "spacenews.com",
     "defense-aerospace.com", "forecastinternational.com",
     "defenceprocurementinternational.com")
_add(1, "editorial", "US service press: independent newsroom, statutory editorial independence",
     "militarytimes.com", "armytimes.com", "navytimes.com", "airforcetimes.com",
     "marinecorpstimes.com", "stripes.com", "airandspaceforces.com")
_add(1, "editorial", "national defence trade press with a staffed newsroom",
     "opex360.com", "air-cosmos.com", "meretmarine.com", "latribune.fr",
     "ouest-france.fr", "esut.de", "euro-sd.com", "hartpunkt.de",
     "soldat-und-technik.de", "behoerden-spiegel.de", "analisidifesa.it", "rid.it",
     "infodefensa.com", "defensa.com", "defence24.pl", "defence24.com",
     "militairespectator.nl", "canadiandefencereview.com",
     "adbr.com.au", "asiapacificdefencereporter.com", "defenceconnect.com.au",
     "asianmilitaryreview.com", "defenceweb.co.za", "thediplomat.com",
     "defesaaereanaval.com.br", "zona-militar.com")

# --- tier 2: real reporting, structural interest or single-nation lens ---------
_add(2, "editorial", "professional or service institute journal - authoritative, institutional viewpoint",
     "usni.org", "naval-review.org", "rusi.org", "wavellroom.com",
     "smallwarsjournal.com", "warontherocks.com", "globalsecurity.org")
_add(2, "editorial", "industry or service association - reports its members' interest",
     "nationaldefensemagazine.org", "seapowermagazine.org", "forces.net")
_add(2, "editorial", "specialist magazine or regional trade press, no wire desk",
     "edrmagazine.eu", "europeandefencereview.eu", "frontline-defence.com",
     "nordicdefencereview.com",
     "espritdecorps.ca", "joint-forces.com", "navylookout.com", "thinkdefence.co.uk",
     "ukdefencejournal.org.uk", "africanaerospace.aero", "tecnologiamilitar.com",
     "naval.com.br", "japan-forward.com", "defensenewskorea.com",
     "pacificdefencereporter.com.au", "militaryaerospace.com", "defense-update.com",
     "thedrive.com", "theaviationist.com", "bruxelles2.eu", "forcesoperations.com",
     "adf-magazine.com", "thedefensepost.com", "defensemirror.com", "overtdefense.com",
     "globaldefencetechnology.com", "airforce-technology.com", "army-technology.com",
     "naval-technology.com", "armyrecognition.com", "airrecognition.com",
     "navalrecognition.com", "sofrep.com", "thecipherbrief.com",
     "spslandforces.com", "indiandefencereview.com", "forceindia.net",
     "bharatshakti.in", "defenceturkey.com", "savunmasanayist.com", "c4defence.com",
     "israeldefense.co.il", "defencehub.live", "milscint.com", "miltech.media")
_add(2, "editorial", "regional outlet, credible but strongly national in outlook",
     "al-monitor.com", "israelhayom.com", "defence-ua.com", "defencearabia.com",
     "defencesecurityasia.com", "turkishdefensenews.com", "defenseturk.net")

_add(2, "editorial", "procurement newsletter built on official contract announcements",
     "defenseindustrydaily.com", "defence-industry.eu")
_add(2, "editorial", "Moscow analytical centre - independent of the state but a Russian institutional lens",
     "cast.ru")

# --- tier 3, ownership: state-owned or state-directed --------------------------
_add(3, "ownership", "state news agency or official government organ",
     "tass.com", "rg.ru", "chinamil.com.cn")
_add(3, "ownership", "state-aligned outlet: reliable on what was announced, not on what it means",
     "vpk.name", "topwar.ru", "militaryreview.ru", "iran-defense.com")

# --- tier 3, editorial: aggregators and blogs ---------------------------------
_add(3, "editorial", "aggregator - republishes other outlets' reporting",
     "idrw.org", "livefistdefence.com", "raksha-anirveda.com", "indiandefencenews.info",
     "defencexp.com", "defencedecode.com", "defenceib.com", "defence-eye.com",
     "defenceaviationpost.com", "militaryleak.com", "globaldefensecorp.com",
     "defence-blog.com", "bulgarianmilitary.com", "realcleardefense.com",
     "defensesystems.com", "asdnews.com", "medefnews.com", "gadn.co.uk",
     "dsti.net", "military.africa", "navalpost.com", "navalforces.net",
     "defencejournal.com", "africanmilitaryblog.com", "egyptdefensereview.com",
     "chanakyaforum.com", "areion24.news", "military.com")
_add(3, "editorial", "opinion-led or advocacy: a position, not a newsroom",
     "19fortyfive.com", "militarywatchmagazine.com", "thedefensist.com",
     "warriormaven.com", "russiandefpolicy.com", "russianmilitaryanalysis.com")
_add(3, "editorial", "lifestyle or veterans' interest, not procurement reporting",
     "coffeeordie.com", "taskandpurpose.com", "sandboxx.us")
_add(3, "editorial", "subscription tip sheet - claims cannot be checked from the page",
     "tacticalreport.com")

# --- not sources --------------------------------------------------------------
for _d, _why in PLATFORM_ARTEFACTS.items():
    TIERS[_d] = (0, "artefact", _why)

# Categories carry a default for anything not named above. This mirrors
# orchestrator/sources.py CATEGORY_TIER, which is the authority -- do not let the
# two drift, and do not add a third table.
CATEGORY_DEFAULT = {
    "gov_primary": 1, "tender_portal": 1, "defence_org": 1, "manufacturer_ir": 1,
    "trade_press": 2, "think_tank": 2, "business_press": 2,
    "aggregator": 3, "blog_forum_social": 3, "unknown": 0,
}

LABEL = {0: "unrated", 1: "stands alone", 2: "corroborate", 3: "lead only"}

# Government does not spell itself ".gov" outside the anglosphere. Japan uses
# go.jp, Korea go.kr, Canada gc.ca, France gouv.fr, Germany bund.de, Spain and
# Latin America gob.*, New Zealand govt.nz. A gov rule that only knows ".gov"
# is the same Latin-calibration mistake as an English-only keyword list -- and it
# would leave every non-anglophone ministry UNRATED on the day they are added.
_GOV_SUFFIXES = (
    ".gov", ".mil", ".int",
    ".go.jp", ".lg.jp", ".go.kr", ".go.id", ".go.th", ".go.tz",
    ".gc.ca", ".canada.ca", ".gouv.fr", ".gouv.qc.ca", ".bund.de", ".govt.nz",
    ".gob.es", ".gob.mx", ".gob.ar", ".gob.cl", ".gob.pe", ".gov.br",
    ".nic.in", ".europa.eu", ".admin.ch", ".overheid.nl", ".gv.at",
)


def _is_gov(d: str) -> bool:
    if d.endswith(_GOV_SUFFIXES):
        return True
    # gov.xx / mil.xx / gob.xx / gouv.xx for any country code
    parts = d.split(".")
    return len(parts) >= 3 and parts[-2] in ("gov", "mil", "gob", "gouv", "govt", "go")


def tier_of(domain: str, category: str | None = None):
    """(tier, basis, reason). Unknown domain in a known category takes the
    category default with basis 'category'; unknown domain in an unknown
    category is UNRATED, never tier 3."""
    d = (domain or "").lower().lstrip(".")
    if d.startswith("www."):
        d = d[4:]
    if d in TIERS:
        return TIERS[d]
    if _is_gov(d):
        return 1, "structural", "government or military domain"
    if category in CATEGORY_DEFAULT:
        t = CATEGORY_DEFAULT[category]
        return t, "category", "default for category %s" % category
    return 0, "unrated", "not assessed"


def demo():
    import collections
    c = collections.Counter(t for t, _, _ in TIERS.values())
    b = collections.Counter(bs for _, bs, _ in TIERS.values())
    print("  %d domains assigned: %s" % (len(TIERS), dict(sorted(c.items()))))
    print("  by basis: %s" % dict(b))

    # 1. an unknown domain must NOT land in tier 3 -- that is a fact invented
    #    about a source nobody has looked at
    t, basis, _ = tier_of("some-new-defence-site.example")
    assert t == 0 and basis == "unrated", (t, basis)

    # 2. a .gov domain is tier 1 without anyone editing this file, because the
    #    user is adding government sources and they must not need curation first
    for g in ("mod.gov.in", "defense.gov", "army.mil", "mod.go.jp"):
        t, basis, _ = tier_of(g)
        assert t == 1 and basis == "structural", (g, t, basis)

    # 3. the state-media call must be visible as an OWNERSHIP claim, not hidden
    #    inside an editorial judgement
    t, basis, _ = tier_of("tass.com")
    assert (t, basis) == (3, "ownership"), (t, basis)

    # 4. a platform artefact must not be tiered as if it were a publisher
    t, basis, _ = tier_of("blogspot.com")
    assert (t, basis) == (0, "artefact"), (t, basis)

    # 5. this file must not disagree with the orchestrator's own table
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]
                          / "orchestrator" / "src"))
    try:
        from mallory_orchestrator.sources import CATEGORY_TIER
    except Exception as e:                     # pragma: no cover - repo layout
        print("  (could not import CATEGORY_TIER: %s)" % e)
    else:
        for cat, t in CATEGORY_TIER.items():
            mine = CATEGORY_DEFAULT.get(cat)
            # 'unknown' is the one deliberate difference: theirs fails to 3,
            # this file fails to 0/unrated. Everything else must agree.
            if cat == "unknown":
                assert mine == 0, "unknown must be unrated here, not tier %s" % mine
                continue
            assert mine == t, "category %s: %s here vs %s in orchestrator" % (cat, mine, t)

    # 6. every named domain carries a reason -- a tier with no stated reason is
    #    an opinion pretending to be data
    assert all(r for _, _, r in TIERS.values()), "a domain was tiered without a reason"
    print("ok - %d tier-1, %d tier-2, %d tier-3, %d artefacts; "
          "%d of the calls are editorial judgement"
          % (c[1], c[2], c[3], c[0], b["editorial"]))


# ---------------------------------------------------------------------------------
# THE OTHER source_tiers.py, re-exported so that importing either one is correct.
#
# There are two files with this name. This one is the trust-tier table above (how much
# a claim weighs). extraction/engine/source_tiers.py is the PUBLISHABILITY rule (maker /
# government / two independent domains) and owns `domain` and `publishable`.
#
# Five scripts in this directory wrote `from source_tiers import domain, publishable`.
# From here that finds THIS module, which has neither, so discover_geo.py, revive_geo.py,
# discover_ties.py, revive_partners.py and mark_shared.py could not be imported at all --
# in the deployed image included, which is why the geo footprint fill could not be run on
# 2026-09-05. The same fault was found and worked around in revive_matchups.py and
# client_portfolio.py by loading the engine module by path, one file at a time.
#
# Re-exporting settles it for every caller instead: whichever source_tiers you reach,
# `tier_of` is the weight and `publishable`/`domain` are the rule. Loaded by path, not by
# import, because `import source_tiers` from the engine directory would find this file
# and recurse.
def _engine():
    import importlib.util
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "engine", "source_tiers.py")
    spec = importlib.util.spec_from_file_location("engine_source_tiers", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    _ENGINE = _engine()
    domain, publishable, maker_of = _ENGINE.domain, _ENGINE.publishable, _ENGINE.maker_of
except Exception as _e:                                               # noqa: BLE001
    # Never take this module down with it: `tier_of` has callers that need no rule.
    # A caller that needs `publishable` gets the ImportError it would have had anyway.
    _ENGINE = None
    print("source_tiers: engine rule unavailable (%s)" % _e, flush=True)


if __name__ == "__main__":
    demo()
