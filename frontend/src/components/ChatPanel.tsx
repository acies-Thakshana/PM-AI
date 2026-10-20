import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useChat } from "../chat/ChatProvider";
import type { ChatMsg } from "../chat/ChatProvider";
import { IconSparkle } from "./icons";
import { Spinner } from "./ThinkingLoader";
import "./ChatPanel.css";

const UNDERSTANDING_LABELS: [keyof ReturnType<typeof useChat>["understanding"], string][] = [
  ["goal", "Goal"],
  ["scope", "Scope"],
  ["period", "Period"],
  ["limits", "Limits"],
  ["output", "Output"],
  ["kpis", "Client KPIs"],
];

function Message({ msg, onOpen }: { msg: ChatMsg; onOpen: (path: string) => void }) {
  return (
    <div className={`chat__msg chat__msg--${msg.role}${msg.error ? " chat__msg--error" : ""}`}>
      <div className="chat__bubble">{msg.text}</div>
      {(msg.links?.length || msg.buttons?.length) && (
        <div className="chat__msg-actions">
          {msg.buttons?.map((b) => (
            <button key={b.label} type="button" className="btn btn--sm btn--secondary" onClick={b.onClick}>
              {b.label}
            </button>
          ))}
          {msg.links?.map((l) => (
            <button key={l.path} type="button" className="btn btn--sm btn--secondary" onClick={() => onOpen(l.path)}>
              {l.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ChatPanel() {
  const chat = useChat();
  const navigate = useNavigate();
  const location = useLocation();
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const { open, messages, busy, build, plan, phase } = chat;

  // The welcome page is a landing page: the assistant starts once the PM is in the flow.
  const hidden = location.pathname === "/";

  useEffect(() => {
    // Push the page content aside while the panel is open so it never covers the page.
    document.body.classList.toggle("chat-open", open && !hidden);
    return () => document.body.classList.remove("chat-open");
  }, [open, hidden]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy, plan, open]);

  if (hidden) return null;

  if (!open) {
    return (
      <button type="button" className="chat__launcher" onClick={() => chat.setOpen(true)} aria-label="Open the assistant">
        <IconSparkle /> Assistant
        {build.status === "running" && <span className="chat__launcher-dot" aria-hidden="true" />}
      </button>
    );
  }

  const submit = () => {
    if (!draft.trim()) return;
    chat.send(draft);
    setDraft("");
  };

  const filled = UNDERSTANDING_LABELS.filter(([key]) => chat.understanding[key]);
  const showSummary = filled.length > 0 || chat.assumptions.length > 0;
  const canBuild = phase !== "build" && build.status !== "running" && build.status !== "waiting_data";
  const openPath = (path: string) => navigate(path);

  return (
    <aside className="chat" aria-label="Assistant">
      <header className="chat__header">
        <span className="chat__title">
          <IconSparkle /> Assistant
        </span>
        <div className="chat__header-actions">
          {canBuild && phase !== "plan" && (
            <button
              type="button"
              className="btn btn--sm btn--primary"
              disabled={busy}
              onClick={() => chat.send(phase === "refine" ? "Is this ready to send?" : "Build this report for me.")}
            >
              {phase === "refine" ? "Check it" : "Build the report"}
            </button>
          )}
          <button type="button" className="chat__icon-btn" title="Start over" aria-label="Start over" onClick={chat.reset} disabled={busy}>
            ↺
          </button>
          <button type="button" className="chat__icon-btn" title="Close" aria-label="Close the assistant" onClick={() => chat.setOpen(false)}>
            ×
          </button>
        </div>
      </header>

      {showSummary && (
        <details className="chat__summary" open>
          <summary>What I understand so far</summary>
          {filled.length > 0 && (
            <dl className="chat__understanding">
              {filled.map(([key, label]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>{chat.understanding[key]}</dd>
                </div>
              ))}
            </dl>
          )}
          {chat.assumptions.length > 0 && (
            <div className="chat__assumptions">
              <div className="chat__assumptions-title">Assumptions (not confirmed by the client)</div>
              <ul>
                {chat.assumptions.map((a) => (
                  <li key={a.id}>
                    {editing === a.id ? (
                      <input
                        autoFocus
                        className="chat__assumption-input"
                        value={a.text}
                        onChange={(e) => chat.editAssumption(a.id, e.target.value)}
                        onBlur={() => setEditing(null)}
                        onKeyDown={(e) => e.key === "Enter" && setEditing(null)}
                      />
                    ) : (
                      <button type="button" className="chat__assumption-text" title="Click to edit" onClick={() => setEditing(a.id)}>
                        {a.text}
                      </button>
                    )}
                    <button type="button" className="chat__icon-btn" aria-label="Remove this assumption" title="Remove" onClick={() => chat.removeAssumption(a.id)}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </details>
      )}

      <div className="chat__messages" role="log" aria-live="polite">
        {messages.map((m) => (
          <Message key={m.id} msg={m} onOpen={openPath} />
        ))}
        {busy && (
          <div className="chat__msg chat__msg--assistant">
            <div className="chat__bubble chat__bubble--typing">
              <Spinner /> Thinking…
            </div>
          </div>
        )}

        {plan && phase === "plan" && (
          <section className="chat__plan" aria-label="Proposed plan">
            <h3>Proposed plan</h3>
            {(["analyses", "features"] as const).map((kind) =>
              plan[kind].length > 0 ? (
                <div key={kind} className="chat__plan-group">
                  <div className="chat__plan-group-title">{kind === "analyses" ? `${plan[kind].length} analyses` : `${plan[kind].length} calculations`}</div>
                  <ul>
                    {plan[kind].map((item, i) => (
                      <li key={`${item.name}-${i}`}>
                        <div>
                          <strong>{item.name}</strong>
                          <span>{item.description}</span>
                        </div>
                        <button type="button" className="chat__icon-btn" aria-label={`Drop ${item.name}`} title="Drop this item" onClick={() => chat.removePlanItem(kind, i)}>
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null
            )}
            <div className="chat__plan-buttons">
              <button type="button" className="btn btn--sm btn--primary" onClick={chat.approvePlan} disabled={busy || (!plan.analyses.length && !plan.features.length)}>
                Approve
              </button>
              <button
                type="button"
                className="btn btn--sm btn--secondary"
                onClick={() => {
                  setDraft("Change the plan: ");
                  document.getElementById("chat-input")?.focus();
                }}
              >
                Change
              </button>
              <button type="button" className="btn btn--sm btn--secondary" onClick={chat.cancelPlan} disabled={busy}>
                Cancel
              </button>
            </div>
          </section>
        )}
        <div ref={endRef} />
      </div>

      {build.status !== "idle" && (
        <div className={`chat__progress chat__progress--${build.status}`} role="status">
          {build.status === "running" && <Spinner />}
          <span>{build.line}</span>
          {build.status === "paused_audit" && (
            <button type="button" className="btn btn--sm btn--secondary" onClick={() => navigate("/audit")}>
              Open audit
            </button>
          )}
        </div>
      )}

      {chat.changes.length > 0 && (
        <details className="chat__changes">
          <summary>What I changed ({chat.changes.length})</summary>
          <ul>
            {chat.changes.map((c) => (
              <li key={c.id} className={`chat__change chat__change--${c.state}`}>
                <span>
                  {c.kind === "analysis" ? "Analysis" : "Calculation"}: {c.label}
                  {c.state === "kept" && " (kept)"}
                  {c.state === "undone" && " (undone)"}
                </span>
                {c.state === "added" && (
                  <span className="chat__change-buttons">
                    <button type="button" className="btn btn--sm btn--secondary" onClick={() => chat.keepChange(c.id)}>
                      Keep
                    </button>
                    <button type="button" className="btn btn--sm btn--secondary" onClick={() => chat.undoChange(c.id)}>
                      Undo
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      {chat.quickReplies.length > 0 && !busy && (
        <div className="chat__quick">
          {chat.quickReplies.map((q) => (
            <button key={q} type="button" className="chat__chip" onClick={() => chat.send(q)}>
              {q}
            </button>
          ))}
        </div>
      )}

      <form
        className="chat__composer"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          id="chat-input"
          rows={2}
          value={draft}
          placeholder={phase === "refine" ? "Ask for a change…" : "Paste the brief or answer here…"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button type="submit" className="btn btn--primary" disabled={busy || !draft.trim()}>
          Send
        </button>
      </form>
    </aside>
  );
}
