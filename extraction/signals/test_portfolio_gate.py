# -*- coding: utf-8 -*-
"""The KSSL portfolio rules, under test -- built from the cases that actually went wrong.

    python test_portfolio_gate.py

deploy/selfcheck.sh runs `for t in test_*.py`, so this file existing is the whole
wiring: it gates a pull request and a push to main.

EVERY FIXTURE BELOW IS A REAL ROW OR A REAL SENTENCE from this repository. Nothing here
was invented to pass:

  * "Bayonet" and "Cleaver" as KSSL products -- 138 and 135 occurrences inside
    extraction/reference_dataset.json, zero rows in the client's own workbook, and a
    corpus check that found every "Cleaver" was "Sian Cleaver, an Airbus engineer".
  * "AAROK" -- reference_dataset.json says "AAROK is a Turgis & Gaillard MALE design
    offered under a 2025 MoU, not a KSSL product" in /geoData/KSSL/India/2/note, and
    four other strings in the SAME FILE call it "KSSL's airframe portfolio (AAROK MALE,
    Omega)".
  * the FN Herstal row and the Ultra UAV row -- rows 26 and 59 of
    portfolio/kssl_portfolio.json, with the sources they actually cite.
  * "Shell forgings" -- the opposite error, and it is on the live path today.

Hermetic: no database, no network, no model.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_portfolio as cp                                       # noqa: E402
import portfolio_gate as pg                                        # noqa: E402

# A workbook stub with the shape client_portfolio.py writes. Real names, real ids.
WORKBOOK = [
    {"product_id": "kalyani-m4", "name": "Kalyani M4",
     "sources": ["https://www.kssl.in/protected-vehicles"]},
    {"product_id": "bharat-150-uav", "name": "Bharat 150 UAV",
     "sources": ["https://www.kssl.in/uav"]},
    {"product_id": "protective-carbine-5-56-30-mm", "name": "Protective Carbine - 5.56 x 30 mm",
     "sources": ["https://www.kssl.in/small-arms"],
     # the ONE occurrence of the string "bayonet" anywhere in the client's workbook
     "specs": [{"k": None, "v": "Compatible with silencer, bayonet and blank-firing attachment",
                "note": None, "ctx": None}]},
    {"product_id": "high-explosive-he-artillery-shells", "name": "High Explosive (HE) Artillery Shells",
     "sources": ["https://www.kssl.in/ammunition"]},
    {"product_id": "illuminating-artillery-shells", "name": "Illuminating Artillery Shells",
     "sources": ["https://www.kssl.in/ammunition"]},
    {"product_id": "incendiary-artillery-shells", "name": "Incendiary Artillery Shells",
     "sources": ["https://www.kssl.in/ammunition"]},
    {"product_id": "smoke-artillery-shells", "name": "Smoke Artillery Shells",
     "sources": ["https://www.kssl.in/ammunition"]},
]

# reference_dataset.json, verbatim. The first two are the disclaimer; the last three are
# the same file contradicting it.
AAROK_PROSE = [
    "KSSL UAV line: Bharat 150 and Omega tactical ISR. AAROK is a Turgis & Gaillard MALE "
    "design offered under a 2025 MoU, not a KSSL product.",
    "Omega tactical ISR (Jan 2026 EP-VI contract) and the Bharat 150. AAROK remains a "
    "Turgis & Gaillard partnership offer, not a KSSL product to counter with.",
    "KSSL is developing indigenous UAV propulsion (KGT-45 gas-turbine engine) to pair with "
    "its airframe portfolio (AAROK MALE, Omega), reducing reliance on foreign engines.",
    "At Rs 30,000cr for 87 aircraft, this is the single largest UAV demand event in the "
    "dataset -- the indigenous MALE class KSSL's AAROK/Omega targets.",
    "Confirm KSSL AAROK/Omega meets the Rs 30,000cr tender's indigenous-content thresholds "
    "before submission.",
]

# portfolio/kssl_portfolio.json rows 26 and 59, with their real sole sources.
FN_HERSTAL = {
    "name": "FN Herstal Integrated Weapon Mounts / C-UAS Turrets",
    "file_category": "Small Arms", "cat": "Small Arms", "specs": [], "features": [],
    "sources": ["https://fnherstal.com/en/news/kalyani-strategic-systems-partners-with-"
                "fn-herstal-to-build-small-arms-and-counter-uas-capability-in-india/"],
}
ULTRA_UAV = {
    "name": "Ultra UAV / Precision Loitering Munition",
    "file_category": "UAVs & Drones", "cat": "UAVs & Drones", "specs": [], "features": [],
    "sources": ["https://scanx.trade/stock-market-news/orders-deals/bharat-forge-subsidiary-"
                "inks-landmark-artillery-deal-with-uae-firm/19143608"],
}


# ---------------------------------------------------------------------------
def test_a_mention_count_is_not_evidence():
    """THE BAYONET DECISION, with the number it was actually made on.

    "Bayonet" was carried as a KSSL product because it occurs 138 times inside
    extraction/reference_dataset.json -- a file this project wrote. Repetition inside a
    curated file is not corroboration; it is one author, 138 times. attest() takes the
    count and must refuse to let it decide anything.
    """
    ok, why = pg.attest("KSSL · Bayonet", WORKBOOK)
    assert not ok, why
    ok2, why2 = pg.attest("KSSL · Bayonet", WORKBOOK, mentions=138)
    assert not ok2, "138 mentions attested a product that is in no workbook row: %s" % why2
    assert why2 != why or "ignored" in why2, \
        "the refusal must SAY the count was ignored, or the guard is invisible: %r" % why2
    # and the count cannot flip a real product either way
    assert pg.attest("KSSL · M4", WORKBOOK, mentions=0)[0]
    assert pg.attest("KSSL · M4", WORKBOOK, mentions=999)[0]


def test_a_common_word_near_kssl_is_not_a_product():
    """THE CLEAVER CASE. Every corpus hit for "Cleaver" was "Sian Cleaver, an Airbus
    engineer", and "bayonet" appears in the client's own workbook exactly once -- as a
    lug on the Protective Carbine, inside a spec bullet.

    Two things have to hold. A one-token name must be marked as ungroundable in free
    text, and -- more important -- there must be NO path from text to attestation at
    all, so a name sitting inside another product's spec bullet cannot become a product.
    """
    assert pg.one_token("Cleaver") and pg.one_token("Bayonet") and pg.one_token("Omega")
    assert not pg.one_token("Kalyani M4")
    for name in ("Cleaver", "Bayonet", "Omega", "MRAUV"):
        ok, why = pg.attest(name, WORKBOOK, mentions=135)
        assert not ok, "%s attested: %s" % (name, why)
    # the workbook row that CONTAINS the word "bayonet" must not lend its name away
    assert pg.attest("Bayonet", WORKBOOK)[0] is False
    assert pg.attest("Protective Carbine", WORKBOOK)[0] is True


def test_an_mou_offer_is_not_ownership():
    """THE AAROK CASE. A file that contradicts itself is not a source, and the
    disclaimer is the half that is a finding about ownership."""
    dm = pg.denials(AAROK_PROSE)
    assert "AAROK" in dm, dm
    banned, sent = pg.denied("KSSL · AAROK", dm)
    assert banned and "not a KSSL product" in sent, (banned, sent)
    # the four contradicting sentences in the same list must not undo it
    assert pg.denied("AAROK", pg.denials(AAROK_PROSE[2:] + AAROK_PROSE[:2]))[0]
    # and it must not ban a real product that merely appears near it
    assert not pg.denied("Kalyani M4", dm)[0]
    assert not pg.denied("Bharat 150 UAV", dm)[0]


def test_a_partners_announcement_is_not_a_product_page():
    """FN Herstal row. The sole citation is the OTHER company's own site announcing that
    the two firms will build something together. That is a relationship."""
    offered, why = pg.offer_only(FN_HERSTAL)
    assert offered, "a partnership announcement was read as a product page"
    assert "fnherstal.com" in why, why
    assert any(sev == "ban" for sev, _r, _w in pg.audit_row(FN_HERSTAL)), \
        pg.audit_row(FN_HERSTAL)
    # the client's own page beside it settles it the other way
    assert not pg.offer_only(dict(FN_HERSTAL,
                                  sources=FN_HERSTAL["sources"] + ["https://www.kssl.in/small-arms"]))[0]


def test_evidence_must_be_about_this_product():
    """Ultra UAV row. Its whole evidence is an article about an ARTILLERY deal with a UAE
    firm. Evidence for the company is not evidence for the product."""
    ok, why = pg.source_verdict(ULTRA_UAV)
    assert not ok, "a single uncorroborated news source cleared the bar: %s" % why
    ok, why = pg.entails(ULTRA_UAV)
    assert not ok, "an artillery headline entailed a loitering munition: %s" % why
    assert any(sev == "hold" for sev, _r, _w in pg.audit_row(ULTRA_UAV))


def test_an_opaque_url_is_not_a_refusal():
    """THE OTHER WAY TO BE WRONG. ddpmod.gov.in/hi/node/7501 is a real government product
    page for the HMRV and its URL contains no words at all. A rule that reads URLs must
    say "not judged" there, not "refused"."""
    hmrv = {"name": "High Mobility Reconnaissance Vehicle - HMRV",
            "cat": "Protected & Armoured Vehicles",
            "sources": ["https://www.ddpmod.gov.in/hi/node/7501",
                        "https://registro.feindefevent.com/feindef2025/en/Products/Details/1339262"]}
    assert pg.entails(hmrv)[0], pg.entails(hmrv)
    assert pg.source_verdict(hmrv)[0], pg.source_verdict(hmrv)
    assert not [s for s, _r, _w in pg.audit_row(hmrv) if s in ("ban", "hold")], pg.audit_row(hmrv)
    # ...and the guard has to hold on its OWN. Above, ddpmod.gov.in is a government
    # publisher and entails() returns before it ever looks at a URL's words, so that
    # assertion passes with the guard removed. This one has only the exhibitor page --
    # news tier, and a path whose only word is "feindef2025".
    only_opaque = dict(hmrv, sources=[hmrv["sources"][1]])
    assert pg.entails(only_opaque)[0], \
        "an opaque path was judged on words it does not have: %s" % (pg.entails(only_opaque),)
    assert "not judged" in pg.entails(only_opaque)[1], pg.entails(only_opaque)


def test_a_group_line_is_not_an_unattested_name():
    """"Shell forgings" is FOUR workbook rows (HE / illuminating / incendiary / smoke)
    sharing one calibre range, and there is no workbook row of that name for a name
    comparison to find. Refusing a real client line costs exactly what publishing a fake
    one costs, so the gate must tell "absent" from "grouped"."""
    assert pg.attest("KSSL · Shell forgings", WORKBOOK)[0]
    assert pg.audit_anchor("KSSL · Shell forgings", WORKBOOK)[0] == "group_only"
    assert pg.audit_anchor("KSSL · M4", WORKBOOK)[0] == "ok"
    assert pg.audit_anchor("KSSL · Bayonet", WORKBOOK)[0] == "not_a_client_product"


def test_being_unable_to_check_is_not_having_checked():
    """An empty portfolio is the state of a database whose serving.client_product has
    not been loaded -- which is exactly when an unchecked name gets published."""
    ok, why = pg.attest("Kalyani M4", [])
    assert not ok and "unable to check" in why, why
    _keep, drop, _g = cp.classify_pairings([(1, "M4", "KSSL · M4")], [], {})
    assert len(drop) == 1, "an empty portfolio admitted a name instead of refusing it"


def test_the_pass_refuses_to_empty_the_tab():
    """A rule change that flagged everything must stop loudly, not blank the page. The
    guard is in main() before any UPDATE; this pins the arithmetic it uses."""
    pairs = [(1, "Bayonet", "KSSL · Bayonet"), (2, "Cleaver", "KSSL · Cleaver")]
    _keep, drop, _g = cp.classify_pairings(pairs, WORKBOOK, {})
    assert len(drop) >= len(pairs), "the whole-tab case must be detectable before a write"
    assert cp.OURS == ("not_a_client_product", "offered_not_owned"), \
        "--restore must stay scoped to this script's own reasons, or it undoes the sibling pass"


def test_the_live_workbook_still_says_what_this_was_built_against():
    """A REGRESSION PIN ON REAL DATA, not on a fixture.

    Runs the rules over the committed portfolio/kssl_portfolio.json. Two rows must be
    found, the other 57 must not be banned, and the count must not silently become
    "everything" or "nothing" -- both of which would look like a passing test.
    """
    rows = cp.load_workbook()
    assert len(rows) == 59, "the workbook changed shape (%d rows); re-audit before editing this" % len(rows)
    banned = {r["name"] for r in rows if any(s == "ban" for s, _x, _y in pg.audit_row(r, {}))}
    held = {r["name"] for r in rows if any(s == "hold" for s, _x, _y in pg.audit_row(r, {}))}
    assert banned == {"FN Herstal Integrated Weapon Mounts / C-UAS Turrets"}, banned
    assert held == {"FN Herstal Integrated Weapon Mounts / C-UAS Turrets",
                    "Ultra UAV / Precision Loitering Munition"}, held
    assert 0 < len(banned | held) < len(rows) // 4, \
        "a rule that flags a quarter of the client's portfolio is a broken rule, not a finding"


def test_module_demos():
    """Both modules' own checks, so a demo cannot rot the way serving_fill's did."""
    assert pg._demo() == 0
    assert cp._demo() == 0


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("  PASS  %s" % name)
        except AssertionError as e:
            fails += 1
            print("  FAIL  %s: %s" % (name, e))
    print("all checks passed" if not fails else "%d FAILED" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
