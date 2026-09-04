/* ===================================================================
   SHARED PARTNERS + ALLIANCE GRAPH

   Where a rival's partner is also one of KSSL's own: the dataset stamps p.koel
   (what KSSL uses that same company for) and p.cid (its canonical company id) at
   export time, matched on id rather than on name. Everything below is presentation
   over those two fields, plus the radial graph layout.

   Built as a factory over the dataset so the shared index memo lives in a closure
   rather than on `window`.
   =================================================================== */
import { esc, escAll, joinParts, srcChips } from "./html.js";

/* KSSL's side of the relationship decides which exposure applies. */
export const OV_KIND = {
  jv: "tech",
  tech: "tech",
  mou: "tech",
  acq: "tech",
  supply: "supplier",
  "Channel partner": "channel",
  "Component supplier": "supplier",
  "Casting supplier": "supplier",
  "Emission-technology supplier": "supplier",
  "Lubricant partner": "supplier",
  "Supply / customer": "supplier",
  "Service partner": "service",
  "Service and retrofit partner": "service",
  "Joint venture": "tech",
  "Technology / ToT": "tech",
  "Acquisition / stake": "tech",
  "MoU / strategic": "tech",
};

/* What each kind of overlap actually does to KSSL. Written as effect → mechanism,
   so a reader can act on it rather than just note it. */
export const OV_DEF = {
  channel: {
    label: "What an overlapping channel costs KSSL",
    lead: "the same dealer quotes KSSL and the rival from one counter, so the brand decision moves from the customer to the salesperson",
    fx: [
      [
        "Brand choice moves to the counter",
        "The dealer earns on whichever brand pays more or ships sooner, so a KSSL enquiry can close as a rival order without the customer shortlisting the rival.",
      ],
      [
        "KSSL’s price becomes the rival’s floor",
        "A dealer quoting both brands sees both discount sheets, so every KSSL scheme tells the rival what to beat and by how little.",
      ],
      [
        "The pipeline leaks",
        "Which customer, which programme, which stage — KSSL’s live funnel sits with a party aligned to the rival as well.",
      ],
      [
        "Service capacity is pooled",
        "Engineers, spares and AMC cover are shared, so KSSL’s uptime promise competes for the same technicians. AMC performance is what earns the repeat order.",
      ],
      [
        "No territory lock",
        "The rival buys the same district reach without building it; KSSL’s channel spend subsidises a shelf it does not own.",
      ],
      [
        "Switching cost is near zero",
        "A dealer tooled for both brands can move volume from KSSL to the rival inside a quarter, with nothing new to justify.",
      ],
    ],
  },
  supplier: {
    label: "What an overlapping supplier costs KSSL",
    lead: "KSSL and the rival buy the same part from the same vendor, so that component stops separating the two platforms",
    fx: [
      [
        "Cost parity on that part",
        "Both buy at a similar landed cost, so KSSL cannot price off a component advantage it does not have.",
      ],
      [
        "Correlated supply risk",
        "One vendor’s capacity, quality or compliance slip hits KSSL and the rival together — and the rival that dual-sources absorbs it while KSSL does not.",
      ],
      [
        "KSSL funds the learning curve",
        "What KSSL asks the vendor to develop becomes a capability the vendor can sell on. KSSL pays for the development; the rival buys it finished.",
      ],
      [
        "Allocation follows the bigger book",
        "In a tight quarter the vendor serves whoever orders more or pays more, which is a volume contest KSSL does not always win.",
      ],
    ],
  },
  service: {
    label: "What an overlapping service network costs KSSL",
    lead: "the aftermarket — KSSL’s stickiest, highest-margin revenue — is delivered by someone who also earns on the rival’s fleet",
    fx: [
      [
        "The annuity is not exclusive",
        "Spares, AMC and retrofit revenue that KSSL treats as locked in is handled by a party with no reason to defend the KSSL brand.",
      ],
      [
        "Every visit is a switching opportunity",
        "An engineer already inside the customer’s plant at end of life is the cheapest possible route for a rival replacement quote.",
      ],
    ],
  },
  tech: {
    label: "What an overlapping technology partner costs KSSL",
    lead: "the partner behind a KSSL capability is also inside a rival, so the capability is a lead-time rather than a moat",
    fx: [
      [
        "A lead-time, not a moat",
        "Whatever the partner supplies or licenses to KSSL it can supply or license again. KSSL’s edge lasts only until the rival signs the same paper.",
      ],
      [
        "Roadmap visibility cuts both ways",
        "A partner that sees where KSSL is taking a platform can price, time and position the rival’s answer against it.",
      ],
    ],
  },
};

/* radial layout constants. The ellipse is wider than tall because the pane is, and
   because labels are horizontal text: it buys room where labels actually need it. */
const PG_CX = 370;
const PG_CY = 228;
const PG_RX = 200;
const PG_RY = 158;
const PG_LBL_MAX = 22; // characters before an ellipsis; full name in <title>

