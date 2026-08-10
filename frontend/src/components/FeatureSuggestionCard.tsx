import { useState } from "react";
import type { FeatureSuggestion } from "../api/audit";
import { IconChevronDown } from "./icons";
import "./FeatureSuggestionCard.css";

interface FeatureSuggestionCardProps {
  suggestion: FeatureSuggestion;
  added: boolean;
  busy: boolean;
  onAdd: () => void;
}

export default function FeatureSuggestionCard({ suggestion, added, busy, onAdd }: FeatureSuggestionCardProps) {
  const [showFormula, setShowFormula] = useState(false);

  return (
    <div className={`feature-suggestion ${added ? "feature-suggestion--added" : ""}`}>
      <div className="feature-suggestion__body">
        <div className="feature-suggestion__top">
          <h4 className="feature-suggestion__name">{suggestion.name}</h4>
          <span className="feature-suggestion__column">{suggestion.output_column}</span>
        </div>
        <p className="feature-suggestion__description">{suggestion.description}</p>

        <button
          type="button"
          className={`feature-suggestion__formula-toggle ${showFormula ? "feature-suggestion__formula-toggle--open" : ""}`}
          onClick={() => setShowFormula((s) => !s)}
        >
          <IconChevronDown />
          {showFormula ? "Hide formula" : "Show formula"}
        </button>
        {showFormula && <p className="feature-suggestion__formula">ƒ {suggestion.formula}</p>}
      </div>

      <button type="button" className="feature-suggestion__btn" disabled={added || busy} onClick={onAdd}>
        {added ? "Added" : busy ? "Adding…" : "Add this feature"}
      </button>
    </div>
  );
}
