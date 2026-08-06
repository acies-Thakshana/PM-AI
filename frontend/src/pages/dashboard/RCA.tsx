import { useEffect, useState } from "react";
import { fetchBloomRisk, fetchRca, type BloomRisk, type RcaGroup } from "../../api/client";

export default function RCA() {
  const [groups, setGroups] = useState<RcaGroup[]>([]);
  const [bloomRisk, setBloomRisk] = useState<BloomRisk[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchRca(), fetchBloomRisk()])
      .then(([r, b]) => {
        setGroups(r);
        setBloomRisk(b);
      })
      .catch((err) => setLoadError(`Failed to load RCA data: ${err?.message ?? err}`));
  }, []);

  if (loadError) return <div className="error-box">{loadError}</div>;

  return (
    <div>
      <div className="panel">
        <h2>
          Bloom Risk Score by Product
          <span className="hint">composite 0-100 score from temperature + humidity excursion share - target &lt;= 15</span>
        </h2>
        {bloomRisk.length === 0 ? (
          <div className="empty-state">No trips loaded yet.</div>
        ) : (
          bloomRisk.map((b) => (
            <div className="stat-bar-row" key={b.Product}>
              <span className="stat-bar-label">
                {b.Product} <span className="hint">({b.TripCount} trips)</span>
              </span>
              <div className="stat-bar-track">
                <div
                  className="stat-bar-fill"
                  style={{
                    width: `${Math.min(b.BloomRiskScore, 100)}%`,
                    background: b.BloomRiskScore > b.TargetMax ? "var(--danger)" : "var(--primary)",
                  }}
                />
              </div>
              <span className="stat-bar-value">{b.BloomRiskScore}</span>
            </div>
          ))
        )}
      </div>

      <div className="panel" style={{ marginTop: 18 }}>
        <h2>
          Root Cause Categories
          <span className="hint">flagged trips grouped by underlying data-quality / triage issue</span>
        </h2>
        {groups.length === 0 ? (
          <div className="empty-state">No flagged trips - nothing to root-cause.</div>
        ) : (
          groups.map((g) => (
            <div className="rca-card" key={g.flag}>
              <div className="rca-card-header" onClick={() => setExpanded(expanded === g.flag ? null : g.flag)}>
                <div>
                  <span className="badge rejected">{g.category}</span>
                  <strong style={{ marginLeft: 8 }}>{g.label}</strong>
                  <span className="hint" style={{ marginLeft: 8 }}>
                    {g.trip_count} trip{g.trip_count > 1 ? "s" : ""}
                  </span>
                </div>
                <span className="rca-toggle">{expanded === g.flag ? "-" : "+"}</span>
              </div>
              <p className="flag-explanation">{g.description}</p>
              {expanded === g.flag && (
                <table>
                  <thead>
                    <tr>
                      <th>Trip</th>
                      <th>Product</th>
                      <th>Destination</th>
                      <th>% In Spec</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.trips.map((t) => (
                      <tr key={t.TripID}>
                        <td>{t.TripID}</td>
                        <td>{t.Product}</td>
                        <td>{t.Destination}</td>
                        <td>{t.CompliancePct != null ? `${t.CompliancePct}%` : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
