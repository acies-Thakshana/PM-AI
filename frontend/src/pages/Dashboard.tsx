import { useEffect, useState } from "react";
import {
  fetchCommodityRisk,
  fetchExcursions,
  fetchFacilities,
  fetchKpis,
  fetchShipments,
  type CommodityRisk,
  type FacilityRanking,
  type KpiSummary,
  type ShipmentSummary,
} from "../api/client";
import CommodityRiskChart from "../components/CommodityRiskChart";
import ExcursionAlertsTable from "../components/ExcursionAlertsTable";
import FacilityRankingChart from "../components/FacilityRankingChart";
import GenerateReportPanel from "../components/GenerateReportPanel";
import KpiCard from "../components/KpiCard";
import TempHumidityChart from "../components/TempHumidityChart";

const REFRESH_MS = 20000;

export default function Dashboard() {
  const [kpis, setKpis] = useState<KpiSummary | null>(null);
  const [shipments, setShipments] = useState<ShipmentSummary[]>([]);
  const [facilities, setFacilities] = useState<FacilityRanking[]>([]);
  const [commodityRisk, setCommodityRisk] = useState<CommodityRisk[]>([]);
  const [excursions, setExcursions] = useState<ShipmentSummary[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      Promise.all([
        fetchKpis(),
        fetchShipments(),
        fetchFacilities(),
        fetchCommodityRisk(),
        fetchExcursions(),
      ])
        .then(([k, s, f, c, e]) => {
          setKpis(k);
          setShipments(s);
          setFacilities(f);
          setCommodityRisk(c);
          setExcursions(e);
          setLastUpdated(new Date());
          setLoadError(null);
        })
        .catch((err) => {
          setLoadError(
            err?.code === "ERR_NETWORK"
              ? "Can't reach the backend API at http://localhost:8000 - is it running?"
              : `Failed to load dashboard data: ${err?.message ?? err}`
          );
        });
    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-shell">
      <div className="app-header">
        <div>
          <h1>Cold Chain / Post-Harvest Assessment Program</h1>
          <div className="subtitle">
            <span className="live-dot" />
            Live from backend data{lastUpdated ? ` - last refreshed ${lastUpdated.toLocaleTimeString()}` : ""}
          </div>
        </div>
      </div>

      {loadError && <div className="error-box" style={{ marginBottom: 16 }}>{loadError}</div>}

      <GenerateReportPanel />

      {kpis && (
        <div className="kpi-row">
          <KpiCard
            label="Temperature Compliance"
            value={`${kpis.avg_temperature_compliance_pct}%`}
            target={`${kpis.targets["Temperature Compliance Rate"]}%`}
            status={kpis.avg_temperature_compliance_pct >= kpis.targets["Temperature Compliance Rate"] ? "on_target" : "at_risk"}
          />
          <KpiCard
            label="Avg Arrival Spoilage"
            value={`${kpis.avg_spoilage_pct}%`}
            target={`<= ${kpis.targets["Maximum Acceptable Spoilage"]}%`}
            status={kpis.avg_spoilage_pct > kpis.targets["Maximum Acceptable Spoilage"] ? "at_risk" : "on_target"}
          />
          <KpiCard
            label="Green Life Retention"
            value={`${kpis.avg_green_life_retention_pct}%`}
            target={`>= ${kpis.targets["Minimum Green Life Retention"]}%`}
            status={kpis.avg_green_life_retention_pct < kpis.targets["Minimum Green Life Retention"] ? "at_risk" : "on_target"}
          />
          <KpiCard
            label="At-Risk Shipments"
            value={String(kpis.at_risk_shipment_count)}
            target="0"
            status={kpis.at_risk_shipment_count > 0 ? "at_risk" : "on_target"}
          />
          <KpiCard
            label="In Transit Now"
            value={String(kpis.shipments_in_transit)}
            target="-"
            status="on_target"
          />
        </div>
      )}

      <div className="panel-grid">
        <TempHumidityChart shipments={shipments} />
        <ExcursionAlertsTable alerts={excursions} />
      </div>

      <div className="panel-grid">
        <FacilityRankingChart facilities={facilities} />
        <CommodityRiskChart risk={commodityRisk} />
      </div>
    </div>
  );
}
