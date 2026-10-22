import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { useLocation } from "react-router-dom";
import { useChat } from "../chat/ChatProvider";
import type { ChatMsg, ReviewStage } from "../chat/ChatProvider";
import { stageOf } from "../chat/rules";
import { CONFIGURE_LOAD_KEY, CONFIGURE_STATUS_KEY, NOT_READY } from "../chat/signals";
import type { ConfigureStatus } from "../chat/signals";
import { useStoredState } from "../state/sessionStore";
import { IconChatBot } from "./icons";
import { Spinner } from "./ThinkingLoader";
import "./ChatPanel.css";

const ASSISTANT_NAME = "Polar";
const ASSISTANT_ROLE = "Program Manager Assistant";

// The panel's width: dragged by its edge, or stepped with the + and - buttons through these shares of the screen.
const WIDTH_STEPS = [0.22, 0.3, 0.42, 0.55, 0.7];
const MIN_WIDTH = 320;
const WIDTH_KEY = "chat.width";

const clampWidth = (px: number) => Math.round(Math.min(Math.max(px, MIN_WIDTH), Math.max(MIN_WIDTH, window.innerWidth * 0.8)));
const defaultWidth = () => clampWidth(window.innerWidth * 0.3);

function loadWidth(): number {
  try {
    const saved = Number(window.localStorage.getItem(WIDTH_KEY));
    if (saved > 0) return clampWidth(saved);
  } catch {
    /* no storage: the default is fine */
  }
  return defaultWidth();
}

