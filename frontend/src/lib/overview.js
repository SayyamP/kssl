/* Overview feed: the sequence logic, the group split, and the per-pillar metric
   strip. Pure — it returns data, and the React components render it. */
import { parseCr } from "./gapModel.js";

export const SEQ_LABEL = {
  recency: "Most Recent First",
  depth: "Richest Analysis First",
  category: "Grouped by Domain",
};
export const SEQ_SUB = {
  recency: "— newest signals at top",
  depth: "— most analytical lenses first",
  category: "— ordered by category",
};

export const SEQ_OPTIONS = [
  ["priority", "Priority (threats first)"],
  ["recency", "Most recent"],
  ["depth", "Analytical depth"],
  ["category", "By domain"],
];

/* parse a date-ish 'ago' field ('07 Mar 2026', 'Jun 2026', '2h ago') into a sortable
   number; newer = higher */
function monthVal(ago) {
  if (!ago) return 0;
  const months = {
    jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
    jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
  };
  const m = ago.toLowerCase().match(/([a-z]{3})\s*(\d{4})/);
  if (m) return parseInt(m[2], 10) * 12 + (months[m[1]] || 0);
  const y = ago.match(/(\d{4})/);
  if (y) return parseInt(y[1], 10) * 12;
  if (/ago/.test(ago)) return 999999; // 'Nh ago' = very recent
  return 0;
}

/* Ordered, re-ranked and split into the groups the feed renders. */
export function buildFeed(cfg, seqMode) {
  const dirRank = { threat: 0, watch: 1, fav: 2 };
  let cards = (cfg.cards || []).slice();
  if (seqMode === "priority") {
    cards.sort(
      (a, b) =>
        dirRank[a.dir] - dirRank[b.dir] ||
        (b.sec ? b.sec.length : 0) - (a.sec ? a.sec.length : 0),
    );
  } else if (seqMode === "recency") {
    cards.sort((a, b) => monthVal(b.ago) - monthVal(a.ago));
  } else if (seqMode === "depth") {
    cards.sort(
      (a, b) =>
        (b.sec ? b.sec.length : 0) - (a.sec ? a.sec.length : 0) ||
        dirRank[a.dir] - dirRank[b.dir],
    );
  } else if (seqMode === "category") {
    cards.sort((a, b) => String(a.meta).localeCompare(String(b.meta)));
  }
  // re-rank display numbers after sort (a copy — the dataset card is not renumbered)
  cards = cards.map((c, n) => ({ ...c, rank: String(n + 1).padStart(2, "0") }));

  const groupDefs =
    seqMode === "priority"
      ? cfg.groups
      : [{ n: 99, h: SEQ_LABEL[seqMode] || "All signals", s: SEQ_SUB[seqMode] || "" }];

  const groups = [];
  let idx = 0;
  groupDefs.forEach((g) => {
    const slice = cards.slice(idx, idx + g.n);
    if (!slice.length) return;
    idx += slice.length;
    groups.push({ h: g.h, s: g.s, cards: slice });
  });
  return { groups, total: (cfg.cards || []).length };
}

/* The open / awarded / closed split, defined once so the nav badges, the tender
   tabs and the market metric tiles can never disagree on what "open" means. */
export function bucketTenders(tenders) {
  const list = tenders || [];
  const isAwarded = (t) => (t.status || "").toLowerCase() === "awarded" || t.urlKind === "award";
  const isClosed = (t) =>
    !isAwarded(t) && (t.isLive === false || t.dl <= 0 || (t.deadline || "").includes("Closed"));
  return {
    awarded: list.filter(isAwarded),
    closed: list.filter(isClosed),
    open: list.filter((t) => !isAwarded(t) && !isClosed(t)),
  };
}

/* Live counts from the served data, so the strip can never drift from the feed.
   Every pillar computes its tiles — the config carries labels and phrasing only;
   a number the service didn't back is never rendered. */
