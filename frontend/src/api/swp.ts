import { API_BASE_URL, apiFetch } from "./apiFetch";

export class SwpApiError extends Error {}

export interface SwpTrip {
  trip_id: string;
  status: string;
  departure: string | null;
  arrival: string | null;
  created: string | null;
  updated: string | null;
  alarmed: boolean | null;
  template: string | null;
  trailer_id: string | null;
}

export interface SwpTripsResponse {
  program_id: string;
  total: number;
  status_counts: Record<string, number>;
  max_trips: number;
  trips: SwpTrip[];
  /** Field names of one trip-list record (helps when a departure date is missing). */
  sample_fields: string[];
}

/** A change made in the app only (nothing is written back to SWP): status label, departure / arrival (ISO UTC). */
export interface TripEdit {
  status?: string;
  departure?: string;
  arrival?: string;
}
export type TripEdits = Record<string, TripEdit>;

export interface SwpLoadRequest {
  program_id: string | null;
  trip_ids: string[];
  sensors: string[];
  edits: TripEdits;
}

export interface SwpLoadResponse {
  session_id: string;
  filename: string;
  row_count: number;
  column_count: number;
  columns: string[];
  trip_ids: string[];
}

export interface SwpSessionTrip {
  trip_id: string;
  status: string | null;
  departure: string | null;
  arrival: string | null;
  mean_temp: number | null;
  segment_days: number | null;
  sensors: string[];
  readings: number;
  gps_points: number;
  edited: boolean;
}

export interface SwpSensorSeries {
  sensor: string;
  serial_number: string | null;
  x: string[];
  y: number[];
}

export interface SwpMapPoint {
  lat: number;
  lng: number;
  time: string | null;
}

export interface SwpTripRaw {
  trip_id: string;
  series: SwpSensorSeries[];
  route: SwpMapPoint[];
  start: SwpMapPoint | null;
  end: SwpMapPoint | null;
}

async function failure(response: Response, fallback: string): Promise<SwpApiError> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return new SwpApiError(body.detail);
  } catch {
    /* keep the fallback */
  }
  return new SwpApiError(`${fallback} (${response.status}).`);
}

/** Step 1: every trip of the program (empty program id = the backend's default). `refresh` skips its short-lived cache. */
export async function fetchAllTrips(programId: string, refresh = false): Promise<SwpTripsResponse> {
  const query = new URLSearchParams();
  if (programId.trim()) query.set("program_id", programId.trim());
  if (refresh) query.set("refresh", "true");
  const qs = query.toString();
  const response = await apiFetch(`${API_BASE_URL}/api/swp/trips${qs ? `?${qs}` : ""}`);
  if (!response.ok) throw await failure(response, "Could not fetch the trips from the SWP API");
  return response.json();
}

/** Step 2: fetch the chosen trips in detail and open an audit session on them. */
export async function loadTrips(request: SwpLoadRequest): Promise<SwpLoadResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/swp/load`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw await failure(response, "Could not load the trips");
  return response.json();
}

export async function fetchSessionTrips(sessionId: string): Promise<SwpSessionTrip[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/swp/${sessionId}/trips`);
  if (!response.ok) throw await failure(response, "Could not list the trips");
  return response.json();
}

export async function fetchTripRaw(sessionId: string, tripId: string): Promise<SwpTripRaw> {
  const response = await apiFetch(`${API_BASE_URL}/api/swp/${sessionId}/trips/${tripId}/raw`);
  if (!response.ok) throw await failure(response, "Could not load the raw readings");
  return response.json();
}
