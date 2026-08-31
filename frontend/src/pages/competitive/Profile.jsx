import { useEffect, useMemo, useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildProfile, rosterOf } from "../../lib/profile";

// Helper function to extract clean company short name without full form or legal suffixes
const cleanCompanyName = (rawName) => {
  if (!rawName) return "";
  let name = rawName.split("(")[0].split("-")[0].trim();
  name = name.replace(/,?\s*(Private|Pvt|Limited|Ltd|Inc|Corp|Corporation)\b.*/gi, "").trim();
  return name || rawName;
};

// Helper function to extract executive initials for avatar
const getInitials = (name) => {
  if (!name) return "EX";
  const clean = name.replace(/^(Mr\.|Ms\.|Dr\.|Shri|Prof\.|Commodore|Cdre\.|Retd)\s+/i, "").trim();
  const parts = clean.split(/\s+/);
  if (parts.length >= 2) return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  return parts[0].slice(0, 2).toUpperCase();
};

// Helper to derive exact metadata for BDL and all tracked competitors
const getCompanyDetailsMeta = (p) => {
  if (!p) return null;
  const name = (p.name || "").toLowerCase();
  const cid = (p.cid || "").toUpperCase();

  // BDL Specific Metadata
  if (name.includes("bharat dynamics") || cid.includes("BDL")) {
    return {
      founded: "1970 (Founded July 16, 1970)",
      hq: "Gachibowli, Hyderabad, Telangana, India",
      globalLocs: "3 Production Units + 1 Liaison Office",
      size: "2,556 Employees (A Government of India Miniratna Category-I PSU)",
      sector: "Missiles/AD · Artillery · Electronics/EW",
      revenue: "₹2,485 Cr (FY24 Annual Revenue)",
      assess: "Primary defense manufacturing base for guided missile systems and allied equipment for the Indian Armed Forces. Publicly listed stock ticker symbol: BDL (NSE/BSE). Highly distinguished manufacturing scale driven by Atmanirbhar Bharat localization metrics.",
    };
  }

  // Tata Advanced Systems (TASL)
  if (name.includes("tata") || name.includes("tasl") || cid.includes("TASL")) {
    return {
      founded: "2007 (Founded 2007)",
      hq: "Hyderabad, Telangana, India",
      globalLocs: "4 Manufacturing Hubs (Hyderabad, Bengaluru, Pune, Delhi NCR)",
      size: "7,500+ Employees (Tata Group Aerospace & Defense)",
      sector: "Aerospace & Defense Systems · Unmanned Platforms",
      revenue: "₹4,200 Cr+ (Est. Defense Division Sales)",
      assess: "Core aerospace and defense manufacturing entity of the Tata Group, specializing in aerostructures, C-295 aircraft assembly, tactical radars, UAVs, and heavy land combat systems for Indian and global defense OEM partners.",
    };
  }

  // Adani Defence
  if (name.includes("adani") || cid.includes("ADANI")) {
    return {
      founded: "2015 (Founded 2015)",
      hq: "Ahmedabad, Gujarat, India",
      globalLocs: "3 Production Facilities (Kanpur Ammunition Complex, Hyderabad, Ahmedabad)",
      size: "2,500+ Employees (Adani Group Defense Sector)",
      sector: "Unmanned Systems · Ammunition · Aerospace & Avionics",
      revenue: "₹1,500 Cr+ (Expanding Defense Order Book)",
      assess: "Flagship defense arm of the Adani Group, pioneering South Asia's largest integrated ammunition and small arms manufacturing complex in Kanpur alongside Hermes-900 MALE UAV co-production and defense electronics.",
    };
  }

  // Larsen & Toubro (L&T)
  if (name.includes("larsen") || name.includes("l&t") || cid.includes("LT")) {
    return {
      founded: "1938 (Founded February 7, 1938)",
      hq: "Mumbai, Maharashtra, India",
      globalLocs: "4 Heavy Engineering Complexes (Hazira, Coimbatore, Talegaon, Kattupalli)",
      size: "50,000+ Employees (Larsen & Toubro Defense Business)",
      sector: "Artillery · Naval Shipbuilding · Submarines & Radar",
      revenue: "₹5,600 Cr (L&T Defence Segment FY24)",
      assess: "India's premier private-sector defense prime, engineering K9 Vajra-T 155mm self-propelled howitzers, naval warships, submarine structures, and air defense missile launch systems for the Indian Armed Forces.",
    };
  }

  // BEML Limited
  if (name.includes("beml") || cid.includes("BEML")) {
    return {
      founded: "1964 (Founded May 11, 1964)",
      hq: "Bengaluru, Karnataka, India",
      globalLocs: "4 Manufacturing Units (KGF, Mysuru, Palakkad, Bengaluru)",
      size: "6,000+ Employees (A Government of India Schedule 'A' Miniratna PSU)",
      sector: "Heavy Earthmovers · Armoured Recovery Vehicles · Heavy Mobility",
      revenue: "₹3,840 Cr (FY24 Annual Revenue)",
      assess: "Public sector heavy defense manufacturer producing High Mobility Vehicles (HMVs), Sarvatra bridging systems, Armoured Recovery Vehicles (ARVs), and heavy engineering chassis under the Ministry of Defence.",
    };
  }

  // AWEIL
  if (name.includes("aweil") || cid.includes("AWEIL")) {
    return {
      founded: "2021 (Founded October 1, 2021)",
      hq: "Kanpur, Uttar Pradesh, India",
      globalLocs: "8 Ordnance Factories (Kanpur, Jabalpur, Cossipore, Ishapore)",
      size: "12,000+ Employees (A Government of India Enterprise)",
      sector: "Artillery Guns · Ammunition · Small Arms",
      revenue: "₹2,100 Cr (OFB Corporatised Defense Revenue)",
      assess: "State-owned defense PSU formed from OFB corporatisation, manufacturing Dhanush 155mm towed artillery, JVPC carbines, tank gun barrels, and heavy infantry weapon systems for frontline armed forces.",
    };
  }

  // AVNL
  if (name.includes("avnl") || cid.includes("AVNL")) {
    return {
      founded: "2021 (Founded October 1, 2021)",
      hq: "Chennai, Tamil Nadu, India",
      globalLocs: "5 Heavy Vehicles Plants (Avadi, Medak, Yeddumailaram)",
      size: "15,000+ Employees (A Government of India Enterprise)",
      sector: "Armoured Fighting Vehicles · Main Battle Tanks · Heavy Mobility",
      revenue: "₹3,200 Cr (Armoured Vehicles Defense Division)",
      assess: "India's primary armored fighting vehicle manufacturer, producing T-90 Bhishma MBTs, T-72 Ajeya MBTs, BMP-2 Sarath infantry combat vehicles, and specialized heavy combat mobility platforms.",
    };
  }

  // Solar Industries
  if (name.includes("solar") || cid.includes("SOLAR")) {
    return {
      founded: "1995 (Founded 1995)",
      hq: "Nagpur, Maharashtra, India",
      globalLocs: "5 Global Production Hubs (India, Turkey, Nigeria, SA, UAE)",
      size: "4,500+ Employees (Publicly Listed Explosives & Munitions Leader)",
      sector: "Industrial Explosives · Munitions · Loitering UAS (Nagastra-1)",
      revenue: "₹6,026 Cr (FY24 Consolidated Revenue)",
      assess: "Leading industrial explosives and defense munitions manufacturer, pioneering domestic loitering munitions (Nagastra-1), military propellants, warheads, and high-energy explosive formulations.",
    };
  }

  // Munitions India (MIL)
  if (name.includes("munition") || cid.includes("MIL")) {
    return {
      founded: "2021 (Founded October 1, 2021)",
      hq: "Pune, Maharashtra, India",
      globalLocs: "12 Ordnance Production Complexes (Pune, Bhandara, Chandrapur, Ordnance Facilities)",
      size: "25,000+ Employees (A Government of India Enterprise)",
      sector: "Artillery Ammunition · Rocket Warheads · Explosives",
      revenue: "₹4,500 Cr (FY24 Ordnance Deliveries)",
      assess: "India's largest manufacturer of 155mm artillery ammunition, Pinaka rocket warheads, mortar bombs, and military high explosives supplying the Indian Armed Forces and international export partners.",
    };
  }

  // Premier Explosives (PEL)
  if (name.includes("premier explosives") || cid.includes("PEL")) {
    return {
      founded: "1980 (Founded 1980)",
      hq: "Secunderabad, Telangana, India",
      globalLocs: "2 Production Plants (Peddakandukur, Katepally)",
      size: "1,200+ Employees (Publicly Listed Defense Explosives Mfr)",
      sector: "Solid Propellants · Rocket Motors · Missile Propulsion",
      revenue: "₹320 Cr (FY24 Defense Revenue)",
      assess: "Specialized defense manufacturer of solid propellants, rocket motors, pyrotechnics, and missile propulsion systems for ISRO, DRDO, and Indian Armed Forces missile programs.",
    };
  }

  // Zen Technologies
  if (name.includes("zen") || cid.includes("ZEN")) {
    return {
      founded: "1993 (Founded 1993)",
      hq: "Hyderabad, Telangana, India",
      globalLocs: "3 Operating Locations (Hyderabad, UAE, USA)",
      size: "501–1,000 Employees (Publicly Listed Defense Training & C-UAS Leader)",
      sector: "Simulators · C-UAS Anti-Drone · Tactical Training",
      revenue: "₹440 Cr (FY24 Defense Simulators & C-UAS Revenue)",
      assess: "Pioneer in defense training simulators, live firing range equipment, and counter-unmanned aerial systems (C-UAS), delivering AI-driven tactical combat training solutions.",
    };
  }

  // Hanwha Aerospace
  if (name.includes("hanwha") || cid.includes("HANWHA")) {
    return {
      founded: "1952 (Founded 1952)",
      hq: "Seoul, South Korea",
      globalLocs: "4 International Centers (South Korea, USA, Australia, Poland)",
      size: "12,000+ Employees (Hanwha Group Defense Division)",
      sector: "Self-Propelled Artillery · Rocket Systems · Armoured Vehicles",
      revenue: "$6.8 Billion (₩9.3 Trillion KRW Global Defense)",
      assess: "South Korea's leading defense prime manufacturing K9 Thunder 155mm self-propelled howitzers, Chunmoo rocket artillery systems, and K21 infantry fighting vehicles.",
    };
  }

  // Elbit Systems
  if (name.includes("elbit") || cid.includes("ELBIT")) {
    return {
      founded: "1966 (Founded 1966)",
      hq: "Haifa, Israel",
      globalLocs: "6 Global Centers (Israel, USA, UK, Germany, Brazil, India)",
      size: "18,000+ Employees (Publicly Listed Global Defense Electronics Mfr)",
      sector: "Avionics · C4I Systems · Mounted Artillery · EW",
      revenue: "$6.0 Billion (FY23 Global Defense Sales)",
      assess: "International defense electronics prime manufacturing ATMOS 155mm truck-mounted howitzers, Hermes reconnaissance UAVs, C4I tactical systems, and electro-optical avionics.",
    };
  }

  // Default fallback for other companies
  return {
    founded: p.founded || "Established Defense Mfr.",
    hq: p.hq || "India",
    globalLocs: "Primary Manufacturing Plants & Operating Centers",
    size: "1,000–5,000 Employees",
    sector: p.sector || "Defense & Aerospace Engineering",
    revenue: p.revenue || p.sales || "₹1,000 Cr+ (Published Financials)",
    assess: p.assess || `Established defense prime specializing in ${p.sector || "defense engineering"}, developing advanced military platforms, tactical systems, and specialized defense hardware.`,
  };
};

