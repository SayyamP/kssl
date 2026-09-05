/* Real per-company news, in the exact shape the news panels already render.
 *
 * Profile, Products, Geo and Partnerships each carried a hard-coded array of
 * articles with the company name substituted into a template — five invented
 * stories repeated for all 119 competitors, attributed to ET, Business Standard,
 * Moneycontrol, The Hindu BusinessLine and NDTV Profit, illustrated with Unsplash
 * stock photos. This module returns the same object shape from
 * `data.competitorNews`, which the pipeline fills from the signal feed, so the
 * panels render unchanged and every field traces to a real article.
 *
 * Nothing here writes prose. `fullText` and `impact` are the pipeline's own
 * signal_detail.what / .why, reached by joining on the article url — the one key
 * the card feed and the news table share. A field with no source stays undefined
 * and the panel's existing `{x && ...}` guard drops it, which is why the render
 * needed no edit.
 *
 * When a company has no news, this returns []. That is the intended behaviour: an
 * empty panel is honest and a populated one was not.
 */

import { formatDate } from "../utils/formatDate.js";

/* "2026-07-13" -> "13 Jul 2026". The panels print this in their `ago` slot, which
   used to hold "2 hours ago" — a freshness the fabricated rows only claimed. A
   real date is the honest thing to put there, and it is never wrong by a day the
   way a relative label drifts. One formatter for the whole app (utils/formatDate);
   this is its ISO face, kept so the call sites read as what they are. */
export function newsDate(iso) {
  if (!iso) return "";
  return formatDate(String(iso));
}

/* url -> the signal detail behind it, so an article can show what the pipeline
   read out of it rather than invented prose. Built once per dataset. */
function detailIndex(data) {
  if (data.__newsDetailIdx) return data.__newsDetailIdx;
  const byUrl = {};
  const lanes = ["competitiveCards", "marketCards", "techCards"];
  lanes.forEach((lane) => {
    (data[lane] || []).forEach((c) => {
      if (c && c.url && !byUrl[c.url]) byUrl[c.url] = (data.details || {})[c.id];
    });
  });
  try {
    Object.defineProperty(data, "__newsDetailIdx", { value: byUrl });
  } catch {
    /* frozen dataset: the index is cheap enough to rebuild */
  }
  return byUrl;
}

function shape(row, byUrl, i) {
  const d = (row.url && byUrl[row.url]) || null;
  return {
    id: row.id != null ? `news-${row.id}` : `news-${i}`,
    category: row.category || "Update",
    ago: newsDate(row.date),
    date: row.date || null,
    title: row.title,
    excerpt: row.description || undefined,
    fullText: (d && d.what) || row.description || undefined,
    impact: (d && d.why) || undefined,
    source: row.source || undefined,
    sourceUrl: row.url || undefined,
    url: row.url || undefined,
    image: row.image || undefined,
    /* The running story this article belongs to, written by news_chain.py from spans
       the extraction layer typed. Undefined on a backend whose database has not run
       the migration yet, and undefined on an article that stands alone -- both mean
       the same thing to every reader below: no trail. */
    storyKey: row.story_key || undefined,
    continuesUrl: row.continues_url || undefined,
    duplicateOfUrl: row.duplicate_of_url || undefined,
    /* The newest row leads. Nothing in the pipeline measures "trending", so the
       flag is a position, not a claim about the story. */
    isTopStory: i === 0,
  };
}

/* Every article for one competitor, newest first. `compId` is the serving key. */
export function companyNews(data, compId) {
  if (!data || !compId) return [];
  const rows = (data.competitorNews || {})[compId] || [];
  const byUrl = detailIndex(data);
  return rows.map((r, i) => shape(r, byUrl, i));
}

/* Tokens worth matching on: drops the short/generic words that would make any
   article "about" the product. "M4" and "F-22" survive; "the" and "system" do not. */
function terms(name) {
  return String(name || "")
    .toLowerCase()
    .split(/[^a-z0-9-]+/)
    .filter((t) => t.length > 2 && !STOP.has(t));
}
const STOP = new Set(["the", "and", "for", "system", "systems", "series", "mark",
                      "new", "gun", "vehicle", "defence", "defense"]);

function mentions(article, name) {
  const t = terms(name);
  if (!t.length) return false;
  const hay = `${article.title || ""} ${article.excerpt || ""} ${article.fullText || ""}`
    .toLowerCase();
  /* Every distinctive token has to appear. One shared word is a coincidence; the
     whole designator is a mention. */
  return t.every((x) => hay.includes(x));
}

/* The company's articles that actually name this product. Returns [] rather than
   falling back to the company feed — an article about a different platform is not
   news about this one, and presenting it as such is the bug we removed. */
export function productNews(data, compId, productName) {
  return companyNews(data, compId).filter((a) => mentions(a, productName));
}

/* The company's articles that actually name this country. */
export function marketNews(data, compId, country) {
  return companyNews(data, compId).filter((a) => mentions(a, country));
}

/* The company's articles that name the partner. */
export function partnerNews(data, compId, partnerLabel) {
  return companyNews(data, compId).filter((a) => mentions(a, partnerLabel));
}

