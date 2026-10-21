import { useEffect, useRef, useState, type ReactNode } from "react";
import { askAssistant } from "../api/assistant";
import type { AssistantStage, AssistantTurn } from "../api/assistant";
import type { StageChrome } from "../context/stageChrome";
import { useStoredState } from "../state/sessionStore";
import ChatComposer from "./ChatComposer";
import ChatMessage from "./ChatMessage";
import ThinkingLoader from "./ThinkingLoader";
import "./ChatMessage.css";
import "./StageChat.css";

interface StageChatProps {
  stage: AssistantStage;
  sessionId: string | null;
  chrome: StageChrome | null;
  /** What the assistant says when the page has nothing more specific to report. */
  intro: string;
  /** Questions worth asking at this stage, offered as chips. */
  suggestions: string[];
  /** The stage's content. In bare mode it is the conversation itself (messages); otherwise it is the page. */
  children: ReactNode;
  /** The page supplies its own messages, so there is no summary message and no card around it. */
  bare?: boolean;
}

/** One stage as a conversation: the assistant reports what it found, the working tools open in a card inside the
 * conversation, and the message box talks to the assistant about this program. */
export default function StageChat({ stage, sessionId, chrome, intro, suggestions, children, bare = false }: StageChatProps) {
  const [turns, setTurns] = useStoredState<AssistantTurn[]>(`${stage}.chat`, []);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (turns.length || asking) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, asking]);

  const ask = async (text: string) => {
    // A page can take the message itself (for example the description of a custom KPI).
    if (chrome?.onSend?.(text)) return;
    if (!sessionId || asking) return;
    const history = turns;
    setTurns((prev) => [...prev, { role: "user", text }]);
    setAsking(true);
    setError(null);
    try {
      const reply = await askAssistant(sessionId, stage, text, history);
      setTurns((prev) => [...prev, { role: "assistant", text: reply }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The assistant could not answer.");
    } finally {
      setAsking(false);
    }
  };

  const stats = chrome?.stats ?? [];

  return (
    <div className="chat-page">
      <div className="chat-page__scroll">
        <div className="chat-page__thread">
          {bare ? (
            children
          ) : (
            <>
              <ChatMessage>
                <p>{chrome?.summary ?? intro}</p>
                {stats.length > 0 && (
                  <div className="chat-stats">
                    {stats.map((s) => (
                      <div className="chat-stat" key={s.label}>
                        <small>{s.label}</small>
                        <b>{s.value}</b>
                        {s.hint && <em>{s.hint}</em>}
                      </div>
                    ))}
                  </div>
                )}
              </ChatMessage>

              <ChatMessage>
                <div className="stage-card">
                  <button type="button" className="stage-card__head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
                    <span>Review and decide</span>
                    <span className="stage-card__toggle">{open ? "Hide" : "Show"}</span>
                  </button>
                  {open && <div className="stage-card__body">{children}</div>}
                </div>
              </ChatMessage>
            </>
          )}

          {turns.map((turn, i) => (
            <ChatMessage key={i} from={turn.role}>
              {turn.role === "assistant" ? <p>{turn.text}</p> : turn.text}
            </ChatMessage>
          ))}

          {asking && (
            <ChatMessage>
              <ThinkingLoader messages={["Reading your program…", "Writing an answer…"]} variant="inline" />
            </ChatMessage>
          )}

          {error && (
            <ChatMessage>
              <div className="upload-page__error">{error}</div>
            </ChatMessage>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <div className="chat-page__dock">
        <div className="chat-page__dock-inner">
          {!bare && (chrome?.back || chrome?.next) && (
            <div className="chat-page__bar">
              <div className="chat-page__dock-left">
                {chrome.back && (
                  <button type="button" className="btn btn--secondary btn--sm" onClick={chrome.back.onClick} disabled={chrome.back.disabled}>
                    {chrome.back.label}
                  </button>
                )}
                {chrome.next?.note && <span className="chat-page__count">{chrome.next.note}</span>}
              </div>
              {chrome.next && (
                <button type="button" className="btn btn--primary btn--sm" onClick={chrome.next.onClick} disabled={chrome.next.disabled}>
                  {chrome.next.label}
                </button>
              )}
            </div>
          )}
          {(chrome?.replies?.length || sessionId) && (
            <div className="stage-chips">
              {chrome?.replies?.map((r) => (
                <button key={r.label} type="button" className={`stage-chip${r.main ? " stage-chip--main" : ""}`} disabled={r.disabled} onClick={r.onClick}>
                  {r.label}
                </button>
              ))}
              {sessionId && suggestions.map((q) => (
                <button key={q} type="button" className="stage-chip" disabled={asking} onClick={() => void ask(q)}>
                  {q}
                </button>
              ))}
            </div>
          )}
          <ChatComposer
            placeholder={sessionId ? "Ask the assistant about this program…" : "Load a program in Configure to chat about it."}
            label="Message to the assistant"
            disabled={!sessionId || asking}
            onSend={(text) => void ask(text)}
          />
        </div>
      </div>
    </div>
  );
}
