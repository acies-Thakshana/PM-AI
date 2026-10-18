import { useEffect, useState } from "react";
import { Viz } from "./Viz.jsx";

const STEPS = [
  "Understanding the question",
  "Matching tables and columns",
  "Writing the query",
  "Running it on the connected tables",
  "Writing the answer"
];

export function AnswerCard({ data }) {
  const score = data.confidence != null && data.confidence !== "" ? Number(data.confidence) : null;
  return (
    <article className="answer">
      {data.question && <h3>{data.question}</h3>}
      {(data.pathLabel || score != null) && (
        <div className="answer-head">
          {data.pathLabel && <span className={"badge " + (data.ok ? "ok" : "warn")}>{data.pathLabel}</span>}
          {score != null && (
            <span className={"badge " + (score >= 0.7 ? "ok" : "warn")}>Confidence {Math.round(score * 100)}%</span>
          )}
        </div>
      )}
      <p className="section-label">Explanation</p>
      <p className="summary-text">{data.explanation || ""}</p>
      {data.warnings && data.warnings.length > 0 && (
        <ul className="warn-list">
          {data.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
      <p className="section-label">Visualization</p>
      <div className="viz-block">
        <Viz viz={data.viz} />
      </div>
      <p className="section-label">Reasoning</p>
      <p className="reasoning-prose">{data.reasoning || ""}</p>
      <p className="section-label">SQL</p>
      <pre className="sql">{data.sql || "No SQL was produced for this answer."}</pre>
    </article>
  );
}

export function ThinkingCard() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setStep((s) => (s < STEPS.length ? s + 1 : s)), 500);
    return () => clearInterval(timer);
  }, []);
  return (
    <article className="answer thinking">
      <ul className="scratchpad-list">
        {STEPS.map((label, i) => {
          const status = i < step ? "status-done" : i === step ? "status-running" : "";
          const mark = i < step ? "✓" : i === step ? "…" : "·";
          return (
            <li className={"scratch-step " + status} key={label}>
              <span className="scratch-mark">{mark}</span>
              <span className="scratch-label"> {label}</span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}
