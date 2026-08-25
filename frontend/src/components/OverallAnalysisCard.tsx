import type { OverallAnalysisReport } from "../api/audit";
import { IconSparkle } from "./icons";
import "./OverallAnalysisCard.css";

interface OverallAnalysisCardProps {
  report: OverallAnalysisReport | undefined;
  loading: boolean;
  error: string | undefined;
  onRefresh: () => void;
}

export default function OverallAnalysisCard({ report, loading, error, onRefresh }: OverallAnalysisCardProps) {
  return (
    <div className="overall-analysis-card">
      <div className="overall-analysis-card__head">
        <h3 className="overall-analysis-card__title">
          <IconSparkle /> Highlights
        </h3>
        <button type="button" className="overall-analysis-card__refresh-btn" disabled={loading} onClick={onRefresh}>
          {loading ? "Computing…" : report ? "Refresh" : "Compute Highlights"}
        </button>
      </div>

      {error && <p className="overall-analysis-card__error">{error}</p>}

      {report && (
        <>
          <ul className="overall-analysis-card__highlights">
            {report.highlights.map((h, idx) => (
              <li key={idx}>
                <span className="overall-analysis-card__highlight-label">{h.label}</span>
                <span className="overall-analysis-card__highlight-value">{h.value}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
