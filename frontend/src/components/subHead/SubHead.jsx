/* Title + count. The filter row lives in the feed's first group header (see
   FeedFilters), which is where the standalone file relocated it to on every rebuild. */
export default function SubHead({ title, count }) {
  return (
    <div className="subhead">
      <div className="left">
        <h1>{title}</h1>
        <span className="cnt">{count}</span>
      </div>
    </div>
  );
}
