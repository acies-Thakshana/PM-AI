import { tidyText } from "../utils/tidyText";
import type { FeatureRepositoryEntry } from "../api/audit";
import Modal from "./Modal";
import "./FeatureSuggestionCard.css";

interface FeatureSuggestionDetailProps {
  suggestion: FeatureRepositoryEntry;
  onClose: () => void;
}

/**
 * The detail window of a suggested calculation: what it is and what it calculates. A suggestion has not been computed
 * yet, so it has no computed-feature window; this is the one it has, from its card and from the assistant.
 */
export default function FeatureSuggestionDetail({ suggestion, onClose }: FeatureSuggestionDetailProps) {
  return (
    <Modal title={suggestion.name} onClose={onClose}>
      <p className="feature-suggestion__modal-description">{tidyText(suggestion.description)}</p>
      <p className="feature-suggestion__formula">{suggestion.calculation_intent}</p>
    </Modal>
  );
}
