"""How much a source is worth, and what a spec value has to clear to be shown.

    python source_tiers.py --demo

A number on a positioning screen is a claim about a real weapon. The rule this
module enforces:

    A spec value may be SHOWN only if
      (a) an OFFICIAL source states it -- the manufacturer's own site, or a
          government/armed-forces/programme site, or
      (b) at least two INDEPENDENT sources state it (two different domains; two
          pages of one outlet are one witness, not two).
    Anything else is archived, not displayed.

`tier()` is deliberately domain-based rather than keyword-based: "official" is a
property of who published the page, and that is exactly what the domain records.
"""
import argparse
import sys
from urllib.parse import urlsplit

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OFFICIAL = "official"
REGISTRY = "registry"
NEWS = "news"

# Manufacturer sites. The maker publishing its own product's specification is the
# primary source for that specification; it is also, of course, the party with an
# interest in it, which is why the UI names the source rather than hiding it.
MAKER_DOMAINS = {
    # The client's OWN sites. kssl.in is the domain the client's portfolio workbook
    # cites on almost every row, and until 2026-09-05 it was not listed here -- so the
    # manufacturer's own specification page ranked as a news mention and needed a
    # second outlet to corroborate what it published about its own gun.
    "bharatforge.com": "Bharat Forge", "bharatforge.eu": "Bharat Forge",
    "kalyanistrategic.com": "Kalyani Strategic Systems",
    "kssl.in": "Kalyani Strategic Systems", "kssl.co.in": "Kalyani Strategic Systems",
    "baesystems.com": "BAE Systems", "knds.com": "KNDS", "knds.de": "KNDS",
    "knds.fr": "KNDS", "nexter-group.fr": "Nexter", "elbitsystems.com": "Elbit Systems",
    "hanwha.com": "Hanwha", "hanwhadefense.com": "Hanwha Defense",
    "saab.com": "Saab", "rheinmetall.com": "Rheinmetall",
    "rheinmetall-defence.com": "Rheinmetall", "leonardo.com": "Leonardo",
    "thalesgroup.com": "Thales", "gd.com": "General Dynamics",
    "gdls.com": "General Dynamics Land Systems", "oshkoshdefense.com": "Oshkosh Defense",
    "paramountgroup.com": "Paramount Group", "otokar.com.tr": "Otokar",
    "nurolmakina.com.tr": "Nurol Makina", "mkek.gov.tr": "MKE",
    "tataadvancedsystems.com": "Tata Advanced Systems", "larsentoubro.com": "Larsen & Toubro",
    "ltdefence.com": "L&T Defence", "mahindradefence.com": "Mahindra Defence",
    "adanidefence.com": "Adani Defence & Aerospace", "ashokleyland.com": "Ashok Leyland",
    "forcemotors.com": "Force Motors", "brahmos.com": "BrahMos Aerospace",
    "bel-india.in": "Bharat Electronics", "hal-india.co.in": "Hindustan Aeronautics",
    "solargroup.com": "Solar Industries", "zentechnologies.com": "Zen Technologies",
    "ideaforge.co.in": "ideaForge", "denel.co.za": "Denel", "patriagroup.com": "Patria",
    "diehl.com": "Diehl", "safran-group.com": "Safran", "norinco.com": "Norinco",
    "excaliburarmy.cz": "Excalibur Army", "milremrobotics.com": "Milrem",
    "aselsan.com.tr": "Aselsan", "roketsan.com.tr": "Roketsan",
}

# Government, armed forces and official programme publishers.
GOV_SUFFIX = (".gov", ".gov.in", ".mil", ".gov.uk", ".gouv.fr", ".gov.au", ".gc.ca",
              ".go.kr", ".go.jp", ".gov.tr", ".gov.za", ".gov.br", ".europa.eu")
GOV_EXACT = {"pib.gov.in", "mod.gov.in", "drdo.gov.in", "ddpmod.gov.in",
             "defense.gov", "army.mil", "dote.osd.mil", "nato.int", "eda.europa.eu"}

# Specialist defence reference publications. Not official, but edited, named and
# accountable -- worth more than a general news site, still needing corroboration.
REGISTRY_DOMAINS = {
    "army-technology.com", "armyrecognition.com", "navalnews.com",
    "airforce-technology.com", "naval-technology.com", "janes.com",
    "shephardmedia.com", "defensenews.com", "breakingdefense.com",
    "defensescoop.com", "militaryfactory.com", "deagel.com", "euro-sd.com",
    "esut.de", "defence24.pl", "asianmilitaryreview.com", "militaryleak.com",
    "defenceweb.co.za", "jpost.com", "flightglobal.com", "aviationweek.com",
    "defense-aerospace.com", "defence-industry.eu",
}


