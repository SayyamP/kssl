import { useData } from "../../state/DataProvider";

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
        {/* `when` comes from signalDate() so the card and its detail panel cannot
            disagree about the same event. Falls back to the card’s own value. */}
        <span className="ago">{when || card.ago}</span>
      </div>
    </div>
  );
}
