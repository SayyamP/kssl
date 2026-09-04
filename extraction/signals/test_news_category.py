"""Checks for fill_competitor_news.news_category: the news pill vocabulary.

    python extraction/signals/test_news_category.py

The bug these guard against: competitor_news.category was a copy of
signal_card.tags, the PORTFOLIO BAND ("Artillery", "UAVs & Drones", ...), while
the Profile page's filter pills are a NEWS-TOPIC vocabulary (Defence, Financial,
Government, Workforce, Markets) matched by substring. No band contains the word
"workforce" or "markets", so those pills were empty for every company, and
"Defence" matched only "Missiles & Air Defence". Repopulating the table without
reconciling the vocabulary leaves the pills empty forever.

Every title below is a real production card. The negative cases are the ones the
first draft of the lexicons got wrong on the live corpus: "strike", "Senator",
"acquire missiles", "employment of a weapon", "guidance system", bare "revenue".
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from fill_competitor_news import NEWS_CATEGORIES, build, news_category  # noqa: E402

# The pills as Profile.jsx renders them (minus "All" and "<Company> Updates", which
# show everything), and its matcher: substring either way, case-folded.
PILLS = ("Defence", "Financial", "Government", "Workforce", "Markets")


def pill_matches(pill, category):
    f, c = pill.lower(), (category or "").lower()
    return c.find(f) >= 0 or f.find(c) >= 0


fails = []


def check(name, got, want):
    ok = got == want
    print("  %s %-62s %s" % ("ok  " if ok else "FAIL", name,
                             "" if ok else "got %r want %r" % (got, want)))
    if not ok:
        fails.append(name)


def card(title, sowhat="", what="", why="", lane="competitive", tags="Artillery"):
    return {"title": title, "sowhat": sowhat, "what": what, "why": why,
            "lane": lane, "tags": tags}


# --- the vocabulary IS the pill set ------------------------------------------
check("vocabulary equals the pills", tuple(sorted(NEWS_CATEGORIES)), tuple(sorted(PILLS)))
for c in NEWS_CATEGORIES:
    check("'%s' reaches exactly one pill" % c,
          sum(1 for p in PILLS if pill_matches(p, c)), 1)

# --- the failure that emptied the pills: a band is not a category -----------
BANDS = ("Artillery", "UAVs & Drones", "Marine / Naval", "Missiles & Air Defence",
         "Protected & Armoured Vehicles", "Ammunition", "Small Arms",
         "Precision Components & Forgings")
for b in BANDS:
    got = news_category(card("Saab wins radar and C2 system contract", tags=b))
    check("band %r is filed as Defence, never as itself" % b, got, "Defence")
    check("band %r never reaches Workforce/Markets on its own" % b,
          got in ("Workforce", "Markets", "Financial", "Government"), False)
check("band with no topic words -> a pill matches it",
      any(pill_matches(p, news_category(card("T", tags="Marine / Naval"))) for p in PILLS),
      True)

# --- nothing supports a label -> None, not an invented one -------------------
check("no band, no lane, no topic words -> None",
      news_category(card("T", tags="", lane="")), None)
check("no band, competitive lane, no topic words -> None",
      news_category(card("T", tags=None, lane="competitive")), None)

# --- Workforce ----------------------------------------------------------------
check("jobs -> Workforce",
      news_category(card("Lockheed Martin expands PAC-3 MSE production in Spain",
                         why="The plant will create 300 jobs by 2028.")), "Workforce")
check("appoints -> Workforce",
      news_category(card("Saab appoints new president to expand in Canada")), "Workforce")
check("missile strike is NOT Workforce",
      news_category(card("Ukrainian Flamingo cruise missiles strike Russian targets",
                         what="The strike hit a depot.")), "Defence")
check("employment OF a weapon is NOT Workforce",
      news_category(card("Australian Army urges drone competency",
                         why="Wider employment of drones changes doctrine.",
                         lane="market")), "Markets")
check("European Union is NOT Workforce (union)",
      news_category(card("EU reports credible intel on Iranian missile delivery",
                         what="The European Union said so.", lane="market")), "Markets")

# --- Financial ----------------------------------------------------------------
check("acquires a BUSINESS -> Financial",
      news_category(card("Leonardo acquires Iveco Defence Business for EUR1.6 billion",
                         what="Leonardo acquires the defence business of Iveco.")),
      "Financial")
check("acquire MISSILES is NOT Financial (procurement)",
      news_category(card("Australia to acquire Lockheed Martin AIM-260A missiles",
                         what="Australia will acquire the missiles.")), "Defence")
check("Defence Acquisition Council is NOT Financial",
      news_category(card("Tata Advanced Systems wins loitering munition contract",
                         why="The Defence Acquisition Council approved it earlier.")),
      "Government")
check("raises guidance -> Financial",
      news_category(card("Leonardo raises FY26 guidance with EUR16.3bn order surge")),
      "Financial")
check("a guidance SYSTEM is NOT Financial",
      news_category(card("Thales delivers next-generation deployable TACAN system",
                         what="TACAN is a tactical air navigation guidance system.")),
      "Defence")
check("'adds to revenue' on a contract win is NOT Financial",
      news_category(card("Rheinmetall secures 155mm artillery shell contract",
                         why="The order adds to Rheinmetall's revenue.")), "Defence")
check("reports record order intake -> Financial",
      news_category(card("RENK reports record order intake in H1 2026")), "Financial")
check("invests $ -> Financial",
      news_category(card("RTX invests $100M to expand LTAMDS production")), "Financial")

# --- Government ---------------------------------------------------------------
check("approves sale -> Government",
      news_category(card("US approves sale of Switchblade 300 drones to Greece")),
      "Government")
check("issues tender -> Government",
      news_category(card("Czech MoD issues tender for Pandur II successor")), "Government")
check("Roshel's Senator vehicle is NOT Government",
      news_category(card("Ukraine receives over 2,500 Canadian Senator vehicles",
                         what="Roshel delivered the Senator APCs.")), "Defence")
check("ministry as the CUSTOMER of a contract is NOT Government",
      news_category(card("Italian Ministry of Defense awards EUR159M contract for SICRAL 3")),
      "Defence")
check("licensed production is NOT Government",
      news_category(card("Shield AI wins India contract for V-BAT drones",
                         what="The drones are built under licence in India.")), "Defence")

# --- Markets ------------------------------------------------------------------
check("export -> Markets",
      news_category(card("Saab Australia marks 100th export of Multi-Function Console")),
      "Markets")
check("expands into a market -> Markets",
      news_category(card("Terra Drone expands into UAE C-UAS market")), "Markets")
check("MARKET lane with no topic words -> Markets (pipeline's own verdict)",
      news_category(card("Bundeswehr orders eight MQ-9B SeaGuardian drones", lane="market")),
      "Markets")
check("bare 'demand' in the why-sentence is NOT Markets",
      news_category(card("Thales expands radar and munitions production",
                         why="This signals growing demand for radars.")), "Defence")
check("bare 'market' in the why-sentence is NOT Markets",
      news_category(card("Rheinmetall wins ACTS contract in UK",
                         why="It strengthens Rheinmetall's position in the market.")),
      "Defence")

# --- precedence ---------------------------------------------------------------
check("jobs beats a budget mention",
      news_category(card("KNDS France expands CAESAR production",
                         why="Recruiting 200 staff under the defence budget.")), "Workforce")
check("acquisition beats a regulatory approval",
      news_category(card("Thales to acquire Exail for EUR3.9bn",
                         what="The deal awaits regulatory approval.")), "Financial")
check("a government act beats an export mention",
      news_category(card("US approves sale of Seahawk helicopters to New Zealand",
                         why="An export win for the maker.")), "Government")

# --- build() writes the topic, never the band ---------------------------------
rows, _ = build(
    [{"id": "pl_d1", "title": "Saab appoints new president", "company": "Saab",
      "tags": "Artillery", "url": "https://p.com/1", "lane": "competitive"},
     {"id": "pl_d2", "title": "Saab wins radar contract", "company": "Saab",
      "tags": "Missiles & Air Defence", "url": "https://p.com/2", "lane": "competitive"}],
    {"Saab": "saab"}, lambda i: "2026-07-13")
check("build: topic row is Workforce", rows[0]["category"], "Workforce")
check("build: band-only row is Defence, not the band", rows[1]["category"], "Defence")
check("build: no written category is a band",
      any(r["category"] in BANDS for r in rows), False)
check("build: every written category reaches a pill",
      all(any(pill_matches(p, r["category"]) for p in PILLS) for r in rows), True)

print()
if fails:
    print("FAILED: %d check(s): %s" % (len(fails), "; ".join(fails)))
    sys.exit(1)
print("test_news_category ok")
