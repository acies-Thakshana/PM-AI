import { useContext } from "react";
import { useNavigate } from "react-router-dom";
import { DataSourceContext, PlannerSkippedContext } from "../context/plannerSkipped";
import "./StepIndicator.css";

interface StepIndicatorProps {
  current: 1 | 2 | 3 | 4 | 5 | 6 | 7;
}

const STEPS = [
  { step: 1, label: "Configure", path: "/upload" },
  { step: 2, label: "Trips", path: "/trips" },
  { step: 3, label: "Planner", path: "/planner" },
  { step: 4, label: "Audit", path: "/audit" },
  { step: 5, label: "Features", path: "/features" },
  { step: 6, label: "Analysis", path: "/analysis" },
  { step: 7, label: "Report", path: "/report" },
] as const;

export default function StepIndicator({ current }: StepIndicatorProps) {
  const navigate = useNavigate();
  const plannerSkipped = useContext(PlannerSkippedContext);
  const source = useContext(DataSourceContext);

  return (
    <ol className="step-indicator" aria-label="Progress">
      {STEPS.map(({ step, label, path }, idx) => {
        // No client brief: the Planner was skipped (only shown once the PM is past it).
        const isSkipped = (step === 3 && plannerSkipped && current > 3) || (step === 2 && source === "upload" && current > 2);
        const isDone = step < current && !isSkipped;
        const isCurrent = step === current;
        if (isSkipped) {
          return (
            <li key={step} className="step-indicator__item step-indicator__item--skipped" title={step === 2 ? "Skipped: the data was uploaded as files" : "Skipped: no client brief was given"}>
              <span className="step-indicator__badge">–</span>
              <span className="step-indicator__label">{label}</span>
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
