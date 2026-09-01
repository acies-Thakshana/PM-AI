import type { FeatureResult } from "../api/types";
import Modal from "./Modal";
import { Distribution, STAT_LABELS, displayStats } from "./FeatureCard";
import "./FeatureCard.css";

interface FeatureDetailModalProps {
  feature: FeatureResult;
  formula?: string;
  onClose: () => void;
}

export default function FeatureDetailModal({ feature, formula, onClose }: FeatureDetailModalProps) {
  const distributionEntries = Object.entries(feature.distribution);
  const statsEntries = displayStats(feature.stats);
  const maxCount = distributionEntries.length > 0 ? Math.max(...distributionEntries.map(([, v]) => v)) : 0;

  return (
    <Modal title={feature.name} onClose={onClose}>
      {formula && <p className="feature-card__formula">ƒ {formula}</p>}
      <p className="feature-card__modal-description">{feature.description}</p>
      {feature.generated_code && (
        <div className="feature-card__code-block">
          <span className="feature-card__code-label">AI-generated pandas code</span>
          <pre className="feature-card__code"><code>{feature.generated_code}</code></pre>
        </div>
      )}
      {statsEntries.length > 0 && (
        <div className="feature-card__stats feature-card__stats--modal">
          {statsEntries.map(([key, value]) => (
            <div className="feature-card__stat-tile" key={key}>
              <span className="feature-card__stat-value">{value}</span>
              <span className="feature-card__stat-label">{STAT_LABELS[key] ?? key}</span>
            </div>
          ))}
        </div>
      )}
      {distributionEntries.length > 0 && <Distribution entries={distributionEntries} maxCount={maxCount} />}
    </Modal>
  );
}
