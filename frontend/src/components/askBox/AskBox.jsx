import { useEffect, useRef, useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { scopedAnswer } from "../../lib/chat";

/* Overview's built-in ask box. Same engine as ScopeChat, different chrome: this one
   was already in the markup, with the signal's own suggested questions under it. */
export default function AskBox({ suggest }) {
  const { scoped, scopeEpoch } = useAppState();
  const { data } = useData();
  const [log, setLog] = useState([]);
  const [text, setText] = useState("");
  const logRef = useRef(null);
  const epoch = scopeEpoch.signal || 0;

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
    setTimeout(() => {
      const answer = scopedAnswer(data, scoped.signal, question);
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
    <div className="askbox">
      <span className="eyebrow">Ask Parallax</span>
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
      <div className="askwrap">
        <input
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") ask();
          }}
          placeholder="Interrogate this signal…"
          type="text"
          value={text}
        />
        <span className="go" onClick={() => ask()} role="button" tabIndex={-1}>
          ↵
        </span>
      </div>
      <div className="suggest">
        {(suggest || []).map((s) => (
          <span className="s" key={s} onClick={() => ask(s)} role="button" tabIndex={-1}>
            {s}
          </span>
        ))}
      </div>
    </div>
  );
}
