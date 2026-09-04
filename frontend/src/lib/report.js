/* The view report behind the three header actions: Copy Summary, Export JSON, Print.
 *
 * Each page publishes ONE object describing what it is showing --
 *
 *   { title, subtitle, sections: [{ h, rows }], payload }
 *
 * where a row is either a [label, value] pair or a plain string, and `payload` is the
 * page's own data as it holds it. Copy renders the sections as text, Print renders them
 * as a sheet, Export writes `payload`. One description, three outputs, so the three
 * buttons can never disagree about what the page contains.
 *
 * Before this the actions read `overviewConfig[pillar].cards` on every view: on the
 * Products page "Copy Summary" copied five overview signals and "Export JSON" wrote ten
 * of them plus two counts, neither of which was the product report on screen. That is
 * the fault behind FE 16 / FE 26 / FE 27.
 *
 * Pure: no DOM, so it can be checked under node. */

const HDR = "137PARALLAX INTELLIGENCE BRIEF";

/* the dataset's own strings carry <b> tags; a text brief must not */
export function plainText(v) {
  return String(v == null ? "" : v)
    .replace(/<[^>]*>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

export function rowText(row) {
  if (Array.isArray(row)) {
    const [k, v] = row;
    const val = plainText(v);
    return val ? `${plainText(k)}: ${val}` : plainText(k);
  }
  return plainText(row);
}

/* `meta` is what the header knows: pillar label, view id, the count line, the date.
   A view that published nothing still gets a truthful brief: the heading, the count,
   and a line saying no summary is published -- never another view's content. */
export function reportText(report, meta = {}) {
  const r = report || {};
  const lines = [HDR];
  const head = [
    meta.pillar ? `Pillar: ${meta.pillar}` : null,
    (r.title || meta.title) ? `View: ${plainText(r.title || meta.title)}` : null,
    meta.date ? `Date: ${meta.date}` : null,
  ].filter(Boolean);
  if (head.length) lines.push(head.join(" | "));
  if (meta.count) lines.push(`Status: ${plainText(meta.count)}`);
  if (r.subtitle) lines.push(plainText(r.subtitle));
  const sections = (r.sections || []).filter((s) => s && (s.rows || []).length);
  if (!sections.length) {
    lines.push("", "This view publishes no summary. Nothing else is held for it here.");
    return lines.join("\n");
  }
  sections.forEach((s) => {
    lines.push("", `--- ${plainText(s.h || "").toUpperCase()} ---`);
    (s.rows || []).forEach((row) => lines.push(rowText(row)));
  });
  return lines.join("\n");
}

/* the export is the page's own payload under a small envelope; nothing is added to it */
export function reportRecord(report, meta = {}) {
  const r = report || {};
  return {
    generated: meta.iso || null,
    pillar: meta.pillarKey || null,
    view: meta.view || null,
    title: plainText(r.title || meta.title || ""),
    count: plainText(meta.count || ""),
    sections: (r.sections || []).map((s) => ({
      h: plainText(s.h || ""),
      rows: (s.rows || []).map((row) =>
        Array.isArray(row) ? [plainText(row[0]), plainText(row[1])] : plainText(row),
      ),
    })),
    payload: r.payload == null ? null : r.payload,
  };
}

export function reportFilename(view, iso) {
  const day = String(iso || "").slice(0, 10) || "undated";
  const slug = String(view || "view").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `parallax-${slug || "view"}-${day}.json`;
}
