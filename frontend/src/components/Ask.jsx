import { useEffect, useRef, useState } from "react";
import { askQuestion } from "../api.js";
import { AnswerCard, ThinkingCard } from "./AnswerCard.jsx";

/** The ask view. App remounts it (new `key`) for a new conversation or domain. */
export function Ask({ hidden, domain, domainLabel, suggestions, sessionId, onAsked, pendingQuestion, clearPending }) {
  const [messages, setMessages] = useState([]); // { type: "user" | "answer" | "error" | "thinking", ... }
  const [busy, setBusy] = useState(false);
  const [hero, setHero] = useState("");
  const [follow, setFollow] = useState("");
  const chatRef = useRef(null);
  const started = messages.length > 0;

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  function send(text, needDomain) {
    const question = String(text || "").trim();
    if (!question || busy || !domain) return;
    setBusy(true);
    onAsked(question);
    setMessages((m) => [...m, { type: "user", text: question }, { type: "thinking" }]);
    askQuestion(question, domain, sessionId)
      .then((view) => ({ type: "answer", view }))
      .catch((error) => ({ type: "error", text: error.message || String(error) }))
      .then((result) => {
        setMessages((m) => [...m.filter((x) => x.type !== "thinking"), result]);
        setBusy(false);
      });
  }

  // A question picked from the sidebar's Recent list, or from elsewhere in the app.
  useEffect(() => {
    if (pendingQuestion) {
      send(pendingQuestion);
      clearPending();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion]);

  return (
    <div id="ask-view" hidden={hidden}>
      <header className="topbar">
        <div>
          <p className="eyebrow">Carrier · NL2SQL workspace</p>
          <h1>Ask</h1>
        </div>
      </header>
      <div id="chat" className={"chat" + (started ? "" : " chat-empty-mode")} ref={chatRef}>
        {!started && (
          <div className="claude-empty">
            <h2>Ask {domainLabel}</h2>
            <p>
              Questions run on the tables in this domain. Each answer includes an explanation, a chart, the reasoning, and
              the SQL.
            </p>
            <form
              className="hero-composer"
              onSubmit={(e) => {
                e.preventDefault();
                send(hero);
                setHero("");
              }}
            >
              <textarea
                rows={3}
                value={hero}
                placeholder="Ask a question about the connected tables…"
                onChange={(e) => setHero(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(hero);
                    setHero("");
                  }
                }}
              />
              <div className="hero-composer-bar">
                <button type="submit">↑</button>
              </div>
            </form>
            <div className="suggestion-pills">
              {suggestions.map((text) => (
                <button key={text} type="button" className="sug-pill" onClick={() => send(text)}>
                  {text}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => {
          if (m.type === "user") return <div className="bubble user" key={i}>{m.text}</div>;
          if (m.type === "thinking") return <ThinkingCard key={i} />;
          if (m.type === "error") return <div className="bubble error" key={i}>{m.text}</div>;
          return <AnswerCard key={i} data={m.view} />;
        })}
      </div>
      {started && (
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(follow);
            setFollow("");
          }}
        >
          <input
            type="text"
            autoComplete="off"
            value={follow}
            placeholder="Ask a question about the connected tables…"
            onChange={(e) => setFollow(e.target.value)}
          />
          <button type="submit">Send</button>
        </form>
      )}
    </div>
  );
}
