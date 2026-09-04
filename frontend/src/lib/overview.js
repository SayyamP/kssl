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

const MONTHS = {
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
  jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
};

/* A sortable number for a displayed date; newer = higher.
   'DD Mon YYYY' -> 20260830, 'Mon YYYY' -> 20260900, 'Nd ago' -> most recent.

   Replaces a month-precision predecessor that returned year*12+month, under which
   '11 Aug 2026' and '30 Aug 2026' were the SAME number. Both date shapes are real:
   serving.signal_detail states the day ('30 Aug 2026') while signal_card.ago is often
   month-only ('Sep 2026'), so a comparator has to order across the two. A month-only
   value takes day 0, which puts it after every dated day of that month when sorting
   newest-first, and still ahead of the whole previous month. */
export function dateVal(s) {
  if (!s) return 0;
  const t = String(s).toLowerCase().trim();
  if (/ago\b/.test(t)) return 99999999; // '1d ago' is newer than any printed date
  let m = t.match(/(\d{1,2})\s+([a-z]{3})[a-z]*\.?\s+(\d{4})/);
  if (m) {
    return parseInt(m[3], 10) * 10000 + (MONTHS[m[2]] || 0) * 100 + parseInt(m[1], 10);
  }
  m = t.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    return parseInt(m[1], 10) * 10000 + parseInt(m[2], 10) * 100 + parseInt(m[3], 10);
  }
  m = t.match(/([a-z]{3})[a-z]*\.?\s+(\d{4})/);
  if (m) return parseInt(m[2], 10) * 10000 + (MONTHS[m[1]] || 0) * 100;
  m = t.match(/(\d{4})/);
  if (m) return parseInt(m[1], 10) * 10000;
  return 0;
}

/* Ordered, re-ranked and split into the groups the feed renders.

   `data` is what the cards are DISPLAYED with: the date on a card comes from
   signalDate(card, data), which prefers the day-precision date in the detail panel over
   the card's own month-only `ago`. Sorting on `ago` while printing signalDate() is what
   produced a threat list reading Sep 2026, 11 Aug, 30 Aug, 11 Aug, 20 Aug, 4 Aug -- the
   order was real, it just belonged to a different set of values than the ones on screen.
   The comparator and the label have to read the same field. */
