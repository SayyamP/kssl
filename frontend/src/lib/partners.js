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

  /* The graph's inner SVG, as one string. Nodes carry data-id so the React view can
     delegate clicks; there is no per-node listener to attach or tear down. */
  function graphSvg(c) {
    const { nodes, edges } = layoutGraph(c);
    const nmap = {};
    nodes.forEach((nd) => {
      nmap[nd.id] = nd;
    });
    let eh = "";
    edges.forEach((e) => {
      const a = nmap[e.a];
      const b = nmap[e.b];
      const isShared = e.koel || e.shared;
      const w = isShared ? 3.2 : 1.6;
      const strokeColor = isShared ? "#e8483a" : "#3a4556";
      eh += `<line class="pg-edge rel-${e.rel}${isShared ? " shared" : ""}" data-b="${e.b}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" style="stroke:${strokeColor};stroke-width:${w};opacity:${isShared ? 1 : 0.7}"></line>`;
    });
    let nh = "";
    nodes.forEach((nd) => {
      if (nd.type === "comp") {
        const tcls = nd.dir === "threat" ? " threat" : nd.dir === "fav" ? " fav" : "";
        nh += `<g class="pg-node comp${tcls}" data-id="${nd.id}"><circle cx="${nd.x}" cy="${nd.y}" r="17"></circle><text class="lbl center la-m" x="${nd.x}" y="${nd.y - 26}">${esc(nd.label)}</text></g>`;
      } else {
        const kc = kindClass(nd.kind);
        const isCore = (nd.insight || "").indexOf("[CORE]") >= 0;
        const r = (isCore ? 11 : 8) + (nd.sig || 1) * 1.4;
        const ring = isCore
          ? `<circle cx="${nd.x}" cy="${nd.y}" r="${r + 4}" fill="none" stroke="#9c2b2b" stroke-width="1.3" stroke-opacity="0.55"></circle>`
          : "";
        const isShared = nd.koel || nd.shared || (nd.rows && nd.rows.some((r) => r.koel || r.shared));
        const shd = isShared ? " shared" : "";
        const L = pgLabel(nd, r);
        // several relationship rows merged into this one company node
        const nRows = (nd.rows && nd.rows.length) || 1;
        const pill =
          nRows > 1
            ? `<text class="lbl nrow ${L.cls}" x="${L.x}" y="${L.y + 11}">${nRows} ties</text>`
            : "";
        nh +=
          `<g class="pg-node ptr ${kc} rel-${nd.rel}${isCore ? " core" : ""}${shd}" data-id="${nd.id}">` +
          `<title>${esc(L.full)}${nRows > 1 ? ` — ${nRows} mapped relationships` : ""}</title>${ring}` +
          `<circle cx="${nd.x}" cy="${nd.y}" r="${r}"></circle>` +
          `<text class="lbl ${L.cls}" x="${L.x}" y="${L.y}">${esc(L.t)}</text>${pill}</g>`;
      }
    });
    return eh + nh;
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
  function tieHtml(c, cid, pid, clientNameOverride) {
    const clientName = clientNameOverride || (d.client && (d.client.short || d.client.name)) || "KSSL";
    const p = (c.partners || []).find((x) => x.id === pid);
    if (!p) return "";
    const isCore = (p.insight || "").indexOf("[CORE]") >= 0;
    const isAdj = (p.insight || "").indexOf("[ADJACENT]") >= 0;
    const relevTag = isCore
      ? `<span class="pat-relev CORE">On a ${clientName} line</span>`
      : isAdj
        ? '<span class="pat-relev ADJACENT">Adjacent</span>'
        : "";
    const insightClean = (p.insight || "")
      .replace(/<b>\[(CORE OVERLAP|CORE|ADJACENT|context|OVERLAP)\]<\/b>\s*/gi, "")
      .replace(/\[(CORE OVERLAP|CORE|ADJACENT|context|OVERLAP)\]\s*/gi, "")
      .trim();
    // Editorial policy: keep descriptive reads (Threat/Dependency/Read), remove
    // decision-influencing 'Opening:' moves.
    let meanClean = p.mean || "";
    if (meanClean) {
      meanClean = meanClean.replace(
        /<b>\s*Opening:\s*<\/b>[\s\S]*?(?=<b>\s*(?:Threat|Dependency|Read|So what)\s*:\s*<\/b>|$)/gi,
        "",
      );
      meanClean = meanClean.replace(/\s{2,}/g, " ").replace(/^\s*·\s*/, "").trim();
    }
    let h = "";
    h += `<div class="pg-tie-back" data-back="comp">‹ Back to ${esc(c.name)}</div>`;
    h +=
      `<div class="tie-hero"><div class="th-name">${esc(p.label)}</div>` +
      `<div class="th-meta"><span class="tie-rel-pill"><span class="rmark rel-${p.rel}"></span>${esc(REL_LABEL[p.rel] || p.ptype)}</span><span>${esc(p.country || "—")}</span>${relevTag}</div></div>`;
    // other relationship rows recorded for this same company
    const sib = (c.partners || []).filter(
      (x) => (x.cid || x.id) === (p.cid || p.id) && x.id !== p.id,
    );
    if (sib.length) {
      h +=
        `<div class="tie-block sib"><span class="tb-l">◆ ${sib.length + 1} relationships on file with ` +
        `${esc(p.label)}</span><div class="tb-x">The graph draws one node per company; these rows are ` +
        'recorded separately in the source data.</div><div class="sib-list">';
      sib.forEach((x) => {
        const note = pgThinNote(x, c.name);
        h +=
          `<div class="sib-row" data-pid="${escAll(x.id)}">` +
          `<span class="rmark rel-${x.rel}"></span><span class="sib-t">${esc(x.ptype || REL_LABEL[x.rel])}` +
          `</span><span class="sib-n">${note ? esc(note) : '<span class="sib-none">no detail on file</span>'}` +
          "</span></div>";
      });
      h += "</div></div>";
    }
    /* facts. A row is written only when the field HAS a value: a revived tie
       carries what its document states and nothing else, and an empty <span>
       under a label reads as "Timeline: (blank)" rather than "not recorded". */
    const factRow = (k, v) =>
      v && v !== "n/d" ? `<span class="tk">${k}</span><span class="tv">${esc(v)}</span>` : "";
    h +=
      '<div class="tie-block fact"><span class="tb-l">The relationship</span>' +
      '<div class="tie-facts-grid">' +
      factRow("Scope", p.ptype) +
      factRow("Programme", p.note) +
      factRow("Deal / scale", p.deal) +
      factRow("Timeline", p.date) +
      "</div></div>";
    /* A direct tie with the client has no roster row behind it (the client is not
       on its own roster), so the shared block below rendered nothing at all and the
       drawer silently contradicted the graph's red line. */
    if (p.clientTie) {
      h +=
        `<div class="tie-block shared"><span class="tb-l">◆ Direct tie with ${clientName}</span>` +
        `<div class="tb-x"><b>${esc(c.name)}</b> and <b>${clientName}</b> are parties to this ` +
        `${esc((p.ptype || "agreement").toLowerCase())} themselves — this is not an overlapping ` +
        "third-party supplier but a relationship between the two companies.</div></div>";
    }
    // shared partner: this same company is on client's own roster — say what that costs
    const clientRelObj = p.koel;
    if (clientRelObj) {
      const idx = pgSharedIndex();
      const all = idx[p.cid] || [];
      const also = all.filter((r) => r.cid !== cid).map((r) => r.name);
      const def = OV_DEF[OV_KIND[clientRelObj.rel] || "tech"];
      h +=
        `<div class="tie-block shared"><span class="tb-l">◆ Overlapping with ${clientName}</span><div class="tb-x">` +
        `<b>${esc(p.label)}</b> is also ${clientName}’s own ${esc((clientRelObj.rel || "partner").toLowerCase())}` +
        `${ovRole(p) ? ` — ${esc(ovRole(p))}` : ""}. ` +
        `It works with ${esc(c.name)} as ${esc((p.ptype || "a partner").toLowerCase())}.` +
        (also.length
          ? ` It also carries <b>${esc(also.join(", "))}</b>, putting ${clientName} on a shelf with ${all.length} rival brand${all.length === 1 ? "" : "s"}.`
          : ` ${clientName} and ${esc(c.name)} are the two brands it carries.`) +
        `<ul>${def ? def.fx.map((f) => `<li><b>${f[0].replace(/KSSL/g, clientName)}.</b> ${f[1].replace(/KSSL/g, clientName)}</li>`).join("") : ""}</ul></div></div>`;
    }
    if (insightClean)
      h += `<div class="tie-block reveal"><span class="tb-l">What this tie reveals</span><div class="tb-x">${insightClean}</div></div>`;
    if (meanClean)
      h += `<div class="tie-block conseq"><span class="tb-l">Competitive read</span><div class="tb-x">${meanClean}</div></div>`;
    /* A revived tie cites the document that STATES it, and says why that source
       counts. The archive rows carried no source at all, which is why they were
       archived; a republished one has to show its evidence here. */
    if (!p.src)
      h +=
        '<div class="tie-block evidence none"><span class="tb-l">Evidence for this tie</span>' +
        '<div class="tb-x">No source recorded. This tie was written before the ' +
        "pipeline stored the document it came from; it is shown, but it cannot be " +
        "checked here.</div></div>";
    if (p.src)
      h +=
        '<div class="tie-block evidence"><span class="tb-l">Evidence for this tie</span>' +
        `<div class="tb-x">${esc(p.srcnote || "")}` +
        `<div class="src-list" style="margin-top:7px">${srcChips([{ label: p.src, url: p.src }])}</div>` +
        "</div></div>";
    h += sourcesSectionHtml(c);
    return h;
  }

  /* Field-level read: the patterns that are invisible in any single dossier. */
  function fieldReadHtml(cid) {
    if (!FIELDSYN) return "";
    const cname = (competitors[cid] && competitors[cid].name) || "competitor";
    let h = `<div class="pg-tie-back" data-back="comp">‹ Back to ${esc(cname)}</div>`;
    h +=
      '<div style="padding:4px 0 8px"><div style="font-size:15px;font-weight:700;margin-bottom:3px">Field-level intelligence</div>' +
      `<div style="font-size:11px;color:var(--d-txt-3);margin-bottom:14px">Patterns across all ${Object.keys(competitors).length} competitors — invisible in any single dossier.</div>`;
    (FIELDSYN.patterns || []).forEach((p, i) => {
      h +=
        `<div class="syn-strat" style="border-left-color:#3d7fbf;margin-bottom:10px"><div class="st">${i + 1}. ${esc(p.field || p.t)}</div>` +
        `<div class="sp"><b>Pattern:</b> ${esc(p.pattern || p.e)}${p.total ? ` <span style="opacity:.6">(${p.n} of ${p.total})</span>` : ""}</div>` +
        `<div class="sp" style="color:var(--d-txt)"><b>Read:</b> ${esc(p.implication || p.s)}</div></div>`;
    });
    h += `<div class="syn-strat" style="border-left-color:#3d7fbf;margin-top:6px"><div class="st">Bottom line</div><div class="sp" style="color:var(--d-txt)">${esc(FIELDSYN.bottomLine || FIELDSYN.bottom || "")}</div></div></div>`;
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
    drawerHead,
    tieHtml,
    fieldReadHtml,
    traceNodeIds,
    ovRole,
    selfCheck,
    geomCheck,
  };
}