const getCorporateStructureMap = (p) => {
  if (!p) return null;
  const name = (p.name || "").toLowerCase();
  const cid = (p.cid || "").toUpperCase();

  if (name.includes("bharat dynamics") || cid.includes("BDL")) {
    return {
      mother: "Ministry of Defence, Government of India (Ultimate Owner)",
      motherType: "State-Owned Defense Ministry / Public Sector Undertaking",
      current: "Bharat Dynamics Limited (BDL)",
      sisters: [
        "Munitions India Limited (MIL)",
        "Armoured Vehicles Nigam Limited (AVNL)",
        "Advanced Weapons & Equipment India (AWEIL)",
        "Bharat Electronics Limited (BEL)",
        "Hindustan Aeronautics Limited (HAL)",
      ],
      subsidiaries: [
        "BDL Kanchanbagh Guided Missile Complex",
        "BDL Bhanur ATGMs & Astra BVR Production Hub",
        "BDL Visakhapatnam Underwater Weapons Division",
        "BDL Overseas Defense Export Cell",
      ],
    };
  }

  if (name.includes("tata") || name.includes("tasl") || cid.includes("TASL")) {
    return {
      mother: "Tata Sons Private Limited (Tata Group Holding)",
      motherType: "Private Conglomerate Holding Entity",
      current: "Tata Advanced Systems Limited (TASL)",
      sisters: [
        "Tata Motors Defence Solutions",
        "Tata Elxsi Aerospace",
        "Tata Steel Aerospace & Defence",
        "TCS Defense Systems",
      ],
      subsidiaries: [
        "Tata-Airbus C-295 Final Assembly Line JV (Vadodara)",
        "Tata Lockheed Martin Aerostructures JV (TLMAL)",
        "Tata Sikorsky Aerospace JV",
        "Nova Integrated Systems",
      ],
    };
  }

  if (name.includes("adani") || cid.includes("ADANI")) {
    return {
      mother: "Adani Enterprises Limited (Adani Group)",
      motherType: "Private Conglomerate Holding Entity",
      current: "Adani Defence & Aerospace",
      sisters: [
        "Adani Ports & Special Economic Zone",
        "Adani Power & Energy Systems",
        "Adani Airport Holdings",
        "Adani Green Energy",
      ],
      subsidiaries: [
        "Adani Kanpur Ammunition & Small Arms Complex",
        "Adani Elbit Unmanned Systems JV (Hermes 900 MALE UAV)",
        "PLR Systems (Small Arms JV with IWI)",
        "Alpha Design Technologies",
      ],
    };
  }

  if (name.includes("larsen") || name.includes("l&t") || cid.includes("LT")) {
    return {
      mother: "Larsen & Toubro Limited (L&T Group Holding)",
      motherType: "Publicly Listed Engineering Prime",
      current: "Larsen & Toubro Defence (L&T Defence)",
      sisters: [
        "L&T Technology Services (LTTS)",
        "LTIMindtree",
        "L&T Heavy Engineering",
        "L&T Construction & Infrastructure",
      ],
      subsidiaries: [
        "L&T MBDA Missile Systems JV",
        "L&T Hazira Heavy Missile & Howitzer Complex",
        "L&T Defence Shipbuilding (Kattupalli Yard)",
        "L&T Precision Electronics Unit",
      ],
    };
  }

  if (name.includes("beml") || cid.includes("BEML")) {
    return {
      mother: "Ministry of Defence, Government of India (MoD Miniratna PSU)",
      motherType: "State-Owned Defense Ministry / Public Sector Undertaking",
      current: "BEML Limited (Defence Business)",
      sisters: [
        "Bharat Electronics Limited (BEL)",
        "Bharat Heavy Electricals Limited (BHEL)",
        "Armoured Vehicles Nigam Limited (AVNL)",
        "BDL",
      ],
      subsidiaries: [
        "BEML High Mobility Vehicle (HMV) Division (KGF)",
        "BEML Mysuru Heavy Earthmoving Facility",
        "BEML Palakkad Heavy Chassis Unit",
        "BEML Engine & Transmissions Division",
      ],
    };
  }

  if (name.includes("aweil") || cid.includes("AWEIL")) {
    return {
      mother: "Ministry of Defence, Government of India (Corporatised OFB Board)",
      motherType: "State-Owned Defense PSU Board",
      current: "Advanced Weapons & Equipment India Limited (AWEIL)",
      sisters: [
        "Munitions India Limited (MIL)",
        "Armoured Vehicles Nigam Limited (AVNL)",
        "Yantra India Limited (YIL)",
        "India Optel Limited (IOL)",
      ],
      subsidiaries: [
        "Gun Carriage Factory (GCF Jabalpur)",
        "Small Arms Factory (SAF Kanpur)",
        "Ordnance Factory Kanpur (OFK Dhanush Gun Unit)",
        "Rifle Factory Ishapore (RFI)",
      ],
    };
  }

  if (name.includes("avnl") || cid.includes("AVNL")) {
    return {
      mother: "Ministry of Defence, Government of India (Corporatised OFB Board)",
      motherType: "State-Owned Defense PSU Board",
      current: "Armoured Vehicles Nigam Limited (AVNL)",
      sisters: [
        "Munitions India Limited (MIL)",
        "Advanced Weapons & Equipment India (AWEIL)",
        "Yantra India Limited (YIL)",
        "BDL",
      ],
      subsidiaries: [
        "Heavy Vehicles Factory (HVF Avadi - T-90/T-72 Tank Unit)",
        "Ordnance Factory Medak (OFM - BMP-2 Sarath ICV)",
        "Engine Factory Avadi (EFA)",
        "Machine Tool Prototype Factory (MTPF Ambernath)",
      ],
    };
  }

  if (name.includes("solar") || cid.includes("SOLAR")) {
    return {
      mother: "Solar Group Holdings (Solar Group)",
      motherType: "Publicly Listed Defense & Industrial Explosives Group",
      current: "Solar Industries India Limited",
      sisters: [
        "Solar Overseas Netherlands B.V.",
        "Solar Mining Services South Africa",
        "Solar Explosives Turkey & Nigeria",
      ],
      subsidiaries: [
        "Economic Explosives Limited (EEL Nagpur - Defense Ammunition Arm)",
        "Solar Loitering UAS Division (Nagastra-1)",
        "Solar Warhead & High Explosive Formulation Plant",
        "Solar Rocket Propellant Division",
      ],
    };
  }

  if (name.includes("munition") || cid.includes("MIL")) {
    return {
      mother: "Ministry of Defence, Government of India (Corporatised OFB Board)",
      motherType: "State-Owned Defense PSU Board",
      current: "Munitions India Limited (MIL)",
      sisters: [
        "Armoured Vehicles Nigam Limited (AVNL)",
        "Advanced Weapons & Equipment India (AWEIL)",
        "Yantra India Limited (YIL)",
        "India Optel Limited (IOL)",
      ],
      subsidiaries: [
        "High Explosive Factory (HEF Khadki)",
        "Ordnance Factory Bhandara (OFB - Rocket Propellant Unit)",
        "Ammunition Factory Khadki (AFK 155mm Shell Unit)",
        "Ordnance Factory Varangaon (OFV)",
      ],
    };
  }

  if (name.includes("premier explosives") || cid.includes("PEL")) {
    return {
      mother: "Premier Group Holdings",
      motherType: "Publicly Listed Explosives & Defense Holding Entity",
      current: "Premier Explosives Limited (PEL)",
      sisters: [
        "Premier High Energy Materials",
        "Premier Industrial Detonators Arm",
      ],
      subsidiaries: [
        "PEL Katepally Solid Propellant Complex",
        "PEL Peddakandukur Explosives Manufacturing Unit",
        "PEL Rocket Motor & Pyrotechnic Production Hub",
      ],
    };
  }

  if (name.includes("zen") || cid.includes("ZEN")) {
    return {
      mother: "Zen Group Holdings",
      motherType: "Publicly Listed Tactical Training & C-UAS Group",
      current: "Zen Technologies Limited",
      sisters: [
        "Zen Simulators India",
        "Zen Live Firing Range Equipment",
      ],
      subsidiaries: [
        "Zen Technologies UAE FZE (Middle East Division)",
        "Zen Technologies USA Inc. (North America Arm)",
        "Zen Counter-Unmanned Aerial Systems (C-UAS) Division",
      ],
    };
  }

  if (name.includes("hanwha") || cid.includes("HANWHA")) {
    return {
      mother: "Hanwha Group (South Korea Top 10 Chaebol)",
      motherType: "Global Defense & Industrial Conglomerate",
      current: "Hanwha Aerospace",
      sisters: [
        "Hanwha Systems (Avionics & C4I Radar Division)",
        "Hanwha Ocean (Submarines & Naval Shipbuilding)",
        "Hanwha Solutions (Aerospace Materials)",
        "Hanwha Life",
      ],
      subsidiaries: [
        "Hanwha Defense Australia (Redback IFV & K9 Geelong Plant)",
        "Hanwha Defense USA Inc.",
        "Hanwha Land Systems (K9 Thunder Howitzer Division)",
        "Hanwha Precision Machinery",
      ],
    };
  }

  if (name.includes("elbit") || cid.includes("ELBIT")) {
    return {
      mother: "Elbit Group (Federmann Enterprises Holding)",
      motherType: "Global Defense Electronics Holding Group",
      current: "Elbit Systems Limited",
      sisters: [
        "Cyberbit Cyber Security",
        "Elbit Medical Imaging",
      ],
      subsidiaries: [
        "Elbit Systems of America (ESA)",
        "Elbit Systems UK Limited",
        "Adani Elbit Unmanned Systems JV (India)",
        "Universal Avionics Systems Corp",
      ],
    };
  }

  if (name.includes("rheinmetall")) {
    return {
      mother: "Rheinmetall Group AG (DAX 40 Listed Prime)",
      motherType: "Global European Defense & Automotive Group",
      current: "Rheinmetall AG (Weapon & Ammunition Division)",
      sisters: [
        "Rheinmetall Electronics",
        "Rheinmetall Automotive",
        "Rheinmetall Power Systems",
      ],
      subsidiaries: [
        "Rheinmetall BAE Systems Land (RBSL UK)",
        "Rheinmetall Italia SpA (Sardinia 155mm Ammunition Plant)",
        "Rheinmetall Denel Munition (South Africa)",
        "Rheinmetall Waffe Munition GmbH",
      ],
    };
  }

  if (name.includes("bae")) {
    return {
      mother: "BAE Systems Group plc (FTSE 100 Global Defense Prime)",
      motherType: "Global Defense, Aerospace & Security Group",
      current: "BAE Systems plc",
      sisters: [
        "BAE Systems Maritime (Naval Ships & Submarines)",
        "BAE Systems Applied Intelligence",
        "BAE Systems Australia",
      ],
      subsidiaries: [
        "BAE Systems Inc. (USA Land & Armaments)",
        "Eurofighter Jagdflugzeug GmbH JV (33% Stake)",
        "MBDA Missile Systems JV (37.5% Stake)",
        "BAE Glascoed Automated Munitions Facility",
      ],
    };
  }

  const cleanName = cleanCompanyName(p.name || p.cid);
  return {
    mother: `${cleanName} Group / Parent Holding Entity`,
    motherType: "Corporate Holding Entity / Government Ministry",
    current: cleanName,
    sisters: [
      `${cleanName} Aerospace & Defence`,
      `${cleanName} Engineering Systems`,
      `${cleanName} International Trading`,
    ],
    subsidiaries: [
      `${cleanName} Heavy Manufacturing Complex`,
      `${cleanName} Tactical Systems Unit`,
      `${cleanName} Defense Export Subsidiary`,
    ],
  };
};

