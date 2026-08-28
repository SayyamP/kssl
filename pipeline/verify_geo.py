"""Check every footprint row against the document it cites, and drop what fails.

    python verify_geo.py --dry
    python verify_geo.py --apply
    python verify_geo.py --demo

A geo row says: this company does THIS THING in THIS COUNTRY, and here is the page
that says so. Grounding checked the company and the country. The THING was never
checked against the cited page, and the audit found five rows where it does not
appear at all:

  * Tata "ALS-50 loitering munition" cited to an article about a Tata Motors
    mine-protected vehicle -- no ALS-50, no loitering munition anywhere in it,
    and a different Tata company. That row is also what gave Tata a UAV band and
    a "spec-confirmed overlap" with the client.
  * Adani "SkyStriker loitering munition, used in Op Sindoor" cited to the Adani
    Defence home page, which mentions neither.
  * BAE "Archer / M777 / naval, multi-billion" cited to a piece about Sweden
    funding Archer barrels for Ukraine.

The company and the country being right is what makes these convincing. The
product is the claim, and an unchecked claim beside a real citation is worse than
no row, because the citation vouches for it.

A row is kept when the distinctive words of its product name appear in its own
cited document. Distinctive is decided by the corpus, not by me: a word the corpus
uses everywhere ("systems", "defence", "vehicle") cannot confirm anything.
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg2

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from revive_matchups import load_docs, norm, index_df, DF                # noqa: E402
from revive_geo import claim_terms, country_forms, find_at             # noqa: E402
from revive_partners import COMMON_NAME, owner_at                        # noqa: E402

DSN = os.environ.get("KSSL_DSN", "postgresql://postgres:kssl@127.0.0.1:5460/kssl")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# discover_geo names its rows after the ACTIVITY, not a product ("Local
# production", "Export / supply"): there is no product claim in them to check, and
# reading the label as one failed rows whose activity was verified when written.
ACTIVITY_NAMES = {"local production", "export / supply", "service / mro",
                  "partnership / licence", "activity"}


def supported(text, name, note, comp_id, comp_name, country):
    """-> (ok, why). Does this document state THIS row's claim?"""
    if not text:
        return False, "cited document is not held"
    if (name or "").strip().lower() in ACTIVITY_NAMES:
        sharp = []
    else:
        sharp, _kw = claim_terms(name, comp_id, comp_name, country)
    rare = [t for t in sharp if DF.get(t, 0.0) and DF[t] < COMMON_NAME]
    if not rare:
        # nothing distinctive to check -- fall back to the two facts grounding did
        # establish, so the row still has to be about this company and this country
        # owner_at, not company_at: it knows the alias list, and "L&T" reduces to
        # two one-letter tokens that match nothing without it
        if owner_at(text, comp_id, comp_name) < 0:
            return False, "the company is not named in its own source"
        if find_at(text, country_forms(country)) < 0:
            return False, "the country is not named in its own source"
        return True, "no distinctive product term to check"
    hit = [t for t in rare if t in text]
    if not hit:
        return False, "none of %s appears in the cited page" % "/".join(rare[:3])
    return True, "cited page names %s" % "/".join(hit[:3])


def main(apply=False):
    con = psycopg2.connect(DSN)
    cur = con.cursor()
    docs = load_docs(cur)
    by_url = {}
    for _d, u, t in docs:
        by_url.setdefault(u, t)
    cur.execute("""SELECT p.comp_id, c.name, p.country, p.name, p.note, p.src, p.ord
                     FROM serving.geo_presence p
                     LEFT JOIN serving.geo_comp c ON c.id = p.comp_id
                    WHERE p.origin='pipeline'
                    ORDER BY p.ord""")
    rows = cur.fetchall()
    index_df(docs, [t for r in rows
                    for t in claim_terms(r[3], r[0], r[1], r[2])[0]])
    keep, drop = [], []
    for comp_id, comp_name, country, name, note, src, ord_ in rows:
        ok, why = supported(by_url.get(src, ""), name, note, comp_id,
                            comp_name or comp_id, country)
        (keep if ok else drop).append((comp_id, country, name, src, why, ord_))

    print("%d pipeline footprint row(s): %d supported, %d not\n"
          % (len(rows), len(keep), len(drop)))
    for comp_id, country, name, src, why, _o in drop:
        print("  DROP %-22s %-12s %-34s %s" % (comp_id[:22], country[:12],
                                               str(name)[:34], why))
    print()
    for comp_id, country, name, src, why, _o in keep[:8]:
        print("  keep %-22s %-12s %-34s %s" % (comp_id[:22], country[:12],
                                               str(name)[:34], why))

    if apply and drop:
        for comp_id, country, _n, _s, _w, ord_ in drop:
            cur.execute("""DELETE FROM serving.geo_presence
                            WHERE origin='pipeline' AND comp_id=%s AND ord=%s""",
                        (comp_id, ord_))
        con.commit()
        print("\ndeleted %d unsupported row(s)." % len(drop))
    elif not apply:
        print("\n(dry run -- nothing written)")
    con.close()
    return drop


def _demo():
    mpv = norm("Tata Motors unveiled its 4x4 mine protected vehicle for the Indian "
               "Army, built at its Pune plant.")
    als = norm("Tata Advanced Systems delivered the ALS-50 loitering munition to "
               "the Indian Air Force after trials.")
    DF.update({"als": 0.002, "loitering": 0.01, "protected": 0.4, "vehicle": 0.5})
    ok, why = supported(mpv, "ALS-50 loitering munition", None,
                        "tata-advanced-systems", "Tata Advanced Systems", "India")
    assert not ok, why
    ok, why = supported(als, "ALS-50 loitering munition", None,
                        "tata-advanced-systems", "Tata Advanced Systems", "India")
    assert ok, why
    # a product named only by generic words cannot be checked -- but the company and
    # the country still have to be in the page
    ok, why = supported(als, "Defence systems", None, "tata-advanced-systems",
                        "Tata Advanced Systems", "India")
    assert ok and "no distinctive" in why, why
    ok, why = supported(norm("a page about something else entirely"), "Defence systems",
                        None, "tata-advanced-systems", "Tata Advanced Systems", "India")
    assert not ok, why
    # a row whose document we do not hold cannot be verified, so it is not kept
    assert not supported("", "ALS-50", None, "x", "X", "India")[0]
    # an activity-named row carries no product claim; it is checked on company and
    # country, which is what it actually asserts
    ok, why = supported(als, "Local production", None, "tata-advanced-systems",
                        "Tata Advanced Systems", "India")
    assert ok and "no distinctive" in why, why
    # ...and a company known by an abbreviation is still named: "L&T" reduces to two
    # one-letter tokens, and checking it without the alias list dropped a good row
    lt = norm("larsen & toubro will assemble the k9 vajra in india at hazira.")
    assert supported(lt, "Local production", None, "l-t", "L&T", "India")[0]
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    _demo() if a.demo else main(a.apply)
