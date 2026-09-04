/* Global search over the dataset already in memory.
 *
 * Pure: (data, query) -> grouped hits, each carrying the route that opens it. The top
 * bar renders the result; nothing here touches the DOM, which is why
 * test_global_search.mjs can exercise it under plain node.
 *
 * The search bar had been reduced to a live filter on whichever page was open, so on
 * a page with nothing to filter (Innovation, Geo, Patents) typing did nothing, and no
 * page ever said "no results". This searches every store the app serves --
 * competitors, products, signals on all three pillars, tenders, innovations -- and an
 * empty result is a value the UI must state, not an absent panel.
 *
 * No backend, no index: the corpus is a few thousand rows and a substring scan of it
 * is well under a frame. */
import { bucketTenders } from "./overview.js";

export const SEARCH_MIN_CHARS = 2;

/* how many of each group the popover lists; the group's `count` is always the whole
   match, so "showing 8 of 264" can be printed */
const DEFAULT_LIMITS = { competitors: 5, products: 5, signals: 8, tenders: 5, innovations: 5 };

const GROUP_LABEL = {
  competitors: "Competitors",
  products: "Products",
  signals: "Signals & Intel",
  tenders: "Tenders",
  innovations: "Innovations",
};

const text = (v) => (v == null ? "" : String(v));
/* the innovation body and the matchup reason carry <b> tags; a reader cannot search for
   markup, and must not be able to match on it either */
const plain = (v) => text(v).replace(/<[^>]*>/g, " ");
const norm = (s) => s.toLowerCase();

function tokensOf(query) {
  return norm(text(query).trim()).split(/\s+/).filter(Boolean);
}

/* every token must appear somewhere in the haystack: a two-word query narrows */
function matches(tokens, fields) {
  const hay = norm(fields.map(plain).join(" "));
  return tokens.every((t) => hay.includes(t));
}

function productName(label) {
  /* "KNDS · CAESAR 6x6" -> "CAESAR 6x6"; a label with no separator is the name */
  const s = text(label);
  const at = s.lastIndexOf("·");
  return (at >= 0 ? s.slice(at + 1) : s).trim();
}

