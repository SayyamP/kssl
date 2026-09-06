/* WHAT THE LETTERS STAND FOR -- the full name behind an abbreviated competitor.
 *
 * Reported on the Profile page: "there are many competitor names in abbreviation, write
 * their full name also both in list and in company detail." Twelve of the 43 served
 * names carry an initialism -- AWEIL, BAE, IDV, IWI, KNDS, KONGSBERG, MBDA, NORINCO,
 * PLR, RTX, SIG, SSS.
 *
 * THE FINDING THAT SHAPED THIS FILE: most of them do not expand any more.
 *
 * KNDS, RTX and BAE Systems were each checked against the company's OWN site, and none
 * of the three expands its letters anywhere on it -- they are legal names now, not
 * initialisms. "RTX = Raytheon Technologies" would be a false statement twice over: it
 * is a FORMER name, and this roster carries a separate Raytheon row, so writing it here
 * would assert that two rostered rivals are one company. An abbreviation that no longer
 * stands for anything is a real answer and is recorded as one, so the page can stay
 * silent about it for a sourced reason rather than look like a gap in the data.
 *
 * PROVENANCE. Every entry carries `src`. Two kinds:
 *   - a URL, read from the company's own site (the house rule: the official site or a
 *     tier-1 independent source, never Wikipedia or Wikidata);
 *   - "workbook", the client-supplied competitor master
 *     (Defence_Competitor_MASTER_DATASET_CORRECTED_2026-09-06, COMPANY DIRECTORY sheet,
 *     "Source Entity Label" column), resolved onto roster ids by the repo's OWN matcher,
 *     competitor_portfolio.match_companies, rather than by hand.
 *
 * An entry with no `src` is not published -- see nameOf(). There is deliberately no
 * fallback that guesses an expansion from capital letters.
 *
 * WHAT WAS LEFT OUT, AND WHY. These are decisions, not omissions:
 *   knds        the workbook resolved it to "KNDS Germany", which is a SUBSIDIARY, not
 *               the group this roster row is. Publishing it would relabel the group as
 *               one of its own national arms. (match_companies is built to refuse an
 *               ambiguous name; this one is not ambiguous by its rule, only wrong.)
 *   rtx         "RTX / Raytheon" -- see above.
 *   kongsberg   "Kongsberg Defence & Aerospace" is the defence DIVISION; the rostered
 *               entity is the group. Different scope, so not a full name for this row.
 *   hanwha      "Hanwha Aerospace / Hanwha Group Defence" is an alternatives list, not
 *               a name.
 *   mbda        mbda-systems.com returns 403 to us, so nothing is sourced. Unknown is
 *               left unknown.
 *   aerovironment, israel-aerospace-industries, larsen-toubro
 *               the workbook label only appends the company's OWN initials -- "(AV)",
 *               "(IAI)", "(L&T)" -- which is the abbreviation, not the expansion of it.
 */

/* `expands` what the initialism stands for, in words.
   `full`    the registered / full entity name.
   `note`    a former name or origin -- true, and NOT a expansion of the letters.
   `src`     URL, or "workbook". Required. */
