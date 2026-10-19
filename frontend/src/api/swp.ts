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
  /** When the list was fetched from SWP (ISO), and whether this answer reused that earlier fetch. */
  fetched_at: string;
  from_cache: boolean;
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
  /** Made up by the page so it can follow this load's API calls with fetchProgress. */
  progress_id?: string;
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
  /** The SWP trip GUID (Inspect is keyed by it); `trip_number` is the numeric Trip ID of the export. */
  trip_id: string;
  trip_number: string | null;
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
export async function fetchAllTrips(programId: string, refresh = false, progressId?: string): Promise<SwpTripsResponse> {
  const query = new URLSearchParams();
  if (progressId) query.set("progress_id", progressId);
  if (programId.trim()) query.set("program_id", programId.trim());
  if (refresh) query.set("refresh", "true");
  const qs = query.toString();
  const response = await apiFetch(`${API_BASE_URL}/api/swp/trips${qs ? `?${qs}` : ""}`);
  if (!response.ok) throw await failure(response, "Could not fetch the trips from the SWP API");
  return response.json();
}

export interface SwpProgress {
  done: number;
  total: number;
  label: string;
  finished: boolean;
}

/** SWP API calls made so far / expected for the operation that was started with this progress id. */
export async function fetchProgress(progressId: string): Promise<SwpProgress> {
  const response = await apiFetch(`${API_BASE_URL}/api/swp/progress/${encodeURIComponent(progressId)}`);
  if (!response.ok) throw await failure(response, "Could not read the progress");
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

export interface SwpTimesResult {
  /** The new times as CET wall-clock text, as shown in the audit table. */
  departure: string | null;
  arrival: string | null;
  /** The same instants in UTC, the form the Trips page keeps its edits in. */
  departure_utc: string | null;
  arrival_utc: string | null;
  segment_days: number | null;
}

/** Change a trip's departure and / or arrival in this session's data (CET wall-clock "YYYY-MM-DDTHH:mm"). The app's
 * data changes; nothing is sent to SWP. */
export async function patchTripTimes(
  sessionId: string,
  tripKey: string,
  times: { departure?: string; arrival?: string }
): Promise<SwpTimesResult> {
  const response = await apiFetch(`${API_BASE_URL}/api/swp/${sessionId}/trips/${tripKey}/times`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(times),
  });
  if (!response.ok) throw await failure(response, "Could not change the times");
  return response.json();
}

export async function fetchTripRaw(sessionId: string, tripId: string): Promise<SwpTripRaw> {
  const response = await apiFetch(`${API_BASE_URL}/api/swp/${sessionId}/trips/${tripId}/raw`);
  if (!response.ok) throw await failure(response, "Could not load the raw readings");
  return response.json();
}