export function metricsFor(cfg, pillar, d) {
  const metrics = (cfg.metrics || []).map((m) => ({ ...m }));
  try {
    const cards = cfg.cards || [];
    const lensSet = new Set();
    cards.forEach((c) => {
      if (c.lens) lensSet.add(c.lens);
      (c.sec || []).forEach((s) => {
        if (s.lens) lensSet.add(s.lens);
      });
    });
    let byLabel = { "All signals": cards.length };
    const subByLabel = {};
    if (pillar === "competitive") {
      byLabel = {
        ...byLabel,
        "Competitive threats": cards.filter((c) => c.dir === "threat").length,
        "Watch signals": cards.filter((c) => c.dir === "watch").length,
        "Companies tracked": new Set(cards.map((c) => c.company).filter(Boolean)).size,
        "Analytical lenses": lensSet.size,
      };
    } else if (pillar === "market") {
      const tenders = (d && d.tenders) || [];
      const { open, awarded, closed } = bucketTenders(tenders);
      // A tender whose source never published a value contributes nothing; if NO open
      // tender carries one, the total is unknown, not zero -- "not measured" and "zero"
      // must not look the same.
      const priced = open.filter((x) => parseCr(x.value) > 0);
      const liveCr = priced.reduce((t, x) => t + parseCr(x.value), 0);
      const countries = new Set(tenders.map((t) => t.country).filter(Boolean));
      const cats = new Set(tenders.map((t) => t.cat).filter(Boolean));
      byLabel = {
        ...byLabel,
        "Live bid value": priced.length ? Math.round(liveCr).toLocaleString("en-IN") : "—",
        "Open opportunities": open.length,
        "Already concluded": awarded.length + closed.length,
        "Markets tracked": countries.size,
      };
      subByLabel["Already concluded"] = `of ${tenders.length} tracked — awarded or closed, not biddable`;
      subByLabel["Live bid value"] = priced.length
        ? `open tenders · ${priced.length} of ${open.length} publish a value`
        : "no open tender publishes a value";
      subByLabel["Markets tracked"] = `countries · ${cats.size} categor${cats.size === 1 ? "y" : "ies"}`;
    } else if (pillar === "technology") {
      const innovations = (d && d.innovations) || {};
      const domains = Object.keys(innovations).filter((k) => (innovations[k] || []).length);
      byLabel = {
        ...byLabel,
        "Capability threats": cards.filter((c) => c.dir === "threat").length,
        "Watch signals": cards.filter((c) => c.dir === "watch").length,
        "Domains tracked": domains.length,
        "Analytical lenses": lensSet.size,
      };
      const nameOf = (id) => {
        const c = ((d && d.techCats) || []).find((x) => x.id === id);
        return c ? c.name : id;
      };
      subByLabel["Domains tracked"] = domains.length
        ? domains.map(nameOf).join("·")
        : "no domains served yet";
    }
    metrics.forEach((m) => {
      if (byLabel[m.l] != null) m.v = String(byLabel[m.l]);
      if (subByLabel[m.l] != null) m.sub = subByLabel[m.l];
    });
  } catch (e) {
    /* the strip is cosmetic; a missing field must never blank the feed */
  }
  return metrics;
}

/* metric tile -> which signals it opens. `tags` is a space-separated string on
   each card. */
export const TILE_LABELS = {
  atstake: "contested bids, by value",
  threat: "threats to active bids",
  fav: "openings to press",
  deadline: "by submission deadline",
  open: "open tenders",
  fit: "strong KSSL fit",
  geo: "markets in play",
  positioning: "rating-matched rivals",
  gap: "capability gaps",
  patents: "patent activity",
  emission: "emission compliance",
  all: "sorted by relevance",
};

export function tilePredicate(act) {
  const has = (c, t) => String(c.tags || "").split(" ").includes(t);
  if (act === "all") return () => true;
  if (act === "atstake") return (c) => c.dir === "threat" || c.dir === "atstake" || has(c, "atstake");
  if (act === "threat") return (c) => c.dir === "threat" || has(c, "threat");
  if (act === "fav" || act === "watch") return (c) => c.dir === "fav" || c.dir === "watch" || has(c, "opening") || has(c, "fav") || has(c, "watch");
  if (act === "open") return () => true;
  if (act === "deadline") return () => true;
  if (act === "gap") return (c) => c.dir === "threat" || has(c, "gap") || has(c, "tech");
  if (act === "patents") return () => true;
  return () => true;
}

