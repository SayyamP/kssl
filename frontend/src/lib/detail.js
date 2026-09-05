/* The statements a signal already carries, and nobody was showing.

   serving_fill.py writes `signal_detail.lens` on every pipeline card: up to six
   propositions from the extraction layer, each rendered as

       Leonardo signed with Esercito Brasiliano — <i>&ldquo;…the article's own
       sentence…&rdquo;</i>

   The detail panel used to render them, stopped, and nothing replaced them — so the
   panel showed two fact rows and one LLM sentence while six evidence-backed statements
   sat unread in the record. The client's complaint ("at a glance … should be like fact
   which read we get whole picture about that article") is exactly that gap, and the
   cheapest honest fix is to show what is already stored rather than extract more.

   THE SHAPES THIS HAS TO SURVIVE. `lens` is not uniform across the two populations:

     * pipeline rows  [["STATEMENT", "<html>"], …]
     * reference rows have carried a bare string ("SPEC RANK"), which is truthy, has a
       `.length`, and has no `.map` — that exact value took the whole application to a
       blank page once already (see ErrorBoundary). A string is not a list of rows.
     * a row can be [label] with nothing after it, or carry an empty second cell.

   So this returns a plain array of HTML strings and never anything else. A caller that
   maps over the result cannot be handed a surprise. */
export function statementRows(lens, cap = 6) {
  if (!Array.isArray(lens)) return [];
  const out = [];
  for (const row of lens) {
    const html = Array.isArray(row) ? row[1] : row;
    if (typeof html !== "string") continue;
    const text = html.trim();
    if (!text) continue;
    out.push(text);
    if (out.length >= cap) break;
  }
  return out;
}
