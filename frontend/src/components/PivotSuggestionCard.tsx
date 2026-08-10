import { useState } from "react";
import type { PivotSuggestion } from "../api/audit";
import { IconExpand } from "./icons";
import Modal from "./Modal";
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
    <>
      <div className={`pivot-suggestion ${added ? "pivot-suggestion--added" : ""}`}>
        <div className="pivot-suggestion__body">
          <div className="pivot-suggestion__top">
            <h4 className="pivot-suggestion__name">{suggestion.name}</h4>
            <span className="pivot-suggestion__group">{suggestion.group_by.join(" / ")}</span>
          </div>
          <p className="pivot-suggestion__description">{suggestion.description}</p>

          <button type="button" className="pivot-suggestion__formula-toggle" onClick={() => setShowFormula(true)}>
            <IconExpand />
            View logic
          </button>
        </div>

        <button type="button" className="pivot-suggestion__btn" disabled={added || busy} onClick={onAdd}>
          {added ? "Added" : busy ? "Adding…" : "Add this analysis"}
        </button>
      </div>

      {showFormula && (
        <Modal title={suggestion.name} onClose={() => setShowFormula(false)}>
          <p className="pivot-suggestion__modal-description">{suggestion.description}</p>
          <p className="pivot-suggestion__formula">ƒ {formulaText(suggestion)}</p>
        </Modal>
      )}
    </>
  );
}
