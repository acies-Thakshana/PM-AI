import { API_BASE_URL, apiFetch } from "./apiFetch";

export class SwpApiError extends Error {}

export interface SwpTrip {
  trip_id: string;
  status: string;
  created: string | null;
  updated: string | null;
  alarmed: boolean | null;
  template: string | null;
  trailer_id: string | null;
}

export interface SwpTripsResponse {
  total: number;
  status_counts: Record<string, number>;
  max_trips: number;
  trips: SwpTrip[];
}

export interface SwpLoadRequest {
  status: string | null;
  n_trips: number;
  trip_ids: string[];
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
  sensors: string[];
  readings: number;
}

export interface SwpSensorSeries {
  sensor: string;
  serial_number: string | null;
  x: string[];
  y: number[];
}

export interface SwpTripRaw {
  trip_id: string;
  series: SwpSensorSeries[];
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

/** Step 1: every trip in the program. `refresh` skips the backend's short-lived cache. */
export async function fetchAllTrips(refresh = false): Promise<SwpTripsResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/swp/trips${refresh ? "?refresh=true" : ""}`);
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