export function searchDataset(data, query, limits = {}) {
  const d = data || {};
  const q = text(query).trim();
  const tokens = tokensOf(q);
  const lim = { ...DEFAULT_LIMITS, ...limits };
  const base = { query: q, total: 0, groups: [], tooShort: false };
  if (q.length < SEARCH_MIN_CHARS || !tokens.length) return { ...base, tooShort: q.length > 0 };

  const clientId = (d.client && d.client.id) || "KSSL";
  const groups = {};
  const add = (key, hit) => {
    (groups[key] = groups[key] || []).push(hit);
  };

  /* competitors: name, sector, hq and the serving key */
  Object.entries(d.competitors || {}).forEach(([cid, c]) => {
    if (!c) return;
    if (matches(tokens, [c.name, c.sector, c.hq, cid])) {
      add("competitors", {
        key: `comp:${cid}`,
        title: text(c.name) || cid,
        meta: text(c.sector),
        target: { pillar: "competitive", view: "profile", payload: { cid } },
      });
    }
  });

  /* products: the rival side and the client side of every matchup, plus the roster's
     own product lists.

     A matchup product opens its POSITIONING dossier, keyed by the matchup id, which
     always resolves. It does not open the Products catalogue: that page joins a
     matchup to a roster company by display name, and a maker with no roster row (68
     of 82 in the reference dataset) has no catalogue to open -- the reader would land
     on a page that does not show what they picked. Roster-listed products carry the
     serving key and do open the catalogue. */
  const seenProduct = new Set();
  Object.entries(d.matchups || {}).forEach(([matchupId, m]) => {
    if (!m) return;
    const rival = productName(m.comp);
    const maker = text(m.compBy) || text(m.comp).split("·")[0].trim();
    if (rival && matches(tokens, [rival, maker, m.cat])) {
      const k = norm(`${maker}|${rival}`);
      if (!seenProduct.has(k)) {
        seenProduct.add(k);
        add("products", {
          key: `prod:${k}`,
          title: rival,
          meta: [maker, text(m.cat)].filter(Boolean).join(" · "),
          target: { pillar: "competitive", view: "positioning", payload: { matchupId } },
        });
      }
    }
    const own = productName(m.bf);
    if (own && own !== "KSSL present" && matches(tokens, [own, m.cat, clientId])) {
      const k = norm(`${clientId}|${own}`);
      if (!seenProduct.has(k)) {
        seenProduct.add(k);
        add("products", {
          key: `prod:${k}`,
          title: own,
          meta: [(d.client && d.client.short) || clientId, text(m.cat)].filter(Boolean).join(" · "),
          target: { pillar: "competitive", view: "positioning", payload: { matchupId } },
        });
      }
    }
  });
  Object.entries(d.competitors || {}).forEach(([cid, c]) => {
    (c && Array.isArray(c.products) ? c.products : []).forEach((p) => {
      const obj = typeof p === "string" ? { name: p } : p || {};
      const name = text(obj.name || obj.n).trim();
      if (!name) return;
      const maker = text(c.name) || cid;
      if (matches(tokens, [name, maker, obj.category])) {
        const k = norm(`${maker}|${name}`);
        if (seenProduct.has(k)) return;
        seenProduct.add(k);
        add("products", {
          key: `prod:${k}`,
          title: name,
          meta: [maker, text(obj.category)].filter(Boolean).join(" · "),
          target: { pillar: "competitive", view: "products", payload: { cid, productName: name } },
        });
      }
    });
  });

  /* signals: each card routes to the pillar whose feed actually lists it */
  [
    ["competitive", "overview", d.competitiveCards],
    ["market", "m-overview", d.marketCards],
    ["technology", "t-overview", d.techCards],
  ].forEach(([pillar, view, cards]) => {
    (cards || []).forEach((card) => {
      if (!card) return;
      if (matches(tokens, [card.title, card.company, card.tags, card.sowhat, card.meta])) {
        add("signals", {
          key: `sig:${pillar}:${card.id}`,
          title: text(card.title),
          meta: text(card.company),
          target: { pillar, view, payload: { cardId: card.id } },
        });
      }
    });
  });

  /* tenders: routed to the tab that holds them -- an awarded tender is not on the open
     pipeline, and Tenders.jsx only finds a pending title inside its own tab's scope */
  const tenders = d.tenders || [];
  const { awarded, closed } = bucketTenders(tenders);
  const awardedSet = new Set(awarded);
  const closedSet = new Set(closed);
  tenders.forEach((t) => {
    if (!t) return;
    if (matches(tokens, [t.title, t.issuer, t.cat, t.country])) {
      const view = awardedSet.has(t) ? "awarded-tenders" : closedSet.has(t) ? "closed-tenders" : "tender";
      add("tenders", {
        key: `tender:${t.id != null ? t.id : t.title}`,
        title: text(t.title),
        meta: [text(t.issuer) || text(t.cat), text(t.country)].filter(Boolean).join(" · "),
        target: { pillar: "market", view, payload: { tenderTitle: t.title } },
      });
    }
  });

  /* innovations: keyed by domain so the page can open the right tab first */
  const catName = (id) => {
    const c = (d.techCats || []).find((x) => x && x.id === id);
    return c ? text(c.name) : text(id);
  };
  Object.entries(d.innovations || {}).forEach(([catId, rows]) => {
    (rows || []).forEach((iv) => {
      if (!iv) return;
      if (matches(tokens, [iv.t, iv.driver, iv.body, iv.whatsNew, catName(catId)])) {
        add("innovations", {
          key: `inn:${catId}:${iv.t}`,
          title: text(iv.t),
          meta: [catName(catId), text(iv.driver)].filter(Boolean).join(" · "),
          target: { pillar: "technology", view: "innovation", payload: { catId, title: iv.t } },
        });
      }
    });
  });

  const out = Object.keys(GROUP_LABEL)
    .filter((key) => groups[key] && groups[key].length)
    .map((key) => ({
      key,
      label: GROUP_LABEL[key],
      count: groups[key].length,
      hits: groups[key].slice(0, lim[key]),
    }));
  return { ...base, groups: out, total: out.reduce((n, g) => n + g.count, 0) };
}
