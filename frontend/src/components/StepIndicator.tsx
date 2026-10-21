import { useContext } from "react";
import { useNavigate } from "react-router-dom";
import { useChat } from "../chat/ChatProvider";
import { PlannerSkippedContext } from "../context/plannerSkipped";
import "./StepIndicator.css";

interface StepIndicatorProps {
  current: 1 | 2 | 3 | 4 | 5 | 6;
}

const STEPS = [
  { step: 1, label: "Configure", path: "/upload" },
  { step: 2, label: "Planner", path: "/planner" },
  { step: 3, label: "Audit", path: "/audit" },
  { step: 4, label: "Features", path: "/features" },
  { step: 5, label: "Analysis", path: "/analysis" },
  { step: 6, label: "Report", path: "/report" },
] as const;

export default function StepIndicator({ current }: StepIndicatorProps) {
  const navigate = useNavigate();
  const plannerSkipped = useContext(PlannerSkippedContext);
  const { audit } = useChat();

  return (
    <ol className="step-indicator" aria-label="Progress">
      {STEPS.map(({ step, label, path }, idx) => {
        // No client brief: the Planner was skipped (only shown once the PM is past it).
        const isSkipped = step === 2 && plannerSkipped && current > 2;
        // A step is only ticked when it is really finished: later pages can be reached (by the assistant, a link or
        // the address bar) while the audit decisions are still open, and that must not look done.
        const auditUnfinished = step === 3 && current > 3 && !audit.reviewed;
        const isDone = step < current && !isSkipped && !auditUnfinished;
        const isCurrent = step === current;
        if (isSkipped) {
          return (
            <li key={step} className="step-indicator__item step-indicator__item--skipped" title="Skipped: no client brief was given">
              <span className="step-indicator__badge">–</span>
              <span className="step-indicator__label">{label}</span>
              {idx < STEPS.length - 1 && <span className="step-indicator__connector" aria-hidden="true" />}
            </li>
          );
        }
        if (auditUnfinished) {
          return (
            <li key={step} className="step-indicator__item step-indicator__item--todo">
              <button
                type="button"
                className="step-indicator__link"
                onClick={() => navigate(path)}
                aria-label="Back to Audit: the decisions are not finished"
                title="The audit decisions are not finished"
              >
                <span className="step-indicator__badge">!</span>
                <span className="step-indicator__label">{label}</span>
              </button>
              {idx < STEPS.length - 1 && <span className="step-indicator__connector" aria-hidden="true" />}
            </li>
          );
        }
        return (
          <li
            key={step}
            className={`step-indicator__item ${
              isCurrent ? "step-indicator__item--current" : isDone ? "step-indicator__item--done" : ""
            }`}
          >
            {isDone ? (
              <button
                type="button"
                className="step-indicator__link"
                onClick={() => navigate(path)}
                aria-label={`Back to ${label}`}
              >
                <span className="step-indicator__badge">✓</span>
                <span className="step-indicator__label">{label}</span>
              </button>
            ) : (
              <>
                <span className="step-indicator__badge">{step}</span>
                <span className="step-indicator__label">{label}</span>
              </>
            )}
            {idx < STEPS.length - 1 && <span className="step-indicator__connector" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}