export function createPartners(d) {
  const { competitors, KSSL_PARTNERS, REL_LABEL, FIELDSYN, COMPSYN, TRACEIDS, sourceRegistry } = d;
  const CLIENT_CID = (d.client && d.client.id) || "KSSL";

  /* Which rivals each shared company serves. Deduped per rival: the dataset carries
     one peer row per source edge, so one company can appear 2-3 times under a single
     competitor (Cummins lists Powerica three times). */
  let _sharedIdx = null;
  function pgSharedIndex() {
    if (_sharedIdx) return _sharedIdx;
    const m = {};
    Object.keys(competitors).forEach((cid) => {
      const c = competitors[cid];
      const seen = {};
      (c.partners || []).forEach((p) => {
        const isShared = p.koel || p.shared;
        const key = p.cid || p.id;
        if (!isShared || !key || seen[key]) return;
        seen[key] = 1;
        (m[key] = m[key] || []).push({ cid, name: c.name });
      });
    });
    _sharedIdx = m;
    return m;
  }
  // distinct partner companies a rival has (not raw edge rows)
  function pgDistinct(c) {
    const s = {};
    let n = 0;
    (c.partners || []).forEach((p) => {
      const k = p.cid || p.id;
      if (!s[k]) {
        s[k] = 1;
        n++;
      }
    });
    return n;
  }
  // deduped shared partners for one rival
  function pgSharedFor(c) {
    const seen = {};
    const out = [];
    (c.partners || []).forEach((p) => {
      const isShared = p.koel || p.shared;
      const key = p.cid || p.id;
      if (!isShared || !key || seen[key]) return;
      seen[key] = 1;
      out.push(p);
    });
    return out;
  }

  /* On a reverse edge (dealer -> KSSL) the description holds the brand they carry,
     not a role, and two KSSL edges just repeat the partner's own name. Printing those
     as "KSSL's own channel partner — Kirloskar" reads as noise. */
  function ovRole(p) {
    const r = ((p.koel && p.koel.role) || "").trim();
    if (!r) return "";
    const flat = (s) => s.toLowerCase().replace(/[^a-z]/g, "");
    const f = flat(r);
    if (!f) return "";
    if (flat(p.label).indexOf(f) >= 0) return ""; // repeats the partner's name
    if ("kalyanistrategicsystemskssslbharatforge".indexOf(f) >= 0 || f === "kssl" || f === "kalyani") return ""; // only names the brand
    return r;
  }

  /* ===================================================================
     GRAPH LAYOUT — one node per partner COMPANY, each on its own line.

     Two defects this replaces:
     1. A node per relationship ROW. The dataset records one edge per source, and
        for a channel partner that means three, so Cummins drew three separate nodes
        all labelled "Powerica Limited". Rows are merged per company here; the drawer
        still lists every row, and c.partners is untouched so counts elsewhere hold.
     2. Concentric rings with `off=(ri%2)*(PI/m)`. With three rings of equal size,
        rings 0 and 2 both got offset 0 — identical angles — so outer lines ran
        exactly through inner nodes. Every node now takes its own angle on one
        ellipse, so no two lines can coincide.
     =================================================================== */
  function pgRowRank(p) {
    const s = p.insight || "";
    return (
      (s.indexOf("[CORE]") >= 0 ? 2 : s.indexOf("[ADJACENT]") >= 0 ? 1 : 0) * 10 +
      (p.sig || 1)
    );
  }
  // one entry per company; the strongest row leads and carries the rest in .rows
  function pgNodes(c) {
    const by = {};
    const order = [];
    (c.partners || []).forEach((p) => {
      const k = p.cid || p.id;
      if (!by[k]) {
        by[k] = { ...p, key: k, rows: [p] };
        order.push(k);
        return;
      }
      const g = by[k];
      const rows = g.rows.concat([p]);
      by[k] = pgRowRank(p) > pgRowRank(g) ? { ...p, key: k, rows } : { ...g, rows };
    });
    return order.map((k) => by[k]);
  }
  // any relationship-row id -> the node that stands for its company
  function pgNodeIdFor(c, pid) {
    const nd = pgNodes(c).filter((n) => n.rows.some((r) => r.id === pid))[0];
    return nd ? nd.id : pid;
  }
  /* The thin CSV-sourced rows carry a company name where a description belongs.
     Echoing it as the programme detail reads as noise, so it is suppressed. */
  function pgThinNote(p, compName) {
    const t = (p.note || "").trim();
    if (!t) return "";
    const flat = (x) => (x || "").toLowerCase().replace(/[^a-z]/g, "");
    const f = flat(t);
    if (!f) return "";
    if (flat(p.label).indexOf(f) >= 0 || f.indexOf(flat(p.label)) >= 0) return "";
    if (flat(compName).indexOf(f) >= 0 || f.indexOf(flat(compName)) >= 0) return "";
    return t;
  }

  function layoutGraph(c) {
    // §8.2: a sparse row may serve center as null — synthesize it from the identity
    const center = c.center || { id: c.id, label: c.name };
    const nodes = [{ ...center, type: "comp", dir: c.dir, x: PG_CX, y: PG_CY }];
    const parts = pgNodes(c).sort((a, b) => pgRowRank(b) - pgRowRank(a));
    const n = parts.length;
    // Cap visual graph nodes to top 16 partners to prevent label overlap on dense graphs
    const displayParts = n > 16 ? parts.slice(0, 16) : parts;
    const m = displayParts.length;

    displayParts.forEach((p, i) => {
      const ang = -Math.PI / 2 + i * ((2 * Math.PI) / m);
      const f = m > 7 && i % 2 ? 0.78 : 1;
      nodes.push({
        ...p,
        type: "ptr",
        ang,
        x: PG_CX + PG_RX * f * Math.cos(ang),
        y: PG_CY + PG_RY * f * Math.sin(ang),
      });
    });

    const edges = displayParts.map((p) => {
      const isShared = p.koel || p.shared || (p.rows && p.rows.some((r) => r.koel || r.shared));
      return {
        a: center.id,
        b: p.id,
        rel: p.rel,
        sig: p.sig,
        koel: !!isShared,
        shared: !!isShared,
      };
    });
    return { nodes, edges };
  }

  /* Labels radiate outward and are anchored by hemisphere, so neighbours diverge
     instead of stacking on the same centre line. text-anchor has to travel as a
     class: a stylesheet rule beats an SVG presentation attribute. */
  function pgLabel(nd, r) {
    const cos = Math.cos(nd.ang || 0);
    const sin = Math.sin(nd.ang || 0);
    const full = nd.label || "";
    const t =
      full.length > PG_LBL_MAX
        ? `${full.slice(0, PG_LBL_MAX - 1).replace(/[\s,(./-]+$/, "")}…`
        : full;
    if (cos > 0.3) return { x: nd.x + r + 7, y: nd.y + 3.4, cls: "la-s", t, full };
    if (cos < -0.3) return { x: nd.x - r - 7, y: nd.y + 3.4, cls: "la-e", t, full };
    return {
      x: nd.x,
      y: sin > 0 ? nd.y + r + 13 : nd.y - r - 6,
      cls: "la-m",
      t,
      full,
    };
  }

  // kind → node shape glyph
  function kindClass(kind) {
    if (/foreign/i.test(kind)) return "foreign";
    if (/govt|drdo/i.test(kind)) return "govt";
    if (/customer/i.test(kind)) return "customer";
    return "domestic";
  }

  function graphSvg(c) {
    if (!c) return "";
    const centerName = esc(c.name || c.label || "Main Company");
    const centerId = c.id || "main";

    // Constellation Canvas Dimensions
    const cx = 465;
    const cy = 285;

    // Direct partners for selected company
    const parts = pgNodes(c).sort((a, b) => pgRowRank(b) - pgRowRank(a));
    const m = parts.length;
    if (m === 0) return "";
    const displayParts = m > 16 ? parts.slice(0, 16) : parts;

    // SVG DEFS & GRADIENTS MATCHING graph wanted.jpeg
    const defsHtml = `
      <defs>
        <!-- Deep cosmic canvas background gradient -->
        <radialGradient id="pgBgGrad" cx="50%" cy="50%" r="70%">
          <stop offset="0%" stop-color="#0e172e" />
          <stop offset="55%" stop-color="#080d1a" />
          <stop offset="100%" stop-color="#03050a" />
        </radialGradient>
        <!-- Center Spotlight Aura Glow -->
        <radialGradient id="pgCenterAura" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="rgba(20, 184, 166, 0.22)" />
          <stop offset="45%" stop-color="rgba(56, 189, 248, 0.10)" />
          <stop offset="100%" stop-color="rgba(0, 0, 0, 0)" />
        </radialGradient>
        <!-- Spherical 3D Node Gradients -->
        <radialGradient id="grad-oem" cx="38%" cy="38%" r="62%">
          <stop offset="0%" stop-color="#ffffff" />
          <stop offset="65%" stop-color="#38bdf8" />
          <stop offset="100%" stop-color="#0284c7" />
        </radialGradient>
        <radialGradient id="grad-teal" cx="35%" cy="35%" r="65%">
          <stop offset="0%" stop-color="#5eead4" />
          <stop offset="60%" stop-color="#14b8a6" />
          <stop offset="100%" stop-color="#0f766e" />
        </radialGradient>
        <radialGradient id="grad-amber" cx="35%" cy="35%" r="65%">
          <stop offset="0%" stop-color="#fef08a" />
          <stop offset="60%" stop-color="#f59e0b" />
          <stop offset="100%" stop-color="#b45309" />
        </radialGradient>
        <radialGradient id="grad-purple" cx="35%" cy="35%" r="65%">
          <stop offset="0%" stop-color="#f3e8ff" />
          <stop offset="60%" stop-color="#a855f7" />
          <stop offset="100%" stop-color="#6b21a8" />
        </radialGradient>
        <radialGradient id="grad-coral" cx="35%" cy="35%" r="65%">
          <stop offset="0%" stop-color="#ffe4e6" />
          <stop offset="60%" stop-color="#f43f5e" />
          <stop offset="100%" stop-color="#9f1239" />
        </radialGradient>
      </defs>
    `;

    // 1. CANVAS SPOTLIGHT AURA
    let svg = defsHtml;
    svg += `<circle cx="${cx}" cy="${cy}" r="340" fill="url(#pgCenterAura)" />`;

    // 2. STAR DUST PARTICLES
    svg += `<g class="pg-particles">`;
    const particlePositions = [
      { x: 150, y: 70, r: 1.3, op: 0.35, col: "#38bdf8" },
      { x: 230, y: 170, r: 1.1, op: 0.4, col: "#f59e0b" },
      { x: 340, y: 65, r: 1.5, op: 0.3, col: "#ffffff" },
      { x: 590, y: 55, r: 1.2, op: 0.4, col: "#a855f7" },
      { x: 740, y: 100, r: 1.6, op: 0.3, col: "#38bdf8" },
      { x: 840, y: 230, r: 1.3, op: 0.4, col: "#f43f5e" },
      { x: 780, y: 440, r: 1.5, op: 0.35, col: "#a855f7" },
      { x: 640, y: 490, r: 1.1, op: 0.4, col: "#38bdf8" },
      { x: 380, y: 500, r: 1.4, op: 0.3, col: "#ffffff" },
      { x: 170, y: 470, r: 1.2, op: 0.4, col: "#14b8a6" },
      { x: 110, y: 250, r: 1.5, op: 0.25, col: "#38bdf8" },
      { x: 880, y: 370, r: 1.3, op: 0.35, col: "#f59e0b" },
    ];
    particlePositions.forEach((pt) => {
      svg += `<circle cx="${pt.x}" cy="${pt.y}" r="${pt.r}" fill="${pt.col}" opacity="${pt.op}" />`;
    });
    svg += `</g>`;

    // 3. CONCENTRIC ORBITAL RINGS & COORDINATE AXES (Matching graph wanted.jpeg)
    svg += `<g class="pg-bg-guides">`;
    svg += `  <circle cx="${cx}" cy="${cy}" r="95" fill="none" stroke="rgba(56, 189, 248, 0.14)" stroke-width="1.2" stroke-dasharray="3 6" />`;
    svg += `  <circle cx="${cx}" cy="${cy}" r="175" fill="none" stroke="rgba(56, 189, 248, 0.09)" stroke-width="1.2" stroke-dasharray="4 8" />`;
    svg += `  <circle cx="${cx}" cy="${cy}" r="260" fill="none" stroke="rgba(56, 189, 248, 0.06)" stroke-width="1" stroke-dasharray="2 10" />`;
    svg += `  <circle cx="${cx}" cy="${cy}" r="340" fill="none" stroke="rgba(56, 189, 248, 0.04)" stroke-width="1" />`;
    svg += `  <line x1="120" y1="${cy}" x2="820" y2="${cy}" stroke="rgba(255,255,255,0.03)" stroke-width="1" stroke-dasharray="2 6" />`;
    svg += `  <line x1="${cx}" y1="40" x2="${cx}" y2="530" stroke="rgba(255,255,255,0.03)" stroke-width="1" stroke-dasharray="2 6" />`;
    svg += `</g>`;

    // 4. MULTI-CLUSTER CATEGORIZATION
    const clusters = {
      amber: [],  // Foreign OEMs / Global Aerospace
      purple: [], // Tech, Radar, Systems, Electronics, JVs
      coral: [],  // Overlapping & Domestic Defense
      teal: []    // Core Strategic, R&D, Unmanned
    };

    displayParts.forEach((p) => {
      const isShared = p.koel || p.shared || (p.rows && p.rows.some((r) => r.koel || r.shared));
      const kindStr = String(p.kind || p.ptype || "").toLowerCase();
      const labelStr = String(p.label || "").toLowerCase();

      if (isShared) {
        clusters.coral.push({ ...p, cluster: "coral", isOverlap: true });
      } else if (/foreign|oem|global|international|us|israel|brazil|france|russia|airbus|embraer/i.test(kindStr + " " + labelStr)) {
        clusters.amber.push({ ...p, cluster: "amber", isOverlap: false });
      } else if (/tech|system|radar|missile|avionics|electronic|sonobuoy|joint venture|jv|mou|elbit|sparton|edge/i.test(kindStr + " " + labelStr)) {
        clusters.purple.push({ ...p, cluster: "purple", isOverlap: false });
      } else if (/govt|drdo|navy|armed|defence|defense|autonomy|drone|uav|aeronautics|general/i.test(kindStr + " " + labelStr)) {
        clusters.teal.push({ ...p, cluster: "teal", isOverlap: false });
      } else {
        // Distribute to the least-populated cluster
        const keys = ["amber", "purple", "coral", "teal"];
        const smallest = keys.reduce((minK, k) => clusters[k].length < clusters[minK].length ? k : minK, "amber");
        clusters[smallest].push({ ...p, cluster: smallest, isOverlap: false });
      }
    });

    // Cluster Layout Definitions
    const clusterConfig = {
      amber: {
        color: "#f59e0b",
        grad: "grad-amber",
        slots: [
          { x: 475, y: 125, r: 21, haloR: 35, isHub: true, lx: 475, ly: 165, anchor: "middle" },
          { x: 565, y: 158, r: 17, haloR: 28, lx: 585, ly: 154, anchor: "start" },
          { x: 390, y: 138, r: 16, haloR: 26, lx: 370, ly: 135, anchor: "end" },
          { x: 515, y: 65,  r: 15, haloR: 24, lx: 535, ly: 63, anchor: "start" },
          { x: 335, y: 92,  r: 14, haloR: 23, lx: 315, ly: 90, anchor: "end" }
        ],
        satellites: [
          { dx: -40, dy: -52, r: 7 },
          { dx: 30, dy: -58, r: 7.5 },
          { dx: 52, dy: -32, r: 7 },
          { dx: 55, dy: 28, r: 6 }
        ]
      },
      purple: {
        color: "#a855f7",
        grad: "grad-purple",
        slots: [
          { x: 670, y: 255, r: 21, haloR: 35, isHub: true, lx: 670, ly: 297, anchor: "middle" },
          { x: 745, y: 225, r: 17, haloR: 27, lx: 765, ly: 222, anchor: "start" },
          { x: 720, y: 340, r: 16, haloR: 26, lx: 740, ly: 338, anchor: "start" },
          { x: 790, y: 300, r: 15, haloR: 24, lx: 810, ly: 298, anchor: "start" }
        ],
        satellites: [
          { dx: -45, dy: -50, r: 8 },
          { dx: 40, dy: -70, r: 6.5 },
          { dx: 55, dy: -25, r: 7.5 },
          { dx: 30, dy: 52, r: 8 }
        ]
      },
      coral: {
        color: "#f43f5e",
        grad: "grad-coral",
        slots: [
          { x: 260, y: 335, r: 21, haloR: 35, isHub: true, lx: 260, ly: 377, anchor: "middle" },
          { x: 215, y: 405, r: 17, haloR: 27, lx: 195, ly: 405, anchor: "end" },
          { x: 195, y: 270, r: 16, haloR: 25, lx: 175, ly: 268, anchor: "end" },
          { x: 315, y: 420, r: 15, haloR: 24, lx: 335, ly: 420, anchor: "start" }
        ],
        satellites: [
          { dx: -55, dy: -35, r: 8 },
          { dx: 35, dy: 65, r: 7.5 },
          { dx: -55, dy: -20, r: 7 },
          { dx: -35, dy: 55, r: 7.5 }
        ]
      },
      teal: {
        color: "#14b8a6",
        grad: "grad-teal",
        slots: [
          { x: 390, y: 245, r: 18, haloR: 30, isHub: true, lx: 370, ly: 243, anchor: "end" },
          { x: 535, y: 270, r: 18, haloR: 30, isHub: true, lx: 555, ly: 268, anchor: "start" },
          { x: 345, y: 310, r: 15, haloR: 25, lx: 325, ly: 308, anchor: "end" },
          { x: 545, y: 345, r: 15, haloR: 25, lx: 565, ly: 343, anchor: "start" }
        ],
        satellites: [
          { dx: -55, dy: -35, r: 7.5 },
          { dx: -25, dy: -65, r: 6.5 },
          { dx: 40, dy: -40, r: 7.5 },
          { dx: 45, dy: 45, r: 7 }
        ]
      }
    };

    let edgeHtml = "";
    let satEdgeHtml = "";
    let nodeHtml = "";
    let satNodeHtml = "";

    // Track placed node coordinates
    const placedNodes = [];

    // Place and render nodes for each cluster
    Object.keys(clusters).forEach((cKey) => {
      const cList = clusters[cKey];
      const cfg = clusterConfig[cKey];

      cList.forEach((p, idx) => {
        const slot = cfg.slots[idx % cfg.slots.length];
        // Add tiny variance if multiple items share slot
        const offsetMultiplier = Math.floor(idx / cfg.slots.length);
        const nx = slot.x + (offsetMultiplier * 20);
        const ny = slot.y + (offsetMultiplier * 20);
        const rNode = slot.r;
        const haloR = slot.haloR;
        const strokeColor = p.isOverlap ? "#ef4444" : cfg.color;
        const fillColor = p.isOverlap ? "#ef4444" : cfg.color;
        const gradId = p.isOverlap ? "grad-coral" : cfg.grad;

        placedNodes.push({ id: p.id, x: nx, y: ny, cluster: cKey, isHub: slot.isHub, color: strokeColor });

        // Edge from Center OEM to Cluster Hub or Partner
        edgeHtml += `<line class="pg-edge" data-a="${centerId}" data-b="${p.id}" x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="${strokeColor}" stroke-width="${slot.isHub ? "1.8px" : "1.4px"}" opacity="${slot.isHub ? "0.65" : "0.50"}" />`;

        // Satellites for this partner node
        const satConfig = cfg.satellites;
        const numSats = Math.min(satConfig.length, 2 + (idx % 2));
        for (let s = 0; s < numSats; s++) {
          const satDef = satConfig[s];
          const sx = nx + satDef.dx;
          const sy = ny + satDef.dy;
          satEdgeHtml += `<line class="pg-edge sat-edge" data-parent="${p.id}" x1="${nx}" y1="${ny}" x2="${sx}" y2="${sy}" stroke="${strokeColor}" stroke-width="1px" opacity="0.32" />`;
          satNodeHtml += `<g class="pg-node sat" data-parent="${p.id}">` +
            `<circle cx="${sx}" cy="${sy}" r="${satDef.r}" fill="${fillColor}" opacity="0.8" />` +
            `<circle cx="${sx}" cy="${sy}" r="${satDef.r + 5}" fill="none" stroke="${strokeColor}" stroke-width="0.8" opacity="0.3" />` +
            `</g>`;
        }

        // Labels
        const fullLabel = String(p.label || "");
        const labelText = esc(
          fullLabel.length > PG_LBL_MAX
            ? `${fullLabel.slice(0, PG_LBL_MAX - 1).replace(/[\s,(./-]+$/, "")}…`
            : fullLabel,
        );
        const kindText = p.isOverlap ? "Overlapping Partner" : esc(p.kind || "Partner");
        const lx = slot.lx ? slot.lx + (offsetMultiplier * 20) : nx;
        const ly = slot.ly ? slot.ly + (offsetMultiplier * 20) : ny + rNode + 16;
        const textAnchor = slot.anchor || "middle";

        // Partner Node Group with clean flat network graph circle
        nodeHtml +=
          `<g class="pg-node ptr ${p.isOverlap ? "overlap" : "direct"}" data-id="${p.id}" data-cluster="${cKey}">` +
          `<title>${labelText} — ${p.isOverlap ? "Overlapping Partner" : kindText}</title>` +
          `<circle class="halo" cx="${nx}" cy="${ny}" r="${haloR}" fill="${cfg.haloFill}" stroke="${strokeColor}" stroke-width="1.3" opacity="0.35" />` +
          `<circle class="net-circle" cx="${nx}" cy="${ny}" r="${rNode}" fill="${fillColor}" stroke="#ffffff" stroke-width="1.8" stroke-opacity="0.65" />` +
          `<text class="lbl-ptr-title" x="${lx}" y="${ly}" text-anchor="${textAnchor}">${labelText}</text>` +
          (kindText ? `<text class="lbl-ptr-sub" x="${lx}" y="${ly + 12}" text-anchor="${textAnchor}">${kindText}</text>` : "") +
          `</g>`;
      });
    });

    // Cross-Cluster and Intra-Cluster Mesh Links
    for (let i = 0; i < placedNodes.length; i++) {
      for (let j = i + 1; j < placedNodes.length; j++) {
        const n1 = placedNodes[i];
        const n2 = placedNodes[j];
        const dist = Math.hypot(n1.x - n2.x, n1.y - n2.y);
        const sameCluster = n1.cluster === n2.cluster;
        const bothHubs = n1.isHub && n2.isHub;

        if ((sameCluster && dist < 140) || (bothHubs && dist < 320)) {
          const strokeCol = sameCluster ? clusterConfig[n1.cluster].color : "rgba(168, 85, 247, 0.45)";
          const strokeW = bothHubs ? "1.4px" : "0.9px";
          const strokeDash = bothHubs ? "4, 5" : "2, 3";
          edgeHtml += `<line class="pg-edge mesh-edge" data-a="${n1.id}" data-b="${n2.id}" x1="${n1.x}" y1="${n1.y}" x2="${n2.x}" y2="${n2.y}" stroke="${strokeCol}" stroke-width="${strokeW}" stroke-dasharray="${strokeDash}" opacity="0.32" />`;
        }
      }
    }

    // 5. CENTER OEM BEACON NODE (Flat network graph circle)
    const centerHtml =
      `<g class="pg-node center-root" data-id="${centerId}">` +
      `<circle class="halo halo-oem" cx="${cx}" cy="${cy}" r="40" fill="none" stroke="rgba(56, 189, 248, 0.4)" stroke-width="1.5" stroke-dasharray="4, 6" />` +
      `<circle class="net-circle" cx="${cx}" cy="${cy}" r="24" fill="#00f0ff" stroke="#ffffff" stroke-width="2.5" />` +
      `<text class="lbl-ptr-title center-title" x="${cx}" y="${cy + 40}" text-anchor="middle">${centerName}</text>` +
      `<text class="lbl-ptr-sub center-sub" x="${cx}" y="${cy + 54}" text-anchor="middle">SELECTED OEM</text>` +
      `</g>`;

    return svg + edgeHtml + satEdgeHtml + satNodeHtml + nodeHtml + centerHtml;
  }


  /* the shared-partner read under the graph */
  function overlapHtml(c, cid, open, clientNameOverride) {
    const clientName = clientNameOverride || (d.client && (d.client.short || d.client.name)) || "KSSL";
    const idx = pgSharedIndex();
    const shared = pgSharedFor(c);
    const dist = pgDistinct(c);
    const nm = esc(c.name);
    // roster size is only used in the prose; an older data file must not break the view
    const nRoster = (KSSL_PARTNERS || []).length;

    if (!dist) {
      return (
        '<div class="pg-ov-h"><span class="pg-ov-t clean">Overlapping partners · no network mapped</span>' +
        `<span class="pg-ov-s">No partner relationships are on file for <b>${nm}</b>, so there is nothing to ` +
        `test against ${clientName}’s own roster of ${nRoster} partners yet.</span></div>`
      );
    }
    if (!shared.length) {
      return (
        '<div class="pg-ov-h"><span class="pg-ov-t clean">Overlapping partners · none</span>' +
        `<span class="pg-ov-s">All <b>${dist}</b> of ${nm}’s mapped partners are its own. None of them appears in ` +
        `${clientName}’s roster of <b>${nRoster}</b> partners, so ${clientName} faces this rival through a separate ` +
        "channel, supply base and service network — no overlapping dealer is quoting both brands, and no red line is drawn " +
        "on the graph above.</span></div>"
      );
    }

    // rank by exposure: the more rival brands a partner carries, the weaker client's hold
    shared.sort((a, b) => (idx[b.cid] || []).length - (idx[a.cid] || []).length);
    const kinds = {};
    shared.forEach((p) => {
      const relKey = (p.koel && p.koel.rel) || p.rel;
      kinds[OV_KIND[relKey] || "tech"] = 1;
    });
    const worst = shared[0];
    const worstN = (idx[worst.cid] || []).length;

    /* TWO KINDS OF RED LINE, AND THEY DO NOT READ THE SAME.

       `clientTie` means the rival's partner IS the client — Saab and Paramount both
       have a direct agreement with KSSL. The shelf language ("carries KSSL and 2
       rivals", "1 of 3 brands on that shelf") describes a THIRD party serving
       several brands, and applying it here told the reader the client is a
       distributor stocking itself. */
    const direct = shared.filter((p) => p.clientTie);
    const viaThird = shared.filter((p) => !p.clientTie);
    let h =
      `<div class="pg-ov-h"><span class="pg-ov-t">◆ Overlapping partners · ${shared.length} of ${dist}</span>` +
      `<span class="pg-ov-s">` +
      (direct.length
        ? `<b>${esc(nm)}</b> has a direct agreement with <b>${clientName}</b> itself` +
          (viaThird.length
            ? `, and ${viaThird.length} of its other partners ${viaThird.length === 1 ? "is" : "are"} also ${clientName}’s`
            : "") +
          " — red above"
        : `<b>${shared.length}</b> of ${nm}’s ${dist} mapped partners ` +
          `${shared.length === 1 ? "is" : "are"} also <b>${clientName}’s</b> own — red above`) +
      (viaThird.length && worstN > 1
        ? `. Widest: <b>${esc(worst.label)}</b> carries ${clientName} and ${worstN} rivals, so ${clientName} is 1 of ${worstN + 1} brands on that shelf.`
        : direct.length
          ? "."
          : `, and ${clientName} holds no exclusivity.`) +
      "</span></div>";

    h += '<div class="pg-ov-ties">';
    shared.forEach((p) => {
      const all = (idx[p.cid] || []).length;
      const also = (idx[p.cid] || []).filter((r) => r.cid !== cid).map((r) => r.name);
      // both sides are almost always the same relation, so print it once
      const pRel = (p.koel && p.koel.rel) || p.rel;
      const same = (pRel || "").toLowerCase() === (p.ptype || "").toLowerCase();
      const rel = same
        ? esc((p.ptype || "partner").toLowerCase())
        : `${esc((pRel || "").toLowerCase())} to ${clientName}, ${esc((p.ptype || "").toLowerCase())} here`;
      h +=
        `<div class="pg-ov-tie" data-pid="${escAll(p.id)}" title="Open this relationship">` +
        `<span class="pg-ov-nm">${esc(p.label)}</span>` +
        `<span class="pg-ov-cnt">${clientName} + ${all} rival${all === 1 ? "" : "s"}</span>` +
        `<span class="pg-ov-use">overlapping ${rel}` +
        `${also.length ? ` · also ${esc(also.join(", "))}` : ""}</span></div>`;
    });
    h += "</div>";

    /* The "what an overlapping partner costs" read used to print HERE, under the ties.
       It is interpretation, not relationship: the canvas states WHO overlaps and on
       what terms, and the side drawer carries what that means. See overlapDefsHtml. */
    return h;
  }

  /* The interpretation half of the overlap read, for the RIGHT-HAND DRAWER.
     Which definitions appear is decided by the SAME `kinds` map the canvas builds —
     a rival whose only overlap is a distributor must not be handed the technology
     read. Returns "" when there is no overlap, so the drawer prints nothing rather
     than an empty heading. */
  function overlapDefsHtml(c, cid, clientNameOverride) {
    const clientName = clientNameOverride || (d.client && (d.client.short || d.client.name)) || "KSSL";
    if (!c || !pgDistinct(c)) return "";
    const shared = pgSharedFor(c);
    if (!shared.length) return "";
    const kinds = {};
    shared.forEach((p) => {
      const relKey = (p.koel && p.koel.rel) || p.rel;
      kinds[OV_KIND[relKey] || "tech"] = 1;
    });
    let h = "";
    Object.keys(kinds).forEach((k) => {
      const def = OV_DEF[k];
      if (!def) return;
      const lbl = def.label.replace(/KSSL/g, clientName);
      const lead = def.lead.replace(/KSSL/g, clientName);
      h +=
        `<div class="pg-ov-kind"><b>${lbl}</b><span class="pg-ov-lead"> — ${lead}</span></div>` +
        '<div class="pg-ov-defs">';
      def.fx.forEach((f) => {
        const dt = f[0].replace(/KSSL/g, clientName);
        const dx = f[1].replace(/KSSL/g, clientName);
        h += `<div class="pg-ov-def"><div class="pg-ov-dt">${dt}</div><div class="pg-ov-dx">${dx}</div></div>`;
      });
      h += "</div>";
    });
    return h;
  }

  /* competitor-level drawer: the synthesis read, or the plain relationship list for
     the rivals that carry no synthesis. */
  function compReportHtml(c, cid, clientNameOverride) {
    const clientName = clientNameOverride || (d.client && (d.client.short || d.client.name)) || "KSSL";
    /* A competitor id restored from localStorage can outlive the dataset that
       held it, and then `c` is an id with no row behind it. Read the ties through
       one guarded local rather than assuming the array exists. */
    const rows = c.partners || [];
    const syn = COMPSYN ? COMPSYN[cid] : null;
    const hasSyn = syn && syn.vulns && syn.vulns.length;
    if (!hasSyn) {
      let b = "";
      /* The "Latest updates" block is gone by request. It was also a live shape bug:
         `c.updates` is an HTML STRING on 10 companies and an always-empty ARRAY on the
         other 20, and `if ([])` is true — so twenty rivals rendered the heading over
         nothing at all. Removing the block removes both. */
      b += `<div class="pg-r-sec"><span class="eyebrow">Relationships (${rows.length})</span><div class="pg-rellist">`;
      rows.forEach((p) => {
        const isCore = (p.insight || "").indexOf("[CORE]") >= 0;
        b +=
          `<div class="pg-rel${isCore ? " core" : ""}" data-pid="${escAll(p.id)}"><span class="rmark rel-${p.rel}"></span>` +
          `<span class="rtxt"><b>${esc(p.label)}</b> <span class="pg-ctag sm">${esc(p.country || "—")}</span> <span class="rtype">${esc(REL_LABEL[p.rel] || p.ptype)}</span><br>` +
          `<span class="rnote">${joinParts([p.note, p.deal !== "n/d" ? p.deal : null, p.date].map(esc))}</span></span></div>`;
      });
      b += "</div></div>";
      // a company revived from the archive has no assessment written for it; an
      // empty box under the heading is not an assessment
      if (c.assess)
        b += `<div class="pg-assess"><span class="tl">Assessment for ${clientName}</span>${c.assess}</div>`;
      b += sourcesSectionHtml(c);
      return b;
    }

    // ---- synthesis mode ----
    const core = rows.filter((p) => (p.insight || "").indexOf("[CORE]") >= 0).length;
    const frgn = rows.filter((p) => p.kind === "Foreign OEM").length;
    let h = "";
    h += `<div class="syn-thesis"><span class="stl">Read on this competitor</span><span class="stx">${esc(syn.thesis)}</span></div>`;
    h +=
      '<div class="syn-stats">' +
      `<div class="syn-stat"><div class="sv">${rows.length}</div><div class="sl">Ties</div></div>` +
      `<div class="syn-stat core"><div class="sv">${core}</div><div class="sl">On ${clientName} lines</div></div>` +
      `<div class="syn-stat frgn"><div class="sv">${frgn}</div><div class="sl">Foreign-IP</div></div>` +
      "</div>";
    h += '<div class="syn-sec-l vuln">▸ Structural weaknesses</div>';
    syn.vulns.forEach((v, i) => {
      const chips = (v.from || []).map((f) => `<span class="syn-chip">${esc(f)}</span>`).join("");
      const traceable = v.from && v.from.length ? " traceable" : "";
      h +=
        `<div class="syn-vuln${traceable}" data-vix="${i}"><div class="syn-vuln-h" data-vulnclick="${i}">` +
        `<span class="syn-vuln-n">${i + 1}</span><div><div class="syn-vuln-t">${esc(v.title)}</div><div class="syn-vuln-from">${chips}</div></div></div>` +
        `<div class="syn-vuln-b"><div class="syn-vuln-intel">${esc(v.intel)}</div></div></div>`;
    });
    if (syn.strat && syn.strat.thesis) {
      h += '<div class="syn-sec-l strat" style="margin-top:16px">▸ What their web reveals</div>';
      h +=
        `<div class="syn-strat"><div class="st">${esc(syn.strat.thesis)}</div>` +
        (syn.strat.pattern ? `<div class="sp"><b>Pattern:</b> ${esc(syn.strat.pattern)}</div>` : "") +
        (syn.strat.sowhat
          ? `<div class="sp" style="color:var(--d-txt)"><b>Read:</b> ${esc(syn.strat.sowhat)}</div>`
          : "") +
        "</div>";
    }
    h += `<button class="field-btn" style="margin-top:16px" data-fieldread="1">◆ Field-level read — patterns across all ${Object.keys(competitors).length}</button>`;
    h += sourcesSectionHtml(c);
    return h;
  }

  function sourcesSectionHtml(c) {
    if (!c) return "";
    const srcs = c.srcs && c.srcs.length ? c.srcs : c.site ? [{ label: "Company website", url: c.site }] : null;
    if (!srcs || !srcs.length) return "";
    return (
      '<div class="pg-drawer-sources" style="margin-top:24px;padding-top:16px;border-top:1px solid var(--l-line,#e0e0e0);">' +
      '<span class="eyebrow" style="display:block;margin-bottom:8px;color:var(--l-txt-3,#888888);font-size:10px;text-transform:uppercase;letter-spacing:0.05em;font-weight:700;">Sources</span>' +
      `<div class="pg-src-links">${srcChips(srcs)}</div>` +
      '</div>'
    );
  }

  function drawerHead(c, cid) {
    const syn = COMPSYN ? COMPSYN[cid] : null;
    const hasSyn = syn && syn.vulns && syn.vulns.length;
    return hasSyn ? "Intelligence" : "Relationships";
  }

  /* one relationship row, the drawer's deepest read */
  function tieHtml(c, cid, pid, clientNameOverride, activeRelCardIndex) {
    const clientName = clientNameOverride || (d.client && (d.client.short || d.client.name)) || "KSSL";
    const p = (c.partners || []).find((x) => x.id === pid);
    if (!p) return "";

    // Clean threat text
    const insightClean = (p.insight || "")
      .replace(/<b>\[(CORE OVERLAP|CORE|ADJACENT|context|OVERLAP)\]<\/b>\s*/gi, "")
      .replace(/\[(CORE OVERLAP|CORE|ADJACENT|context|OVERLAP)\]\s*/gi, "")
      .replace(/<b>\s*Threat\s*:\s*<\/b>[\s\S]*?(?=<b>\s*(?:Dependency|Read|So what)\s*:\s*<\/b>|$)/gi, "")
      .replace(/Threat\s*:.*?(?=(Dependency|Read|So what):|$)/gi, "")
      .trim();

    let meanClean = p.mean || "";
    if (meanClean) {
      meanClean = meanClean
        .replace(/<b>\s*(?:Opening|Threat)\s*:\s*<\/b>[\s\S]*?(?=<b>\s*(?:Dependency|Read|So what)\s*:\s*<\/b>|$)/gi, "")
        .replace(/Threat\s*:.*?(?=(Dependency|Read|So what):|$)/gi, "")
        .replace(/\s{2,}/g, " ")
        .replace(/^\s*·\s*/, "")
        .trim();
    }

    const sib = (c.partners || []).filter(
      (x) => (x.cid || x.id) === (p.cid || p.id) && x.id !== p.id,
    );

    /* These relationship cards used to pad three real fields out to three cards of
       invented analysis: a "Defense Intelligence Unit" and an "MoD Official Gazette"
       as issuing bodies, an "Intelligence analysis ... reveals a high degree of
       technical dependency" finding nobody made, Unsplash stock photos, and a
       sourceUrl that fell back to https://www.mod.gov.in for rows with no citation
       at all. Every field below is now either a value the row states or absent, and
       a card whose substance is missing is not emitted. The render is unchanged:
       fewer cards, and each one true. */
    const NL = String.fromCharCode(10);
    const real = (v) => {
      const t = typeof v === "string" ? v.trim() : v;
      return t && t !== "n/d" && t !== "null" ? t : null;
    };
    const sourceUrl = real(p.src) && p.src.startsWith("http") ? p.src : undefined;
    const relLabel = (REL_LABEL[p.rel] || real(p.ptype) || "Partnership").toUpperCase();
    const cat = real(p.country) ? `${relLabel} · ${p.country.toUpperCase()}` : relLabel;

    const lines = [];
    if (real(p.ptype)) lines.push(`Type: ${p.ptype}`);
    if (real(p.note)) lines.push(`Scope: ${p.note}`);
    if (real(p.deal)) lines.push(`Deal: ${p.deal}`);
    if (real(p.date)) lines.push(`Recorded: ${p.date}`);
    if (real(p.srcnote)) lines.push(`Source note: ${p.srcnote}`);

    const cards = [
      {
        id: 0,
        category: cat,
        ago: real(p.date) || "",
        title: `${c.name} ↔ ${p.label}`,
        excerpt: real(p.note) || "",
        source: real(p.src) || undefined,
        sourceUrl: sourceUrl,
        image: real(p.image) || undefined,
        fullBodyText: lines.join(NL),
        /* `mean` is the pipeline's own read of the tie, not a sentence written here. */
        impact: real(p.mean) || undefined,
      },
    ];

    /* Only when the row actually carries an insight. It was previously emitted for
       every partner with a generic sentence standing in. */
    if (insightClean) {
      cards.push({
        id: cards.length,
        category: "STRATEGIC READ",
        ago: real(p.date) || "",
        title: `${c.name} ↔ ${p.label} · Strategic read`,
        excerpt: insightClean,
        source: real(p.src) || undefined,
        sourceUrl: sourceUrl,
        image: undefined,
        fullBodyText: [insightClean, meanClean].filter(Boolean).join(NL + NL),
        impact: real(p.mean) || undefined,
      });
    }

    // Sibling rows on the same tie: real values only, and no card without one.
    sib.forEach((x) => {
      const note = pgThinNote(x, c.name);
      if (!real(note) && !real(x.deal) && !real(x.ptype)) return;
      const xl = (REL_LABEL[x.rel] || real(x.ptype) || "Partnership").toUpperCase();
      cards.push({
        id: cards.length,
        category: real(x.country) ? `${xl} · ${x.country.toUpperCase()}` : xl,
        ago: real(x.date) || "",
        title: `${c.name} ↔ ${p.label}${real(x.ptype) ? ` · ${x.ptype}` : ""}`,
        excerpt: real(note) || "",
        source: real(x.src) || undefined,
        sourceUrl: real(x.src) && x.src.startsWith("http") ? x.src : sourceUrl,
        image: undefined,
        fullBodyText: [
          real(x.ptype) ? `Type: ${x.ptype}` : null,
          real(note) ? `Scope: ${note}` : null,
          real(x.deal) ? `Deal: ${x.deal}` : null,
          real(x.date) ? `Recorded: ${x.date}` : null,
        ].filter(Boolean).join(NL),
        impact: undefined,
      });
    });

    // IF AN ACTIVE CARD IS SELECTED -> RENDER BIG WHITE DETAILED SCREEN MATCHING PRODUCTS PAGE NEWS DETAIL VIEW
    if (activeRelCardIndex !== null && activeRelCardIndex !== undefined && cards[activeRelCardIndex]) {
      const card = cards[activeRelCardIndex];
      let h = "";
      h += `<div style="background: #ffffff; color: #161614; padding: 24px; border: 1px solid #e2e0d8; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); display: flex; flex-direction: column; gap: 16px;">`;

      // Top Header Bar
      h += `  <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e0d8; padding-bottom: 14px;">`;
      h += `    <div style="display: flex; align-items: center; gap: 8px;">`;
      h += `      <span style="width: 8px; height: 8px; border-radius: 50%; background: #b5341f; display: inline-block;"></span>`;
      h += `      <span style="font-family: var(--mono); font-size: 11px; color: #b5341f; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;">`;
      h += `        ${esc(c.name)} · ${esc(card.category)} · ${esc(card.ago)}`;
      h += `      </span>`;
      h += `    </div>`;
      h += `    <button type="button" data-backrelcards="true" style="background: #f0efea; border: 1px solid #cfcdc3; color: #161614; padding: 5px 12px; border-radius: 6px; font-size: 11.5px; font-weight: 600; cursor: pointer; white-space: nowrap; flex-shrink: 0; display: inline-flex; align-items: center; gap: 4px;">`;
      h += `      ← Back`;
      h += `    </button>`;
      h += `  </div>`;

      // Headline Title
      h += `  <h2 style="font-size: 22px; font-weight: 700; color: #161614; line-height: 1.35; margin: 0;">`;
      h += `    ${esc(card.title)}`;
      h += `  </h2>`;

      // Source Publisher Subtitle
      h += `  <div style="font-size: 12px; color: #6b6a63; font-weight: 600;">`;
      h += card.url
        ? `    Source Publisher: <a href="${esc(card.url)}" target="_blank" rel="noopener noreferrer" style="color: #b5341f;">${esc(card.source)} ↗</a>`
        : `    Source Publisher: <span style="color: #b5341f;">${esc(card.source)}</span>`;
      h += `  </div>`;

      /* Featured hero image, with a fallback. serving.partner.image exists as a column
         but is populated on 0 of 582 partner objects the API serves, so this block never
         ran -- and there was no else, so the card simply had a hole where every other
         card has an image. A neutral tile keeps the layout honest until the column is
         written. */
      if (card.image) {
        h += `  <div style="width: 100%; max-height: 320px; overflow: hidden; border-radius: 6px; background: #f0efea;">`;
        h += `    <img src="${card.image}" alt="${esc(card.title)}" style="width: 100%; height: 100%; object-fit: cover;" />`;
        h += `  </div>`;
      } else {
        h += `  <div style="width: 100%; height: 120px; border-radius: 6px; background: #f0efea; border: 1px solid #e3e1d8; display: flex; align-items: center; justify-content: center;">`;
        h += `    <span style="font-family: var(--mono); font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase; color: #8a8880;">No image published with this article</span>`;
        h += `  </div>`;
      }

      // Full Text Body Content
      h += `  <div style="font-size: 14px; color: #3d3d39; line-height: 1.75; white-space: pre-line;">`;
      h += `    ${card.fullBodyText}`;
      h += `  </div>`;

      // Strategic Impact Box
      if (card.impact) {
        h += `  <div style="margin-top: 8px; padding: 16px 20px; background: #f7f6f3; border: 1px solid #e2e0d8; border-radius: 6px;">`;
        h += `    <span style="font-family: var(--mono); font-size: 11px; color: #6b6a63; display: block; margin-bottom: 4px; letter-spacing: .08em; text-transform: uppercase; font-weight: 700;">PARTNERSHIP STRATEGIC IMPACT</span>`;
        h += `    <div style="font-size: 13px; color: #161614; line-height: 1.55; font-weight: 500;">`;
        h += `      ${esc(card.impact)}`;
        h += `    </div>`;
        h += `  </div>`;
      }



      h += `</div>`;
      return h;
    }

    // DEFAULT VIEW -> RENDER MULTIPLE NEWS-STYLE FEED CARDS GRID MATCHING MIDDLE NEWS COLUMN (WHITE THEME)
    let h = "";
    h +=
      `<div class="tie-hero"><div class="th-name" style="color: #161614;">${esc(c.name)} ↔ ${esc(p.label)}</div>` +
      `<div class="th-meta"><span class="tie-rel-pill"><span class="rmark rel-${p.rel}"></span>${esc(REL_LABEL[p.rel] || p.ptype)}</span><span>${esc(p.country || "—")}</span></div></div>`;

    h += `<div style="font-size: 12px; color: #6b6a63; margin: 12px 0 16px 0;">Select a card below to read detailed intelligence on this relationship:</div>`;

    h += `<div style="display: flex; flex-direction: column; gap: 12px;">`;
    cards.forEach((card, idx) => {
      h +=
        `<div class="pg-news-feed-card" data-relcard="${idx}" style="display: flex; gap: 12px; padding: 14px; background: #ffffff; border: 1px solid #e2e0d8; border-radius: 8px; cursor: pointer; transition: all 0.15s ease-in-out; box-shadow: 0 1px 3px rgba(0,0,0,0.04);">` +
          `<div style="width: 90px; height: 75px; border-radius: 6px; background: #f7f6f3; display: flex; flex-direction: column; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #e2e0d8;">` +
            `<span class="rmark rel-${p.rel}" style="width: 10px; height: 10px; border-radius: 50%;"></span>` +
            `<span style="font-family: var(--mono); font-size: 8.5px; color: #6b6a63; font-weight: 700; margin-top: 4px; text-align: center; padding: 0 2px;">CARD ${idx + 1}</span>` +
          `</div>` +
          `<div style="display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0;">` +
            `<div style="font-family: var(--mono); font-size: 10.5px; color: #b5341f; font-weight: 600; text-transform: uppercase;">` +
              `${esc(card.category)} · ${esc(card.ago)}` +
            `</div>` +
            `<div style="font-size: 13px; font-weight: 700; color: #161614; line-height: 1.35;">` +
              `${esc(card.title)}` +
            `</div>` +
            `<div style="font-size: 11.5px; color: #6b6a63; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">` +
              `${esc(card.excerpt)}` +
            `</div>` +
            `<span style="font-size: 11px; color: #3d3d39; margin-top: auto;">` +
              `<span class="src-dot"></span>${esc(card.source)}` +
            `</span>` +
          `</div>` +
        `</div>`;
    });
    h += `</div>`;
    return h;
  }

  /* Field-level read: the patterns that are invisible in any single dossier. */
  function fieldReadHtml(cid) {
    if (!FIELDSYN) return "";
    const cname = (competitors[cid] && competitors[cid].name) || "competitor";
    let h = "";
    h +=
      '<div style="padding:4px 0 8px"><div style="font-size:15px;font-weight:700;margin-bottom:3px">Field-level intelligence</div>' +
      `<div style="font-size:11px;color:var(--d-txt-3);margin-bottom:14px">Patterns across all ${Object.keys(competitors).length} competitors — invisible in any single dossier.</div>`;
    (FIELDSYN.patterns || []).forEach((p, i) => {
      h +=
        `<div class="syn-strat" style="border-left-color:#3d7fbf;margin-bottom:10px"><div class="st">${i + 1}. ${esc(p.field || p.t)}</div>` +
        `<div class="sp"><b>Pattern:</b> ${esc(p.pattern || p.e)}${p.total ? ` <span style="opacity:.6">(${p.n} of ${p.total})</span>` : ""}</div>` +
        `<div class="sp" style="color:var(--d-txt)"><b>Read:</b> ${esc(p.implication || p.s)}</div></div>`;
    });
    h += `<div class="syn-strat" style="border-left-color:#3d7fbf;margin-top:6px"><div class="st">Bottom Line</div><div class="sp" style="color:var(--d-txt)">${esc(FIELDSYN.bottomLine || FIELDSYN.bottom || "")}</div></div></div>`;
    // every URL behind the corpus, grouped by company — same list pattern as above
    try {
      if (sourceRegistry && sourceRegistry.length) {
        const byCo = {};
        sourceRegistry.forEach((r) => {
          (byCo[r.company || "Other"] = byCo[r.company || "Other"] || []).push(r);
        });
        h += `<div class="syn-sec-l" style="margin-top:16px">▸ All tracked sources (${sourceRegistry.length})</div>`;
        Object.keys(byCo)
          .sort()
          .forEach((co) => {
            h +=
              `<div class="syn-strat" style="border-left-color:#3d7fbf;margin-bottom:8px"><div class="st">${esc(co)}</div>` +
              `<div class="src-list" style="margin:7px 0 0">${srcChips(byCo[co].map((r) => ({ label: r.label || r.url, url: r.url })))}</div></div>`;
          });
      }
    } catch (e) {
      /* the source registry is decoration here; never let it break the read */
    }
    return h;
  }

  /* Which partner nodes a vulnerability draws on. Explicit trace ids first
     (deterministic), fuzzy label match as the fallback.
     An empty list means "no explicit ids for this vulnerability", but [] is truthy,
     so the original guard disabled the fuzzy fallback and nothing ever traced —
     every one of the 44 slots the export emits is empty. */
  function traceNodeIds(c, cid, ix) {
    const syn = COMPSYN && COMPSYN[cid];
    if (!syn || !syn.vulns[ix]) return [];
    const froms = syn.vulns[ix].from || [];
    const tmap = TRACEIDS && TRACEIDS[cid] ? TRACEIDS[cid] : null;
    const tl = (tmap && tmap[ix]) || null;
    const explicit = tl && tl.length ? tl : null;
    const out = [];
    (c.partners || []).forEach((p) => {
      let hit;
      if (explicit) hit = explicit.indexOf(p.id) >= 0;
      else {
        const lbl = (p.label || "").toLowerCase();
        hit = froms.some((f) => {
          const ff = f.toLowerCase().split("/")[0].split(" ")[0];
          return ff.length > 2 && lbl.indexOf(ff) >= 0;
        });
      }
      if (hit) {
        const gid = pgNodeIdFor(c, p.id);
        if (out.indexOf(gid) < 0) out.push(gid);
      }
    });
    return out;
  }

  /* Guards the overlap logic against the ways it can go quietly wrong: an unmatched
     partner, a double-counted duplicate row, or a KSSL relation with no definition
     behind it (which would silently print the wrong consequence). */
  function selfCheck() {
    const fail = [];
    const ok = (cond, msg) => {
      if (!cond) fail.push(msg);
    };
    const idx = pgSharedIndex();
    const roster = {};
    (KSSL_PARTNERS || []).forEach((p) => {
      const k = p.cid || p.id;
      if (k) roster[k] = p;
    });
    let flagged = 0;
    Object.keys(competitors).forEach((cid) => {
      const c = competitors[cid];
      if (c.isBf || cid === CLIENT_CID) return;
      const sh = pgSharedFor(c);
      sh.forEach((p) => {
        const k = p.cid || p.id;
        if (!k) return;
        flagged++;
        ok(!!roster[k], `${p.label} is flagged shared but is absent from roster`);
        const rel = (p.koel && p.koel.rel) || p.rel;
        ok(!!rel, `${p.label} is flagged shared but does not say what client uses it for`);
        const hits = (idx[k] || []).filter((r) => r.cid === cid);
        ok(hits.length === 1, `${p.label} appears ${hits.length} times for ${c.name} — duplicate rows leaked`);
      });
      ok(sh.length <= pgDistinct(c), `${c.name} has more shared partners than distinct partners`);
    });
    if (fail.length && KSSL_PARTNERS && KSSL_PARTNERS.length > 0) {
      console.error("shared-partner self-check FAILED:", fail);
    }
    return fail;
  }

  /* Measures the three things the old layout got wrong, on every competitor: a line
     with no node of its own, a line passing through someone else's node, and labels
     sitting on top of each other. Geometry, not eyeballing. */
  function geomCheck() {
    const fail = [];
    const ok = (c, m) => {
      if (!c) fail.push(m);
    };
    const CH = 5.55; // mono advance at 9.5px
    let worstGap = 999;
    let worstClear = 999;
    let pairs = 0;
    let labels = 0;
    Object.keys(competitors).forEach((cid) => {
      const c = competitors[cid];
      if (c.isBf || cid === CLIENT_CID) return;
      c.id = cid;
      c.center = c.center || { id: cid, label: c.name };
      const parts = pgNodes(c);
      if (!parts.length) return;
      const { nodes, edges } = layoutGraph(c);
      const ptr = nodes.filter((n) => n.type === "ptr");
      const hub = nodes.filter((n) => n.type === "comp")[0];

      // one node per company, one edge per node
      ok(ptr.length === parts.length, `${c.name}: node count does not match its companies`);
      ok(edges.length === ptr.length, `${c.name}: ${edges.length} edges for ${ptr.length} nodes`);
      const ids = {};
      ptr.forEach((n) => {
        ids[n.id] = (ids[n.id] || 0) + 1;
      });
      ok(Object.keys(ids).length === ptr.length, `${c.name}: two nodes share an id`);
      edges.forEach((e) => ok(ids[e.b] === 1, `${c.name}: edge ${e.b} has no node of its own`));
      const lbl = {};
      ptr.forEach((n) => {
        lbl[n.label] = (lbl[n.label] || 0) + 1;
      });
      Object.keys(lbl).forEach((k) =>
        ok(lbl[k] === 1, `${c.name}: label "${k}" appears ${lbl[k]} times`),
      );
      // a line must clear every node that is not its endpoint
      ptr.forEach((e, i) => {
        const dx = e.x - hub.x;
        const dy = e.y - hub.y;
        const len = Math.hypot(dx, dy);
        ptr.forEach((o, j) => {
          if (i === j) return;
          let t = ((o.x - hub.x) * dx + (o.y - hub.y) * dy) / (len * len);
          t = Math.max(0, Math.min(1, t));
          const px = hub.x + t * dx;
          const py = hub.y + t * dy;
          const dist = Math.hypot(o.x - px, o.y - py);
          const rad = ((o.insight || "").indexOf("[CORE]") >= 0 ? 11 : 8) + (o.sig || 1) * 1.4;
          worstClear = Math.min(worstClear, dist - rad);
          ok(
            dist > rad + 3,
            `${c.name}: the line to ${e.label} passes through ${o.label} (${dist.toFixed(1)}px from a ${rad.toFixed(1)}px node)`,
          );
          pairs++;
        });
      });
      // labels must not overlap: rectangle test on the anchored text boxes
      const boxes = ptr.map((nd) => {
        const rad = ((nd.insight || "").indexOf("[CORE]") >= 0 ? 11 : 8) + (nd.sig || 1) * 1.4;
        const L = pgLabel(nd, rad);
        const w = L.t.length * CH;
        const x0 = L.cls === "la-s" ? L.x : L.cls === "la-e" ? L.x - w : L.x - w / 2;
        const h = nd.rows && nd.rows.length > 1 ? 21 : 10;
        return { x0, x1: x0 + w, y0: L.y - 8, y1: L.y - 8 + h, t: L.t };
      });
      labels += boxes.length;
      for (let i = 0; i < boxes.length; i++)
        for (let j = i + 1; j < boxes.length; j++) {
          const a = boxes[i];
          const b = boxes[j];
          const over = a.x0 < b.x1 - 1 && b.x0 < a.x1 - 1 && a.y0 < b.y1 - 1 && b.y0 < a.y1 - 1;
          ok(!over, `${c.name}: labels overlap — "${a.t}" and "${b.t}"`);
        }
      // everything must stay inside the viewBox
      boxes.forEach((b) =>
        ok(
          b.x0 >= 22 && b.x1 <= 722 && b.y0 >= 30 && b.y1 <= 434,
          `${c.name}: label "${b.t}" falls outside the viewBox [${b.x0.toFixed(0)}..${b.x1.toFixed(0)}]`,
        ),
      );
    });
    if (fail.length)
      console.error(
        "graph geometry self-check FAILED:",
        fail.slice(0, 14),
        fail.length > 14 ? `(+${fail.length - 14} more)` : "",
      );
    return {
      fail,
      worstAngleGapDeg: +((worstGap * 180) / Math.PI).toFixed(1),
      worstNodeClearancePx: +worstClear.toFixed(1),
      linePairsTested: pairs,
      labelsTested: labels,
    };
  }

  function allPartnersRosterHtml(c, cid, clientNameOverride) {
    if (!c) return "";
    const clientName = clientNameOverride || (d.client && (d.client.short || d.client.name)) || "KSSL";
    const parts = pgNodes(c);

    let h = "";
    h += `<div style="padding: 16px 18px; border-bottom: 1px solid var(--l-line, #e2e0d8);">`;
    h += `  <div style="font-family: var(--mono); font-size: 11px; color: #b5341f; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;">`;
    h += `    ${esc(c.name)} ALLIANCE NETWORK (${parts.length} MAPPED PARTNERS)`;
    h += `  </div>`;
    h += `  <div style="font-size: 12px; color: #6b6a63; margin-top: 4px; line-height: 1.4;">`;
    h += `    Click on any partner card below or any node on the graph to open its full relationship detail page.`;
    h += `  </div>`;
    h += `</div>`;

    h += `<div style="display: flex; flex-direction: column; gap: 10px; padding: 16px 18px;">`;
    parts.forEach((p) => {
      const isShared = p.koel || p.shared || (p.rows && p.rows.some((r) => r.koel || r.shared));
      const isOverlap = !!isShared;
      const statusBadge = isOverlap
        ? `<span style="font-family: var(--mono); font-size: 9.5px; background: rgba(239, 68, 68, 0.12); color: #dc2626; border: 1px solid rgba(239, 68, 68, 0.3); padding: 2px 7px; border-radius: 4px; font-weight: 700; white-space: nowrap; flex-shrink: 0; display: inline-flex; align-items: center; gap: 4px;">Overlapping Partner</span>`
        : `<span style="font-family: var(--mono); font-size: 9.5px; background: rgba(34, 197, 94, 0.12); color: #16a34a; border: 1px solid rgba(34, 197, 94, 0.3); padding: 2px 7px; border-radius: 4px; font-weight: 700; white-space: nowrap; flex-shrink: 0; display: inline-flex; align-items: center; gap: 4px;">Direct Partner</span>`;

      const kindText = esc(p.kind || p.ptype || REL_LABEL[p.rel] || "Partner");
      const noteText = esc(p.note || p.insight || "Strategic defense manufacturing and supply tie.");

      h +=
        `<div class="pg-partner-roster-card" data-pid="${escAll(p.id)}" style="padding: 14px; background: #ffffff; border: 1px solid #e2e0d8; border-radius: 8px; cursor: pointer; transition: all 0.15s ease-in-out; display: flex; flex-direction: column; gap: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);">` +
        `<div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: nowrap; width: 100%;">` +
        `<span style="font-size: 13.5px; font-weight: 700; color: #161614; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0;" title="${esc(p.label)}">${esc(p.label)}</span>` +
        `${statusBadge}` +
        `</div>` +
        `<div style="display: flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10.5px; color: #6b6a63;">` +
        `<span style="background: #f0efea; padding: 2px 6px; border-radius: 3px; font-weight: 600; white-space: nowrap;">${kindText}</span>` +
        `<span>·</span>` +
        `<span style="white-space: nowrap;">${esc(p.country || "INDIA")}</span>` +
        `</div>` +
        `<div style="font-size: 12px; color: #4b5563; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">` +
        `${noteText}` +
        `</div>` +
        `<div style="font-size: 11px; font-weight: 600; color: #b5341f; margin-top: 2px; display: inline-flex; align-items: center; gap: 4px;">` +
        `View Relationship Detail →` +
        `</div>` +
        `</div>`;
    });
    h += `</div>`;

    return h;
  }

  return {
    pgSharedIndex,
    pgSharedFor,
    pgDistinct,
    pgNodes,
    pgNodeIdFor,
    pgThinNote,
    layoutGraph,
    graphSvg,
    overlapHtml,
    overlapDefsHtml,
    compReportHtml,
    allPartnersRosterHtml,
    drawerHead,
    tieHtml,
    fieldReadHtml,
    traceNodeIds,
    ovRole,
    selfCheck,
    geomCheck,
  };
}
