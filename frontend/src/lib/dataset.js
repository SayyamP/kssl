/* ===== KSSL dataset wiring =====
   The embedded dataset carries the 35 globals. What follows is only the joins the
   stored dataset does not carry, plus two shape adapters. Nothing here is data — it
   is glue, and it is the same glue the standalone HTML runs on load.

   Pure: takes the fetched object, returns a new wired one. Nothing is written to
   `window`, so the app can re-fetch and re-wire without a reload. */
import { computeSpecEdge } from "./edge.js";
import { wireTendersWithRealDays } from "./tenderCalc.js";
import { titleCaseHeadline } from "./profile.js";
import { logger } from "../utils/logger.js";

export function wireDataset(raw) {
  // shallow clone the containers we mutate; the leaf objects are ours after a fetch
  const d = { ...raw };

  /* ONE capitalisation for every headline in the app, applied at the single point they
     all enter it. Doing it here rather than at the render sites is the whole point: the
     SAME headline is held in five places -- the card, its detail panel, the innovation
     rail, the per-company news feed -- and casing them at four render sites would let a
     card and its own panel disagree, which is the exact shape of the date bug fixed
     just before this one.

     The stored text is untouched. This is a display rule; the record still holds the
     publisher's headline verbatim, and the source link still leads to it. */
  try {
    ["competitiveCards", "marketCards", "techCards"].forEach((lane) => {
      d[lane] = (d[lane] || []).map((c) => ({ ...c, title: titleCaseHeadline(c.title) }));
    });
    const mapValues = (obj, fn) =>
      Object.fromEntries(Object.entries(obj || {}).map(([k, v]) => [k, fn(v)]));
    d.innovations = mapValues(d.innovations, (rows) =>
      (rows || []).map((iv) => ({ ...iv, t: titleCaseHeadline(iv.t) })));
    d.competitorNews = mapValues(d.competitorNews, (rows) =>
      (rows || []).map((n) => ({ ...n, title: titleCaseHeadline(n.title) })));
    // the drill-down behind a card carries its own copy of the headline
    d.details = mapValues(d.details, (x) =>
      x && x.title ? { ...x, title: titleCaseHeadline(x.title) } : x);

    /* PRODUCT NAMES, through the same funnel and for the same reason. 63 of 124 stored
       product names are sentence case or lower -- "air defense systems", "launched
       effects", "tracked combat ground vehicles", "AK-203 assault rifle" -- while
       others arrive title cased, so the portfolio reads as two lists stacked. The same
       name is printed on the profile, the portfolio grid, the matchup list and the spec
       comparison; casing it at those four render sites is how "nag carrier" and "Nag
       Carrier" ended up on the same screen.

       titleCaseHeadline, NOT formatLabel. formatLabel lower-cases every word outside a
       fixed acronym list, which is right for a field LABEL and wrong for a product:
       it splits on the hyphen and prints "Ak-203". titleCaseHeadline raises only and
       eats no acronym, so AK-203, K10, YFQ-44A and BrahMos survive it.

       Stored text untouched -- display rule only. */
    const caseProduct = (p) => {
      if (typeof p === "string") return titleCaseHeadline(p);
      if (p && typeof p === "object" && typeof p.name === "string") {
        return { ...p, name: titleCaseHeadline(p.name) };
      }
      return p;
    };
    // competitors is a MAP keyed by comp_id, not an array -- mapValues, not .map()
    d.competitors = mapValues(d.competitors, (c) =>
      c && Array.isArray(c.products) ? { ...c, products: c.products.map(caseProduct) } : c);
  } catch (e) {
    logger.warn("wiring:headlineCase", e);
  }

  // overviewConfig needs the card arrays by reference (the exporter emits them apart)
  try {
    d.overviewConfig = {
      competitive: { ...d.overviewConfig.competitive, cards: d.competitiveCards },
      market: { ...d.overviewConfig.market, cards: d.marketCards },
      technology: { ...d.overviewConfig.technology, cards: d.techCards },
    };
  } catch (e) {
    logger.warn("wiring:overviewConfig", e);
  }

  // innovations may key on a domain the tech-area table doesn't list ('uncategorised');
  // append a chip for it so no innovation is unreachable from the rail.
  try {
    d.techCats = d.techCats.slice();
    Object.keys(d.innovations).forEach((k) => {
      if (!d.techCats.some((c) => c.id === k)) {
        d.techCats.push({
          id: k,
          name:
            (d.techAreaMeta[k] && d.techAreaMeta[k].area) ||
            k.replace(/-/g, " ").replace(/\b\w/g, (m) => m.toUpperCase()),
        });
      }
    });
  } catch (e) {
    logger.warn("wiring:techCats", e);
  }

  /* matchups[].edge is read everywhere as a 0-100 competitive index (50 = parity,
     <50 = client behind): the gap block, the positioning report, the gap engine and
     the scoped chat all assume that. It is derived, not stored — the dataset ships
     only the measured specs plus kvaDeltaPct (a signed rating delta, a different
     quantity), so compute the index here exactly as the dossier gauge does. */
  try {
    Object.keys(d.matchups).forEach((id) => {
      d.matchups[id].edge = computeSpecEdge(d.matchups[id]).edge; // null when too few measured specs
    });
  } catch (e) {
    logger.warn("wiring:matchup.edge", e);
  }

  /* RESOLVE THE CLIENT'S ID ONCE, FROM THE DATA.

     `client.short` is a display label ("KSSL"); the pipeline keys every row by a
     slug ("kalyani-strategic-systems"). Joining on the label therefore matched
     nothing, and each consumer failed differently but silently: the geo overlap
     layer reported "no shared product category" for every rival in every country,
     the country header printed "KSSL absent" over KSSL's own sourced rows, and the
     Partnerships tab listed the client in its own competitor list and produced a
     shared-partner analysis of the client against itself. One lookup, done here,
     so no consumer has to know which id space it is in. */
  try {
    const fromComps = Object.keys(d.competitors || {}).find(
      (k) => (d.competitors[k] || {}).dir === "client",
    );
    const fromGeo = (d.geoComps || []).find((c) => c.isBf);
    const resolved = fromComps || (fromGeo && fromGeo.id);
    if (resolved) d.client = { ...(d.client || {}), id: resolved };
  } catch (e) {
    logger.warn("wiring:client.id", e);
  }

  // the client's own footprint rows are its own presence, not rival activity:
  // mark them 'bf' so they read as "KSSL present" and don't get a counter-product line.
  try {
    const clientShort =
      (d.client && (d.client.id || d.client.short || d.client.name)) || "KSSL";
    const ownGeo = (d.geoData && d.geoData[clientShort]) || {};
    Object.keys(ownGeo).forEach((ct) =>
      ownGeo[ct].forEach((p) => {
        p.c = "bf";
      }),
    );
  // geoData contains client footprint under clientShort key
  } catch (e) {
    logger.warn("wiring:geoData", e);
  }

  try {
    adaptPatents(d);
  } catch (e) {
    logger.warn("wiring:PATENTS", e);
  }

  /* Compute real remaining days for all tenders based on DB record and current system date */
  try {
    if (d.tenders) {
      d.tenders = wireTendersWithRealDays(d.tenders);
    }
  } catch (e) {
    logger.warn("wiring:tenders", e);
  }

  /* Shared-partner marking is decided in the PIPELINE (mark_shared.py), not here.

     What used to sit in this block compared the two labels as strings and needed a
     common run of more than five characters, so "DRDO" — four — matched nothing,
     and the graph drew no red line at all while two rivals sat on the same
     government partner as the client. Guessing at identity from a label is what
     produced that; the pipeline resolves every organisation to one id and stamps
     `cid`, `shared`, `koel` and `clientTie` onto the tie.

     All that is left here is the join those ids make possible: attach the client's
     own roster row so the drawer can say what the client uses the same company for. */
  try {
    const roster = {};
    (d.KSSL_PARTNERS || []).forEach((p) => {
      const k = p.cid || p.id;
      if (k) roster[k] = p;
    });
    Object.keys(d.competitors || {}).forEach((cid) => {
      (d.competitors[cid].partners || []).forEach((p) => {
        if (p.shared && p.cid && roster[p.cid] && !p.koel) p.koel = roster[p.cid];
      });
    });
  } catch (e) {
    logger.warn("wiring:sharedPartners", e);
  }

  /* The chat knowledge base reads flattened geo rows and innovation items
     (d.geoRows / d.techItems) that the stored dataset does not carry. */
  try {
    const nameOf = {};
    (d.geoComps || []).forEach((c) => {
      nameOf[c.id] = c.name;
    });
    d.geoRows = [];
    Object.keys(d.geoData || {}).forEach((cid) =>
      Object.keys(d.geoData[cid]).forEach((ct) =>
        d.geoData[cid][ct].forEach((p) =>
          d.geoRows.push({ country: ct, company: nameOf[cid] || cid, name: p.name, c: p.c }),
        ),
      ),
    );
    d.techItems = [];
    Object.keys(d.innovations || {}).forEach((dom) =>
      (d.innovations[dom] || []).forEach((iv) => d.techItems.push({ ...iv, dom })),
    );
  } catch (e) {
    logger.warn("wiring:chatKb", e);
  }

  d.signalTheme = {};
  d.themeSignals = {};

  return d;
}