/* Self-check: `node src/lib/news.js` (or import newsSelfCheck from a page). */
/* THE FEED IS A HEADLINE, NOT AN ARCHIVE.
 *
 * Profile opened six articles and grew by six on every click with no ceiling, so
 * Rheinmetall's 56 rows ended as 55 stacked cards in a 28%-wide column. Products
 * had no limit at all -- `feedProdArticles.map(...)` rendered every article naming
 * the product. Either way the page just grows downward and the sections beneath it
 * are pushed out of reach.
 *
 * So: the feed carries the newest FEED_N, and everything else -- including those
 * FEED_N, because a reader looking for one article should not have to work out
 * which surface it is on -- is listed in full below, newest first. The split is a
 * pure function so it can be tested rather than eyeballed.
 */
export const FEED_N = 6;

export function feedSplit(articles, n = FEED_N) {
  const all = Array.isArray(articles) ? articles : [];
  return { feed: all.slice(0, n), rest: all.slice(n), all, total: all.length };
}

/* THE TRAIL.
   A company's articles arrive newest-first and flat, so three PAC-3 stories in a
   fortnight read as three unrelated events and the same wire piece from four outlets
   reads as four. news_chain.py says which of them are one running story; this folds
   that into the shape the feed renders.

   Only the NEWEST article of a story carries the trail -- repeating it on every card
   would print the same thread three times in one column. The older members leave the
   feed and stay reachable through it, and the full News section below still lists
   every one of them, because a reader hunting one article should not have to know
   which surface it is on.

   A DUPLICATE IS NOT A DEVELOPMENT. A syndicated reprint folds into the article it
   copies as `alsoIn`; calling it a continuation would invent a development that never
   happened. */
export function collapseThreads(articles) {
  const all = Array.isArray(articles) ? articles : [];
  const byUrl = {};
  all.forEach((a) => { if (a.url) byUrl[a.url] = a; });

  // Fold reprints into what they reprint. A duplicate whose original is not in this
  // list stays a top-level article: hiding it would lose it entirely.
  const alsoIn = {};
  const folded = new Set();
  all.forEach((a) => {
    const orig = a.duplicateOfUrl;
    if (orig && byUrl[orig] && orig !== a.url) {
      (alsoIn[orig] = alsoIn[orig] || []).push(a);
      folded.add(a.url);
    }
  });

  const kept = all.filter((a) => !folded.has(a.url));
  // Within a story, the first survivor in the incoming (newest-first) order is the
  // head; the rest become its trail rather than separate cards.
  const headOf = {};
  kept.forEach((a) => {
    if (!a.storyKey) return;
    if (!(a.storyKey in headOf)) headOf[a.storyKey] = a.url;
  });

  return kept
    .filter((a) => !a.storyKey || headOf[a.storyKey] === a.url)
    .map((a) => {
      /* A trail member can have reprints of its own, and they have to travel with
         it: attaching alsoIn only to the head made a reprint of a trailed article
         unreachable from anywhere in the feed. */
      const trail = a.storyKey
        ? kept
            .filter((b) => b.storyKey === a.storyKey && b.url !== a.url)
            .map((b) => (alsoIn[b.url] ? { ...b, alsoIn: alsoIn[b.url] } : b))
        : [];
      const also = alsoIn[a.url] || [];
      return (trail.length || also.length) ? { ...a, trail, alsoIn: also } : a;
    });
}

export function newsSelfCheck() {
  const data = {
    competitorNews: {
      saab: [
        { id: 1, title: "Saab receives Carl-Gustaf M4 order", description: "so what",
          source: "saab.com", date: "2026-07-13", category: "Artillery",
          url: "https://saab.com/a", image: "https://saab.com/i.jpg" },
        { id: 2, title: "Saab opens a plant in Brazil", description: "d2",
          source: "p.com", date: "2026-06-02", category: "Industry",
          url: "https://p.com/b" },
      ],
    },
    competitiveCards: [{ id: "pl_1", url: "https://saab.com/a" }],
    details: { pl_1: { what: "the long read", why: "why it matters" } },
  };
  const out = [];
  const t = (name, ok) => { if (!ok) out.push(name); };

  const n = companyNews(data, "saab");
  t("two rows for the company", n.length === 2);
  t("newest leads", n[0].id === "news-1" && n[0].isTopStory === true);
  t("second is not a top story", n[1].isTopStory === false);
  t("date is rendered, not relative", n[0].ago === "13 Jul 2026");
  t("publisher survives", n[0].source === "saab.com");
  t("fullText comes from the joined detail", n[0].fullText === "the long read");
  t("impact comes from the joined detail", n[0].impact === "why it matters");
  t("no detail -> excerpt is the body", n[1].fullText === "d2");
  t("no detail -> no invented impact", n[1].impact === undefined);
  t("missing image stays undefined", n[1].image === undefined);
  t("unknown company is empty, not a template",
    companyNews(data, "nobody").length === 0 && companyNews(data, null).length === 0);

  t("product filter keeps the matching article",
    productNews(data, "saab", "Carl-Gustaf M4").length === 1);
  t("product filter drops the other one",
    productNews(data, "saab", "Gripen").length === 0);
  t("a generic word alone does not match",
    productNews(data, "saab", "system").length === 0);
  t("market filter matches the country named in the story",
    marketNews(data, "saab", "Brazil").length === 1);
  t("market filter is empty rather than wrong",
    marketNews(data, "saab", "Peru").length === 0);
  t("newsDate passes through what it cannot parse", newsDate("soon") === "soon");
  t("newsDate on nothing is empty", newsDate(null) === "");

  return out;
}