export const COMPANY_NAMES = {
  /* -- the letters genuinely stand for something, each read off the company's site -- */
  aweil: {
    expands: "Advanced Weapons and Equipment India Limited",
    src: "https://aweil.in/",
  },
  iwi: {
    expands: "Israel Weapon Industries",
    src: "https://iwi.net/about-us/",
  },
  idv: {
    expands: "Iveco Defence Vehicles",
    src: "workbook",
  },
  norinco: {
    expands: "China North Industries Group",
    src: "workbook",
  },

  /* -- checked, and the letters do not expand. Sourced silence, not missing data. -- */
  knds: { noExpansion: true, src: "https://knds.com/" },
  rtx: { noExpansion: true, src: "https://www.rtx.com/who-we-are" },
  "bae-systems": { noExpansion: true, src: "https://www.baesystems.com/en/our-company/about-us" },

  /* SSS is not expanded on the company's own site either, but the site does state where
     the name comes from, which is the useful half of the answer. It is a `note`, not an
     `expands`: "Stumpp Schuele & Somappa" is the parent, and asserting the three S's
     stand for it would be inventing a fact the source does not carry. */
  "sss-defence": {
    note: "defence division of Stumpp Schuele & Somappa, established 2017",
    src: "https://www.sssdefence.com/",
  },

  /* -- full / registered entity names, from the client's competitor master -- */
  adani: { full: "Adani Defence & Aerospace", src: "workbook" },
  anduril: { full: "Anduril Industries", src: "workbook" },
  "bharat-dynamics": { full: "Bharat Dynamics Limited", src: "workbook" },
  kalashnikov: { full: "Kalashnikov Concern", src: "workbook" },
  mahindra: { full: "Mahindra Defence Systems Limited", src: "workbook" },
  "munitions-india": { full: "Munitions India Limited", src: "workbook" },
  patria: { full: "Patria Oyj", src: "workbook" },
  poongsan: { full: "Poongsan Corporation", src: "workbook" },
  "premier-explosives": { full: "Premier Explosives Limited", src: "workbook" },
  roshel: { full: "Roshel Inc.", src: "workbook" },
  saab: { full: "Saab AB", src: "workbook" },
  "sig-sauer": { full: "SIG SAUER, Inc.", src: "workbook" },
  supacat: { full: "Supacat Limited", src: "workbook" },
  "tata-advanced-systems": { full: "Tata Advanced Systems Limited", src: "workbook" },
  "uvision-air": { full: "UVision Air Ltd.", src: "workbook" },

  /* A joint venture. The parents are the informative part and the workbook states them;
     what the three letters stand for is NOT stated anywhere we can reach -- the domain
     plrsystems.com is now a parked "for sale" page, so the company has no live site. */
  "plr-systems": {
    full: "PLR Systems Pvt Ltd",
    note: "Adani and IWI joint venture",
    src: "workbook",
  },

  /* A rename, not an abbreviation: the rostered "Nexter" is now KNDS France. */
  nexter: { full: "KNDS France", note: "formerly Nexter", src: "workbook" },
};

const WORDS = /[A-Za-z&]+/g;
const JOINERS = new Set(["AND", "OF", "THE", "FOR"]);

/** The all-caps tokens in a name -- the ones a reader cannot decode. */
export function initialisms(name) {
  const out = [];
  for (const tok of String(name == null ? "" : name).match(WORDS) || []) {
    if (tok.length < 2 || JOINERS.has(tok.toUpperCase())) continue;
    if (tok === tok.toUpperCase() && /^[A-Za-z]+$/.test(tok)) out.push(tok);
  }
  return out;
}

/** Does this served name contain something a reader would need expanded? */
export const isAbbreviated = (name) => initialisms(name).length > 0;

const clean = (s) => String(s == null ? "" : s).replace(/&amp;/g, "&").trim();

/* What to publish for one competitor. Returns null when there is nothing SOURCED to
   say -- the caller renders nothing rather than a blank row, so an unknown never
   appears as an empty value the reader could mistake for "no full name exists". */
export function nameOf(cid, servedName) {
  const e = COMPANY_NAMES[cid];
  if (!e || !e.src) return null;
  const short = clean(servedName);
  const full = clean(e.expands || e.full);
  /* A "full name" identical to the short one tells the reader nothing. */
  if (full && full.toLowerCase() === short.toLowerCase()) return null;
  if (!full && !e.note && !e.noExpansion) return null;
  return {
    full: full || "",
    note: clean(e.note),
    /* True only where the letters were checked and genuinely stand for nothing. */
    noExpansion: !!e.noExpansion && !full,
    src: e.src,
    fromWorkbook: e.src === "workbook",
  };
}

/* The one line the LIST shows under the short name. Only a real expansion or a fuller
   entity name earns a line there; a note alone ("formerly ...") is detail-pane material
   and would make the list say something other than the company's name. */
export function listLine(cid, servedName) {
  const n = nameOf(cid, servedName);
  return n && n.full ? n.full : "";
}

/* The DETAIL row: full name, with the note and the sourced no-expansion case spelled
   out in words rather than left blank. */
export function detailLine(cid, servedName) {
  const n = nameOf(cid, servedName);
  if (!n) return "";
  if (n.full) return n.note ? `${n.full} — ${n.note}` : n.full;
  if (n.note) return n.note;
  return "not an abbreviation — the letters do not stand for anything";
}
