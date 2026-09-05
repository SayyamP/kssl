/* The route: which pillar, which view. One resolver for the three places a route
   comes from -- the hash of a pasted or hand-edited link, the route saved from the
   last visit, and the default -- so every one of them lands on a page.

   Before this, getInitialAppState validated the PILLAR and never the view: a link
   carrying #v=nonsense (a typo, a view renamed in a later build) booted into a
   permanently blank pane -- rail drawn, no row active, nothing beneath the heading --
   and the same route was then saved to localStorage, so the blank pane came back on
   every later visit until the reader clicked a rail row. Pure, so it is tested under
   node (test_route.mjs); AppState.jsx is the only caller. */

export const PILLARS = ["competitive", "market", "technology"];
export const PILLAR_LABEL = {
  competitive: "Competitive",
  market: "Market",
  technology: "Technology",
};

/* Which rail item each pillar opens on, and the pillar each rail belongs to. */
export const RAIL = {
  /* `gap-competitive` is ARCHIVED, not deleted: it is off the rail but Layout still
     routes it, so a saved route or a pasted #v=gap-competitive link still resolves.
     Same for `awarded-tenders` / `closed-tenders`, which the Market overview now
     carries as tabs. Those live in ARCHIVED below, so the resolver knows them. */
  competitive: [
    { view: "overview", label: "Overview", ix: "grid", overview: true },
    { view: "profile", label: "Competitor", ix: "01" },
    { view: "products", label: "Products", ix: "02" },
    { view: "positioning", label: "Positioning", ix: "03" },
    { view: "partnerships", label: "Partnerships", ix: "04" },
    { view: "geo", label: "Geo Footprint", ix: "05" },
    { view: "patents-comp", label: "Patents", ix: "06" },
  ],
  market: [
    /* Overview is the SIGNAL FEED again, as the other two pillars' overviews are — the
       tender report that briefly occupied this slot is its own tab below. An overview
       that reads differently from every other pillar's overview is not an overview. */
    { view: "m-overview", label: "Overview", ix: "grid", overview: true },
    { view: "m-report", label: "Market Report", ix: "01" },
    { view: "tender", label: "Tender Pipeline", ix: "02" },
  ],
  technology: [
    { view: "t-overview", label: "Overview", ix: "grid", overview: true },
    { view: "innovation", label: "Innovation Pipeline", ix: "01" },
  ],
};

/* Off the rail, still routed by Layout. */
export const ARCHIVED = {
  competitive: ["gap-competitive"],
  market: ["awarded-tenders", "closed-tenders"],
  technology: [],
};

export const DEFAULT_ROUTE = { pillar: "competitive", view: "overview" };

const OVERVIEW_VIEWS = new Set(["overview", "m-overview", "t-overview"]);
export const isOverview = (view) => OVERVIEW_VIEWS.has(view);

/* The pillar a view belongs to, or null for a view no pillar knows. */
export function pillarOfView(view) {
  for (const p of PILLARS) {
    if (RAIL[p].some((r) => r.view === view) || ARCHIVED[p].includes(view)) return p;
  }
  return null;
}

export const overviewOf = (pillar) => RAIL[pillar][0].view;

/* {pillar, view} from a hash, or null when the hash carries no route at all -- so a
   plain "#section" anchor is not mistaken for navigation. Never validates; that is
   resolveRoute's job. */
export function parseRoute(hash) {
  if (!hash || typeof hash !== "string") return null;
  const q = hash.replace(/^#/, "");
  if (!q.includes("p=") && !q.includes("v=")) return null;
  const params = new URLSearchParams(q);
  return { pillar: params.get("p") || "", view: params.get("v") || "" };
}

/* A route that always names a page. The view decides the pillar when it belongs to
   one (a link to `tender` is a link to the Market pillar whatever `p` says); an
   unknown view lands on the overview of the pillar named, or of the pillar saved. */
function settle(route) {
  if (!route) return null;
  const owner = pillarOfView(route.view);
  if (owner) return { pillar: owner, view: route.view };
  if (PILLARS.includes(route.pillar)) return { pillar: route.pillar, view: overviewOf(route.pillar) };
  return null;
}

export function resolveRoute(hash, saved) {
  return settle(parseRoute(hash)) || settle(saved && typeof saved === "object" ? saved : null) || DEFAULT_ROUTE;
}
