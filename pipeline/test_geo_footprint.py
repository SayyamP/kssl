"""The entailment gate refuses a co-mention and accepts a stated presence.

    python test_geo_footprint.py          (no DB needed)
    pytest test_geo_footprint.py

Every negative fixture is a sentence that actually sits in extracted.document /
extracted.proposition for the client group or a rival, found while building the writer:
each one puts the company and a country in one sentence and states no presence there.
Every positive fixture is likewise a real sentence. Invented fixtures would test the
gate against my own idea of the failure, which is how the previous grounding passed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fill_geo_footprint as g                                   # noqa: E402

CLIENT = g.rx_of(g.surfaces_of(g.CLIENT_ID, g.CLIENT_NAME))
RHEIN = g.rx_of(g.surfaces_of("rheinmetall", "Rheinmetall"))
SAAB = g.rx_of(["Saab"])
ELBIT = g.rx_of(g.surfaces_of("elbit-systems", "Elbit Systems"))
OTHERS = g.rx_of(["Paramount Group", "Paramount", "Embraer", "AM General", "Leonardo"])


def verdicts(sentence, rx, own=False, polarity=None):
    return g.gate(sentence, rx, own_site=own, other_rx=OTHERS, polarity=polarity)


def accepted(sentence, rx, own=False):
    return {(v.country, v.kind) for v in verdicts(sentence, rx, own) if v.ok}


def refused(sentence, rx, own=False):
    return {v.country: v.reason for v in verdicts(sentence, rx, own) if not v.ok}


def test_no_control_characters():
    g.no_control_chars()
    for name in dir(g):
        rx = getattr(g, name)
        if hasattr(rx, "pattern"):
            assert not any(ord(c) < 32 for c in rx.pattern), name


# ---------------------------------------------------------------- co-mentions REFUSED

def test_award_in_germany_is_not_a_presence():
    # bharatforge.com/company/about-us
    s = ("Baba Kalyani, Chairman & Managing Director, Bharat Forge was honoured with the "
         "“Cross of the Order of Merit” of the Federal Republic of Germany by the "
         "German Ambassador to India, His Excellency Mr. Michael Steiner on November 7, 2012.")
    assert accepted(s, CLIENT, own=True) == set()
    assert "Germany" in refused(s, CLIENT, own=True)


def test_trade_show_dateline_is_not_a_presence():
    # edrmagazine.eu, the Simha 4x4 launch at Eurosatory
    s = ("Kalyani Strategic Systems Limited and Paramount unveil Simha 4×4 – "
         "next-generation modular multipurpose vehicle for the global market Eurosatory, "
         "Paris, France | June 16, 2026: Kalyani Strategic Systems Limited (KSSL), the "
         "wholly-owned defence subsidiary of Bharat Forge Limited, and Paramount, today")
    assert accepted(s, CLIENT) == set()
    assert "France" in refused(s, CLIENT)


def test_mou_with_a_foreign_firm_is_not_a_presence():
    # bharatforge.com media listing
    s = ("Bharat Forge signs an MOU with DASTAN, KYRGYZSTAN, to work on technologies for "
         "Underwater Naval Weapons")
    assert accepted(s, CLIENT, own=True) == set()
    r = refused(s, CLIENT, own=True)
    assert "Kyrgyzstan" in r and "intent" in r["Kyrgyzstan"]


def test_letter_of_intent_with_a_us_partner_at_idex():
    # idrw.org
    s = ("Bharat Forge’s subsidiary, Kalyani Strategic Systems Ltd (KSSL), has signed a "
         "Letter of Intent (LoI) with US-based AM General to supply Made-in-India advanced "
         "artillery cannons. The agreement, signed at IDEX 2025 in Abu Dhabi, marks a "
         "significant milestone.")
    assert accepted(s, CLIENT) == set()


def test_partner_nationality_is_not_this_companys_country():
    # defence-industry.eu on Rheinmetall's South African subsidiary
    s = ("Rheinmetall, a prominent German defence technology company, has taken a bold step "
         "to expand its global operations by establishing a new subsidiary in South Africa.")
    got = accepted(s, RHEIN)
    assert ("South Africa", "of") in got, got
    assert not any(c == "Germany" for c, _k in got), got


def test_elections_are_not_a_presence():
    # bharatforge.com/AR2025/management-letter.html
    s = ("The elections in the United States have led to sweeping policy changes that "
         "influenced global trade dynamics.")
    assert accepted(s, CLIENT, own=True) == set()


def test_trade_fair_line_on_own_site_without_the_company():
    # bharatforge.com/company/about-us
    s = ("Hannover Messe 2015, the world’s leading trade fair for industrial "
         "technologies was held in Hannover, Germany in April 2015 and India was the "
         "partner country.")
    assert accepted(s, CLIENT, own=True) == set()


def test_announced_plans_are_not_a_facility_yet():
    # a real Saab statement in the corpus
    s = ("Saab announced plans to set up a manufacturing facility for the Carl-Gustaf "
         "weapon system in India, with production expected to start in 2024.")
    assert accepted(s, SAAB) == set()
    assert "intent" in refused(s, SAAB)["India"]


def test_a_person_or_a_product_is_not_the_company():
    assert not g.is_company_subject("Mr. Baba Kalyani")
    assert not g.is_company_subject("Kalyani M4 armoured vehicle")
    assert not g.is_company_subject("KSSL light tank")
    assert g.is_company_subject("Kalyani Strategic Systems Limited")
    assert g.is_company_subject("KSSL and Paramount")


def test_list_of_headlines_is_not_a_statement():
    s = ("Argentina Australia Austria Belgium Brazil Canada China Denmark Egypt Finland "
         "France Germany Greece Hungary India Rheinmetall")
    assert accepted(s, RHEIN) == set()


# ---------------------------------------------------------------- presences ACCEPTED

def test_own_site_facility_list_first_person():
    # bharatforge.com/AR2020/about-bharat-forge-limited.php
    s = ("We cater to customers globally through 10 manufacturing facilities spread across "
         "five countries: India, United States, Sweden, Germany and France.")
    got = accepted(s, CLIENT, own=True)
    assert got == {("India", "lp"), ("USA", "lp"), ("Sweden", "lp"), ("Germany", "lp"),
                   ("France", "lp")}, got
    # off the company's own site, "we" is nobody
    assert accepted(s, CLIENT, own=False) == set()


def test_own_site_fragment_without_an_agent_is_refused():
    # bharatforge.com/AR2019/about_bharat_forge.html -- a true fact, but the line names
    # nobody: neither the company nor "we". The AR2020 sentence above carries it.
    s = "10 facilities across US, Sweden, Germany, France and India"
    assert accepted(s, CLIENT, own=True) == set()
    assert "not the agent" in refused(s, CLIENT, own=True)["USA"]


def test_geographic_footprint_page():
    # bharatforge.com/AR2025/geographic-footprint.html
    s = ("As a global engineering leader, Bharat Forge operates 18 manufacturing facilities "
         "across five countries, with a strong presence in key markets such as India, "
         "North America, and Europe.")
    got = accepted(s, CLIENT, own=True)
    assert ("India", "of") in got or ("India", "lp") in got, got
    assert any(c == "Europe" for c, _k in got), got


def test_local_production_with_a_partner():
    # military.africa on the Kalyani M4
    s = ("Bharat Forge Limited, part of the Kalyani Group, partnered with Paramount Group to "
         "produce Mbombe 4/Kalyani M4 4×4 armoured vehicles in India.")
    assert ("India", "lp") in accepted(s, CLIENT)


def test_order_from_the_countrys_ministry_is_a_delivery():
    # military.africa
    s = ("To further its ‘make in India’ drive, the Indian Ministry of Defense "
         "ordered the Kalyani M4 4×4 armoured vehicles for its troops in a $25 million "
         "deal with Bharat Forge.")
    assert ("India", "ex") in accepted(s, CLIENT)


def test_supplied_to_the_army():
    # bharatforge.com annual report interview
    s = ("We are getting repeat orders for our armored personnel vehicles and recently "
         "supplied vehicles to the Indian Army.")
    assert ("India", "ex") in accepted(s, CLIENT, own=True)


def test_inaugurated_plant_with_city_and_region_before_the_country():
    # armyrecognition-style report on Zalaegerszeg
    s = ("Rheinmetall recently inaugurated the first part of its new engineering and "
         "production plant in Zalaegerszeg, western Hungary.")
    assert ("Hungary", "lp") in accepted(s, RHEIN)


def test_possessive_facility_in_country():
    # saab.com press release
    s = ("The latest acquisition will be supplied through Saab’s manufacturing facility "
         "in India, established at Reliance MET City in Jhajjar, Haryana.")
    assert ("India", "lp") in accepted(s, SAAB)


def test_demonym_subsidiary():
    # elbitsystems.com
    s = ("The Brazilian Air Force (FAB) and AEL Sistemas, Elbit Systems’ Brazilian "
         "subsidiary, the prime contractor of the Brazilian Link-BR2 strategic program, "
         "concluded successful series of flight tests.")
    got = accepted(s, ELBIT)
    assert ("Brazil", "of") in got, got


def test_registered_office_is_hq():
    # saab.com articles of association
    s = "The registered office of the Company shall be located in Linköping, Sweden."
    vs = [v for v in verdicts(s, SAAB, own=True) if v.ok]
    assert vs and vs[0].kind == "hq" and vs[0].country == "Sweden", vs
    assert vs[0].city.startswith("Link"), vs[0].city


def test_another_companys_plant_is_not_this_companys():
    s = ("Embraer’s industrial site in Gavião Peixoto, Brazil produces Gripen E "
         "fighter jets for Saab.")
    got = accepted(s, SAAB)
    assert ("Brazil", "lp") not in got and ("Brazil", "of") not in got, got


def test_new_country_is_recognised_but_held():
    s = "Saab has a Swiss subsidiary that produces training ammunition."
    vs = [v for v in verdicts(s, SAAB) if v.ok]
    assert vs and vs[0].country == "Switzerland"
    assert "Switzerland" in g.NEW_COUNTRIES and "Switzerland" not in g.SERVED


def test_negative_polarity_refuses():
    s = "Rheinmetall operates a plant in Hungary."
    assert accepted(s, RHEIN)
    assert not [v for v in verdicts(s, RHEIN, polarity="negative") if v.ok]


def run_all():
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
    print("%d gate test(s) passed" % n)


if __name__ == "__main__":
    run_all()
