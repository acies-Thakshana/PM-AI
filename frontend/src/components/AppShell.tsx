import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { InShellContext } from "../context/inShell";
import { StageChromeContext } from "../context/stageChrome";
import type { StageChrome } from "../context/stageChrome";
import StageChat from "./StageChat";
import type { AssistantStage } from "../api/assistant";
import "./AppShell.css";

interface AppShellProps {
  /** Clears everything loaded so far, so a new program can be set up. */
  onNewProgram: () => void;
  /** The audit session of the program in play, which the stage assistant answers about. */
  sessionId: string | null;
}

// The Planner is part of Configure: it is a conversation that follows the setup, not a stage of its own.
const STAGES = [
  { id: "configure", label: "Configure", hint: "Brief, data and plan", paths: ["/upload", "/planner"] },
  { id: "audit", label: "Audit", hint: "Check the data", paths: ["/audit"] },
  { id: "features", label: "Features", hint: "Build the columns", paths: ["/features"] },
  { id: "analysis", label: "Analysis", hint: "Charts and drill-downs", paths: ["/analysis"] },
  { id: "report", label: "Report", hint: "Slides and insights", paths: ["/report"] },
] as const;

// Pages that are a conversation themselves (own thread and message box). Every other stage opens with the
// assistant saying what it is for, and its page content follows as the assistant's reply.
const CONVERSATION_PATHS = ["/upload", "/planner"];
const STAGE_BY_PATH: Record<string, AssistantStage> = {
  "/audit": "audit",
  "/features": "features",
  "/analysis": "analysis",
  "/report": "report",
};

// What the assistant says when the page has nothing more specific, and what is worth asking at each stage.
const INTROS: Record<AssistantStage, string> = {
  audit: "I checked your trips before building anything on them. Go through what I flagged below, decide what to do with each, and continue when you are happy with the data.",
  features: "These are the features from your plan. Compute the ones you accepted on the audited data, or add one of your own.",
  analysis: "These are the analyses from your plan. Run them, filter the results and drill down.",
  report: "Choose what goes into the report, edit the key messages, then download it as a PowerPoint.",
};

const SUGGESTIONS: Record<AssistantStage, string[]> = {
  audit: ["What needs my decision?", "Why were these trips flagged?", "What happens if I exclude outliers?"],
  features: ["What do these features measure?", "Which features did I accept?"],
  analysis: ["Which analyses did I plan?", "What should I look at first?"],
  report: ["What will the report contain?", "What did the audit change?"],
};

/** Sidebar of stages plus one scrolling content area. Every page after Welcome renders inside it. */
export default function AppShell({ onNewProgram, sessionId }: AppShellProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  // What the current stage page tells the conversation (summary, numbers, Back and Next).
  const [chrome, setChrome] = useState<StageChrome | null>(null);

  const currentIndex = Math.max(
    0,
    STAGES.findIndex((s) => (s.paths as readonly string[]).includes(location.pathname))
  );
  const current = STAGES[currentIndex];
  const subtitle = location.pathname === "/planner" ? "Plan" : current.hint;

  // The drawer closes whenever the page changes.
  useEffect(() => setOpen(false), [location.pathname]);

  const toggleMenu = () => {
    if (window.matchMedia("(min-width: 900px)").matches) setCollapsed((c) => !c);
    else setOpen((o) => !o);
  };

  const handleNewProgram = () => {
    onNewProgram();
    navigate("/upload");
  };

  return (
    <InShellContext.Provider value={true}>
      <div className={`app-shell${collapsed ? " app-shell--collapsed" : ""}${open ? " app-shell--open" : ""}`}>
        <aside className="app-shell__side" aria-label="Stages">
          <div className="app-shell__brand">
            <img src="/carrier-logo.svg" alt="Carrier Global" className="app-shell__logo" />
          </div>
          <div className="app-shell__product">Program Manager AI</div>
          <button type="button" className="app-shell__new" onClick={handleNewProgram}>
            <span aria-hidden="true">+</span> New program
          </button>
          <div className="app-shell__label">Stages</div>
          <nav className="app-shell__stages">
            {STAGES.map((stage, i) => (
              <NavLink
                key={stage.id}
                to={stage.paths[0]}
                className={`app-shell__stage${i === currentIndex ? " is-current" : ""}${i < currentIndex ? " is-done" : ""}`}
                aria-current={i === currentIndex ? "page" : undefined}
              >
                <span className="app-shell__dot">{i < currentIndex ? "✓" : i + 1}</span>
                {stage.label}
              </NavLink>
            ))}
          </nav>
        </aside>
        <div className="app-shell__scrim" onClick={() => setOpen(false)} />

        <div className="app-shell__main">
          <header className="app-shell__bar">
            <button type="button" className="app-shell__menu" onClick={toggleMenu} aria-label="Toggle menu">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M4 7h16M4 12h16M4 17h16" />
              </svg>
            </button>
            <h1 className="app-shell__title">{current.label}</h1>
            <span className="app-shell__sub">{subtitle}</span>
          </header>
          <div className="app-shell__content">
            {CONVERSATION_PATHS.includes(location.pathname) ? (
              <Outlet />
            ) : (
              <StageChromeContext.Provider value={setChrome}>
                <StageChat
                  key={location.pathname}
                  stage={STAGE_BY_PATH[location.pathname] ?? "audit"}
                  sessionId={sessionId}
                  chrome={chrome}
                  intro={INTROS[STAGE_BY_PATH[location.pathname] ?? "audit"]}
                  suggestions={SUGGESTIONS[STAGE_BY_PATH[location.pathname] ?? "audit"]}
                  bare={["/audit", "/features", "/analysis", "/report"].includes(location.pathname)}
                >
                  <Outlet />
                </StageChat>
              </StageChromeContext.Provider>
            )}
          </div>
        </div>
      </div>
    </InShellContext.Provider>
  );
}