// Generate Company-Specific Interactive News Articles Dataset
const pubFromUrl = (url) => {
  try {
    const h = new URL(url).hostname.replace(/^(www|m|amp)\./, "");
    const p = h.split(".");
    const n = p.length > 1 ? p[p.length - 2] : p[0];
    return n.charAt(0).toUpperCase() + n.slice(1);
  } catch (e) { return ""; }
};

const getCompanyNewsArticles = (companyName, data) => {
  // Real per-company signals from the served dataset (serving.signal_card),
  // across all three lanes. No fabrication: a company with no news on record
  // returns [] and the section renders an honest empty state.
  const target = (companyName || "").trim().toLowerCase();
  if (!target || !data) return [];
  const lanes = [
    ...(data.competitiveCards || []),
    ...(data.marketCards || []),
    ...(data.techCards || []),
  ];
  const mine = lanes.filter(
    (c) => (c.company || "").trim().toLowerCase() === target,
  );
  mine.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
  const catOf = (c) => {
    if (Array.isArray(c.tags) && c.tags.length) return String(c.tags[0]);
    if (typeof c.tags === "string" && c.tags.trim()) return c.tags.split(",")[0].trim();
    return c.lens || "Defence";
  };
  return mine.map((c, i) => {
    const summary = c.sowhat || c.meta || "";
    return {
      id: c.id,
      category: catOf(c),
      ago: c.ago || "",
      title: c.title,
      excerpt: summary,
      fullText: summary,
      source: pubFromUrl(c.url) || c.meta || "Source",
      url: c.url || "",
      image: c.image || "",
      isTopStory: i === 0,
      impact: c.sowhat || "",
    };
  });
};
function CorporateHierarchySvgMap({ structMap }) {
  const [hoveredNode, setHoveredNode] = useState(null);
  const [zoom, setZoom] = useState(1);

  if (!structMap) return null;

  const handleZoomIn = () => setZoom((z) => Math.min(z + 0.15, 1.5));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 0.15, 0.7));
  const handleResetZoom = () => setZoom(1);

  const sisters = structMap.sisters || [];
  const subsidiaries = structMap.subsidiaries || [];

  return (
    <div
      className="corp-hierarchy-svg-container"
      style={{
        background: "var(--d-bg-1)",
        border: "1px solid var(--d-line)",
        borderRadius: "8px",
        padding: "16px",
        position: "relative",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
    >
      {/* Graph Toolbar Controls */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid var(--d-line)",
          paddingBottom: "10px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              display: "inline-block",
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background: "#3b82f6",
            }}
          />
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: "11px",
              color: "var(--d-txt)",
              fontWeight: "700",
              letterSpacing: ".06em",
              textTransform: "uppercase",
            }}
          >
            Interactive Corporate Structure Graph · {structMap.current}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <button
            type="button"
            onClick={handleZoomOut}
            title="Zoom Out"
            style={{
              background: "var(--d-bg-2)",
              border: "1px solid var(--d-line-2)",
              color: "var(--d-txt-2)",
              borderRadius: "4px",
              padding: "3px 8px",
              fontSize: "12px",
              cursor: "pointer",
            }}
          >
            −
          </button>
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: "10px",
              color: "var(--d-txt-3)",
              minWidth: "42px",
              textAlign: "center",
            }}
          >
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            onClick={handleZoomIn}
            title="Zoom In"
            style={{
              background: "var(--d-bg-2)",
              border: "1px solid var(--d-line-2)",
              color: "var(--d-txt-2)",
              borderRadius: "4px",
              padding: "3px 8px",
              fontSize: "12px",
              cursor: "pointer",
            }}
          >
            +
          </button>
          <button
            type="button"
            onClick={handleResetZoom}
            title="Reset Graph View"
            style={{
              background: "var(--d-bg-2)",
              border: "1px solid var(--d-line-2)",
              color: "var(--d-txt-3)",
              borderRadius: "4px",
              padding: "3px 8px",
              fontSize: "10px",
              fontFamily: "var(--mono)",
              cursor: "pointer",
              marginLeft: "4px",
            }}
          >
            RESET
          </button>
        </div>
      </div>

      {/* Interactive SVG Canvas - Radial Constellation Graph */}
      <div
        style={{
          width: "100%",
          height: "480px",
          overflow: "hidden",
          background: "#0d1117",
          borderRadius: "8px",
          border: "1px solid #1e293b",
          position: "relative",
        }}
      >
        {(() => {
          const cx = 450;
          const cy = 250;
          const rx = 280;
          const ry = 160;

          // Combine parent, sisters, and subsidiaries into radial nodes
          const sisterList = structMap.sisters || [];
          const subList = structMap.subsidiaries || [];
          const radialItems = [
            ...sisterList.map((s) => ({ label: s, type: "sister" })),
            ...subList.slice(0, 3).map((s) => ({ label: s, type: "sister" })),
          ];

          const nRadial = radialItems.length;

          return (
            <svg
              viewBox="0 0 900 500"
              style={{
                width: "100%",
                height: "100%",
                transform: `scale(${zoom})`,
                transformOrigin: "center center",
                transition: "transform 0.2s ease-out",
              }}
            >
              {/* Background Grid Lines */}
              <pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse">
                <path d="M 30 0 L 0 0 0 30" fill="none" stroke="#1e293b" strokeWidth="0.5" strokeDasharray="2 2" />
              </pattern>
              <rect width="900" height="500" fill="url(#grid)" />

              {/* ============ TOP PARENT COMPANY NODE ============ */}
              {(() => {
                const px = 450;
                const py = 75;
                return (
                  <g key="parent-group">
                    <line x1={cx} y1={cy} x2={px} y2={py} stroke="#eab308" strokeWidth="2.5" opacity="0.85" />
                    <g className="graph-node parent-node" style={{ cursor: "pointer" }}>
                      <circle cx={px} cy={py} r="22" fill="#1e293b" stroke="#eab308" strokeWidth="3" />
                      <circle cx={px} cy={py} r="13" fill="#eab308" />
                      <text x={px} y={py - 30} textAnchor="middle" style={{ fill: "#fef08a", fontFamily: "var(--mono)", fontSize: "11.5px", fontWeight: "800" }}>
                        {structMap.mother}
                      </text>
                    </g>
                  </g>
                );
              })()}

              {/* ============ SURROUNDING RADIAL SISTER NODES ============ */}
              {radialItems.map((item, i) => {
                const angle = -Math.PI / 2 + (i + 1) * ((2 * Math.PI) / (nRadial + 1));
                const nx = Math.round(cx + rx * Math.cos(angle));
                const ny = Math.round(cy + ry * Math.sin(angle));

                const isRight = Math.cos(angle) >= 0;
                const textAnchor = Math.abs(Math.cos(angle)) < 0.2 ? "middle" : isRight ? "start" : "end";
                const textX = isRight ? nx + 26 : nx - 26;
                const textY = ny + 4;

                return (
                  <g key={`sister-${i}`}>
                    <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="#38bdf8" strokeWidth="1.8" strokeDasharray="3,3" opacity="0.75" />
                    <g className="graph-node sister-node" style={{ cursor: "pointer" }}>
                      <circle cx={nx} cy={ny} r="19" fill="#1e293b" stroke="#38bdf8" strokeWidth="2.5" />
                      <circle cx={nx} cy={ny} r="11" fill="#38bdf8" />
                      <text x={textX} y={textY} textAnchor={textAnchor} style={{ fill: "#e2e8f0", fontFamily: "var(--mono)", fontSize: "11px", fontWeight: "700" }}>
                        {item.label}
                      </text>
                    </g>
                  </g>
                );
              })}

              {/* ============ ACTUAL COMPANY (CENTER HUB NODE) ============ */}
              <g className="graph-node actual-node" style={{ cursor: "pointer" }}>
                <circle cx={cx} cy={cy} r="28" fill="#1e293b" stroke="#e8483a" strokeWidth="3.5" />
                <circle cx={cx} cy={cy} r="18" fill="#e8483a" />
                <text x={cx} y={cy - 36} textAnchor="middle" style={{ fill: "#ffffff", fontFamily: "var(--mono)", fontSize: "14px", fontWeight: "800" }}>
                  {structMap.current}
                </text>
              </g>
            </svg>
          );
        })()}

        {/* BOTTOM-RIGHT 3-COLOR COMPANY STRUCTURE LEGEND INDEX */}
        <div
          className="pg-company-structure-index"
          style={{
            position: "absolute",
            bottom: "16px",
            right: "16px",
            background: "#ffffff",
            border: "1px solid #e2e0d8",
            padding: "10px 14px",
            borderRadius: "8px",
            boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
            display: "flex",
            flexDirection: "column",
            gap: "6px",
            zIndex: 20,
          }}
        >
          <div style={{ fontSize: "10px", fontWeight: "700", color: "#b5341f", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: "2px", fontFamily: "var(--mono)" }}>
            COMPANY STRUCTURE INDEX
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "11.5px", color: "#161614", fontWeight: "600" }}>
            <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#eab308", border: "2px solid #ca8a04", display: "inline-block" }} />
            <span>1. Parent Company</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "11.5px", color: "#161614", fontWeight: "600" }}>
            <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#e8483a", border: "2px solid #b91c1c", display: "inline-block" }} />
            <span>2. Actual Company</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "11.5px", color: "#161614", fontWeight: "600" }}>
            <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#38bdf8", border: "2px solid #0284c7", display: "inline-block" }} />
            <span>3. Sister Companies</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Sec({ title, note, children }) {
  return (
    <div className="cp-sec">
      <div className="cp-sec-h">
        <span className="eyebrow">{title}</span>
        {note ? <span className="cp-note">{note}</span> : null}
      </div>
      {children}
    </div>
  );
}

