/* Escaping + the source-chip helper, used by every panel.
   Every record in the generated dataset carries `srcs: [{label,url}]`. */

/* Attribute-safe: quotes too, because these land inside href="" and title="". */
export function attr(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/* Text-node escape, the `esc_` of the original. */
export function esc(s) {
  return String(s == null ? "" : s).replace(/</g, "&lt;");
}

/* For a value going into a DOUBLE-QUOTED ATTRIBUTE. esc() escapes only `<`, which is
   right for text between tags and wrong inside title="..." -- a partner label carrying
   a quote closes the attribute early and the rest of it becomes markup. The labels here
   are model output (Rheinmetall's "Skyranger" is the shape that does it), so the quote
   has to go. */
export function escAttr(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* Full escape for interpolated prose (the `_gesc`/`esc` of the gap + geo blocks). */
export function escAll(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/* The reverse of escAll, for the few fields that were escaped at WRITE time and are
   then rendered as TEXT (React JSX children escape on their own, so an already
   encoded value reaches the screen with its entity showing — `Defence &amp; Aerospace`).
   Loops because a double-escaped value ("&amp;amp;") needs two passes; the string
   shrinks every pass, so it always terminates. */
const ENTITIES = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  "#39": "'",
  nbsp: " ",
};
export function unescapeEntities(s) {
  if (s == null) return "";
  let out = String(s);
  let prev;
  do {
    prev = out;
    out = out.replace(/&(amp|lt|gt|quot|apos|#39|nbsp);/g, (_, k) => ENTITIES[k]);
  } while (out !== prev);
  return out;
}

/* Meta lines ("issuer · country · value") are built from fields the record may not
   carry. Joining the PRESENT parts is the only way a missing one cannot leave a
   dangling separator behind it. */
export function plainText(s) {
  /* For React TEXT children: strip tags AND decode entities. stripTags() escapes
     < and > for HTML interpolation, so its output shows &lt; literally in a text
     node — wrong context. This one is for JSX text. */
  return unescapeEntities(String(s == null ? "" : s).replace(/<[^>]+>/g, ""));
}

export function joinParts(parts, sep) {
  return (parts || [])
    .filter((p) => p != null && String(p).trim() !== "")
    .join(sep || " · ");
}

/* Strip the markup the dataset carries inside prose fields, for plain-text contexts
   (chat answers, report bullets). */
export function stripTags(s) {
  /* Every caller interpolates the result straight into HTML, so a bare "<" that
     was never a tag has to be neutralised too. "Leads on Weight (<14)" survived
     the tag regex (no closing ">"), then the browser read "<14)…" as a malformed
     tag and ate the value plus everything up to the next ">" — the CEO briefing
     printed "Leads on Weight (" with no figure at all. Leave & alone so already
     encoded entities are not double-escaped. */
  return String(s == null ? "" : s)
    .replace(/<[^>]+>/g, "")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/* Three distinct pages on one domain all label as that domain, so the row read
   "saab.com · saab.com · saab.com" — three chips that look like one source repeated.
   Give a repeated label the page it actually points at, and fall back to a counter
   when even the path cannot tell them apart. */
function pathHint(url) {
  const tail = String(url)
    .replace(/^https?:\/\/[^/]*/, "")
    .replace(/[?#].*$/, "")
    .split("/")
    .filter(Boolean)
    .pop();
  if (!tail) return "";
  const clean = tail.replace(/\.(html?|php|aspx?|pdf)$/i, "").replace(/[-_]+/g, " ").trim();
  return clean.length > 22 ? `${clean.slice(0, 21)}…` : clean;
}

export function srcChips(srcs, extraClass) {
  if (!srcs || !srcs.length) return "";
  const seen = {};
  const usedLabel = {};
  const out = [];
  srcs.forEach((s) => {
    if (!s || !s.url || seen[s.url]) return;
    seen[s.url] = 1;
    let lab = String(s.label || s.url)
      .replace(/^https?:\/\/(www\.)?/, "")
      .replace(/\/$/, "");
    const base = lab;
    const n = (usedLabel[base] || 0) + 1;
    usedLabel[base] = n;
    if (n > 1) {
      const hint = pathHint(s.url);
      const withHint = hint ? `${base} / ${hint}` : "";
      lab = withHint && !usedLabel[withHint] ? withHint : `${base} (${n})`;
      usedLabel[lab] = (usedLabel[lab] || 0) + 1;
    }
    if (lab.length > 34) lab = `${lab.slice(0, 33)}…`;
    // stopPropagation so a chip inside a clickable tile/row doesn't trigger its handler
    out.push(
      `<a class="srcchip" href="${attr(s.url)}" target="_blank" rel="noopener noreferrer"` +
        ` title="${attr(s.url)}" onclick="event.stopPropagation()">${attr(lab)}</a>`,
    );
  });
  return out.length
    ? `<span class="srcchips${extraClass ? ` ${extraClass}` : ""}">${out.join("")}</span>`
    : "";
}

export function srcKvRow(srcs, label) {
  const h = srcChips(srcs);
  return h
    ? `<div class="kv"><span class="k">${label || "Sources"}</span><span class="v">${h}</span></div>`
    : "";
}

/* Escape for a served field that is ALLOWED to carry inline markup -- the pipeline
   writes a partner's `mean` with <b>Threat:</b> / <b>Opening:</b> labels, and the
   drawer's synthesis path parses those very tags. Everything is escaped, then the
   bare inline tags come back: b, i, em, strong, br, with no attributes. A tag that
   carries an attribute, and any other tag, stays text -- a served string is data. */
export function escRich(s) {
  /* Balanced pairs only: an opener with an attribute stays text, and so does its
     closer, so a stray </b> can never close a legitimate bold further up. */
  return escAll(s)
    .replace(/&lt;br\s*\/?&gt;/gi, "<br>")
    .replace(/&lt;(b|i|em|strong)&gt;([\s\S]*?)&lt;\/\1&gt;/gi, "<$1>$2</$1>");
}
