import axios from "axios";

const API_BASE = "http://localhost:8000";

export const api = axios.create({ baseURL: API_BASE });

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

export const startReportGeneration = () =>
  api.post<{ job_id: string }>("/api/report/generate").then((r) => r.data.job_id);

export const fetchReportStatus = (jobId: string) =>
  api.get<ReportJob>(`/api/report/status/${jobId}`).then((r) => r.data);

export const downloadReportUrl = (jobId: string) => `${API_BASE}/api/report/download/${jobId}`;

// --- Phase 2: data ingestion ---

export type IngestSource = "sensiwatch" | "coldstream" | "customer-profile" | "business-rules";

export interface TripFlagCounts {
  [flag: string]: number;
}

export interface TripIngestResult {
  source: "sensiwatch" | "coldstream";
  trip_count: number;
  reading_count: number;
  flags: TripFlagCounts;
}

export interface CustomerProfileIngestResult {
  source: "customer_profile";
  char_count: number;
  section_count: number;
  confirmed_trip_count: number;
}

export interface BusinessRulesIngestResult {
  source: "business_rules";
  product_count: number;
  standard_kpi_count: number;
  customer_kpi_count: number;
}

export type IngestResult = TripIngestResult | CustomerProfileIngestResult | BusinessRulesIngestResult;

export interface IngestStatus {
  sensiwatch: Omit<TripIngestResult, "source"> | null;
  coldstream: Omit<TripIngestResult, "source"> | null;
  customer_profile_loaded: boolean;
  business_rules_loaded: boolean;
}

export const loadSampleData = (source: IngestSource) =>
  api.post<IngestResult>(`/api/ingest/${source}/load-sample`).then((r) => r.data);

export const uploadData = (source: IngestSource, file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return api
    .post<IngestResult>(`/api/ingest/${source}`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export const fetchIngestStatus = () => api.get<IngestStatus>("/api/ingest/status").then((r) => r.data);

// --- Phase 2: dashboard-over-uploaded-trip-data ---

export interface TripKpiSummary {
  trips_loaded: number;
  avg_compliance_pct: number | null;
  flagged_trip_count: number;
  active_trip_count: number;
  likely_arrived_count: number;
  stuck_trip_count: number;
  sources_loaded: string[];
}

export interface TripSummary {
  TripID: string;
  Source: "SensiWatch" | "ColdStream";
  Product: string;
  Origin: string;
  Destination: string;
  OriginLat: number | null;
  OriginLon: number | null;
  DestinationLat: number | null;
  DestinationLon: number | null;
  Status: string;
  Flag: string;
  DistanceToDestinationKm: number | null;
  CustomerConfirmation: string | null;
  CompliancePct: number | null;
  HumidityCompliancePct: number | null;
  CreatedDate: number | null;
  ReadingCount: number;
}

export interface TripSensorReading {
  ReadingID: string;
  TripID: string;
  Timestamp: number;
  TemperatureC: number;
  HumidityPct: number;
}

export interface TripSensorSeries {
  trip_id: string;
  source: string;
  product: string;
  target_temp_min: number;
  target_temp_max: number;
  readings: TripSensorReading[];
}

export interface ProductRisk {
  Product: string;
  TripCount: number;
  AvgCompliancePct: number;
  FlaggedCount: number;
}

export interface DestinationRanking {
  Destination: string;
  TripCount: number;
  AvgCompliancePct: number;
  FlaggedCount: number;
}

export const fetchTripKpis = () => api.get<TripKpiSummary>("/api/trips/kpis").then((r) => r.data);

export const fetchTrips = () => api.get<TripSummary[]>("/api/trips").then((r) => r.data);

export const fetchTripSensorSeries = (tripId: string) =>
  api.get<TripSensorSeries>(`/api/trips/${tripId}/sensor-series`).then((r) => r.data);

export const fetchFlaggedTrips = () => api.get<TripSummary[]>("/api/trips/flagged").then((r) => r.data);

export const fetchProductRisk = () => api.get<ProductRisk[]>("/api/trips/product-risk").then((r) => r.data);

export const fetchDestinationRanking = () =>
  api.get<DestinationRanking[]>("/api/trips/destination-ranking").then((r) => r.data);

// --- Phase 4: executive summary / RCA / bloom risk ---

export interface ExecutiveSummary {
  customer: string;
  kpis: TripKpiSummary;
  by_source: Record<string, number>;
  top_flagged_products: ProductRisk[];
}

export interface RcaGroup {
  flag: string;
  category: string;
  label: string;
  description: string;
  trip_count: number;
  trips: { TripID: string; Product: string; Destination: string; CompliancePct: number | null }[];
}

export interface BloomRisk {
  Product: string;
  TripCount: number;
  BloomRiskScore: number;
  TargetMax: number;
}

export const fetchExecutiveSummary = () => api.get<ExecutiveSummary>("/api/trips/executive-summary").then((r) => r.data);

export const fetchRca = () => api.get<RcaGroup[]>("/api/trips/rca").then((r) => r.data);

export const fetchBloomRisk = () => api.get<BloomRisk[]>("/api/trips/bloom-risk").then((r) => r.data);