function Message({ msg, onOpen }: { msg: ChatMsg; onOpen: (path: string) => void }) {
  return (
    <div className={`chat__msg chat__msg--${msg.role}${msg.error ? " chat__msg--error" : ""}`}>
      {msg.role === "assistant" && (
        <span className="chat__msg-avatar" aria-hidden="true">
          <IconChatBot />
        </span>
      )}
      <div className="chat__msg-body">
        <div className="chat__bubble">
          {msg.facts ? (
            <>
              <div className="chat__facts-title">{msg.text.split("\n")[0]}</div>
              <dl className="chat__facts">
                {msg.facts.map((f) => (
                  <div key={f.label}>
                    <dt>{f.label}</dt>
                    <dd>{f.value}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : (
            msg.text
          )}
        </div>
        {!!msg.links?.length && (
          <div className="chat__msg-actions">
            {msg.links.map((l) => (
              <button key={l.path} type="button" className="chat__chip chat__chip--small" onClick={() => onOpen(l.path)}>
                {l.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPanel() {
  const chat = useChat();
  const location = useLocation();
  const [draft, setDraft] = useState("");
  // The Configure page tells whether "Load & continue" can be pressed; pressing it here raises the counter it watches.
  const [configure] = useStoredState<ConfigureStatus>(CONFIGURE_STATUS_KEY, NOT_READY);
  const [, setLoadRequest] = useStoredState<number>(CONFIGURE_LOAD_KEY, 0);
  const [editing, setEditing] = useState<string | null>(null);
  const [width, setWidth] = useState(loadWidth);
  const [resizing, setResizing] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const { open, messages, busy, build, phase } = chat;

  // The assistant is there from the first page; only unknown routes (which redirect) have none.
  const hidden = !["/", "/upload", "/planner", "/audit", "/features", "/analysis", "/report"].includes(location.pathname);

  useEffect(() => {
    // Push the page content aside while the panel is open so it never covers the page.
    document.body.classList.toggle("chat-open", open && !hidden);
    return () => document.body.classList.remove("chat-open");
  }, [open, hidden]);

  // The page and its detail windows read the width from this variable, so they move with the panel.
  useEffect(() => {
    document.documentElement.style.setProperty("--chat-width", `${width}px`);
    try {
      window.localStorage.setItem(WIDTH_KEY, String(width));
    } catch {
      /* not saved: it just starts at the default next time */
    }
  }, [width]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy, open]);

  const startDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setResizing(true);
  }, []);
  const drag = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (resizing) setWidth(clampWidth(window.innerWidth - event.clientX));
    },
    [resizing]
  );
  const stopDrag = useCallback(() => setResizing(false), []);
  const nudge = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") setWidth((w) => clampWidth(w + 24));
    if (event.key === "ArrowRight") setWidth((w) => clampWidth(w - 24));
  }, []);
  const step = (direction: 1 | -1) => {
    const sizes = WIDTH_STEPS.map((share) => clampWidth(window.innerWidth * share));
    const next = direction > 0 ? sizes.find((s) => s > width + 8) : [...sizes].reverse().find((s) => s < width - 8);
    if (next) setWidth(next);
  };

  if (hidden) return null;

  if (!open) {
    return (
      <button
        type="button"
        className={`chat__launcher${build.status === "running" ? " chat__launcher--busy" : ""}`}
        onClick={() => chat.setOpen(true)}
        aria-label={`Open ${ASSISTANT_NAME}, the ${ASSISTANT_ROLE}`}
        title={`${ASSISTANT_NAME}, your ${ASSISTANT_ROLE}`}
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

  // What the assistant understood from the brief is said as a reply in the conversation, not kept in a box.
  // The questions start by themselves on the Planner page (the data is loaded by then); the button is only for starting
  // them again by hand. Before that, on the Configure page, the next step is loading the data.
  const started = messages.some((m) => m.role === "user") || Object.values(chat.understanding).some(Boolean);
  const fresh = phase === "interview" && !started && stageOf(location.pathname) === "planner";
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
  const waiting = (r: { state: string }) => r.state === "pending" || r.state === "working" || r.state === "error";
  const stageReview = reviewStage ? chat.review.filter((r) => r.stage === reviewStage && (reviewStage === "planner" || waiting(r))) : [];
  const pendingReview = stageReview.filter(waiting);
  const reviewOpen = reviewStage === "planner" || chat.suggestedFor === reviewStage;
  // The list of analyses is for watching them being built: it is gone once they have all finished.
  const showBuildItems = chat.buildItems.some((i) => i.state === "queued" || i.state === "running");
  const itemKinds = new Set(chat.buildItems.map((i) => i.kind ?? "analysis"));
  const progressTitle = itemKinds.size > 1 ? "Working on your items" : itemKinds.has("feature") ? "Computing your calculation" : "Building your analyses";
  const itemPath = (item: { id: string; kind?: string }) => `${item.kind === "feature" ? "/features" : "/analysis"}?open=${item.id}`;
  const undoable = chat.changes.filter((c) => c.state === "added");
  const showChanges = undoable.length > 0 && (stage === "features" || stage === "analysis" || stage === "report");
  // The way on to the next page, from the chat itself, with a line about the page the PM is on.
  const nextStep: { label: string; path: string; enabled: boolean; hint: string } | null =
    stage === "planner"
      ? { label: "Continue to Data audit", path: "/audit", enabled: true, hint: "Planner: accept or reject the suggestions here or on the page, then go on." }
      : stage === "audit"
        ? {
            label: "Continue to Features",
            path: "/features",
            enabled: chat.audit.reviewed,
            hint: chat.audit.reviewed
              ? "Data audit: every decision is made."
              : `Data audit: decide the findings on the page first${chat.audit.pending ? ` (${chat.audit.pending} left)` : ""}.`,
          }
        : stage === "features"
          ? { label: "Continue to Analysis", path: "/analysis", enabled: true, hint: "Features: open a calculation to see its formula, or ask me about it." }
          : stage === "analysis"
            ? { label: "Continue to Report", path: "/report", enabled: true, hint: "Analysis: open an analysis to see its chart, or ask me to explain it." }
            : null;
  // Shortcuts to add something belong to its own page: calculations on Features, analyses on Analysis.
  const showCalculations = stage === "features";
  const showAnalyses = stage === "analysis";
  // "My own": the PM describes it in the chat; the assistant drafts it, adds it and opens it on its page.
  const startOwn = (prefix: string) => {
    setDraft(prefix);
    document.getElementById("chat-input")?.focus();
  };

  return (
    <aside className={`chat${resizing ? " chat--resizing" : ""}`} aria-label={`${ASSISTANT_NAME}, ${ASSISTANT_ROLE}`}>
      <div
        className="chat__resize"
        role="separator"
        aria-orientation="vertical"
        aria-label="Drag to resize the assistant"
        tabIndex={0}
        onPointerDown={startDrag}
        onPointerMove={drag}
        onPointerUp={stopDrag}
        onPointerCancel={stopDrag}
        onKeyDown={nudge}
      />

      <header className="chat__header">
        <span className="chat__avatar" aria-hidden="true">
          <IconChatBot />
          <span className="chat__avatar-dot" />
        </span>
        <span className="chat__identity">
          <span className="chat__name">{ASSISTANT_NAME}</span>
          <span className="chat__role">{ASSISTANT_ROLE}</span>
        </span>
        <div className="chat__header-actions">
          {headerAction && (
            <button type="button" className="chat__action" disabled={busy} onClick={headerAction.run}>
              {headerAction.label}
            </button>
          )}
          <button type="button" className="chat__icon-btn" title="Make it smaller" aria-label="Make the assistant smaller" onClick={() => step(-1)}>
            −
          </button>
          <button type="button" className="chat__icon-btn" title="Make it bigger" aria-label="Make the assistant bigger" onClick={() => step(1)}>
            +
          </button>
          <button type="button" className="chat__icon-btn" title="Start over" aria-label="Start over" onClick={chat.reset} disabled={busy}>
            ↺
          </button>
          <button type="button" className="chat__icon-btn" title="Close" aria-label="Close the assistant" onClick={() => chat.setOpen(false)}>
            ×
          </button>
        </div>
      </header>

      {chat.assumptions.length > 0 && (
        <details className="chat__card chat__summary chat__assumptions" key={`assumptions-${phase === "readback"}`} open={phase === "readback"}>
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
            <span className="chat__msg-avatar" aria-hidden="true">
              <IconChatBot />
            </span>
            <div className="chat__msg-body">
              <div className="chat__bubble chat__bubble--typing">
                <Spinner /> Thinking…
              </div>
            </div>
          </div>
        )}

        {stage === "audit" && (
          <section className="chat__card chat__stage-note" aria-label="Data audit status">
            <h3>Data audit</h3>
            <p>
              {chat.audit.reviewed
                ? "Every audit decision is made. You can go on to Features."
                : chat.audit.pending > 0
                  ? `${chat.audit.pending} decision${chat.audit.pending > 1 ? "s" : ""} left. These are decided on this page; I can't decide them for you.`
                  : "The audit still has steps left. Finish its checks on this page."}
            </p>
          </section>
        )}
        {reviewStage && stageReview.length > 0 && (
          <details className="chat__card chat__review" key={`review-${reviewStage}-${reviewOpen}`} open={reviewOpen}>
            <summary>Suggestions to review ({pendingReview.length} waiting)</summary>
            <p className="chat__stage-hint">You can also accept or reject them on the page.</p>
            <ul>
              {stageReview.map((r) => (
                <li key={r.id} className={`chat__review-item chat__review-item--${r.state}`}>
                  <div className="chat__review-text">
                    <button type="button" className="chat__review-name" title="Open this on its page" onClick={() => chat.inspect(r)}>
                      {r.name}
                    </button>
                    <span>
                      {r.kind === "feature" ? "Calculation" : "Analysis"}
                      {r.description ? `: ${r.description}` : ""}
                    </span>
                    {r.error && <span className="chat__review-error">{r.error}</span>}
                  </div>
                  {r.state === "accepted" || r.state === "rejected" ? (
                    <span className={`chat__review-done chat__review-done--${r.state}`}>{r.state === "accepted" ? "Accepted" : "Rejected"}</span>
                  ) : (
                    <span className="chat__change-buttons">
                      {r.stage !== "planner" && (
                        <button type="button" className="chat__btn chat__btn--ghost" onClick={() => chat.inspect(r)}>
                          Details
                        </button>
                      )}
                      <button type="button" className="chat__btn chat__btn--solid" disabled={r.state === "working"} onClick={() => chat.decide(r.id, true)}>
                        {r.state === "working" ? "…" : "Accept"}
                      </button>
                      <button type="button" className="chat__btn chat__btn--ghost" disabled={r.state === "working"} onClick={() => chat.decide(r.id, false)}>
                        Reject
                      </button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
            {pendingReview.some((r) => r.state === "pending") && (
              <div className="chat__plan-buttons">
                <button type="button" className="chat__btn chat__btn--solid" onClick={() => chat.acceptAll(reviewStage)}>
                  Accept all
                </button>
              </div>
            )}
          </details>
        )}
        <div ref={endRef} />
      </div>

      {showBuildItems && (
        <section className="chat__card chat__live" aria-label="Work in progress">
          <div className="chat__live-title">{progressTitle}</div>
          <ul>
            {chat.buildItems.map((item) => (
              <li key={item.id} className={`chat__live-item chat__live-item--${item.state}`}>
                <span className="chat__live-state" aria-hidden="true">
                  {item.state === "running" ? <Spinner /> : item.state === "done" ? "✓" : item.state === "failed" ? "!" : "·"}
                </span>
                <button type="button" className="chat__live-name chat__live-open" title="Open this item" onClick={() => openPath(itemPath(item))}>
                  {item.name}
                </button>
                <span className="chat__live-label">
                  {item.state === "queued" ? "waiting" : item.state === "running" ? (item.kind === "feature" ? "computing" : "building") : item.state === "done" ? "ready" : "failed"}
                </span>
                {item.state === "failed" && item.error && <span className="chat__live-error">{item.error}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {build.status !== "idle" && (
        <div className={`chat__progress chat__progress--${build.status}`} role="status">
          {build.status === "running" && <Spinner />}
          <span>{build.line}</span>
          {build.status === "paused_audit" && (
            <button type="button" className="chat__btn chat__btn--ghost" onClick={() => openPath("/audit")}>
              Open audit
            </button>
          )}
        </div>
      )}

      {showChanges && (
        <details className="chat__card chat__changes">
          <summary>What I changed ({undoable.length})</summary>
          <ul>
            {undoable.map((c) => (
              <li key={c.id} className="chat__change">
                <span>
                  {c.kind === "analysis" ? "Analysis" : "Calculation"}: {c.label}
                </span>
                <button type="button" className="chat__btn chat__btn--ghost" onClick={() => chat.undoChange(c.id)}>
                  Undo
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}

      {reviewStage && pendingReview.length > 0 && (
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
        <details className="chat__card chat__ask">
          <summary>
            Suggested questions <span className="chat__ask-count">{chat.nextQuestions.length}</span>
          </summary>
          <div className="chat__quick chat__quick--next" aria-label="Questions you could ask">
            {chat.nextQuestions.map((q) => (
              <button key={q} type="button" className="chat__chip" onClick={() => chat.send(q)}>
                {q}
              </button>
            ))}
          </div>
        </details>
      )}

      {chat.quickReplies.length > 0 && !busy && (
        <div className="chat__quick">
          {chat.quickReplies.map((q) => (
            <button key={q} type="button" className={`chat__chip${q.startsWith("Skip the questions") ? " chat__chip--skip" : ""}`} onClick={() => chat.send(q)}>
              {q}
            </button>
          ))}
        </div>
      )}

      {nextStep && (
        <div className="chat__loadbar">
          <button type="button" className="chat__load" disabled={!nextStep.enabled} onClick={() => openPath(nextStep.path)}>
            {nextStep.label}
          </button>
          <span className="chat__load-hint">{nextStep.hint}</span>
        </div>
      )}

      {stage === "configure" && (
        <div className="chat__loadbar">
          <button type="button" className="chat__load" disabled={!configure.canContinue} onClick={() => setLoadRequest((n) => n + 1)}>
            {configure.label}
          </button>
          <span className="chat__load-hint">
            {configure.canContinue ? "Loads your data and opens the next page." : configure.hint || "Working…"}
          </span>
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
          placeholder={phase === "refine" ? `Ask ${ASSISTANT_NAME} for a change…` : "Paste the brief or answer here…"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button type="submit" className="chat__send" disabled={busy || !draft.trim()} aria-label="Send">
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M5 12h13M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>
    </aside>
  );
}