/* ===== Dynamic nav counts (computed from live data, never hardcoded) ===== */
export function navCounts(d, gapModel) {
  const counts = {};
  try {
    // Positioning: distinct competitor companies across matchups
    const posCompanies = new Set();
    Object.values(d.matchups).forEach((m) => {
      const co = (m.comp || "").split("·")[0].trim();
      if (co) posCompanies.add(co);
    });
    counts.positioning = posCompanies.size;
    // Partnerships: competitor profiles (exclude the client's own reference network)
    counts.partnerships = Object.keys(d.competitors).filter((k) => k !== ((d.client && d.client.id) || "KSSL")).length;
    // Geo: distinct countries across all companies' footprints
    const geoCountries = new Set();
    Object.values(d.geoData).forEach((byCountry) =>
      Object.keys(byCountry || {}).forEach((c) => geoCountries.add(c)),
    );
    counts.geo = geoCountries.size;
    counts.overview = d.competitiveCards.length;
    /* Profile lists the rivals — the client's own row is not a competitor profile.
       `d.client.id` is the slug by the time this runs; wireDataset resolves it from
       the row whose dir is "client", precisely so this join is not on a display label. */
    counts.profile = Object.keys(d.competitors).filter(
      (k) => k !== ((d.client && d.client.id) || "KSSL"),
    ).length;

    const { open, awarded, closed } = bucketTenders(d.tenders);
    /* The Market overview badge counts the TENDERS it opens — all of them, since the
       page carries open, awarded, closed and the portals as tabs. It used to count
       `marketCards` — three signal cards — and sat as a "3" above a page listing
       eighty-nine tenders. Tender Pipeline below it is the open subset, so the two
       rows now say different things. */
    /* Overview is the signal feed again, so its badge counts the CARDS it opens — the
       same thing the competitive and technology overview badges count. The tender total
       moved with the tender report to its own row. */
    counts["m-overview"] = (d.marketCards || []).length;
    counts["m-report"] = (d.tenders || []).length;
    counts.tender = open.length;
    counts["awarded-tenders"] = awarded.length;
    counts["closed-tenders"] = closed.length;

    // patents badge: indexed filings, not a hardcoded 1
    counts["patents-comp"] = (d.PATENTS && d.PATENTS._meta && d.PATENTS._meta.total) || 0;
    const innovTotal = Object.keys(d.innovations).reduce(
      (n, k) => n + (d.innovations[k] || []).length,
      0,
    );
    // the Overview badge counts the FEED it opens (tech signal cards); the Innovation
    // badge counts innovations. Labelling one with the other's number was a mismatch
    // visible on screen: badge 29 above a feed of 11.
    counts["t-overview"] = d.techCards.length;
    counts.innovation = innovTotal;
    // gap badge: how many 'behind' gaps this pillar carries
    counts["gap-competitive"] = (gapModel || []).filter(
      (g) => g.direction === "behind" && g.pillar === "competitive",
    ).length;
  } catch (e) {
    /* counts are cosmetic; never break the app over one */
  }
  return counts;
}

/* Header strings, computed rather than hardcoded. */
export function viewMetaFor(d) {
  let allianceCount = 0;
  let geoCountries = new Set();
  try {
    Object.entries(d.competitors).forEach(([k, c]) => {
      if (k !== ((d.client && d.client.id) || "KSSL") && c.partners) allianceCount += c.partners.length;
    });
    Object.values(d.geoData).forEach((byCountry) =>
      Object.keys(byCountry || {}).forEach((c) => geoCountries.add(c)),
    );
  } catch (e) {
    /* fall through to the static copy below */
  }
  const partnerCount = Object.keys(d.competitors).filter((k) => k !== ((d.client && d.client.id) || "KSSL")).length;
  const geoCompCount = Object.keys(d.geoData).filter((k) => k !== ((d.client && d.client.short) || "KSSL")).length;
  const alertCount = d.competitiveCards.length;
  return {
    overview: {
      title: "Competitive Intelligence",
      cnt: `${alertCount} active signals · sorted by relevance`,
      filters: true,
    },
    profile: {
      title: "Company Profile",
      cnt: `${partnerCount} companies tracked · everything the corpus holds on one rival`,
      filters: false,
    },
    positioning: {
      title: "Positioning",
      cnt: "KSSL products mapped to rival products by spec category",
      filters: true,
    },
    partnerships: {
      title: "Partnerships",
      cnt: `${partnerCount} competitors · ${allianceCount} alliances mapped`,
      filters: false,
    },
    geo: {
      title: "Geo Footprint",
      cnt: `${geoCompCount} competitors · ${geoCountries.size} markets · competitor activity by country`,
      filters: false,
    },
    tender: {
      title: "Tender Pipeline",
      cnt: "Live opportunities matched to product portfolio",
      filters: false,
    },
    "awarded-tenders": {
      title: "Awarded Tenders",
      cnt: "Contracts awarded or settled",
      filters: false,
    },
    "closed-tenders": {
      title: "Closed Tenders",
      cnt: "Opportunities closed or expired",
      filters: false,
    },
    innovation: {
      title: "Innovation Pipeline",
      cnt: "Technology developments tracked across KSSL product domains",
      filters: false,
    },
    "patents-comp": {
      title: "Patents",
      cnt: "Filings by rival and by technology field · sourced from patent records",
      filters: false,
    },
    "gap-competitive": {
      title: "Gap Analysis",
      cnt: "Where KSSL trails rivals, from the Positioning spec comparisons",
      filters: false,
    },
  };
}
