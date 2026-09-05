"""KSSL's portfolio, as the CLIENT states it -- and the join to the serving vocabulary.

Source: KSSL_FINAL_CONSOLIDATED_MASTER_PRODUCT_SPECIFICATIONS_CLEAN_STANDARDIZED.xlsx,
sheet "Master Database", 59 product rows in 7 categories (received 2026-09-05, kept at
extraction/signals/portfolio/). The client's words: "for portfolio reference though not
complete i think but enough to start". So this file is AUTHORITATIVE BUT INCOMPLETE: a
product named here is on-portfolio for certain; a product absent from it is NOT thereby
off-portfolio. This module therefore only ever ADDS positive anchors to the relevance
gate -- it never refuses anything on its own.

TWO ID SPACES, JOINED EXPLICITLY. The file's category headings and the serving tags
(serving.signal_card.tags, CAT_META labels) are not the same vocabulary, and this
project has already lost a whole layer to a display label used as a join key. The map
below is the join; every row of it is a decision, and the two serving tags the file has
no heading for are kept, not dropped:

    file "Protected Vehicles"          -> tag "Protected & Armoured Vehicles"
    file "Armoured Vehicles - MRO"     -> tag "Protected & Armoured Vehicles"
                                          (CAT_META also carries "Armoured Vehicle MRO")
    file "Marine / Naval"              -> tag "Marine / Naval"
    file "UAVs & Drones"               -> tag "UAVs & Drones"   (the file puts C-UAS, the
                                          ECARS ground rover and a loitering munition here)
    file "Artillery" / "Ammunition" / "Small Arms" -> the same-named tags
    (no heading)                       -> tag "Missiles & Air Defence": the file lists
                                          "MRSAM Missile Subsystems" and "Spike ATGM
                                          Sub-assemblies" UNDER Ammunition, so missiles
                                          are on-portfolio as subsystems; the tag stays
                                          and the keyword gate keeps judging it
    (no heading, no rows)              -> tag "Precision Components & Forgings": nothing
                                          in the file; the tag stays and the keyword gate
                                          alone judges it. Not concluded off-portfolio.

Anchors are matched whole-word, case-insensitive, hyphen/space-tolerant, by
serving_fill._line_named(). Generic product-group words from the file (e.g. "gearbox",
"road wheel", "steering gear") are included because a rival's news uses the generic
word, not KSSL's brand name.
"""

# file category heading -> serving tag(s). A LIST, because MRO maps to two labels.
FILE_CATEGORY_TO_TAG = {
    "Artillery": ["Artillery"],
    "Ammunition": ["Ammunition"],
    "Small Arms": ["Small Arms"],
    "Protected Vehicles": ["Protected & Armoured Vehicles"],
    "Armoured Vehicles - MRO": ["Protected & Armoured Vehicles", "Armoured Vehicle MRO"],
    "Marine / Naval": ["Marine / Naval"],
    "UAVs & Drones": ["UAVs & Drones"],
}

# reference_dataset.json techCats id -> serving tag. A THIRD id space: the Innovation
# Pipeline files rows by these eight ids ("armoured", "materials", ...), not by tag.
TECH_AREA_TO_TAG = {
    "artillery": "Artillery",
    "armoured": "Protected & Armoured Vehicles",
    "smallarms": "Small Arms",
    "ammunition": "Ammunition",
    "missiles": "Missiles & Air Defence",
    "naval": "Marine / Naval",
    "uav": "UAVs & Drones",
    "materials": "Precision Components & Forgings",
}

# serving tags the file has NO heading for. Kept on purpose; see the module docstring.
TAGS_WITHOUT_FILE_HEADING = {
    "Missiles & Air Defence": "product rows MRSAM subsystems + Spike ATGM sub-assemblies (filed under Ammunition)",
    "Precision Components & Forgings": "no rows in the file; keyword gate only",
}

