/* WHAT THE MAP SAYS ABOUT ONE COUNTRY -- as data, so it can be tested without Leaflet.
   GeoMap.jsx turns these objects into the tooltip's HTML and does nothing else with them.

   Everything here exists because of three faults reported on the live footprint map on
   2026-09-06. They are separate bugs with one shape: the badge asserted more than the
   rows behind it.
*/

/* 'bf' IS A WHO, NOT A WHAT.

   Reported verbatim: "why geo footprint KSSL present KSSL present written 2 time in
   india". serving.ui_config maps actLabel.bf = "KSSL present", and the badge was built
   as `${clientLabel} Present` followed by the LABELS of the client's own activity rows.
   India carries four c='bf' product rows, so the badge rendered

       KSSL Present . KSSL present / Local production

   -- the name of the company, twice, before the one activity that says anything.

   'bf' does not name an activity. It marks the row as the client's, which is the thing
   the badge's first half already says, so it can never appear in the second half. It is
   dropped by CODE, and any label that merely restates the client's name is dropped as
   well, so a later edit to the label dictionary cannot bring the echo back.

   Everything else survives: an 'lp' row still contributes "Local production", which is
   what a reader learns something from. */
export const CLIENT_ACT = "bf";

const fold = (v) =>
  String(v == null ? "" : v)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

/** True when this label says nothing the "<client> Present" half has not already said. */
export function echoesPresence(label, clientLabel) {
  const f = fold(label);
  if (!f) return true;
  const c = fold(clientLabel);
  if (!c) return false;
  return f === c || f === `${c} present` || f === `${c} presence`;
}

/** The distinct activity labels a set of footprint rows names, in row order. */
export function activityLabels(rows, actLabel) {
  const out = [];
  const seen = new Set();
  (rows || []).forEach((r) => {
    const label = r && (actLabel || {})[r.c];
    if (!label || seen.has(label)) return;
    seen.add(label);
    out.push(label);
  });
  return out;
}

/** The same, for the CLIENT's own rows: 'bf' and any self-naming label removed. */
export function ownActivityLabels(rows, actLabel, clientLabel) {
  /* READ THROUGH THE OVERWRITE. dataset.js stamps p.c = 'bf' over EVERY client
     footprint row, so by the time the badge sees them the real activity code is
     already gone: India is stored c='lp' ("Local production") and arrives here as
     'bf'. Dropping 'bf' therefore removes the echo AND the only thing the badge
     still had to say, leaving a bare "KSSL Present" on a row whose activity we do
     know. dataset.js now keeps the original in `c0`; prefer it, and fall back to
     `c` for any caller that did not come through that path. */
  return activityLabels(
    (rows || [])
      .map((r) => (r && r.c === CLIENT_ACT && r.c0 ? { ...r, c: r.c0 } : r))
      .filter((r) => r && r.c !== CLIENT_ACT),
    actLabel,
  ).filter((label) => !echoesPresence(label, clientLabel));
}

/* AN ESTIMATE MUST NOT LOOK LIKE A MEASUREMENT.

   serving.geo_presence.src holds the URL a row was read from, or the literal "syn" when
   the row is an analytical estimate rather than a sourced fact (those rows also carry
   val='estimate'). pages/competitive/Geo.jsx has always marked them -- a .syn dot and
   the words "analytical estimate" in the source line. GeoMap.jsx never read src at all,
   so an estimated presence drew the same green pin, with the same wording, as a
   presence three documents state.

   That is the house rule "not measured must not look like zero" in its other direction:
   estimated must not look like measured. The client's own footprint outside India is
   exactly this case -- the Saudi Arabia and Europe rows are both src='syn'. */
export const isEstimate = (row) => !!row && row.src === "syn";

/** How many of these rows are sourced and how many are estimates. */
export function evidenceOf(rows) {
  let sourced = 0;
  let estimated = 0;
  (rows || []).forEach((r) => (isEstimate(r) ? (estimated += 1) : (sourced += 1)));
  return {
    sourced,
    estimated,
    total: sourced + estimated,
    /* Nothing here is sourced. The whole claim is an estimate, and the badge has to
       say so in its own text rather than in a footnote nobody hovers. */
    allEstimated: estimated > 0 && sourced === 0,
  };
}

