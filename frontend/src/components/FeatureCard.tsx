import type { FeatureResult } from "../api/audit";
import "./FeatureCard.css";

interface FeatureCardProps {
  feature: FeatureResult;
}

const STAT_LABELS: Record<string, string> = {
  mean: "Mean",
  median: "Median",
  min: "Min",
  max: "Max",
};

export default function FeatureCard({ feature }: FeatureCardProps) {
  const total = feature.non_null_count + feature.null_count;
  const distributionEntries = Object.entries(feature.distribution);
  const maxCount = distributionEntries.length > 0 ? Math.max(...distributionEntries.map(([, v]) => v)) : 0;

  return (
    <div className="feature-card">
      <div className="feature-card__header">
        <h3 className="feature-card__name">{feature.name}</h3>
        <span className="feature-card__column">{feature.output_column}</span>
      </div>
      <p className="feature-card__description">{feature.description}</p>
      <p className="feature-card__coverage">
        {feature.non_null_count.toLocaleString()} of {total.toLocaleString()} rows populated
        {feature.null_count > 0 && ` (${feature.null_count.toLocaleString()} null)`}
      </p>

      {distributionEntries.length > 0 && (
        <ul className="feature-card__distribution">
          {distributionEntries.map(([label, count]) => (
            <li key={label} className="feature-card__dist-row">
              <span className="feature-card__dist-label">{label}</span>
              <span className="feature-card__dist-bar-track">
                <span
                  className="feature-card__dist-bar"
                  style={{ width: maxCount > 0 ? `${(count / maxCount) * 100}%` : "0%" }}
                />
              </span>
              <span className="feature-card__dist-count">{count.toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}

      {Object.keys(feature.stats).length > 0 && (
        <div className="feature-card__stats">
          {Object.entries(feature.stats).map(([key, value]) => (
            <div className="feature-card__stat-tile" key={key}>
              <span className="feature-card__stat-value">{value}</span>
              <span className="feature-card__stat-label">{STAT_LABELS[key] ?? key}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