/* PATENTS shape adapter. The dataset emits byArea / byAssignee; the render code
   reads byCompetitor / byTechnology. Empty in -> empty out, and both patent views
   fall through to their documented empty state instead of throwing. */
function adaptPatents(d) {
  const PATENTS = d.PATENTS;
  if (!PATENTS) return;
  const byArea = PATENTS.byArea || {};
  const byAssignee = PATENTS.byAssignee || {};

  function norm(r) {
    return {
      id: r.no || r.id || "",
      title: r.title || "",
      assignee: r.assignee || "",
      // the dataset uses granted/published; the badge CSS knows granted/filed/pending
      status: /grant/i.test(r.status || "")
        ? "granted"
        : /pend/i.test(r.status || "")
          ? "pending"
          : "filed",
      filed: r.filed || "",
      granted: r.granted || "",
      jurisdiction: r.country || r.jurisdiction || "",
      ipc: r.ipc || [],
      abstract: r.abstract || r.claims || "",
      techArea: r.area || r.techArea || "",
      // threat was dropped here once, so every holder rendered as 'low' while the
      // dataset actually carries 22 high / 24 medium / 12 low.
      threat: (r.threat || "").toLowerCase(),
      koel_relevance: r.relev || "",
      srcs: r.srcs || [],
      url: r.url || "",
    };
  }

  /* Assignees are legal entity names ('Caterpillar Inc.'), competitors are trading
     names ('Caterpillar India'). Match on shared distinctive tokens, best score wins,
     one assignee to at most one competitor. The client's own filings are never
     attributed to a rival. */
  const STOP =
    /^(inc|ltd|limited|corporation|corp|company|gmbh|oyj|holdings|group|india|indian|systems|solutions|technologies|energy|generation|electric|vehicles|commercial|components|industries|heavy|and|the|pvt|private|defence|defense|aerospace|strategic|advanced)$/;
  function toks(s) {
    return (s || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((w) => w.length > 2 && !STOP.test(w));
  }
  const clientRe = new RegExp(
    ((d.client && d.client.name) || "the client")
      .replace(/\s*\(.*?\)\s*/g, "")
      .replace(/[^a-z0-9 ]/gi, "")
      .trim()
      .replace(/\s+/g, "\\s+"),
    "i",
  );
  const compToks = d.compOrder.map((cid) => ({
    cid,
    t: toks(d.competitors[cid].name),
  }));

  PATENTS.byCompetitor = {};
  Object.keys(byAssignee).forEach((name) => {
    if (clientRe.test(name)) return; // KSSL's own filings
    const at = toks(name);
    let best = null;
    let bestN = 0;
    compToks.forEach((c) => {
      const n = c.t.filter((w) => at.indexOf(w) >= 0).length;
      if (n > bestN) {
        bestN = n;
        best = c.cid;
      }
    });
    if (!best) return;
    if (!PATENTS.byCompetitor[best])
      PATENTS.byCompetitor[best] = { stats: null, records: [] };
    PATENTS.byCompetitor[best].records = PATENTS.byCompetitor[best].records.concat(
      byAssignee[name].map(norm),
    );
  });

  PATENTS.byTechnology = {};
  Object.keys(byArea).forEach((area) => {
    const recs = byArea[area].map(norm);
    let meta = null;
    Object.keys(d.techAreaMeta || {}).forEach((k) => {
      if (d.techAreaMeta[k].area === area) meta = d.techAreaMeta[k];
    });
    /* Per-holder facts. NOT a share percentage: only 1 of 56 (field, assignee) pairs
       in this dataset has more than one filing, so share is always 1/N and a share
       bar chart is guaranteed to render identical bars. What actually separates
       holders here is whether the filing is GRANTED (enforceable now) vs merely
       published, where it is filed, how recent it is, and its assessed threat. */
    const THREAT_RANK = { high: 3, medium: 2, low: 1 };
    const byName = {};
    recs.forEach((r) => {
      if (!r.assignee) return;
      const g = (byName[r.assignee] = byName[r.assignee] || {
        name: r.assignee,
        filings: 0,
        granted: 0,
        countries: {},
        latest: null,
        threat: "low",
        recs: [],
      });
      g.filings++;
      if (r.status === "granted") g.granted++;
      if (r.jurisdiction) g.countries[r.jurisdiction] = 1;
      const yr = parseInt((r.granted || r.filed || "").slice(0, 4), 10);
      if (yr && (!g.latest || yr > g.latest)) g.latest = yr;
      const t = (r.threat || "").toLowerCase();
      if ((THREAT_RANK[t] || 0) > (THREAT_RANK[g.threat] || 0)) g.threat = t;
      g.recs.push(r);
    });
    const isClient = (n) => clientRe.test(n || "");
    const holders = Object.keys(byName)
      .map((n) => {
        const g = byName[n];
        return {
          name: n,
          filings: g.filings,
          granted: g.granted,
          pending: g.filings - g.granted,
          countries: Object.keys(g.countries),
          latest: g.latest,
          threat: g.threat,
          isClient: isClient(n),
          isRival: !isClient(n),
          trend: (meta && meta.trend) || "flat",
        };
      })
      .sort((a, b) => {
        // client pinned first — it is the reference point the banner above talks about,
        // and it carries no threat rating so it would otherwise sort among the 'low' rows
        if (a.isClient !== b.isClient) return a.isClient ? -1 : 1;
        // then most consequential: granted before pending, then threat, then recency
        return (
          b.granted - a.granted ||
          (THREAT_RANK[b.threat] || 0) - (THREAT_RANK[a.threat] || 0) ||
          (b.latest || 0) - (a.latest || 0) ||
          a.name.localeCompare(b.name)
        );
      });
    PATENTS.byTechnology[area] = {
      stats: {
        totalFilings: recs.length,
        activeAssignees: holders.length,
        koel_position: (meta && meta.position) || "—",
      },
      crowding: recs.length >= 25 ? "crowded" : recs.length >= 8 ? "emerging" : "open",
      summary: (meta && (meta.why || meta.desc)) || "",
      leaders: holders,
      whitespace: [],
      koel: {
        filings: recs.filter((r) => /kalyani|kssl|bharat\s*forge/i.test(r.assignee || "")).length,
        position: (meta && meta.reason) || "No KSSL filings recorded in this field yet.",
      },
      records: recs,
    };
  });
}