def domain(url):
    """-> registrable-ish host, lowercased, without www or a leading sub for maker sites."""
    if not url or "://" not in url:
        return ""
    h = urlsplit(url).netloc.lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def tier(url):
    """-> OFFICIAL | REGISTRY | NEWS."""
    h = domain(url)
    if not h:
        return NEWS
    if h in MAKER_DOMAINS or any(h.endswith("." + d) or h == d for d in MAKER_DOMAINS):
        return OFFICIAL
    if h in GOV_EXACT or h.endswith(GOV_SUFFIX):
        return OFFICIAL
    if h in REGISTRY_DOMAINS or any(h.endswith("." + d) for d in REGISTRY_DOMAINS):
        return REGISTRY
    return NEWS


def maker_of(url):
    """Which manufacturer publishes this domain, if any."""
    h = domain(url)
    for d, name in MAKER_DOMAINS.items():
        if h == d or h.endswith("." + d):
            return name
    return None


def publishable(urls, product_maker=None):
    """-> (ok, why, tier_used, n_independent).

    `product_maker` matters: an official page only counts as OFFICIAL FOR THIS
    PRODUCT when it is the product's own maker publishing it. Rheinmetall's site
    is not an authority on a KNDS gun, and treating it as one would let a rival's
    marketing set our numbers."""
    doms, tiers = set(), {}
    for u in urls or []:
        d = domain(u)
        if not d:
            continue
        doms.add(d)
        t = tier(u)
        if t == OFFICIAL and product_maker:
            who = maker_of(u)
            # a government source is official for anyone; a maker site only for its own
            if who and not _same_org(who, product_maker):
                t = REGISTRY
        tiers[d] = t
    if not doms:
        return False, "no source", None, 0
    if OFFICIAL in tiers.values():
        return True, "stated by an official source", OFFICIAL, len(doms)
    if len(doms) >= 2:
        return True, "corroborated by %d independent sources" % len(doms), \
            (REGISTRY if REGISTRY in tiers.values() else NEWS), len(doms)
    only = list(tiers.values())[0]
    return False, ("single %s source, uncorroborated" % only), only, 1


# Kalyani, KSSL and Bharat Forge are ONE client identity (Bharat Forge is the
# parent). Treating them as different companies made bharatforge.com a third-party
# source for a KSSL product, so the manufacturer's own specification was demoted
# and needed corroborating -- by outlets quoting that same page.
_CLIENT = ("kalyani", "kssl", "bharatforge", "bharatforgelimited", "bharatforgeltd")


def _same_org(a, b):
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    ca = any(c in na for c in _CLIENT)
    cb = any(c in nb for c in _CLIENT)
    return ca and cb


def _norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _demo():
    assert tier("https://www.bharatforge.com/x") == OFFICIAL
    assert tier("https://pib.gov.in/release") == OFFICIAL
    assert tier("https://www.army.mil/article/1") == OFFICIAL
    assert tier("https://www.armyrecognition.com/a") == REGISTRY
    assert tier("https://idrw.org/a") == NEWS
    assert tier("") == NEWS and tier(None) == NEWS
    assert maker_of("https://knds.de/en/p") == "KNDS"

    # one official source is enough
    ok, why, t, n = publishable(["https://knds.com/caesar"], "KNDS")
    assert ok and t == OFFICIAL, (ok, why, t)
    # ...but only when it is the PRODUCT'S OWN maker. A rival's site is not an
    # authority on this product, so it drops to registry and needs corroboration.
    ok2, _w, t2, _n = publishable(["https://rheinmetall.com/page"], "KNDS")
    assert not ok2 and t2 == REGISTRY, (ok2, t2)
    # two independent domains clear the bar
    ok3, why3, _t, n3 = publishable(
        ["https://armyrecognition.com/a", "https://euro-sd.com/b"], "KNDS")
    assert ok3 and n3 == 2 and "corroborated" in why3
    # two pages of ONE outlet are one witness
    ok4, _w, _t, n4 = publishable(
        ["https://idrw.org/a", "https://idrw.org/b"], "KNDS")
    assert not ok4 and n4 == 1
    assert not publishable([], "KNDS")[0]
    # the client group is one company: Bharat Forge's page IS official for a KSSL product
    ok5, _w, t5, _n = publishable(["https://www.bharatforge.com/defence"],
                                  "Kalyani Strategic Systems")
    assert ok5 and t5 == OFFICIAL, (ok5, t5)
    assert _same_org("Bharat Forge", "Kalyani Strategic Systems")
    assert not _same_org("KNDS", "BAE Systems")
    # a subsidiary-style name still matches its own site
    assert _same_org("BAE Systems", "BAE Systems Bofors")
    print("ok (%d maker domains, %d registries)" % (len(MAKER_DOMAINS),
                                                    len(REGISTRY_DOMAINS)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
    else:
        for u in ("https://bharatforge.com/p", "https://armyrecognition.com/x",
                  "https://idrw.org/y", "https://pib.gov.in/z"):
            print("%-40s %s" % (u, tier(u)))
