import type { FeatureResult } from "../api/audit";
import { IconExpand, IconGrid, IconShieldCheck } from "./icons";
import "./FeatureCard.css";

interface FeatureCardProps {
  feature: FeatureResult;
  colorIndex?: number;
  onExpand: () => void;
}

export const STAT_LABELS: Record<string, string> = {
  mean: "Mean",
  median: "Median",
  min: "Min",
  max: "Max",
};

const ICON_COLORS = ["blue", "teal", "purple", "amber"] as const;

export function Distribution({ entries, maxCount }: { entries: [string, number][]; maxCount: number }) {
  return (
    <ul className="feature-card__distribution">
      {entries.map(([label, count]) => (
        <li key={label} className="feature-card__dist-row">
          <span className="feature-card__dist-label">{label}</span>
          <span className="feature-card__dist-bar-track">
            <span className="feature-card__dist-bar" style={{ width: maxCount > 0 ? `${(count / maxCount) * 100}%` : "0%" }} />
          </span>
          <span className="feature-card__dist-count">{count.toLocaleString()}</span>
        </li>
      ))}
    </ul>
  );
}

export default function FeatureCard({ feature, colorIndex = 0, onExpand }: FeatureCardProps) {
  const total = feature.non_null_count + feature.null_count;
  const distributionEntries = Object.entries(feature.distribution);
  const statsEntries = Object.entries(feature.stats);
  const isNumeric = statsEntries.length > 0;
  const maxCount = distributionEntries.length > 0 ? Math.max(...distributionEntries.map(([, v]) => v)) : 0;
  const previewEntries = distributionEntries.slice(0, 4);
  const color = ICON_COLORS[colorIndex % ICON_COLORS.length];

  return (
    <div className="feature-card">
      <div className="feature-card__header">
        <span className={`feature-card__icon feature-card__icon--${color}`}>{isNumeric ? <IconShieldCheck /> : <IconGrid />}</span>
        <div className="feature-card__header-text">
          <h3 className="feature-card__name">{feature.name}</h3>
          <span className="feature-card__column">{feature.output_column}</span>
        </div>
        <div className="feature-card__badges">
          {feature.id.startsWith("ai_") && <span className="feature-card__ai-badge">AI</span>}
          {feature.id.startsWith("custom_") && <span className="feature-card__custom-badge">Custom</span>}
        </div>
      </div>
      <p className="feature-card__description">{feature.description}</p>
      <p className="feature-card__coverage">
        {feature.non_null_count.toLocaleString()} of {total.toLocaleString()} rows populated
        {feature.null_count > 0 && ` (${feature.null_count.toLocaleString()} null)`}
      </p>

      {previewEntries.length > 0 && <Distribution entries={previewEntries} maxCount={maxCount} />}

      {isNumeric && (
        <div className="feature-card__stats">
          {statsEntries.map(([key, value]) => (
            <div className="feature-card__stat-tile" key={key}>
              <span className="feature-card__stat-value">{value}</span>
              <span className="feature-card__stat-label">{STAT_LABELS[key] ?? key}</span>
            </div>
          ))}
        </div>
      )}

      {(distributionEntries.length > previewEntries.length || isNumeric) && (
        <button type="button" className="feature-card__expand-btn" onClick={onExpand}>
          <IconExpand />
          {isNumeric ? "View trend over time" : "View full breakdown"}
        </button>
      )}
    </div>
  );
}
