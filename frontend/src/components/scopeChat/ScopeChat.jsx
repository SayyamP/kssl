import { useEffect, useRef, useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { scopedAnswer } from "../../lib/chat";

/* The sticky bar at the bottom of a white detail panel. It answers only about that
   panel's selection, and its log clears when the selection changes — the epoch
   counter in AppState is what tells it that happened. */
export default function ScopeChat({ scopeKey, placeholder }) {
  const { scoped, scopeEpoch } = useAppState();
  const { data } = useData();
  const [log, setLog] = useState([]);
  const [text, setText] = useState("");
  const logRef = useRef(null);
  const epoch = scopeEpoch[scopeKey] || 0;

  useEffect(() => {
    setLog([]);
  }, [epoch]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const ask = (value) => {
    const question = (value ?? text).trim();
    if (!question) return;
    setText("");
    setLog((prev) => [...prev, { q: question, a: null }]);
    // the brief pause is the original's; it reads as thinking rather than a lookup
    setTimeout(() => {
      const answer = scopedAnswer(data, scoped[scopeKey], question);
      setLog((prev) => {
        const next = prev.slice();
        for (let i = next.length - 1; i >= 0; i--)
          if (next[i].a === null) {
            next[i] = { ...next[i], a: answer };
            break;
          }
        return next;
      });
    }, 360);
  };

  return (
    <div className="scopechat" data-key={scopeKey}>
      <div className="sc-log" ref={logRef} style={{ display: log.length ? "" : "none" }}>
        {log.map((row, i) => (
          <div key={`${row.q}-${i}`}>
            <div className="sc-q">{row.q}</div>
            {row.a === null ? (
              <div className="sc-a sc-typing">…</div>
            ) : (
              <div className="sc-a" dangerouslySetInnerHTML={{ __html: row.a }} />
            )}
          </div>
        ))}
      </div>
      <div className="sc-bar">
        <span className="sc-spark">✦</span>
        <input
          className="sc-input"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") ask();
          }}
          placeholder={placeholder}
          type="text"
          value={text}
        />
        <button className="sc-send" onClick={() => ask()} type="button">
          Ask
        </button>
      </div>
    </div>
  );
}
