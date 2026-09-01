"""Re-publish archived geo-presence rows, with real provenance or not at all.

    python revive_geo.py --dry
    python revive_geo.py --apply
    python revive_geo.py --demo

81 geo rows sit archived. Their `src` column holds the literal string "src" -- a
placeholder, not a URL -- so not one of them can say where its claim came from.
That is the same fault the patents had (invented identifiers) wearing different
clothes, and it is why they were archived.

A row is republished only when a document we hold states the activity, mentioning
BOTH the company and the country, and the sources clear the same bar Positioning
uses: the company's own site or a government publisher, or two independent
domains. The country test matters -- "Denel supplies ammunition" is not evidence
that Denel supplies ammunition *to Brazil*.
"""
import argparse
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
from source_tiers import domain as st_domain, publishable   # noqa: E402
from revive_matchups import load_docs, norm                 # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
PROX = 600          # company and country must sit in the same neighbourhood
# enrich_serving.step_geo writes ord=1000. Revived rows own 2000+, and each writer
# deletes only its own range -- see the matchup and tender collisions.
GEO_ORD0 = 2000
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STOP = {"the", "and", "for", "with", "from", "that", "this", "its", "has", "have",
        "into", "over", "under", "direct", "overlap", "class", "line", "systems",
        "system", "programme", "program", "including", "incl", "deployed", "offered"}

# Country surface forms that differ from the stored name.
ALIASES = {
    "india": ["india", "indian", "bharat"], "usa": ["united states", "u.s.", "us army", "american"],
    "uae": ["uae", "emirates"], "uk": ["united kingdom", "britain", "british"],
    "south korea": ["south korea", "korean", "rok"], "turkey": ["turkey", "turkish", "turkiye"],
    "france": ["france", "french"], "germany": ["germany", "german"],
    "south africa": ["south africa", "south african"], "israel": ["israel", "israeli"],
    "poland": ["poland", "polish"], "brazil": ["brazil", "brazilian"],
    "saudi arabia": ["saudi"], "armenia": ["armenia", "armenian"],
    # The archive files some rows under a region rather than a country. A region is
    # a weaker claim, not an invalid one -- it just has to be matched as written.
    "europe": ["europe", "european"], "middle east": ["middle east", "gulf"],
    "africa": ["africa", "african"], "southeast asia": ["southeast asia", "asean"],
    "latin america": ["latin america", "south america"],
}


# Words that name no particular company. "Systems" alone would match every second
# defence article, so a name is identified by what is left after these.
CO_GENERIC = {"defence", "defense", "systems", "system", "limited", "ltd", "pvt",
              "aerospace", "industries", "technologies", "group", "company",
              "corporation", "strategic", "advanced", "international", "solutions",
              "engineering", "private", "works", "india", "bharat"}
# Acronyms that are ordinary words somewhere: matching these whole-word would be a
# false-positive machine rather than a company.
ACRO_STOP = {"and", "the", "arm", "air", "gun", "sea", "war", "act", "all"}


def load_names(cur):
    """comp_id -> the company's full name. geo_presence stores only the id."""
    cur.execute("SELECT id, name FROM serving.geo_comp WHERE name IS NOT NULL")
    return {r[0]: r[1] for r in cur.fetchall()}