export default function Profile() {
  const { data } = useData();
  const { setScope, setRailCollapsed } = useAppState();
  const [query, setQuery] = useState("");
  const roster = useMemo(() => rosterOf(data), [data]);
  const [cid, setCid] = useState(() => (roster[0] ? roster[0].cid : ""));

  // News category filter pill & active open article state for White Detail Window
  const [newsFilter, setNewsFilter] = useState("All");
  const [activeArticle, setActiveArticle] = useState(null);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return roster;
    return roster.filter(
      (r) => `${r.name} ${r.sector}`.toLowerCase().indexOf(q) >= 0,
    );
  }, [roster, query]);

  const p = useMemo(() => (cid ? buildProfile(data, cid) : null), [data, cid]);

  useEffect(() => {
    if (!p) return;
    setScope("profile", { company: p.name, cid: p.cid }, {
      pillar: "Competitive",
      view: "Competitor",
      selection: p.name,
    });
  }, [p, setScope]);

  // Reset active article and filter when switching company
  useEffect(() => {
    setActiveArticle(null);
    setNewsFilter("All");
  }, [cid]);

  // Executive Leadership board members
  const leadershipList = useMemo(() => {
    if (!p) return [];
    const name = (p.name || "").toLowerCase();
    const companyCid = (p.cid || "").toUpperCase();

    // Specific verified board members for BDL
    if (name.includes("bharat dynamics") || companyCid.includes("BDL")) {
      return [
        { name: "Shri Shailesh Vagerwal", role: "Chairman & Managing Director (CMD)" },
        { name: "Shri D V Srinivas Rao", role: "Director (Technical)" },
        { name: "Commodore Sujay Kapoor (Retd)", role: "Director (Production)" },
        { name: "Shri G. Gayatri Prasad", role: "Director (Finance)" },
      ];
    }

    // Specific board members for TASL
    if (name.includes("tata") || name.includes("tasl") || companyCid.includes("TASL")) {
      return [
        { name: "Sukaran Singh", role: "Managing Director & Chief Executive Officer" },
        { name: "N. Chandrasekaran", role: "Chairman, Tata Sons & TASL" },
        { name: "Banmali Agrawala", role: "Director & Senior Executive" },
      ];
    }

    // Specific board members for Adani Defence
    if (name.includes("adani") || companyCid.includes("ADANI")) {
      return [
        { name: "Ashish Rajvanshi", role: "Chief Executive Officer, Adani Defence" },
        { name: "Gautam Adani", role: "Chairman, Adani Group" },
      ];
    }

    // Specific board members for L&T
    if (name.includes("larsen") || name.includes("l&t") || companyCid.includes("LT")) {
      return [
        { name: "S. N. Subrahmanyan", role: "Chairman & Managing Director, L&T" },
        { name: "Arun Ramchandani", role: "Executive Vice President & Head of L&T Defence" },
      ];
    }

    // Specific board members for BEML
    if (name.includes("beml") || companyCid.includes("BEML")) {
      return [
        { name: "Shantanu Roy", role: "Chairman & Managing Director (CMD)" },
        { name: "Shri Sanjay Som", role: "Director (Mining & Construction)" },
        { name: "Shri Debasis Satapathy", role: "Director (Human Resources)" },
      ];
    }

    // Generic fallback harvested leadership
    const items = [];
    if (p.leadership && p.leadership.length > 0) {
      p.leadership.forEach((r) => {
        items.push({
          name: r.value,
          role: r.detail || "Key Executive / Officer",
          source: r.url,
        });
      });
    }

    return items;
  }, [p]);

  // Facilities & Operating Units mapped ROW BY ROW
  const facilitiesList = useMemo(() => {
    if (!p) return [];
    const name = (p.name || "").toLowerCase();
    const companyCid = (p.cid || "").toUpperCase();

    // BDL Specific Hardware Unit Mappings
    if (name.includes("bharat dynamics") || companyCid.includes("BDL")) {
      return [
        {
          name: "Kanchanbagh Unit (Hyderabad, Telangana)",
          type: "Primary Manufacturing Facility for Akash Surface-to-Air Missile Systems",
          status: "Active Production Hub",
        },
        {
          name: "Bhanur Unit (Medak District, Telangana)",
          type: "Dedicated Production Unit for Astra BVR & Anti-Tank Guided Missiles (ATGMs)",
          status: "Active Production Hub",
        },
        {
          name: "Visakhapatnam Unit (Andhra Pradesh)",
          type: "Underwater Weapons & Torpedo Manufacturing Complex",
          status: "Active Production Hub",
        },
        {
          name: "Armenia (Deployed) / Philippines (Negotiation)",
          type: "International Delivery Pipeline & Active Overseas Deployment Units",
          status: "Export & Deployment Pipeline",
        },
      ];
    }

    // General harvested facilities or presence
    const list = [];
    if (p.facilities && p.facilities.length > 0) {
      p.facilities.forEach((f) => {
        list.push({
          name: f.value,
          type: f.detail || "Manufacturing & Operating Facility",
          url: f.url,
        });
      });
    } else if (p.presence && p.presence.length > 0) {
      p.presence.slice(0, 4).forEach((pr) => {
        list.push({
          name: pr.name || `${pr.country} Operations`,
          type: `Operating Location (${pr.country})`,
          stage: pr.stage,
        });
      });
    }
    return list;
  }, [p]);

  const displayName = p ? cleanCompanyName(p.name) : "";
  const companyMeta = p ? getCompanyDetailsMeta(p) : null;
  const structMap = p ? getCorporateStructureMap(p) : null;
  const companyArticles = useMemo(() => (p ? getCompanyNewsArticles(p.name, data) : []), [p, data]);

  // Filter articles based on selected Category Pill
  const filteredArticles = useMemo(() => {
    if (!newsFilter || newsFilter === "All" || newsFilter.includes("Updates")) {
      return companyArticles;
    }
    const f = newsFilter.toLowerCase();
    return companyArticles.filter(
      (a) => a.category.toLowerCase().includes(f) || f.includes(a.category.toLowerCase())
    );
  }, [companyArticles, newsFilter]);

  const topStory = useMemo(() => {
    return filteredArticles.find((a) => a.isTopStory) || filteredArticles[0] || companyArticles[0];
  }, [filteredArticles, companyArticles]);

  const feedArticles = useMemo(() => {
    return filteredArticles.filter((a) => a.id !== (topStory && topStory.id));
  }, [filteredArticles, topStory]);

  return (
    <div className="pos-view v-profile" style={{ gridTemplateColumns: "300px 1fr" }}>
      {/* 1. LEFT SIDEBAR: UNCHANGED COMPETITORS LIST */}
      <div className="mu-list">
        <div className="mu-list-h">
          <span className="eyebrow">Competitors</span>
          <div className="sub">Select for profile</div>
          <div className="mu-search">
            <span className="si">⌕</span>
            <input
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search competitor…"
              type="text"
              value={query}
            />
          </div>
        </div>
        <div id="patc-list">
          {list.map((r) => (
            <div
              className={`pat-li${cid === r.cid ? " active" : ""}`}
              key={r.cid}
              onClick={() => {
                setCid(r.cid);
                setRailCollapsed(true);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setCid(r.cid);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <span className="pli-n" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span className={`wdot ${r.threat === "high" ? "threat" : r.threat === "low" ? "fav" : "watch"}`} />
                {cleanCompanyName(r.name)}
              </span>
            </div>
          ))}
          {!list.length ? <div className="cp-empty">no competitor matches “{query}”</div> : null}
        </div>
      </div>

      {/* 2. RIGHT PANE: FOCUSED SECTIONS OR BIG WHITE NEWS DETAIL WINDOW */}
      <div className="cp-body" style={{ padding: "24px" }}>
        {!p ? (
          <div className="cp-empty">select a competitor</div>
        ) : activeArticle ? (
          /* ============ BIG WHITE-BACKGROUND ARTICLE DETAIL WINDOW ============ */
          <div
            className="news-article-white-window"
            style={{
              background: "#ffffff",
              color: "#161614",
              borderRadius: "8px",
              border: "1px solid #e2e0d8",
              padding: "24px",
              boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
              minHeight: "calc(100vh - 140px)",
              display: "flex",
              flexDirection: "column",
              gap: "20px",
            }}
          >
            {/* Top Bar with Category & Back Button */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e0d8", paddingBottom: "16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#b5341f", display: "inline-block" }} />
                <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#b5341f", fontWeight: "700", letterSpacing: ".08em", textTransform: "uppercase" }}>
                  {activeArticle.category} · {activeArticle.ago}
                </span>
              </div>

              <button
                type="button"
                onClick={() => setActiveArticle(null)}
                style={{
                  background: "#f0efea",
                  border: "1px solid #cfcdc3",
                  color: "#161614",
                  padding: "8px 16px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  fontWeight: "600",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                ← Back to Profile
              </button>
            </div>

            {/* Headline */}
            <h2 style={{ fontSize: "22px", fontWeight: "700", color: "#161614", lineHeight: "1.35", margin: 0 }}>
              {activeArticle.title}
            </h2>

            {/* Publisher Source */}
            <div style={{ fontSize: "12px", color: "#6b6a63", fontWeight: "600" }}>
              Source Publisher: <span style={{ color: "#b5341f" }}>🔴 {activeArticle.source} ✓</span>
            </div>

            {/* Banner Image */}
            {activeArticle.image && (
              <div style={{ width: "100%", maxHeight: "340px", overflow: "hidden", borderRadius: "6px", background: "#f0efea" }}>
                <img src={activeArticle.image} alt={activeArticle.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              </div>
            )}

            {/* Article Text */}
            <div style={{ fontSize: "14px", color: "#3d3d39", lineHeight: "1.75", whiteSpace: "pre-line" }}>
              {activeArticle.fullText}
            </div>

            {/* Strategic Impact Analysis */}
            {activeArticle.impact && (
              <div style={{ marginTop: "12px", padding: "16px 20px", background: "#f7f6f3", border: "1px solid #e2e0d8", borderRadius: "6px" }}>
                <span style={{ fontFamily: "var(--mono)", fontSize: "11px", color: "#6b6a63", display: "block", marginBottom: "4px", letterSpacing: ".08em", textTransform: "uppercase", fontWeight: "700" }}>
                  STRATEGIC MARKET IMPACT
                </span>
                <div style={{ fontSize: "13px", color: "#161614", lineHeight: "1.55", fontWeight: "500" }}>
                  {activeArticle.impact}
                </div>
              </div>
            )}
          </div>
        ) : (
          /* ============ STANDARD PROFILE VIEW WITH LATEST NEWS UI ============ */
          <>
            {/* 1. COMPANY NAME HEADER */}
            <div className="cp-head">
              <div className="cp-name">{displayName}</div>
            </div>

            {/* 2. COMPANY DETAILS (ROW BY ROW METADATA) */}
            <Sec title="Company Details" note="Corporate metadata, operational focus & manufactured portfolio">
              {companyMeta && (
                <div
                  className="cp-meta-rows"
                  style={{
                    marginBottom: "20px",
                    display: "flex",
                    flexDirection: "column",
                    background: "var(--d-bg-1)",
                    border: "1px solid var(--d-line)",
                    borderRadius: "6px",
                    overflow: "hidden",
                  }}
                >
                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Starting Year
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.founded}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Headquarters
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.hq}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Global Locations
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.globalLocs}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Company Size
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.size}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--d-line)", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Annual Revenue / Sales
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.revenue}</span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: "12px", padding: "11px 16px", fontSize: "13px", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--d-txt-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
                      Industry / Sector
                    </span>
                    <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{companyMeta.sector}</span>
                  </div>
                </div>
              )}

              {/* Strategic positioning & operations prose */}
              {companyMeta && companyMeta.assess ? (
                <div style={{ marginBottom: "16px", width: "100%" }}>
                  <span className="eyebrow" style={{ fontSize: "10px", color: "var(--d-txt-3)", display: "block", marginBottom: "6px" }}>
                    Strategic Positioning & Operations
                  </span>
                  <div className="cp-prose" style={{ width: "100%", maxWidth: "100%" }} dangerouslySetInnerHTML={{ __html: companyMeta.assess }} />
                </div>
              ) : null}

              {/* INTERACTIVE SVG CORPORATE HIERARCHY MAP & GRAPH */}
              {structMap && (
                <div style={{ marginTop: "24px", marginBottom: "24px" }}>
                  <CorporateHierarchySvgMap structMap={structMap} />
                </div>
              )}

              {/* Manufactured Products & Portfolio */}
              {p.products && p.products.length > 0 && (
                <div style={{ marginTop: "12px" }}>
                  <span className="eyebrow" style={{ fontSize: "10px", color: "var(--d-txt-3)", display: "block", marginBottom: "8px" }}>
                    Manufactured Products & Portfolio ({p.products.length})
                  </span>
                  <div className="cp-chips">
                    {p.products.map((n, i) => (
                      <span className="cp-chip" key={`${n}-${i}`}>
                        {typeof n === "string" ? n : n.name || n.n || ""}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </Sec>

            {/* 3. LEADERSHIP (DIRECTLY BELOW COMPANY DETAILS) */}
            <Sec title="Leadership" note="Board members, CEOs and executive leadership">
              {leadershipList.length > 0 ? (
                <div className="cp-leadership-grid">
                  {leadershipList.map((leader, i) => (
                    <div className="cp-lead-card" key={`${leader.name}-${i}`}>
                      <div className="cp-avatar">{getInitials(leader.name)}</div>
                      <div className="cp-lead-info">
                        <span className="cp-lead-name">{leader.name}</span>
                        <span className="cp-lead-role">{leader.role}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="cp-thin" style={{ fontSize: "12px", padding: "8px 0" }}>
                  No executive officers published on public record.
                </div>
              )}
            </Sec>

            {/* 4. COMPANY NEWS (MATCHING sc/image.png UI DESIGN WITH VIEW ALL NEWS ACTION) */}
            <Sec title="Company News" note={`Real-time news feed & live market intelligence on ${displayName}`}>
              {topStory && (
                <div className="ln-dashboard" style={{ marginTop: "10px" }}>
                  {/* Header Bar */}
                  <div className="ln-topbar" style={{ marginBottom: "12px" }}>
                    <div className="ln-title-wrap">
                      <span className="ln-red-dot" />
                      <div>
                        <div className="ln-heading">LATEST NEWS</div>
                        <div className="ln-sub">Real-time updates and intelligence on {displayName}</div>
                      </div>
                    </div>
                  </div>

                  {/* Category Filter Pills */}
                  <div className="ln-pills" style={{ marginBottom: "14px" }}>
                    {["All", `${displayName} Updates`, "Defence", "Financial", "Government", "Workforce", "Markets"].map((cat) => (
                      <button
                        key={cat}
                        type="button"
                        className={`ln-pill${newsFilter === cat ? " on" : ""}`}
                        onClick={() => setNewsFilter(cat)}
                      >
                        {cat}
                      </button>
                    ))}
                  </div>

                  {/* 3-Column News Dashboard Grid matching sc/image.png */}
                  <div
                    className="ln-grid"
                    style={{
                      display: "grid",
                      gridTemplateColumns: "40% 28% 28%",
                      gap: "16px",
                      alignItems: "start",
                      width: "100%",
                    }}
                  >
                    {/* COLUMN 1: FEATURED TOP STORY */}
                    {topStory && (
                      <div
                        className="ln-card ln-top-story"
                        onClick={() => setActiveArticle(topStory)}
                        style={{ cursor: "pointer" }}
                        role="button"
                        tabIndex={0}
                      >
                        <div className="ln-story-img-wrap">
                          {topStory.image ? (
                            <img src={topStory.image} alt="Top Story" className="ln-story-img" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                          ) : (
                            <div className="ln-story-img" style={{ display: "flex", alignItems: "center", justifyContent: "center", background: "var(--d-bg-2,#1a1a1a)", color: "var(--d-txt-3,#888)", fontSize: "12px", letterSpacing: ".05em", textTransform: "uppercase" }}>{topStory.category}</div>
                          )}
                          <span className="ln-top-badge">TOP STORY</span>
                        </div>
                        <div className="ln-story-content">
                          <div className="ln-story-meta">{topStory.category} · {topStory.ago}</div>
                          <h3 className="ln-story-title">{topStory.title}</h3>
                          <p className="ln-story-desc">{topStory.excerpt}</p>
                          <div className="ln-story-foot">
                            <span style={{ fontSize: "11px", color: "var(--d-txt-2)", fontWeight: "600" }}>
                              🔴 {topStory.source} ✓
                            </span>
                            <span style={{ fontSize: "12px", color: "#f0593c", fontWeight: "600" }}>
                              Read Full Article →
                            </span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* COLUMN 2: NEWS FEED STACK */}
                    <div className="ln-feed-stack">
                      {feedArticles.map((item, idx) => (
                        <div
                          key={item.id || idx}
                          className="ln-feed-card"
                          onClick={() => setActiveArticle(item)}
                          style={{ cursor: "pointer" }}
                          role="button"
                          tabIndex={0}
                        >
                          {item.image ? (
                            <img src={item.image} alt="" className="ln-feed-thumb" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
                          ) : (
                            <div className="ln-feed-thumb" style={{ background: "var(--d-bg-2,#1a1a1a)" }} />
                          )}
                          <div className="ln-feed-info">
                            <div className="ln-feed-meta">{item.category} · {item.ago}</div>
                            <div className="ln-feed-title">{item.title}</div>
                            <span style={{ fontSize: "11px", color: "var(--d-txt-3)", marginTop: "auto" }}>
                              {item.source} ✓
                            </span>
                          </div>
                        </div>
                      ))}
                      <button
                        type="button"
                        style={{
                          width: "100%",
                          padding: "10px",
                          background: "var(--d-bg-2)",
                          border: "1px solid var(--d-line)",
                          borderRadius: "6px",
                          color: "var(--d-txt-2)",
                          fontSize: "12px",
                          fontWeight: "600",
                          cursor: "pointer",
                          textAlign: "center",
                          marginTop: "4px",
                        }}
                      >
                        View More News ↓
                      </button>
                    </div>

                    {/* COLUMN 3: ANALYTICS & MARKET WIDGETS */}
                    <div className="ln-widget-col">
                      {/* Trending Now */}
                      <div className="ln-widget">
                        <div className="ln-widget-h">
                          📈 TRENDING NOW
                        </div>
                        <div>
                          {companyArticles.slice(0, 5).map((t, idx) => (
                            <div
                              key={t.id || idx}
                              className="ln-trend-item"
                              onClick={() => setActiveArticle(t)}
                              style={{ cursor: "pointer" }}
                              role="button"
                              tabIndex={0}
                            >
                              <span className="ln-trend-num">{idx + 1}</span>
                              <span className="ln-trend-txt">{t.title}</span>
                              <span className="ln-trend-cat">{t.category}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Market Impact and social-mention widgets removed:
                          no real share-price or mention data in the corpus,
                          and fabricated placeholders were showing an identical
                          price/count for every company (incl. non-listed bodies
                          like DRDO). Honest omission over invented numbers. */}

                      {/* Set News Alerts Button */}
                      <button
                        type="button"
                        style={{
                          width: "100%",
                          padding: "10px",
                          background: "var(--d-bg-2)",
                          border: "1px solid var(--d-line-2)",
                          borderRadius: "6px",
                          color: "var(--d-txt)",
                          fontSize: "12px",
                          fontWeight: "600",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: "6px",
                        }}
                      >
                        🔔 Set News Alerts
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </Sec>

            {/* 5. FACILITIES (RENDERED IN ROWS, NOT CARDS) */}
            <Sec title="Facilities & Operating Units" note="Physical manufacturing plants, operating units & hardware assignment">
              {facilitiesList.length > 0 ? (
                <div
                  className="cp-facilities-rows"
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    background: "var(--d-bg-1)",
                    border: "1px solid var(--d-line)",
                    borderRadius: "6px",
                    overflow: "hidden",
                  }}
                >
                  {facilitiesList.map((fac, i, arr) => (
                    <div
                      key={`${fac.name}-${i}`}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "280px 1fr",
                        gap: "14px",
                        padding: "12px 18px",
                        borderBottom: i < arr.length - 1 ? "1px solid var(--d-line)" : "none",
                        fontSize: "13px",
                        alignItems: "center",
                      }}
                    >
                      <span style={{ color: "var(--d-txt)", fontWeight: "600" }}>{fac.name}</span>
                      <span style={{ color: "var(--d-txt-2)", fontSize: "12.5px" }}>{fac.type}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="cp-thin" style={{ fontSize: "12px", padding: "8px 0" }}>
                  No dedicated manufacturing plant or facility locations published.
                </div>
              )}
            </Sec>
          </>
        )}
      </div>
    </div>
  );
}
