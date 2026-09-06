import { useData } from "../../state/DataProvider";
import { NO_DATE_LABEL, SEVERITY_UNASSESSED_LABEL } from "../../lib/overview.js";

/* One row in the overview feed. `title` and `sowhat` carry markup from the dataset
   (bolded figures), so they are injected rather than escaped.

   `card.meta` ("Artillery · Hanwha Defense USA · from bench") is deliberately NOT
   rendered — the operator asked for title and description only. The field stays on the
   card because buildFeed's `category` sort orders on it (lib/overview.js). */
export default function SignalCard({ card, dirWord, selected, fresh, onSelect, when }) {
  const { data } = useData();
  return (
    <div
      className={`alert${selected ? " sel" : ""}${fresh ? " fresh" : ""}`}
      data-dir={card.dir}
      data-id={card.id}
      onClick={() => onSelect(card.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(card.id);
        }
      }}
    >
      <div className="gut">
        <span className={`sig ${card.dir}`} />
        <span className="rank">{card.rank}</span>
      </div>
      <div className="body">
        <div className="ttl" dangerouslySetInnerHTML={{ __html: card.title }} />
        <div className="sowhat" dangerouslySetInnerHTML={{ __html: card.sowhat }} />
        {card.match && card.match.length > 0 && card.match[0].n && (
          <div className="koel-prod-highlight-row">
            <span className="kph-label">{data.client?.short || "KSSL"} Product:</span>
            <span className="kph-val">{card.match[0].n}</span>
          </div>
        )}
      </div>
      <div className="aside">
        <span className={`dirtag ${card.dir}`}>{dirWord}</span>
        {/* SEVERITY, AND THE ABSENCE OF ONE, LOOK DIFFERENT.
            The feed is sequenced by this value, so it has to be legible on the row that
            it moved -- a reader cannot check an order whose key is invisible. A card the
            pipeline could not grade reads "severity not assessed", greyed, rather than
            borrowing the word "low", which is a measurement we did not make. `title`
            carries the grounds, so the badge can be interrogated rather than believed. */}
        {card.dir === "threat" ? (
          <span
            className={`sevtag ${card.severity || "unassessed"}`}
            title={card.impactLabel || ""}
          >
            {card.severityLabel || SEVERITY_UNASSESSED_LABEL}
          </span>
        ) : null}
        {/* `when` comes from signalDate() so the card and its detail panel cannot
            disagree about the same event. Falls back to the card’s own value.

            AND SAYS SO WHEN THERE IS NONE. An undated card sorts to the bottom of its
            severity band (dateVal("") is 0, and the date key is descending) -- printing
            an empty corner alongside that made it look like a rendering slip rather than
            a fact about the article. */}
        <span className="ago">{when || card.ago || NO_DATE_LABEL}</span>
      </div>
    </div>
  );
}