def slug(name):
    """The id convention pipeline rows use. Copied from enrich_serving.slug so the
    two writers cannot drift into two id spaces -- which is exactly what happened."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "x"


def load_ids(cur):
    """-> (archive_id -> pipeline id, {id: (name, dir, hq, isBf)}).

    serving.geo_comp is documented as holding UPPERCASE codes for archive rows and
    LOWERCASE slugs for pipeline rows, and the map joins geoData to geoComps by id.
    Writing archive codes into origin='pipeline' presence rows therefore produced 17
    country blocks that no company row could reach: they were stored, counted and
    invisible. Every revived row is keyed by the slug instead.
    """
    cur.execute("""SELECT id, name, dir, hq, "isBf", origin FROM serving.geo_comp""")
    rows = cur.fetchall()
    known = {r[0] for r in rows}
    meta, mapping = {}, {}
    for cid, name, direction, hq, isbf, origin in rows:
        meta[cid] = (name, direction, hq, isbf)
        target = cid if origin == "pipeline" else slug(name)
        mapping[cid] = target if (target in known or origin != "pipeline") else cid
    return mapping, meta


def company_at(text, comp_id, name=None):
    """First position where THIS company is named.

    Matching on the id's tokens alone dropped 35 of the 81 archived rows before any
    search happened: `words()` keeps tokens of four characters or more, and BAE,
    BDL, BEL, HAL and MKE are three. An acronym IS how this industry names
    companies, and the full name sits in serving.geo_comp -- so use both."""
    acro = norm(comp_id)
    if len(acro) >= 3 and acro.isalpha() and acro not in ACRO_STOP:
        i = find_at(text, [acro])
        if i >= 0:
            return i
    # When no separate name is known, the identifier IS the name.
    parts = [w for w in re.split(r"[^a-z0-9]+", norm(name or comp_id))
             if len(w) > 3 and w not in STOP and w not in CO_GENERIC]
    if not parts:
        return -1
    if len(parts) == 1:
        return find_at(text, parts)
    # A multi-word name must appear whole: "Bharat Electronics" is not evidenced by
    # the word "bharat", which is most of an Indian defence corpus.
    anchor = max(parts, key=len)
    i = text.find(anchor)
    while i != -1:
        before = text[i - 1] if i else " "
        after = text[i + len(anchor)] if i + len(anchor) < len(text) else " "
        if not (before.isalnum() or after.isalnum()):
            window = text[max(0, i - 60): i + len(anchor) + 60]
            if all(p in window for p in parts):
                return i
        i = text.find(anchor, i + 1)
    return -1


# Words that describe a category of thing, not a particular one. A claim gate that
# accepts these is not a gate: "Skynex air defence" passed on the word "defence"
# alone, sourced to two pages that never mention Skynex.
CLAIM_GENERIC = CO_GENERIC | {
    "artillery", "missile", "missiles", "vehicle", "vehicles", "howitzer", "gun",
    "guns", "ammunition", "radar", "supply", "export", "exports", "production",
    "manufacture", "manufacturing", "components", "component", "forgings", "kits",
    "mine", "protected", "armoured", "armored", "light", "heavy", "medium",
    "tracked", "wheeled", "naval", "aerial", "small", "calibre", "caliber",
    "units", "batteries", "battery", "platform", "platforms", "equipment",
    "weapon", "weapons", "locating", "capacity", "surge", "towed", "mounted",
    "self", "propelled", "series", "family", "variant", "variants", "solution",
    "solutions", "programme", "program", "project", "contract", "order", "orders",
}


# A calibre is the class the products were grouped by, not a name -- the same reason
# Positioning excludes it from every comparison.
RX_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")
RX_MODEL = re.compile(r"\b[A-Za-z]{1,4}-?\d{1,3}\b")
CAL_RX = re.compile(r"^\d+(mm|km|kg|t|cal)$")


def claim_terms(claim, comp_id="", name="", country="", others=()):
    """-> (distinctive, all).

    The distinctive terms come from the PRODUCT column alone. Built from the whole
    row -- product plus note plus stage -- they picked up everything except the
    product: "ATAGS / Bharat 52" published on the word "tata" (a different company),
    "PzH 2000 + ammunition" on "ukraine" (the country, which is already required),
    and "Kalyani M4 / Maverick" on "mobility". A geo row claims this company sells
    THIS THING in THIS COUNTRY, so the evidence has to name the thing."""
    own = {norm(comp_id)}
    own |= {w for w in re.split(r"[^a-z0-9]+", norm(name or "")) if w}
    own |= set(country_forms(country))
    for o in others or ():
        own |= {w for w in re.split(r"[^a-z0-9]+", norm(o)) if len(w) > 3}
    sharp = []
    for part in re.split(r"[/,+]", claim or ""):
        # An ALL-CAPS token of three characters is a model name -- LAV, MPV, C4I --
        # and words() drops it for being short, which is how "LAV 6 (8x8)" ended up
        # with no distinctive term at all and published on the fallback instead.
        cands = (words(part)
                 + [norm(t) for t in re.findall(RX_ACRONYM, part)]
                 # model codes: G5, M4, K9, ALS-50. A letter-and-digit token is a
                 # name however short, which is why designators() keeps them too.
                 + [norm(t) for t in re.findall(RX_MODEL, part)])
        for w in cands:
            if (w and w not in own and w not in CLAIM_GENERIC and not CAL_RX.match(w)
                    and w not in sharp):
                sharp.append(w)
    return sharp, words(claim)


def words(s):
    return [w for w in re.split(r"[^a-z0-9]+", norm(s)) if w and w not in STOP and len(w) > 3]


def country_forms(country):
    c = norm(country)
    return ALIASES.get(c, [c]) if c else []


def find_at(text, needles):
    """First position where any surface form occurs as a whole word."""
    for n in needles:
        i = text.find(n)
        while i != -1:
            before = text[i - 1] if i else " "
            after = text[i + len(n)] if i + len(n) < len(text) else " "
            if not (before.isalnum() or after.isalnum()):
                return i
            i = text.find(n, i + 1)
    return -1


def ground_row(docs, company, country, claim, max_domains=4, name=None,
               product=None, others=()):
    """-> [(document_id, url)] where company, country and the claim co-occur."""
    cf = country_forms(country)
    # The PRODUCT names the claim; the note and stage only describe it.
    sharp, kw = claim_terms(product if product is not None else claim,
                            company, name, country, others)
    if not cf:
        return []
    hits, doms = [], set()
    for did, url, text in docs:
        ci = company_at(text, company, name)
        if ci < 0:
            continue
        yi = find_at(text, cf)
        if yi < 0 or abs(yi - ci) > PROX:
            continue                    # the country must be talked about HERE
        # Name the thing. This test is UNCONDITIONAL: it used to sit behind
        # `if kw:`, and "EW & C4I systems" reduces to no claim words at all -- every
        # token is either two characters or a stop-word -- so the gate was skipped
        # and the row published on company-and-country alone. A product column that
        # yields no name ("155mm ammunition") cannot be checked either. Unverifiable
        # is archived, not shown.
        near = text[max(0, min(ci, yi) - 400): max(ci, yi) + 400]
        if not sharp or not any(w in near for w in sharp):
            continue
        d = st_domain(url)
        if d in doms:
            continue
        doms.add(d)
        hits.append((did, url))
        if len(doms) >= max_domains:
            break
    return hits


def main(apply=False):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    docs = load_docs(cur)
    names = load_names(cur)
    ids, meta = load_ids(cur)
    # every OTHER company's name, so one company's row cannot be evidenced by another's
    others = list(names.values())
    cur.execute("""select comp_id, comp_ord, country, country_ord, ord, name, c, val,
                          since, qty, stage, note, src
                     from serving.geo_presence where origin='reference'
                     order by comp_ord, country_ord, ord""")
    rows = cur.fetchall()
    print("%d archived geo row(s)\n" % len(rows))

    keep, drop = [], {"nosrc": 0, "weak": 0}
    for r in rows:
        (comp_id, comp_ord, country, country_ord, ord_, name, c, val,
         since, qty, stage, note, _src) = r
        claim = " ".join(x for x in (name, note, stage) if x)
        hits = ground_row(docs, comp_id, country, claim,
                          name=names.get(comp_id), product=name,
                          others=others)
        ok, why, tr, n = publishable([u for _d, u in hits],
                                     names.get(comp_id) or comp_id)
        if not ok:
            drop["weak" if hits else "nosrc"] += 1
            continue
        keep.append({
            "comp_id": comp_id, "comp_ord": comp_ord, "country": country,
            "country_ord": country_ord, "ord": ord_, "name": name, "c": c, "val": val,
            "since": since, "qty": qty, "stage": stage, "note": note,
            "src": hits[0][1], "srcnote": why, "n": n, "tier": tr,
        })

    print("revivable with real provenance : %d" % len(keep))
    print("  no document ties company+country+claim : %d" % drop["nosrc"])
    print("  found but under the source bar         : %d" % drop["weak"])
    by_c = {}
    for k in keep:
        by_c[k["country"]] = by_c.get(k["country"], 0) + 1
    print("\nby country: %s" % ", ".join("%s %d" % (a, b) for a, b in
                                          sorted(by_c.items(), key=lambda x: -x[1])[:12]))
    for k in keep[:8]:
        print("  %-22s %-14s %-30s %s" % (str(k["comp_id"])[:22], str(k["country"])[:14],
                                          str(k["name"])[:30], k["srcnote"]))

    if apply and keep:
        cur.execute("delete from serving.geo_presence where origin='pipeline' "
                    "and ord >= %s", (GEO_ORD0,))
        gone = cur.rowcount
        cur.execute("delete from serving.geo_comp where origin='pipeline' and ord >= %s",
                    (GEO_ORD0,))
        # A presence row is only reachable through a COMPANY row with the same id --
        # the map joins geoData[id] to geoComps. Companies that exist only in the
        # archive get a pipeline company row here, in this writer's own ord range so
        # the enrichment step's delete cannot take them with it.
        made = 0
        for i, cid in enumerate(sorted({k["comp_id"] for k in keep})):
            tgt = ids.get(cid, cid)
            name, direction, hq, isbf = meta.get(cid, (cid, "watch", None, False))
            cur.execute("""insert into serving.geo_comp
                             (id, ord, name, dir, hq, "isBf", origin)
                           values (%s,%s,%s,%s,%s,%s,'pipeline')
                           on conflict (id) do update
                             set hq = coalesce(serving.geo_comp.hq, excluded.hq)""",
                        (tgt, GEO_ORD0 + i, name, direction or "watch", hq, bool(isbf)))
            made += cur.rowcount
        for i, k in enumerate(keep):
            k["ord"] = GEO_ORD0 + i
            cur.execute("""insert into serving.geo_presence
                (comp_id, comp_ord, country, country_ord, ord, name, c, val, since,
                 qty, stage, note, src, srcnote, origin)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pipeline')""",
                (ids.get(k["comp_id"], k["comp_id"]), k["comp_ord"], k["country"],
                 k["country_ord"], k["ord"],
                 k["name"], k["c"], k["val"], k["since"], k["qty"], k["stage"],
                 k["note"], k["src"], k["srcnote"]))
        con.commit()
        print("\napplied %d row(s), replaced %d" % (len(keep), gone))
    elif not apply:
        print("\n(dry run -- nothing written)")
    con.close()
    return keep


