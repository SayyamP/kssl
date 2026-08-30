import { useEffect, useMemo, useRef, useState } from "react";
import { useAppState } from "../../state/AppState";
import { useData } from "../../state/DataProvider";
import { buildKnowledgeBase, groundedAnswer } from "../../lib/chat";

/* The floating cross-pillar assistant. It reads the current selection from AppState
   (whatever panel last set it) and answers from the whole corpus, not just that
   panel — which is the difference between it and ScopeChat. */
export default function MalloryChat() {
  const { chatCtx } = useAppState();
  const { data } = useData();
  const [collapsed, setCollapsed] = useState(true);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const clientShort = data.client?.short || "KSSL";
  const clientName = data.client?.name || "the client";

  const [log, setLog] = useState([
    {
      who: "bot",
      html:
        `I can connect intelligence across Competitive, Market, and Technology. Select anything in a panel and ask me about it — for example, which rivals are active in a market, who leads a technology area, or how a tender maps to ${clientShort}'s product range.`,
    },
  ]);
  const logRef = useRef(null);
  const inputRef = useRef(null);

  // the knowledge base is a projection of the corpus; build it once per dataset
  const kb = useMemo(() => buildKnowledgeBase(data), [data]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log, collapsed]);

  const chips = chatCtx.selection
    ? [
        "Who are the competitors here?",
        "How does this map to other pillars?",
        `What does the data show for ${clientShort}?`,
      ]
    : data.chatSuggest && data.chatSuggest.overview && data.chatSuggest.overview.length >= 3
      ? data.chatSuggest.overview.slice(0, 3)
      : [
          `Which rivals beat ${clientShort} on key specs?`,
          "Which markets are rivals active in?",
          `Which tenders fit ${clientShort} best?`,
        ];

  const submit = (value) => {
    const question = (value ?? text).trim();
    if (!question || busy) return;
    setText("");
    setBusy(true);
    setLog((prev) => [...prev, { who: "user", html: question.replace(/</g, "&lt;") }, { who: "typing" }]);
    // brief, natural "thinking" delay — the answer itself is computed locally
    setTimeout(
      () => {
        let answer;
        try {
          answer = groundedAnswer(data, question, {
            pillar: chatCtx.view,
            data: chatCtx.selection ? { title: chatCtx.selection } : null,
          });
        } catch (e) {
          answer =
            "I couldn't process that one — try rephrasing, or ask about a competitor, market, category, or tender.";
        }
        setLog((prev) => [...prev.filter((m) => m.who !== "typing"), { who: "bot", html: answer }]);
        setBusy(false);
        if (inputRef.current) inputRef.current.focus();
      },
      420 + Math.random() * 380,
    );
  };

  return (
    <div className={`mchat${collapsed ? " collapsed" : ""}`} id="mallory-chat">
      <button className="mchat-toggle" onClick={() => setCollapsed(false)} type="button">
        <span className="mchat-spark">◆</span>
        <span className="mchat-toggle-lab">Ask Parallax</span>
      </button>
      <div className="mchat-window">
        <div className="mchat-head">
          <div className="mchat-head-l">
            <span className="mchat-spark">◆</span>
            <div>
              <div className="mchat-title">Parallax · Intelligence Assistant</div>
              <div className="mchat-sub">
                {chatCtx.selection
                  ? `Context: ${chatCtx.selection}`
                  : "Cross-pillar — ask about any signal, competitor, or tender"}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: "6px" }}>
            <button
              className="mchat-close"
              title="Clear Chat History"
              onClick={() =>
                setLog([
                  {
                    who: "bot",
                    html: `I can connect intelligence across Competitive, Market, and Technology. Select anything in a panel and ask me about it.`,
                  },
                ])
              }
              type="button"
            >
              🗑️
            </button>
            <button className="mchat-close" onClick={() => setCollapsed(true)} type="button">
              ✕
            </button>
          </div>
        </div>
        <div className="mchat-log" ref={logRef}>
          {log.map((m, i) =>
            m.who === "typing" ? (
              <div className="mchat-msg bot" key="typing">
                <div className="mchat-bubble">
                  <div className="mchat-typing">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              </div>
            ) : (
              <div className={`mchat-msg ${m.who}`} key={`${i}-${m.who}`}>
                <div className="mchat-bubble">
                  <div dangerouslySetInnerHTML={{ __html: m.html }} />
                  {m.who === "bot" && (
                    <button
                      className="mchat-copy-btn"
                      title="Copy Answer"
                      onClick={() => {
                        const tmp = document.createElement("div");
                        tmp.innerHTML = m.html;
                        navigator.clipboard.writeText(tmp.innerText || tmp.textContent);
                      }}
                    >
                      📋 Copy
                    </button>
                  )}
                </div>
              </div>
            ),
          )}
        </div>
        <div className="mchat-suggest">
          {chips.map((c) => (
            <span className="mchat-chip" key={c} onClick={() => submit(c)} role="button" tabIndex={-1}>
              {c}
            </span>
          ))}
        </div>
        <div className="mchat-input">
          <input
            autoComplete="off"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="Ask about competitors, markets, tenders…"
            ref={inputRef}
            type="text"
            value={text}
          />
          <button className="mchat-send" disabled={busy} onClick={() => submit()} type="button">
            →
          </button>
        </div>
        <div className="mchat-foot">
          Grounded in {clientName} platform intelligence · sourced + analytical data
        </div>
      </div>
    </div>
  );
}
