/* The publisher line on an article, as a link that actually goes there.

   Reported: "News items do not consistently redirect to the original source. Each news
   item should link directly to its actual/original source URL."

   Inconsistently is right: the Geo drawer had an <a>, the Competitive profile drawer
   and the product drawer printed the publisher name as plain text. All three read the
   same field. 1,171 of the 1,177 served signal cards carry a url, so this was almost
   never a data gap -- the link existed and was not rendered.

   The six rows with no url say so, rather than looking identical to a link that does
   nothing. That distinction is the whole point of the report: a reader who clicks and
   gets no response cannot tell a missing source from a broken page. */

/* Only http(s) becomes a link. These urls come from the pipeline rather than from a
   person, but an href is a place a stray value would be honoured silently. */
export function sourceHref(u) {
  return typeof u === "string" && /^https?:\/\//i.test(u) ? u : null;
}

export default function SourceLink({ url, source, color, label = "Source Publisher" }) {
  const href = sourceHref(url);
  const name = source || "Unattributed";
  return (
    <>
      {label}:{" "}
      {href ? (
        <a
          href={href}
          rel="noopener noreferrer"
          style={{ color, fontWeight: 600, textDecoration: "underline" }}
          target="_blank"
        >
          <span className="src-dot"></span>
          {name}
        </a>
      ) : (
        <>
          <span style={{ color }}>
            <span className="src-dot"></span>
            {name}
          </span>{" "}
          <span style={{ color: "var(--d-txt-3)", fontSize: "10.5px" }}>
            (no source link on file)
          </span>
        </>
      )}
    </>
  );
}