/** The wording that goes beside a presence, or null when nothing needs saying. */
export function evidenceNote(rows) {
  const ev = evidenceOf(rows);
  if (!ev.estimated) return null;
  if (ev.allEstimated)
    return ev.total === 1
      ? "analytical estimate, not a sourced row"
      : `all ${ev.total} rows are analytical estimates, not sourced`;
  return ev.estimated === 1
    ? `1 of ${ev.total} rows is an analytical estimate`
    : `${ev.estimated} of ${ev.total} rows are analytical estimates`;
}

/* THE COUNTRY BADGE.

   Returns { text, cls, estimated, note } -- never HTML, so a test can read the words.
   `cls` keeps the caller's existing "present"/"absent" classes and adds "est" when the
   presence rests only on estimates, so CSS can render it differently from a sourced one
   without the caller re-deriving the rule. */
export function presenceBadge({ clientLabel, rows, rivalCount, actLabel }) {
  const own = rows || [];
  if (!own.length) {
    return {
      text:
        rivalCount > 0
          ? `${clientLabel} Absent · Contested Market ⚠`
          : "No activity on file",
      cls: "absent",
      estimated: false,
      note: null,
    };
  }
  const ev = evidenceOf(own);
  const acts = ownActivityLabels(own, actLabel, clientLabel);
  const parts = [`${clientLabel} Present`];
  if (ev.allEstimated) parts.push("estimated, not sourced");
  if (acts.length) parts.push(acts.join(" / "));
  return {
    text: parts.join(" · "),
    cls: ev.allEstimated ? "present est" : "present",
    estimated: ev.estimated > 0,
    note: evidenceNote(own),
  };
}

/* "IS KSSL ONLY INDIA?" -- asked of this map, and the map could not answer it.

   The client has rows in three places: India, Saudi Arabia and "Europe". Only one of
   those is a plottable country. "Europe" is a continent and is deliberately not pinned
   (a point for it landed inside Poland, which is separately its own row), and the Saudi
   Arabia row is an analytical estimate. So a reader saw one green dot over India and
   read it as the whole footprint -- an answer the data does not support, produced by
   two honest rules with nothing tying them together for the client's own row.

   This states the client's footprint in words beside the map: every country it holds a
   row in, which of those are estimates, and the regional rows that exist and cannot be
   drawn. No new geography is invented -- a region stays a region. `plan` is
   lib/geoCountries.geoPlotPlan over the client's own countries. */
export function clientFootprintNote({ clientLabel, ownByCountry, plan }) {
  const own = ownByCountry || {};
  const mark = (ct) => {
    const ev = evidenceOf(own[ct] || []);
    return ev.allEstimated ? `${ct} (estimated)` : ct;
  };
  const drawn = (plan && plan.plotted ? plan.plotted : []).map((p) => p.ct);
  const regions = (plan && plan.regions ? plan.regions : []).slice();
  const unlocated = (plan && plan.unlocated ? plan.unlocated : []).slice();
  if (!drawn.length && !regions.length && !unlocated.length) return null;
  const parts = [];
  parts.push(
    drawn.length
      ? `${clientLabel} footprint: ${drawn.map(mark).join(", ")}`
      : `${clientLabel} has no footprint row in any country this map can draw`,
  );
  if (regions.length)
    parts.push(`recorded but not a country, so not pinned: ${regions.map(mark).join(", ")}`);
  if (unlocated.length)
    parts.push(`no map coordinates: ${unlocated.map(mark).join(", ")}`);
  return parts.join(" · ");
}

/* WHAT ONE COMPANY DOES IN ONE COUNTRY, for the tooltip's company list.

   `isHq` is decided by lib/geoCountries.isHeadOffice, which reads the stated origin
   column and the tidied hq -- not by a string comparison here. */
export function companyRole({ comp, rows, actLabel, clientLabel, isHq }) {
  const c = comp || {};
  const acts = c.isBf
    ? ownActivityLabels(rows, actLabel, clientLabel)
    : activityLabels(rows, actLabel);
  const parts = isHq ? ["Head office", ...acts] : acts;
  if (parts.length) return parts.join(" · ");
  return c.isBf ? `${clientLabel} presence` : "Competitor";
}
