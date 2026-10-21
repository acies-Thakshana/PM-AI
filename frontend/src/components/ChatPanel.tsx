import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useChat } from "../chat/ChatProvider";
import type { ChatMsg, ReviewStage } from "../chat/ChatProvider";
import { stageOf } from "../chat/rules";
import { IconChatBot, IconSparkle } from "./icons";
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
      {!!msg.links?.length && (
        <div className="chat__msg-actions">
          {msg.links.map((l) => (
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
  const location = useLocation();
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const { open, messages, busy, build, phase } = chat;

  // The assistant is there from the first page; only unknown routes (which redirect) have none.
  const hidden = !["/", "/upload", "/planner", "/audit", "/features", "/analysis", "/report"].includes(location.pathname);

  useEffect(() => {
    // Push the page content aside while the panel is open so it never covers the page.
    document.body.classList.toggle("chat-open", open && !hidden);
    return () => document.body.classList.remove("chat-open");
  }, [open, hidden]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy, open]);

  if (hidden) return null;

  if (!open) {
    return (
      <button
        type="button"
        className={`chat__launcher${build.status === "running" ? " chat__launcher--busy" : ""}`}
        onClick={() => chat.setOpen(true)}
        aria-label="Open the assistant"
        title="Assistant"
      >
        <IconChatBot />
        {build.status === "running" && <span className="chat__launcher-dot" aria-hidden="true" />}
      </button>
    );
  }

  const submit = () => {
    if (!draft.trim()) return;
    chat.send(draft);
    setDraft("");
  };

  // While the interview runs, the six things it settles are open so the PM sees what is still unanswered;
  // when the assistant reads the brief back, only the assumptions are open; afterwards both fold away.
  const interviewing = phase === "interview";
  const fresh = phase === "interview" && messages.length <= 1;
  // One main button, by where the conversation is: begin the interview, build once it is confirmed, check at the end.
  const buildBusy = build.status === "running" || build.status === "waiting_data" || build.status === "paused_audit";
  const headerAction: { label: string; run: () => void } | null = fresh
    ? { label: "Start", run: chat.startInterview }
    : phase === "ready" && !buildBusy
      ? { label: "Build the report", run: chat.startBuild }
      : phase === "refine"
        ? { label: "Check it", run: () => chat.send("Is this ready to send?") }
        : null;
  const openPath = chat.openPage;

  // The assistant only shows what belongs to the page the PM is on, so nothing appears before its step.
  const stage = stageOf(location.pathname);
  const reviewStage: ReviewStage | null = stage === "planner" || stage === "features" || stage === "analysis" ? stage : null;
  const stageReview = reviewStage ? chat.review.filter((r) => r.stage === reviewStage) : [];
  const pendingReview = stageReview.filter((r) => r.state === "pending" || r.state === "working" || r.state === "error");
  const showUnderstanding = stage === "configure" || Object.values(chat.understanding).some(Boolean);
  const showBuildItems = chat.buildItems.length > 0 && (stage === "analysis" || stage === "report" || build.status === "running");
  const showChanges = chat.changes.length > 0 && (stage === "features" || stage === "analysis" || stage === "report");
  // Shortcuts to add something belong to its own page: calculations on Features, analyses on Analysis.
  const showCalculations = stage === "features";
  const showAnalyses = stage === "analysis";
  // "My own": the PM describes it in the chat; the assistant drafts it, adds it and opens it on its page.
  const startOwn = (prefix: string) => {
    setDraft(prefix);
    document.getElementById("chat-input")?.focus();
  };

  return (
    <aside className="chat" aria-label="Assistant">
      <header className="chat__header">
        <span className="chat__title">
          <IconSparkle /> Assistant
        </span>
        <div className="chat__header-actions">
          {headerAction && (
            <button type="button" className="btn btn--sm btn--primary" disabled={busy} onClick={headerAction.run}>
              {headerAction.label}
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

      {showUnderstanding && (
        <details className="chat__summary" key={`understanding-${interviewing}`} open={interviewing}>
          <summary>What I understand so far</summary>
          <dl className="chat__understanding">
            {UNDERSTANDING_LABELS.map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd className={chat.understanding[key] ? undefined : "chat__open"}>{chat.understanding[key] || "Not asked yet"}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}

      {chat.assumptions.length > 0 && (
        <details className="chat__summary chat__assumptions" key={`assumptions-${phase === "readback"}`} open={phase === "readback"}>
          <summary>Assumptions ({chat.assumptions.length}), not confirmed by the client</summary>
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

        {stage === "audit" && (
          <section className="chat__plan chat__stage-note" aria-label="Data audit status">
            <h3>Data audit</h3>
            <p>
              {chat.audit.reviewed
                ? "Every audit decision is made. You can go on to Features."
                : chat.audit.pending > 0
                  ? `${chat.audit.pending} decision${chat.audit.pending > 1 ? "s" : ""} left. These are decided on this page; the assistant can't decide them for you.`
                  : "The audit still has steps left. Finish its checks on this page."}
            </p>
          </section>
        )}
        {reviewStage && stageReview.length > 0 && (
          <section className="chat__plan chat__review" aria-label="Suggestions to review">
            <h3>Suggestions to review ({pendingReview.length} waiting)</h3>
            <p className="chat__stage-hint">You can also accept or reject them on the page.</p>
            <ul>
              {stageReview.map((r) => (
                <li key={r.id} className={`chat__review-item chat__review-item--${r.state}`}>
                  <div>
                    <strong>{r.name}</strong>
                    <span>
                      {r.kind === "feature" ? "Calculation" : "Analysis"}
                      {r.description ? `: ${r.description}` : ""}
                    </span>
                    {r.error && <span className="chat__review-error">{r.error}</span>}
                  </div>
                  {r.state === "accepted" || r.state === "rejected" ? (
                    <span className="chat__review-done">{r.state === "accepted" ? "Accepted" : "Rejected"}</span>
                  ) : (
                    <span className="chat__change-buttons">
                      <button type="button" className="btn btn--sm btn--secondary" onClick={() => chat.inspect(r)}>
                        Details
                      </button>
                      <button type="button" className="btn btn--sm btn--primary" disabled={r.state === "working"} onClick={() => chat.decide(r.id, true)}>
                        {r.state === "working" ? "…" : "Accept"}
                      </button>
                      <button type="button" className="btn btn--sm btn--secondary" disabled={r.state === "working"} onClick={() => chat.decide(r.id, false)}>
                        Reject
                      </button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
            {pendingReview.some((r) => r.state === "pending") && (
              <div className="chat__plan-buttons">
                <button type="button" className="btn btn--sm btn--primary" onClick={() => chat.acceptAll(reviewStage)}>
                  Accept all
                </button>
              </div>
            )}
          </section>
        )}
        <div ref={endRef} />
      </div>

      {showBuildItems && (
        <section className="chat__live" aria-label="Analyses being built">
          <div className="chat__live-title">
            Analyses ({chat.buildItems.filter((i) => i.state === "done").length} of {chat.buildItems.length})
          </div>
          <ul>
            {chat.buildItems.map((item) => (
              <li key={item.id} className={`chat__live-item chat__live-item--${item.state}`}>
                <span className="chat__live-state" aria-hidden="true">
                  {item.state === "running" ? <Spinner /> : item.state === "done" ? "✓" : item.state === "failed" ? "!" : "·"}
                </span>
                <button type="button" className="chat__live-name chat__live-open" title="Open this analysis" onClick={() => openPath(`/analysis?open=${item.id}`)}>
                  {item.name}
                </button>
                <span className="chat__live-label">
                  {item.state === "queued" ? "waiting" : item.state === "running" ? "building" : item.state === "done" ? "ready" : "failed"}
                </span>
                {item.state === "failed" && item.error && <span className="chat__live-error">{item.error}</span>}
              </li>
            ))}
          </ul>
          <button type="button" className="btn btn--sm btn--secondary" onClick={() => openPath("/analysis")}>
            Open the analyses
          </button>
        </section>
      )}

      {build.status !== "idle" && (
        <div className={`chat__progress chat__progress--${build.status}`} role="status">
          {build.status === "running" && <Spinner />}
          <span>{build.line}</span>
          {build.status === "paused_audit" && (
            <button type="button" className="btn btn--sm btn--secondary" onClick={() => openPath("/audit")}>
              Open audit
            </button>
          )}
        </div>
      )}

      {showChanges && (
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

      {reviewStage && (
        <label className="chat__auto">
          <input type="checkbox" checked={chat.autoAccept[reviewStage]} onChange={(e) => chat.setAutoAccept(reviewStage, e.target.checked)} />
          Accept suggestions automatically on this page
        </label>
      )}

      {chat.hasSession && !busy && (showCalculations || showAnalyses) && (
        <div className="chat__quick chat__quick--add" aria-label="Add to the report">
          {showCalculations && (
            <button type="button" className="chat__chip" onClick={() => chat.suggestWithAi("feature")}>
              ✨ Suggest calculations (AI)
            </button>
          )}
          {showAnalyses && (
            <button type="button" className="chat__chip" onClick={() => chat.suggestWithAi("analysis")}>
              ✨ Suggest analyses (AI)
            </button>
          )}
          {showCalculations && (
            <button type="button" className="chat__chip" onClick={() => startOwn("Add a calculation: ")}>
              + My own calculation
            </button>
          )}
          {showAnalyses && (
            <button type="button" className="chat__chip" onClick={() => startOwn("Add an analysis: ")}>
              + My own analysis
            </button>
          )}
        </div>
      )}

      {chat.nextQuestions.length > 0 && !busy && (
        <div className="chat__quick chat__quick--next" aria-label="Questions you could ask">
          <span className="chat__quick-label">You could ask:</span>
          {chat.nextQuestions.map((q) => (
            <button key={q} type="button" className="chat__chip" onClick={() => chat.send(q)}>
              {q}
            </button>
          ))}
        </div>
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
