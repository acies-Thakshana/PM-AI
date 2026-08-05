import axios from "axios";

const API_BASE = "http://localhost:8000";

export const api = axios.create({ baseURL: API_BASE });

export interface KpiSummary {
  shipments_assessed: number;
  shipments_in_transit: number;
  avg_temperature_compliance_pct: number;
  avg_spoilage_pct: number;
  avg_green_life_retention_pct: number;
  at_risk_shipment_count: number;
  targets: Record<string, number>;
}

export interface ShipmentSummary {
  ShipmentID: string;
  Commodity: string;
  OriginFarm: string;
  DestinationFacilityID: string;
  DestinationFacility: string;
  TransitStatus: string;
  DistanceKM: number;
  QuantityKG: number;
  CompliancePct: number | null;
  ExcursionDegHours: number | null;
  MaxDeltaC: number | null;
  DoorOpenEvents: number | null;
  SpoilagePct: number | null;
  GreenLifeRemainingDays: number | null;
  ArrivalGradeScore: number | null;
  RejectionReason: string | null;
}

export interface SensorReading {
  ReadingID: string;
  ShipmentID: string;
  Timestamp: number;
  TemperatureC: number;
  HumidityPct: number;
  CheckpointLocation: string;
  DoorOpenEvent: "Y" | "N";
}

export interface SensorSeries {
  shipment_id: string;
  commodity: string;
  target_temp_min: number;
  target_temp_max: number;
  target_humidity_min: number;
  target_humidity_max: number;
  transit_status: string;
  readings: SensorReading[];
}

export interface FacilityRanking {
  FacilityID: string;
  DestinationFacilityID: string;
  DestinationFacility: string;
  ShipmentCount: number;
  AvgCompliancePct: number;
  AvgSpoilagePct: number;
  AvgExcursionDegHours: number;
  FacilityType: string;
  RefrigerationSystemType: string;
  InstallYear: number;
}

export interface CommodityRisk {
  Commodity: string;
  ShipmentCount: number;
  AvgSpoilagePct: number;
  AvgGreenLifeRetentionPct: number;
  AvgExcursionDegHours: number;
}

export interface ReportJob {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  stage_label: string;
  created_at: string;
  file_path: string | null;
  file_name: string | null;
  error: string | null;
  tool_calls?: number;
}

export const fetchKpis = () => api.get<KpiSummary>("/api/dashboard/kpis").then((r) => r.data);

export const fetchShipments = () =>
  api.get<ShipmentSummary[]>("/api/dashboard/shipments").then((r) => r.data);

export const fetchSensorSeries = (shipmentId: string) =>
  api.get<SensorSeries>(`/api/dashboard/shipments/${shipmentId}/sensor-series`).then((r) => r.data);

export const fetchFacilities = () =>
  api.get<FacilityRanking[]>("/api/dashboard/facilities").then((r) => r.data);

export const fetchExcursions = () =>
  api.get<ShipmentSummary[]>("/api/dashboard/excursions").then((r) => r.data);

export const fetchCommodityRisk = () =>
  api.get<CommodityRisk[]>("/api/dashboard/commodity-risk").then((r) => r.data);

export const startReportGeneration = () =>
  api.post<{ job_id: string }>("/api/report/generate").then((r) => r.data.job_id);

export const fetchReportStatus = (jobId: string) =>
  api.get<ReportJob>(`/api/report/status/${jobId}`).then((r) => r.data);

export const downloadReportUrl = (jobId: string) => `${API_BASE}/api/report/download/${jobId}`;
