import { useState } from "react";
import type { PivotSuggestion } from "../api/audit";
import { IconChevronDown } from "./icons";
import "./PivotSuggestionCard.css";

interface PivotSuggestionCardProps {
  suggestion: PivotSuggestion;
  added: boolean;
  busy: boolean;
  onAdd: () => void;
}

function formulaText(suggestion: PivotSuggestion): string {
  const metrics = suggestion.metrics.map((m) => `${m.agg}(${m.column}) as ${m.output_label}`).join(", ");
  return `GROUP BY ${suggestion.group_by.join(", ")} -> ${metrics}`;
}

export default function PivotSuggestionCard({ suggestion, added, busy, onAdd }: PivotSuggestionCardProps) {
  const [showFormula, setShowFormula] = useState(false);

  return (
    <div className={`pivot-suggestion ${added ? "pivot-suggestion--added" : ""}`}>
      <div className="pivot-suggestion__body">
        <div className="pivot-suggestion__top">
          <h4 className="pivot-suggestion__name">{suggestion.name}</h4>
          <span className="pivot-suggestion__group">{suggestion.group_by.join(" / ")}</span>
        </div>
        <p className="pivot-suggestion__description">{suggestion.description}</p>

        <button
          type="button"
          className={`pivot-suggestion__formula-toggle ${showFormula ? "pivot-suggestion__formula-toggle--open" : ""}`}
          onClick={() => setShowFormula((s) => !s)}
        >
          <IconChevronDown />
          {showFormula ? "Hide logic" : "Show logic"}
        </button>
        {showFormula && <p className="pivot-suggestion__formula">ƒ {formulaText(suggestion)}</p>}
      </div>

      <button type="button" className="pivot-suggestion__btn" disabled={added || busy} onClick={onAdd}>
        {added ? "Added" : busy ? "Adding…" : "Add this pivot"}
      </button>
    </div>
  );
}
