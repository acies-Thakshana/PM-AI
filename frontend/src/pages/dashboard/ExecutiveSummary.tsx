import { useEffect, useState } from "react";
import { fetchExecutiveSummary, fetchTrips, type ExecutiveSummary as ExecutiveSummaryData, type TripSummary } from "../../api/client";
import KpiCard from "../../components/KpiCard";
import ShipmentMap from "../../components/ShipmentMap";

const REFRESH_MS = 20000;

export default function ExecutiveSummary() {
  const [summary, setSummary] = useState<ExecutiveSummaryData | null>(null);
  const [trips, setTrips] = useState<TripSummary[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      Promise.all([fetchExecutiveSummary(), fetchTrips()])
        .then(([s, t]) => {
          setSummary(s);
          setTrips(t);
          setLastUpdated(new Date());
          setLoadError(null);
        })
        .catch((err) => {
          setLoadError(
            err?.code === "ERR_NETWORK"
              ? "Can't reach the backend API at http://localhost:8000 - is it running?"
              : `Failed to load executive summary: ${err?.message ?? err}`
          );
        });
    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  const kpis = summary?.kpis;
  const noDataLoaded = kpis && kpis.trips_loaded === 0;
  const bySource = summary?.by_source ?? {};
  const totalTrips = Object.values(bySource).reduce((a, b) => a + b, 0);

  return (
    <div>
      <div className="app-header" style={{ marginTop: 4 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>{summary?.customer ?? "Customer"}</h2>
          <div className="subtitle">
            Cold chain program overview
            {lastUpdated ? ` - last refreshed ${lastUpdated.toLocaleTimeString()}` : ""}
          </div>
        </div>
      </div>

      {loadError && <div className="error-box" style={{ marginBottom: 16 }}>{loadError}</div>}

      {noDataLoaded && (
        <div className="error-box" style={{ marginBottom: 16, background: "#fff3e0", color: "#b06f00" }}>
          No trip data loaded yet - go to <strong>1. Data Upload</strong> and load the SensiWatch/ColdStream samples
          first.
        </div>
      )}

      {kpis && kpis.trips_loaded > 0 && (
        <>
          <div className="kpi-row">
            <KpiCard label="Trips Loaded" value={String(kpis.trips_loaded)} target="-" status="on_target" />
            <KpiCard
              label="Avg % Time In Spec"
              value={kpis.avg_compliance_pct != null ? `${kpis.avg_compliance_pct}%` : "-"}
              target=">= 95%"
              status={kpis.avg_compliance_pct != null && kpis.avg_compliance_pct < 95 ? "at_risk" : "on_target"}
            />
            <KpiCard
              label="Flagged Trips"
              value={String(kpis.flagged_trip_count)}
              target="0"
              status={kpis.flagged_trip_count > 0 ? "at_risk" : "on_target"}
            />
            <KpiCard
              label="Should Be Closed"
              value={String(kpis.likely_arrived_count)}
              target="0"
              status={kpis.likely_arrived_count > 0 ? "at_risk" : "on_target"}
            />
            <KpiCard
              label="Stuck - Needs Investigation"
              value={String(kpis.stuck_trip_count)}
              target="0"
              status={kpis.stuck_trip_count > 0 ? "at_risk" : "on_target"}
            />
            <KpiCard label="Active In Transit" value={String(kpis.active_trip_count)} target="-" status="on_target" />
          </div>

          <div className="panel-grid">
            <ShipmentMap trips={trips} title="Shipment Network" />
            <div className="panel">
              <h2>
                Program Snapshot
                <span className="hint">shipments by source and highest-risk products</span>
              </h2>
              <div className="stat-block-title">Shipments by Source</div>
              {Object.entries(bySource).map(([source, count]) => (
                <div className="stat-bar-row" key={source}>
                  <span className="stat-bar-label">{source}</span>
                  <div className="stat-bar-track">
                    <div
                      className="stat-bar-fill"
                      style={{ width: `${totalTrips ? (count / totalTrips) * 100 : 0}%` }}
                    />
                  </div>
                  <span className="stat-bar-value">{count}</span>
                </div>
              ))}

              <div className="stat-block-title" style={{ marginTop: 18 }}>
                Top Flagged Products
              </div>
              {summary && summary.top_flagged_products.length === 0 ? (
                <div className="empty-state">No flagged products - clean data set.</div>
              ) : (
                summary?.top_flagged_products.map((p) => (
                  <div className="stat-bar-row" key={p.Product}>
                    <span className="stat-bar-label">{p.Product}</span>
                    <span className="badge rejected">{p.FlaggedCount} flagged</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
