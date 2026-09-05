"""The subject is the headline, and an accessory is not a subject.

    python3 test_portfolio_surfaces.py

THE REPORT, second time round. "check whether on the whole website which things is
there like signals, for each should be KSSL relevant means portfolio relevant because
otherwise it will not make sense."

Audited on the live rows AFTER the first off_portfolio() fix, and on every surface,
not just the feed. Three things were wrong, and every string below is a REAL row from
the serving tables that shows one of them:

  1. The gate ran on title + what + sowhat, and `sowhat` names the category by
     construction ("...relevant to KSSL's Protected & Armoured Vehicles line"), so the
     own-category override rescued almost anything:
         "Thales wins U.S. Marine Corps order for Minerva cameras"   -> served
     -- the client's own example, a camera deal, kept because "vehicles" appeared.

  2. The override matched keyword PREFIXES: `isr` rescued "Israeli", `vehicle`
     rescued field hospitals, `marg` would rescue "margin". And it had no words for
     the things the corpus actually calls KSSL's lines (RWS, APS, CCA, UGV, SHORAD,
     loitering munition), so on the innovation surface a third of the refusals were
     WRONG: "Rheinmetall unveiled KF41 Lynx Skyranger 35 air-defence system" was
     refused for the word "radar" in its body.

  3. Bugs: the autocannon rule matched "5.56x45mm" (a carbine became a conflict); a
     helicopter that is merely the LAUNCH PLATFORM ("Spike NLOS missile fired from
     Apache helicopter") was a conflict; "SAL guidance" hit `laser`; "Orbital ATK"
     hit `orbital`.

The rule now: a negative term in the HEADLINE, with no KSSL line named in the
headline, is off-portfolio. A negative term only in the BODY is an accessory unless
nothing anywhere names a KSSL line. Still a negative list with an override -- a
positive list was measured at refusing ~70% of relevant cards and is not coming back.

No DB, no network -- pure predicate, so it runs in the image build.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serving_fill as sf                                            # noqa: E402

bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print("  FAIL " + msg)


# ------------------------------------------------------------------ signal cards
# (category, title, what) -- REAL served rows the old gate KEPT; all off-portfolio
CARD_OFF = [
    ("Protected & Armoured Vehicles", "Thales wins U.S. Marine Corps order for Minerva cameras",
     "Thales has been awarded a contract by the U.S. Marine Corps for Minerva cameras "
     "to be fitted to its vehicles."),
    ("Protected & Armoured Vehicles", "Rheinmetall wins Danish MoD contract for field hospitals",
     "Rheinmetall Mobile Systeme GmbH signed a contract with the Danish procurement "
     "authority for five Role 2 field hospitals."),
    ("Protected & Armoured Vehicles", "Rheinmetall wins Bundeswehr contract for mobile medical stations",
     "The Bundeswehr ordered mobile medical stations mounted on armoured vehicles."),
    ("Missiles & Air Defence", "Lockheed Martin Maintains F-35 Production at 156 Jets Annually",
     "Lockheed Martin will keep F-35 output at 156 jets a year; the fighter carries "
     "air-to-air missiles and supports air defence."),
    ("Missiles & Air Defence", "Leonardo unveils Newton electronic warfare simulation software",
     "Newton models electronic warfare scenarios for missiles and air defence training."),
    ("Marine / Naval", "Royal Australian Navy's SEA 1442 Phase 5 seeks advanced maritime communications systems",
     "The Leonardo Global Group will pursue the SEA 1442 Phase 5 maritime communications programme."),
    ("Missiles & Air Defence", "Thales delivers next-generation deployable TACAN system",
     "Thales delivered the D-TACAN navigation system to the Spanish Air Force."),
    ("Marine / Naval", "Lockheed Martin secures Australian submarine combat system role",
     "Lockheed Martin will integrate the combat system for Australia's naval submarines."),
    ("Missiles & Air Defence", "BAE Systems wins ROKAF F-15K EW system contract",
     "BAE Systems will supply the electronic warfare suite for the F-15K, protecting it "
     "from air defence threats."),
    ("Missiles & Air Defence", "Rival firms showcase laser weapon advancements",
     "Several firms showed high-energy laser weapons for air defense at the show."),
    ("UAVs & Drones", "Leonardo joins GCAP for new gen multi-domain combat system",
     "Leonardo joined the GCAP sixth-generation fighter programme with a UAV element."),
    ("Marine / Naval", "HAL to Restart Su-30MKI Production for IAF",
     "HAL will restart the Su-30MKI fighter line for the Indian Air Force."),
    ("UAVs & Drones", "BAE Systems offers T-7 for RAF pilot training",
     "BAE Systems is offering the T-7 trainer jet for Royal Air Force pilot training."),
]

# (category, title, what) -- REAL rows that must survive: a KSSL line IS the subject
CARD_KEEP = [
    ("Missiles & Air Defence", "BrahMos-A missile operational on Su-30MKI fighters",
     "The air-launched BrahMos is now operational on the Su-30MKI fleet."),
    ("Artillery", "KNDS wins Malaysian Caesar self-propelled howitzer order",
     "KNDS will deliver Caesar 6x6 howitzers with a fire-control radar link."),
    ("Ammunition", "Rheinmetall wins NATO contract for 155mm artillery shells",
     "NATO's NSPA ordered 155mm shells under a framework contract."),
    ("Small Arms", "Indian Army issues RFP for 450 Carl Gustaf Mk-IV rocket launchers",
     "The RFP covers 450 launchers with optical sights and thermal imaging clip-ons."),
    ("Protected & Armoured Vehicles", "Rheinmetall's Lynx IFV Secures International Contracts",
     "The Lynx infantry fighting vehicle carries a 30mm cannon and a radar-based APS."),
    ("UAVs & Drones", "Anduril's robotic fighter jet completes live-fire test",
     "The Fury collaborative combat aircraft, an unmanned combat air vehicle, fired live."),
    ("Marine / Naval", "Kongsberg and Oceaneering chosen for US Navy's XLUUV CAMP programme",
     "The unmanned underwater vehicle programme covers an autonomous underwater vehicle "
     "with sonar payload."),
    ("Missiles & Air Defence", "Saab wins RBS 70 NG order from Latvia",
     "The RBS 70 NG is a laser-guided man-portable air defence missile."),
    # The client's master list has a "Counter-UAS (C-UAS) Mobile System" and a C-UAS
    # turret, so counter-drone news is ON-portfolio -- a judgement that rests on the
    # FILE, not on the keyword gate (which, in enrich_serving's competitor gate, still
    # strips counter-drone as not-KSSL).
    ("UAVs & Drones", "AeroVironment wins $500M IDIQ for JIATF-401 C-UAS support",
     "The contract covers counter-unmanned aircraft systems support for JIATF-401."),
    ("UAVs & Drones", "Robin Radar Systems Expands in US CUAS Market",
     "Robin Radar's drone-detection radars are sold into the US counter-UAS market."),
]

for cat, title, what in CARD_OFF:
    check(sf.off_portfolio(cat, what, title=title), "card not refused [%s] %s" % (cat, title))
for cat, title, what in CARD_KEEP:
    check(not sf.off_portfolio(cat, what, title=title), "card wrongly refused [%s] %s" % (cat, title))
    check(not sf.category_conflict(cat, what, title=title), "card wrongly conflicted [%s] %s" % (cat, title))

# The old call shape (one text, no title) must still work, and must still refuse the
# first report's rows -- test_off_portfolio.py pins those; here only the shape.
check(sf.off_portfolio("UAVs & Drones",
                       "Leonardo DRS Secures Contract for Over 50,000 Thermal Imaging Cameras"),
      "old call shape broke")

# ------------------------------------------------------------------ innovations
# (KSSL category for the area, t, body) -- REAL rows the old gate REFUSED; all relevant
INNOV_KEEP = [
    ("Protected & Armoured Vehicles", "KNDS 30M781 cannon integrated with EOS R500 RWS",
     "The 30mm cannon was integrated with the R500 remote weapon station, which carries "
     "a radar and day/night sensors."),
    ("UAVs & Drones", "Leonardo unveils first pre-production AWHERO RUAS",
     "AWHERO is a rotary unmanned aerial system, an unmanned helicopter for naval ISR."),
    ("UAVs & Drones", "Proteus unmanned rotary-wing technology demonstrator unveiled",
     "Proteus is an uncrewed rotorcraft demonstrator for the Royal Navy."),
    ("Missiles & Air Defence", "Spike NLOS missile fired from Apache helicopter",
     "The Spike NLOS missile was fired from an AH-64 Apache helicopter in a trial."),
    ("Small Arms", "Rheinmetall and Steyr Mannlicher developed RS556 modular assault rifle",
     "The RS556 is chambered in 5.56x45 mm and offered to the Bundeswehr."),
    ("Small Arms", "DRDO developed a Close Quarter Battle carbine",
     "The 5.56×45mm CQB carbine completed user trials."),
    ("Artillery", "Excalibur S demonstrated robust SAL guidance",
     "The Excalibur S 155mm round used semi-active laser guidance to hit moving targets."),
    ("Missiles & Air Defence", "Rheinmetall unveiled KF41 Lynx Skyranger 35 air-defence system",
     "The Skyranger 35 turret pairs a 35mm revolver gun with a search radar."),
    ("Protected & Armoured Vehicles", "Leopard 2 PL modernization program demonstrated",
     "The Leopard 2 PL tank upgrade adds thermal imaging and new armour."),
    ("UAVs & Drones", "YFQ-44A CCA made its first autonomous flight",
     "The collaborative combat aircraft flew under Anduril's autonomy software."),
    ("Missiles & Air Defence", "Kalashnikov Concern will demonstrate KUB-2-E and KUB-SM loitering munitions",
     "The KUB loitering munitions carry an electro-optical seeker."),
    ("Ammunition", "Saab and Raytheon completed test firings of guided Carl-Gustaf munition",
     "The guided munition uses a laser designator for terminal guidance."),
    ("Protected & Armoured Vehicles", "MK44 Bushmaster Chain Gun demonstrated with air-bursting munition fuze",
     "Orbital ATK demonstrated the MK44 chain gun with an airburst fuze."),
    ("UAVs & Drones", "Raytheon launches Coyote LE SR from helicopter",
     "The Coyote drone was launched from a helicopter in a demonstration."),
    ("Protected & Armoured Vehicles", "Hanwha upgrades APS to detect UAVs and elevate launchers",
     "The active protection system software was upgraded to detect UAVs."),
    # second pass over the live rows: a fighter's name is not only a fighter's
    ("Marine / Naval", "Rafael delivers 1000th TYPHOON naval weapon station",
     "The TYPHOON 30mm remotely controlled naval gun mount has an electro-optical director."),
    ("Marine / Naval", "Turkey tested Typhoon Block 3 ASBM hitting small naval target",
     "Roketsan's Typhoon ballistic missile hit a small target at sea, tracked by radar."),
    ("Protected & Armoured Vehicles", "Rheinmetall unveiled Natter 7.62 remote-controlled weapon station",
     "The Natter RCWS carries a 7.62mm machine gun with a thermal imaging camera."),
    ("UAVs & Drones", "Teledyne FLIR launches Black Recon autonomous micro-drone",
     "The micro-drone carries a thermal camera for vehicle-launched reconnaissance."),
    ("UAVs & Drones", "Vehicle-Mounted Counter-Drone System with high-energy laser and gun",
     "DRDO's counter-drone system pairs a 2kW laser with a gun on a truck."),
    ("UAVs & Drones", "Leonardo unveiled Falco Xplorer, a large unmanned air system",
     "The Falco Xplorer carries a Gabbiano radar and a satellite datalink."),
]
# (category, t, body) -- REAL rows that are off-portfolio, refused before and after
INNOV_OFF = [
    ("Marine / Naval", "KONGSBERG unveils Aegir SSA sonar system", "A new ship sonar family."),
    ("Marine / Naval", "Lockheed Martin delivered HELIOS laser weapon system",
     "The 60kW laser weapon was installed on a destroyer."),
    ("Precision Components & Forgings", "L3Harris evolves BNVD-Fused night vision goggles",
     "The binocular night vision device fuses image intensification and thermal."),
    ("Marine / Naval", "Raytheon's SPY-6 radar reaches milestone", "The radar array was delivered."),
    # kept by the old gate, off-portfolio by hand
    ("Protected & Armoured Vehicles", "Rheinmetall awarded contract for Trailblazer camera system",
     "Trailblazer is a driver vision camera system for armoured vehicles."),
    ("Missiles & Air Defence", "Lockheed Martin achieves first light in DEIMOS laser weapon system",
     "DEIMOS is a 50kW-class laser weapon for short-range air defense."),
    ("Marine / Naval", "Developing advanced software for SPY-6 radars",
     "ONR is developing software for the naval SPY-6 radar family."),
]
for cat, t, body in INNOV_KEEP:
    check(not sf.off_portfolio(cat, body, title=t), "innovation wrongly refused [%s] %s" % (cat, t))
    check(not sf.category_conflict(cat, body, title=t), "innovation wrongly conflicted [%s] %s" % (cat, t))
for cat, t, body in INNOV_OFF:
    check(sf.off_portfolio(cat, body, title=t) or sf.category_conflict(cat, body, title=t),
          "innovation not refused [%s] %s" % (cat, t))

# ------------------------------------------------------------------ geo / partner (no category)
# name, note -- REAL geo_presence rows. With no category the override is any KSSL line.
GEO_OFF = [
    ("Dhruv / LCH helicopters", "HAL builds the Dhruv and LCH helicopters at Bengaluru."),
    ("F-35 to NATO operators", "Lockheed Martin delivers F-35 fighters to European NATO operators."),
    ("SAR satellite manufacturing facility", "ICEYE opened a SAR satellite plant in Germany."),
    ("radar production and test capacity", "Thales expanded radar production in Hengelo."),
    ("Viasat satellite broadband services", "Viasat provides satellite broadband to Ukraine."),
]
GEO_KEEP = [
    ("Helicopters / naval guns", "Leonardo builds helicopters and the 76/62 naval gun in Italy."),
    ("JSM for F-35 fleet order", "Japan ordered the Joint Strike Missile for its F-35 fleet."),
    ("155mm artillery ammunition plant", "Rheinmetall builds a 155mm shell plant in Hungary."),
]
for name, note in GEO_OFF:
    check(sf.off_portfolio("", note, title=name), "geo not refused: %s" % name)
for name, note in GEO_KEEP:
    check(not sf.off_portfolio("", note, title=name), "geo wrongly refused: %s" % name)
    check(not sf.category_conflict("", note, title=name), "geo wrongly conflicted: %s" % name)

# ------------------------------------------------------------------ tender / matchup
# REAL tender: a hand-held drone jammer IS the client's C-UAS line (file row), and the
# anchor "drone jammer" must not be stripped as a mere modifier of "jammer"
check(not sf.off_portfolio("UAVs & Drones", "", title="Portable Hand Held Drone Jammer System"),
      "tender wrongly refused: drone jammer (C-UAS is in the client's file)")
# REAL matchup: Yugoimport's Nora B-52 is a howitzer, not the bomber -- 8 live rows
check(not sf.off_portfolio("Artillery", "CAESAR-class 155mm truck-mounted howitzer",
                           title="Yugoimport SDPR - Nora B-52"),
      "matchup wrongly refused: Nora B-52 howitzer")
# but a KSSL word that merely MODIFIES the foreign thing does not rescue it
check(sf.off_portfolio("Marine / Naval", "The systems will enhance submarine crew awareness.",
                       title="kta Naval Systems to develop combat systems for thyssenkrupp submarines"),
      "'submarines' must not rescue a combat-system (software) row")

# REAL partner row: aero-engine FORGINGS are KSSL's precision-components line
check(not sf.off_portfolio("", "Partnership arrangement for forged and machined aero-engine "
                            "parts (LEAP ecosystem), leveraging Bharat Forge's forging base.",
                            title="Safran"),
      "partner wrongly refused: Safran aero-engine forgings")

# ------------------------------------------------------------------ the bugs by name
check(not sf.category_conflict("Small Arms", "5.56x45mm Close Quarter Battle Carbine"),
      "5.56x45mm is a carbine calibre, not an autocannon")
check(sf.category_conflict("UAVs & Drones", "Leonardo wins 15 helicopter order from Avincis"),
      "a manned helicopter order is still a conflict under UAVs")
check(sf.category_conflict("Marine / Naval", "Leonardo delivers first NH90 NFH naval helicopters to Qatar"),
      "'naval' must not rescue a helicopter delivery")
check(sf.off_portfolio("Protected & Armoured Vehicles",
                       "The Israeli order covers 200 vehicles with thermal imaging cameras.",
                       title="Elbit wins Israeli thermal camera order"),
      "'isr' must not match 'Israeli' and 'vehicle' must not rescue a camera order")
check(not sf.off_portfolio("Precision Components & Forgings",
                           "Bharat Forge will supply forged crankshafts.",
                           title="Bharat Forge wins forged crankshaft order"),
      "'forged' names the precision-components line")

# ------------------------------------------------------------------ the client's file
# Every one of the 59 product names in the client's master list must name a KSSL line
# through the anchors of the tag its file category maps to -- and that evidence must be
# labelled "file", so the audit can say which judgements rest on the client's word.
import portfolio                                                     # noqa: E402

for file_cat, name in portfolio.PRODUCT_NAMES:
    tags = portfolio.FILE_CATEGORY_TO_TAG.get(file_cat)
    check(tags, "file category has no serving tag mapping: %s" % file_cat)
    check(sf.portfolio_evidence(tags[0] if tags else "", "", title=name) == "file",
          "file product not anchored [%s] %s" % (file_cat, name))
    check(not sf.off_portfolio(tags[0] if tags else "", "", title=name),
          "file product refused [%s] %s" % (file_cat, name))

# the two serving tags the file has no heading for are declared, not dropped
for tag in ("Missiles & Air Defence", "Precision Components & Forgings"):
    check(tag in portfolio.TAGS_WITHOUT_FILE_HEADING, "unmapped serving tag undeclared: %s" % tag)
    check(tag in portfolio.ANCHORS, "serving tag silently dropped from anchors: %s" % tag)

# When the xlsx and openpyxl are both present (a workstation, not the image), the
# transcription must match the file: same categories, every product name present.
_xlsx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio",
                     "KSSL_master_products_2026-09-05.xlsx")
try:
    import openpyxl                                                  # noqa: E402
    _ws = openpyxl.load_workbook(_xlsx, read_only=True, data_only=True)["Master Database"]
    _rows = [r for r in _ws.iter_rows(min_row=2, values_only=True) if r and r[0]]
    check(len(_rows) == len(portfolio.PRODUCT_NAMES),
          "file has %d rows, PRODUCT_NAMES has %d" % (len(_rows), len(portfolio.PRODUCT_NAMES)))
    _norm = lambda s: "".join(ch for ch in str(s).lower().replace("×", "x")     # noqa: E731
                              if ch.isalnum())
    _have = {_norm(n) for _c, n in portfolio.PRODUCT_NAMES}
    for r in _rows:
        check(str(r[0]).strip() in portfolio.FILE_CATEGORY_TO_TAG,
              "file category not in the map: %r" % r[0])
        check(_norm(r[1])[:24] in {h[:24] for h in _have},
              "file product missing from PRODUCT_NAMES: %r" % r[1])
    print("  (xlsx present: %d rows cross-checked)" % len(_rows))
except ImportError:
    print("  (openpyxl absent: xlsx cross-check skipped, transcription checked only)")
except FileNotFoundError:
    print("  (xlsx absent: cross-check skipped)")

# empty input is not off-portfolio
for empty in ("", None):
    check(not sf.off_portfolio("Artillery", empty), "empty text treated as off-portfolio")
    check(not sf.off_portfolio("Artillery", empty, title=empty), "empty title treated as off-portfolio")

if bad:
    print("\n%d failure(s)" % bad)
    sys.exit(1)
print("ok - portfolio gate: %d card / %d innovation / %d geo off-portfolio rows refused, "
      "%d / %d / %d relevant rows kept"
      % (len(CARD_OFF), len(INNOV_OFF), len(GEO_OFF), len(CARD_KEEP), len(INNOV_KEEP), len(GEO_KEEP)))