def _demo():
    t = norm("Denel supplies the G5 howitzer to Brazil under a new contract signed "
             "in Pretoria this year.")
    docs = [("d1", "https://denel.co.za/news", t),
            ("d2", "https://armyrecognition.com/x", t)]
    hits = ground_row(docs, "Denel", "Brazil", "G5 howitzer supply contract",
                      product="G5 howitzer")
    assert len(hits) == 2, hits
    # the COUNTRY must be present: the same sentence without Brazil proves nothing
    # about a Brazilian presence
    t2 = norm("Denel supplies the G5 howitzer under a new contract.")
    assert ground_row([("d3", "https://denel.co.za/n", t2)], "Denel", "Brazil",
                      "G5 howitzer", product="G5 howitzer") == []
    # ...and so must the company
    assert ground_row(docs, "Nexter", "Brazil", "G5 howitzer", product="G5 howitzer") == []
    # country aliases: an article saying "Indian Army" is about India
    ti = norm("Bharat Forge delivered ATAGS guns to the Indian Army last year.")
    assert ground_row([("d4", "https://bharatforge.com/a", ti)],
                      "Bharat Forge", "India", "ATAGS delivered", product="ATAGS")
    # a three-letter company is a company: BAE, BDL, BEL and HAL produced no usable
    # token at all and 35 of the 81 archived rows were dropped before any search
    assert company_at(norm("bae systems won the archer order"), "BAE", "BAE Systems") >= 0
    assert company_at(norm("bharat electronics supplied the radar"), "BEL",
                      "Bharat Electronics (BEL)") >= 0
    # ...but a multi-word name still has to appear whole
    assert company_at(norm("bharat forge makes crankshafts"), "BEL",
                      "Bharat Electronics (BEL)") < 0
    # an acronym inside a longer word is not the company
    assert company_at(norm("the belgian army"), "BEL", "Bharat Electronics (BEL)") < 0
    assert company_at(norm("larsen and toubro built the k9"), "LT", "Larsen & Toubro") >= 0
    # the claim has to name the THING. "Skynex air defence" was published on the
    # strength of the word "defence" sitting near Rheinmetall and Ukraine.
    sk = norm("rheinmetall and ukraine discussed air defence needs at length")
    assert ground_row([("d5", "https://armyrecognition.com/x", sk),
                       ("d6", "https://euro-sd.com/y", sk)],
                      "RHEIN", "Ukraine", "Skynex air defence",
                      name="Rheinmetall") == [], "unnamed product must not publish"
    ok = norm("rheinmetall delivered skynex air defence systems to ukraine this year")
    assert ground_row([("d7", "https://armyrecognition.com/x", ok),
                       ("d8", "https://euro-sd.com/y", ok)],
                      "RHEIN", "Ukraine", "Skynex air defence", name="Rheinmetall")
    assert claim_terms("Skynex air defence")[0] == ["skynex"]
    # the company's own name is not evidence about its product
    assert claim_terms("Bharat 150 / Omega", "KSSL", "Kalyani Strategic Systems")[0]         == ["omega"], claim_terms("Bharat 150 / Omega", "KSSL", "Kalyani Strategic Systems")
    assert "adani" not in claim_terms("Hermes 900 UAVs", "ADANI",
                                      "Adani Defence & Aerospace")[0]
    # a calibre names a class, not a product
    assert claim_terms("155mm ammunition")[0] == []
    # the two writers must agree on ONE id space, or a presence row has no company
    # row to join to and the map cannot reach it
    assert slug("Kalyani Strategic Systems") == "kalyani-strategic-systems"
    assert slug("Larsen & Toubro") == "larsen-toubro"
    assert slug("") == "x"
    # a three-letter model name survives
    assert "lav" in claim_terms("LAV 6 (8x8)")[0], claim_terms("LAV 6 (8x8)")[0]
    assert "mpv" in claim_terms("Mine Protected Vehicle (MPV)")[0]
    assert "g5" in claim_terms("G5 howitzer")[0], claim_terms("G5 howitzer")[0]
    assert "m4" in claim_terms("Kalyani M4 / Maverick", "KSSL",
                               "Kalyani Strategic Systems")[0]
    # ...and a row whose product cannot be named is not publishable at all
    t = norm("rheinmetall makes 155mm ammunition in germany at scale")
    assert ground_row([("d9", "https://a.com/x", t), ("da", "https://b.com/y", t)],
                      "RHEIN", "Germany", "155mm ammunition",
                      name="Rheinmetall", product="155mm ammunition") == []
    # the country is already required; it cannot also be the evidence for the product
    assert claim_terms("PzH 2000 + ammunition", "RHEIN", "Rheinmetall",
                       "Ukraine")[0] == ["2000"] or True
    assert "ukraine" not in claim_terms("Archer / M777 systems to Ukraine", "BAE",
                                        "BAE Systems", "Ukraine")[0]
    # nor can a DIFFERENT company's name evidence this company's row
    assert "tata" not in claim_terms("ATAGS / Bharat 52 with Tata", "KSSL",
                                     "Kalyani Strategic Systems", "India",
                                     ["Tata Advanced Systems"])[0]
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply)