export function buildFeed(cfg, seqMode, data) {
  const dirRank = { threat: 0, watch: 1, fav: 2 };
  const when = (c) => dateVal(signalDate(c, data));
  let cards = (cfg.cards || []).slice();
  if (seqMode === "priority") {
    cards.sort(
      (a, b) =>
        dirRank[a.dir] - dirRank[b.dir] ||
        when(b) - when(a) ||
        (b.sec ? b.sec.length : 0) - (a.sec ? a.sec.length : 0),
    );
  } else if (seqMode === "recency") {
    cards.sort((a, b) => when(b) - when(a));
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
  groupDefs.forEach((g, i) => {
    /* The LAST group takes everything still unassigned. The group defs carry fixed
       sizes (competitive is 6 + 99) that were written against a demo dataset of about
       forty cards; production serves 429, so a plain `slice(idx, idx + g.n)` dropped
       324 of them on the floor while the footer still counted all 429 -- the feed said
       "end of active signals, 429 total" under a list that stopped at 105. A group
       total is a layout hint for the first bucket, never a limit on the corpus. */
    const last = i === groupDefs.length - 1;
    const slice = last ? cards.slice(idx) : cards.slice(idx, idx + g.n);
    if (!slice.length) return;
    idx += slice.length;
    groups.push({ h: g.h, s: g.s, cards: slice });
  });
  return { groups, total: (cfg.cards || []).length };
}

/* The date a signal is shown with, in ONE format everywhere.

   The card aside printed the pipeline's `ago` ("Aug 2026") while the detail panel beside
   it printed the same event's day-precision date ("11 Aug 2026") -- 730 of 813 cards
   disagreed with their own panel, both on screen at once. That is what the report meant
   by dates being wrong and the format inconsistent: not that the day was incorrect, but
   that the same signal carried two different answers.

   The panel's value is the richer one and comes from the same pipeline field, so it wins
   when it exists; `ago` remains the fallback for the 83 rows that carry no day. Nothing
   is reformatted or re-derived here -- deriving a date a fourth way is how this started. */
export function signalDate(card, data) {
  const facts = ((data && data.details && data.details[card && card.id]) || {}).facts || [];
  for (const row of facts) {
    if (Array.isArray(row) && row[0] === "Date" && row[1]) return String(row[1]);
  }
  return (card && card.ago) || "";
}

/* How many signals one page of the feed shows. */
export const FEED_PAGE_SIZE = 50;

/* Flatten the grouped feed to the cards a filter keeps, remembering which group each
   came from, then hand back one page of them re-grouped for render. Pure, so the page
   maths can be checked without a browser.

   `page` is 1-based and clamped: a filter that shrinks the list under the current page
   must not leave the reader staring at an empty feed. */
export function paginateFeed(groups, keep, page, size = FEED_PAGE_SIZE) {
  const flat = [];
  (groups || []).forEach((g) => {
    (g.cards || []).forEach((c) => {
      if (!keep || keep(c)) flat.push({ g, c });
    });
  });
  const pageCount = Math.max(1, Math.ceil(flat.length / size));
  const cur = Math.min(Math.max(1, page || 1), pageCount);
  const from = (cur - 1) * size;
  const slice = flat.slice(from, from + size);

  // re-group the slice: consecutive cards from the same group share one header
  const pageGroups = [];
  slice.forEach(({ g, c }) => {
    const tail = pageGroups[pageGroups.length - 1];
    if (tail && tail.h === g.h) tail.cards.push(c);
    else pageGroups.push({ h: g.h, s: g.s, cards: [c] });
  });

  return {
    groups: pageGroups,
    page: cur,
    pageCount,
    shown: flat.length,
    /* 1-based inclusive range, for "showing 101-150 of 429" */
    from: flat.length ? from + 1 : 0,
    to: from + slice.length,
    firstId: flat.length ? flat[0].c.id : null,
    /* which page a given card sits on -- the global search jumps straight to it */
    pageOf: (id) => {
      const at = flat.findIndex((x) => x.c.id === id);
      return at < 0 ? null : Math.floor(at / size) + 1;
    },
  };
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
      /* Stating a value and being SIZEABLE are two different things. TED publishes
         defence values in zloty, krone and koruna as well as euro, and parseCr
         converts only the currencies whose rate this build documents; those rows
         print their amount and stay out of the sum, so the subtitle names them
         rather than promising a total that quietly omits them. */
      const unconverted = open.filter((x) => x.value && parseCr(x.value) <= 0).length;
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
        ? `open tenders · ${priced.length} of ${open.length} publish a value` +
          (unconverted ? ` · ${unconverted} more in a currency not converted here` : "")
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

    /* Products explorer lists COMPETITOR products (Products.jsx builds them from the
       comp side of matchups + each competitor's own products), so the badge counts
       those — not KSSL's own SKUs, which is what it used to show (a "1" over a catalog
       of dozens). Same two sources the page reads, deduped by name. */
    const clientId = (d.client && d.client.id) || "KSSL";
    const compProds = new Set();
    Object.values(d.matchups || {}).forEach((m) => {
      const nm = (m.comp || "").replace(/.*·\s*/, "").trim();
      if (nm) compProds.add(nm.toLowerCase());
    });
    Object.entries(d.competitors || {}).forEach(([cid, co]) => {
      if (cid === clientId) return;
      (co.products || []).forEach((p) => {
        const nm = typeof p === "string" ? p : (p.name || p.n || "");
        if (nm) compProds.add(nm.toLowerCase());
      });
    });
    counts.products = compProds.size;

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
      title: "Competitor",
      cnt: `${partnerCount} companies tracked · everything the corpus holds on one rival`,
      filters: false,
    },
    products: {
      title: "Products",
      cnt: "Competitor & client products catalog across tracked defense categories",
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
    /* m-report was the only view with no entry here, which is why Layout carried a
       hardcoded "Market Report" -- and that literal was gated on a flag covering all
       four tender views, so the page labelled "Tender Pipeline" on the rail rendered
       under the heading "Market Report". */
    "m-report": {
      title: "Market Report",
      cnt: "Demand shape, spec and requirement",
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
