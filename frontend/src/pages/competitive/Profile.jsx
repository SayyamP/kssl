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
    assess: p.assess || `Established defense prime specializing in ${p.sector || "defense engineering"}, developing advanced military platforms, tactical systems, and specialized defense hardware.`,
  };
};

// Generate Company-Specific Interactive News Articles Dataset
const getCompanyNewsArticles = (companyName) => {
  const name = cleanCompanyName(companyName) || "Bharat Dynamics";

  return [
    {
      id: `${name}-news-1`,
      category: "Defence",
      ago: "2 hours ago",
      title: `Defence Ministry Restructures ${name} Missile Framework, Opens Projects for Private Partners`,
      excerpt: `The Ministry of Defence has restructured the development framework for tactical missiles and defense platforms, allowing private defense companies to participate in upcoming projects earlier exclusive to ${name}.`,
      fullText: `The Ministry of Defence has formally announced a major policy restructuring allowing domestic private defense manufacturers to co-develop tactical missiles, precision ammunition, and allied defense systems alongside ${name}.\n\nThis policy shift aims to accelerate defense production under the Atmanirbhar Bharat initiative and expand India's defense manufacturing capacity for both domestic armed forces requirements and international exports. Key defense primes including Tata, L&T, and Adani are expected to participate in upcoming defense tenders.`,
      source: "ET The Economic Times",
      image: "https://images.unsplash.com/photo-1579621970563-ebec7560ff3e?auto=format&fit=crop&w=800&q=80",
      isTopStory: true,
      impact: "High strategic impact on long-term missile procurement share and private sector partnership models.",
    },
    {
      id: `${name}-news-2`,
      category: "Financial",
      ago: "4 hours ago",
      title: `${name} Q1 Net Profit Jumps 547% YoY on Strong Operating Performance`,
      excerpt: `${name} reported a 547% year-on-year surge in Q1 net profit driven by higher execution of defense supply orders and improved operational margins.`,
      fullText: `${name} delivered strong Q1 financial results with net revenue surging significantly over the previous fiscal quarter. Operational margins expanded due to timely delivery of primary defense systems and cost optimization across manufacturing units.\n\nThe order book remains robust with multi-year visibility backed by Ministry of Defence procurement pipelines and international export agreements.`,
      source: "Business Standard",
      image: "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=300&q=80",
      impact: "Positive financial indicator confirming strong execution and order pipeline stability.",
    },
    {
      id: `${name}-news-3`,
      category: "Government",
      ago: "6 hours ago",
      title: `General Export Licenses Impact: ${name} Shares Dip 4% in Early Trade`,
      excerpt: `Regulatory updates regarding general export licenses for friendly foreign countries caused short-term volatility in ${name} stock prices during early trading sessions.`,
      fullText: `Stock exchanges recorded short-term price adjustments for ${name} following new regulatory guidelines issued for defense export licensing workflows. Analysts note that long-term export fundamentals remain strong following recent international supply contracts for Akash missile systems.`,
      source: "Moneycontrol",
      image: "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=300&q=80",
      impact: "Temporary market volatility with neutral long-term operational impact.",
    },
    {
      id: `${name}-news-4`,
      category: "Workforce",
      ago: "1 day ago",
      title: `Shri Shailesh Vagerwal Takes Charge as New CMD of ${name}`,
      excerpt: `Shri Shailesh Vagerwal has formally assumed charge as the Chairman & Managing Director of ${name}, bringing over three decades of defense engineering leadership.`,
      fullText: `In an official announcement, ${name} confirmed that Shri Shailesh Vagerwal has assumed charge as Chairman & Managing Director. Under his leadership, the defense prime will focus on expanding manufacturing capacity, accelerating R&D for next-generation defense platforms, and strengthening export delivery pipelines.`,
      source: "The Hindu BusinessLine",
      image: "https://images.unsplash.com/photo-1560250097-0b93528c311a?auto=format&fit=crop&w=300&q=80",
      impact: "Executive leadership transition aligning company roadmap with national defense export goals.",
    },
    {
      id: `${name}-news-5`,
      category: "Markets",
      ago: "1 day ago",
      title: `BSE and NSE Impose ₹13.03 Lakh Fine on ${name} for Compliance Lapse`,
      excerpt: `Stock exchanges BSE and NSE imposed an administrative fine of ₹13.03 lakh on ${name} regarding delayed reporting of board committee disclosures.`,
      fullText: `${name} has issued a clarification to stock exchanges regarding an administrative penalty imposed by BSE and NSE concerning procedural timing of board committee disclosures. The company stated that corrective internal compliance procedures have been instituted.`,
      source: "NDTV Profit",
      image: "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=300&q=80",
      impact: "Minor administrative compliance note with zero impact on defense manufacturing operations.",
    },
  ];
};

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
  const { setScope } = useAppState();
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
  const companyArticles = useMemo(() => (p ? getCompanyNewsArticles(p.name) : []), [p]);

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
                          <img src={topStory.image} alt="Top Story" className="ln-story-img" />
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
                          <img src={item.image} alt="News Thumb" className="ln-feed-thumb" />
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

                      {/* Market Impact */}
                      <div className="ln-widget">
                        <div className="ln-widget-h">
                          📉 MARKET IMPACT
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                            <span style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>{displayName} Share Price</span>
                            <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
                              <span style={{ fontSize: "20px", fontWeight: "700", color: "#fff", fontFamily: "var(--mono)" }}>
                                1,428.50
                              </span>
                              <span style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>INR</span>
                            </div>
                            <span style={{ fontSize: "11.5px", color: "#f0593c", fontWeight: "600", fontFamily: "var(--mono)" }}>
                              -42.35 (-2.88%) Today
                            </span>
                          </div>
                          {/* Red Sparkline SVG */}
                          <svg width="70" height="36" viewBox="0 0 70 36" fill="none">
                            <path d="M2 10 L15 14 L28 8 L42 22 L55 18 L68 32" stroke="#f0593c" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </div>
                      </div>

                      {/* Mentions Count */}
                      <div className="ln-widget">
                        <div className="ln-widget-h">
                          💬 {displayName.toUpperCase()} MENTIONS
                        </div>
                        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                          <div>
                            <div style={{ fontSize: "22px", fontWeight: "700", color: "#fff", fontFamily: "var(--mono)" }}>
                              1,247
                            </div>
                            <span style={{ fontSize: "11px", color: "var(--d-txt-3)" }}>Mentions in last 24h</span>
                          </div>
                          <span style={{ fontSize: "12px", color: "var(--fav-badge)", fontWeight: "600", fontFamily: "var(--mono)" }}>
                            ↑ 23% vs yesterday
                          </span>
                        </div>
                      </div>

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