# Positive anchors per serving tag, transcribed from the 59 product rows. Brand names
# first, then the generic product-group words the same rows use.
ANCHORS = {
    "Artillery": [
        "atags", "bharat 45", "bharat 52", "bharat ulh", "garuda 105", "garuda",
        "marg", "marg 155", "marg 39", "marg 45", "marg 52", "marg er", "marg tc-20",
        "155/39", "155/45", "155/52", "ultra-light howitzer", "ultra light howitzer",
        "mounted gun system", "towed gun", "105 mm", "105mm", "155 mm", "155mm",
    ],
    "Ammunition": [
        "erfb", "erfb-bt", "erfb-bb", "fsapds", "apfsds", "artillery shell", "artillery shells",
        "shell body", "shell bodies", "he shell", "high explosive shell", "illuminating shell",
        "smoke shell", "incendiary shell", "grenade cartridge", "grenade cartridges",
        "small arms cartridge", "small arms cartridges", "cartridges", "ciws",
        "programmable ammunition", "smart ammunition", "mrsam", "spike atgm", "spike",
        "sub-assemblies", "integration kits",
    ],
    "Small Arms": [
        "assault rifle", "ar m5f41", "arsenal ar", "cqb carbine", "f90", "cqb",
        "weapon mount", "weapon mounts", "c-uas turret", "light machine gun", "lmg",
        "mg-m2", "arsenal mg", "protective carbine", "5.56", "5.56 mm", "5.56mm",
        "7.62", "7.62 mm", "7.62mm", "sniper rifle", "sniper rifles", "t-5000", "t-5000m",
        "ubgl", "under-barrel grenade launcher", "under barrel grenade launcher",
        "grenade launcher",
    ],
    "Protected & Armoured Vehicles": [
        "armoured personnel carrier", "armored personnel carrier", "apc",
        "armoured troops carrier", "armoured troop carrier", "troop carrier",
        "high mobility reconnaissance vehicle", "hmrv", "reconnaissance vehicle",
        "kalyani m4", "kalyani maverick", "maverick", "light bullet-proof vehicle",
        "bullet-proof vehicle", "bulletproof vehicle", "light tactical vehicle",
        "tactical vehicle", "mine protected vehicle", "mine-protected vehicle",
        "mine protected", "mrap", "simha", "simha 4x4", "ultra-light strike vehicle",
        "strike vehicle", "light armoured", "light armored", "infantry mobility vehicle",
        "stanag 4569", "armoured vehicle", "armoured vehicles", "armored vehicle",
        "armored vehicles",
        # Armoured Vehicles - MRO rows (same tag, plus the CAT_META MRO label below)
        "driveline", "gearbox", "gearboxes", "gun barrel", "gun barrels",
        "breech", "breeches", "muzzle brake", "muzzle brakes", "powertrain", "crankshaft",
        "connecting rod", "turbocharger", "supercharger", "cylinder liner", "running gear",
        "road wheel", "road wheels", "sprocket", "road-wheel arm",
        "t-90", "t-72", "bmp-2", "bmp", "armoured vehicle mro", "vehicle mro", "tank mro",
    ],
    "Armoured Vehicle MRO": [
        "driveline", "gearbox", "gearboxes", "gun barrel", "gun barrels",
        "breech", "breeches", "muzzle brake", "muzzle brakes", "powertrain", "crankshaft",
        "connecting rod", "turbocharger", "supercharger", "cylinder liner", "running gear",
        "road wheel", "road wheels", "sprocket", "t-90", "t-72", "bmp-2", "bmp",
        "armoured vehicle mro", "vehicle mro", "tank mro", "armoured vehicles",
        "armoured vehicle", "armored vehicles", "armored vehicle",
    ],
    "Marine / Naval": [
        "acoustic warning", "acoustic warning device", "subsea sensor", "subsea sensors",
        "steering gear", "cstg", "expendable underwater target", "underwater target",
        "eut", "rudder stock", "fin stabilizer", "fin stabiliser", "naval gun", "naval guns",
        "57 mm", "57mm", "127 mm", "127mm", "propulsion shafting", "shafting",
        "shafting integrator", "submarine battery", "submarine batteries",
        "lithium-ion battery", "lithium-ion batteries", "li-ion battery",
        "torpedo homing head", "homing head", "homing heads", "torpedo", "torpedoes",
        "underwater systems", "underwater system", "mechanical products",
    ],
    "UAVs & Drones": [
        "bharat 150", "multi-rotor", "multirotor", "vtol", "uas", "uav", "uavs",
        "counter-uas", "counter uas", "c-uas", "cuas", "c-suas", "counter-drone",
        "counter drone", "anti-drone", "drone defence", "drone defense", "drone jammer",
        "drone jammers",
        "ecars", "autonomous rover", "ugv", "ugvs", "unmanned ground",
        "unmanned ground vehicle", "kalyani uav", "multi-role uav", "ultra uav",
        "loitering munition", "loitering munitions", "precision loitering munition",
    ],
    # no file heading -- anchors are the product rows that name missiles
    "Missiles & Air Defence": [
        "mrsam", "mrsam missile", "missile subsystem", "missile subsystems",
        "spike atgm", "spike", "atgm",
    ],
    # no file heading, no rows -- nothing to anchor; the keyword gate judges alone
    "Precision Components & Forgings": [],
}

