"""A category LABEL is not a subject.

    python3 test_off_portfolio.py

THE REPORT. "check in the signals we generated whether they are actually a threat to
KSSL or not, because there are some camera signals that KSSL doesn't work in."

Audited on the live rows: about a third of every served surface was about a product
class KSSL has no line in, and 33 of 103 THREAT badges were off-portfolio. The row that
names the fault:

    "Leonardo DRS Secures Contract for Over 50,000 Thermal Imaging Cameras"
        category: UAVs & Drones     dir: threat

Three gates said yes. `cat` was one of the nine, so the only subject test passed;
_GAIN_RX found "contract"; Leonardo is on the curated roster. Nothing anywhere asked
whether the ARTICLE was about drones.

WHAT THIS FILE PINS, and the second half is the one that matters:

  1. the negative list catches the real off-portfolio rows -- every string below is a
     REAL title from serving.signal_card, not one I invented to pass;
  2. it does NOT refuse a relevant card that merely MENTIONS a foreign word. This is
     where a keyword gate normally goes wrong: "BrahMos fired from a Su-30" is a missile
     signal, "Archer with a radar-guided shell" is an artillery signal. If the override
     ever breaks, this file fails rather than the client quietly losing real signals.

No DB, no network -- pure predicate, so it runs in the image build.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serving_fill as sf                                            # noqa: E402

# (category, title) -- REAL rows that must be refused
OFF = [
    ("UAVs & Drones", "Leonardo DRS Secures Contract for Over 50,000 Thermal Imaging Cameras"),
    ("UAVs & Drones", "Leonardo wins 15 helicopter order from Avincis"),
    ("UAVs & Drones", "Saab wins Giraffe 1X radar order from France"),
    ("UAVs & Drones", "Leonardo advances in space robotics and autonomous orbital ops"),
    ("UAVs & Drones", "Anduril wins NATO eAirC2 Data Platform contract"),
    ("UAVs & Drones", "Saab wins contract for 16 Gripen E fighter aircraft for Ukraine"),
    ("Protected & Armoured Vehicles", "Rheinmetall wins major Moroccan field hospital order"),
    ("Protected & Armoured Vehicles", "Rheinmetall wins Bundeswehr contract for mobile medical stations"),
    ("Protected & Armoured Vehicles", "Raytheon UK-led consortium wins 2 billion pound UK army training contract"),
    ("Precision Components & Forgings", "Lockheed awarded 514m dollars for GPS IIIF satellites"),
    ("Precision Components & Forgings", "BAE delivers Roman Space Telescope instrument"),
    ("Marine / Naval", "Thales Alenia Space wins 862M euro ESA Lunar Lander contract"),
    ("Marine / Naval", "Qatar orders NH90 helicopters"),
    ("Small Arms", "Senop OSKAR thermal smart sight enters production"),
    ("Small Arms", "L3Harris unveils BNVD-Fused night vision goggles"),
    ("Missiles & Air Defence", "Thales Singapore wins AI air-traffic management deal"),
    ("Artillery", "Nokia and KNDS trial 5G software defined battle-management"),
]

# must SURVIVE: a real KSSL-line signal that happens to name a foreign thing
KEEP = [
    ("Missiles & Air Defence", "BrahMos supersonic cruise missile fired from a Su-30 fighter aircraft"),
    ("Artillery", "Archer howitzer fires radar-guided Excalibur shell in trials"),
    ("Artillery", "K9 Vajra self-propelled howitzer order signed"),
    ("Ammunition", "155mm artillery shell production doubles at new plant"),
    ("Protected & Armoured Vehicles", "Rheinmetall Lynx KF41 infantry fighting vehicle selected"),
    ("UAVs & Drones", "Anduril Altius-600M loitering munition enters service"),
    ("Small Arms", "AK-203 assault rifle production begins at Korwa"),
    ("Marine / Naval", "Naval gun mount delivered for new frigate"),
    ("Missiles & Air Defence", "Pinaka rocket artillery system test-fired"),
]

bad = 0

for cat, title in OFF:
    if not sf.off_portfolio(cat, title):
        bad += 1
        print("  FAIL not refused [%s] %s" % (cat, title))

for cat, title in KEEP:
    if sf.off_portfolio(cat, title):
        bad += 1
        print("  FAIL wrongly refused [%s] %s" % (cat, title))

# the helicopter rule must now fire for EVERY category, not just vehicles/small arms --
# that restriction is exactly how a helicopter became a drone signal
if not sf.category_conflict("UAVs & Drones", "Leonardo wins 15 helicopter order"):
    bad += 1
    print("  FAIL category_conflict still lets a helicopter be a drone")
if not sf.category_conflict("Marine / Naval", "Qatar orders NH90 rotorcraft"):
    bad += 1
    print("  FAIL category_conflict still lets a rotorcraft be a naval signal")

# empty input is not off-portfolio
for empty in ("", None):
    if sf.off_portfolio("Artillery", empty):
        bad += 1
        print("  FAIL empty text treated as off-portfolio")

if bad:
    print("\n%d failure(s)" % bad)
    sys.exit(1)
print("ok - off_portfolio: %d real off-portfolio titles refused, %d KSSL-line titles kept"
      % (len(OFF), len(KEEP)))