# The 59 product names as written in the file, for the coverage test: every one of
# them must be rescued by an anchor of its own tag.
PRODUCT_NAMES = [
    ("Artillery", "ATAGS"), ("Artillery", "Bharat 45"), ("Artillery", "Bharat 52"),
    ("Artillery", "Bharat ULH 155/39"), ("Artillery", "Garuda 105 V2"),
    ("Artillery", "MaRG 155-BR"), ("Artillery", "MaRG 39"), ("Artillery", "MaRG 45"),
    ("Artillery", "MaRG 52"), ("Artillery", "MaRG ER"), ("Artillery", "MaRG TC-20"),
    ("Ammunition", "Artillery ERFB Projectiles (ERFB-BT / ERFB-BB)"),
    ("Ammunition", "CIWS Smart Programmable Ammunition"),
    ("Ammunition", "Conventional Artillery Shell Bodies (Empty & Filled)"),
    ("Ammunition", "FSAPDS Ammunition"), ("Ammunition", "High Explosive (HE) Artillery Shells"),
    ("Ammunition", "Illuminating Artillery Shells"), ("Ammunition", "Incendiary Artillery Shells"),
    ("Ammunition", "Low- & Medium-Velocity Grenade Cartridges"),
    ("Ammunition", "MRSAM Missile Subsystems & Integration Kits"),
    ("Ammunition", "Small Arms Cartridges Suite"), ("Ammunition", "Smoke Artillery Shells"),
    ("Ammunition", "Spike ATGM Sub-assemblies"),
    ("Small Arms", "Assault Rifle - AR M5F41 / Arsenal AR Series"),
    ("Small Arms", "CQB Carbine - F90"),
    ("Small Arms", "FN Herstal Integrated Weapon Mounts / C-UAS Turret"),
    ("Small Arms", "Light Machine Gun - 7.62mm MG-M2 / Arsenal MG"),
    ("Small Arms", "Protective Carbine - 5.56 x 30 mm"), ("Small Arms", "Sniper Rifles - T-5000M"),
    ("Small Arms", "Under-Barrel Grenade Launcher (UBGL)"),
    ("Protected Vehicles", "Armoured Personnel Carrier"),
    ("Protected Vehicles", "Armoured Troops Carrier"),
    ("Protected Vehicles", "High Mobility Reconnaissance Vehicle - HMRV"),
    ("Protected Vehicles", "Kalyani M4"), ("Protected Vehicles", "Kalyani Maverick"),
    ("Protected Vehicles", "Light Bullet-Proof Vehicle"),
    ("Protected Vehicles", "Light Tactical Vehicle"), ("Protected Vehicles", "Mine Protected Vehicle"),
    ("Protected Vehicles", "Simha 4x4"), ("Protected Vehicles", "Ultra-Light Strike Vehicle"),
    ("Armoured Vehicles - MRO", "Driveline - Armoured Vehicles / MRO"),
    ("Armoured Vehicles - MRO", "MRO - Armoured Vehicles"),
    ("Armoured Vehicles - MRO", "Ordnance - Armoured Vehicles / MRO"),
    ("Armoured Vehicles - MRO", "Powertrain - Armoured Vehicles / MRO"),
    ("Armoured Vehicles - MRO", "Running Gear - Armoured Vehicles / MRO"),
    ("Marine / Naval", "Acoustic Warning Devices & Subsea Sensors"),
    ("Marine / Naval", "CSTG - Control System for Steering Gear"),
    ("Marine / Naval", "EUT - Expendable Underwater Target"),
    ("Marine / Naval", "Mechanical Products - Marine"), ("Marine / Naval", "Naval Guns"),
    ("Marine / Naval", "PSI - Propulsion Shafting Integrator"),
    ("Marine / Naval", "Submarine Lithium-Ion Battery Systems"),
    ("Marine / Naval", "UMHT - Torpedo Homing Head / MRO"),
    ("Marine / Naval", "Underwater Systems Portfolio"),
    ("UAVs & Drones", "Bharat 150 UAV"), ("UAVs & Drones", "Counter-UAS (C-UAS) Mobile System"),
    ("UAVs & Drones", "ECARS - Enhanced Collaborative Autonomous Rover System"),
    ("UAVs & Drones", "Kalyani UAV / Multi-role UAV platform"),
    ("UAVs & Drones", "Ultra UAV / Precision Loitering Munition"),
]
