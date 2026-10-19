import type { SwpTrip, SwpTripsResponse, TripEdits } from "../api/swp";

/** What the Configure page asks for. `selectedIds` null means "every matching trip, up to the limit". */
export interface SwpConfigState {
  programId: string;
  /** Departure-date range (YYYY-MM-DD, UTC); either end may be empty. */
  dateFrom: string;
  dateTo: string;
  sensors: string[];
  selectedIds: string[] | null;
}

export const SENSOR_OPTIONS = ["Temperature", "Light", "Humidity"] as const;

export const EMPTY_SWP_CONFIG: SwpConfigState = {
  programId: "",
  dateFrom: "",
  dateTo: "",
  sensors: [...SENSOR_OPTIONS],
  selectedIds: null,
};

/** Trips whose departure date is inside the range. With no range every trip matches; with one, trips
 * without a departure date can't be placed in it and are left out. Newest departure first. */
export function matchingTrips(data: SwpTripsResponse | null, config: SwpConfigState): SwpTrip[] {
  const trips = data?.trips ?? [];
  const filtered = trips.filter((t) => {
    if (!config.dateFrom && !config.dateTo) return true;
    const day = t.departure?.slice(0, 10);
    if (!day) return false;
    return (!config.dateFrom || day >= config.dateFrom) && (!config.dateTo || day <= config.dateTo);
  });
  return [...filtered].sort((a, b) => (b.departure ?? "").localeCompare(a.departure ?? ""));
}

/** The trips that will be loaded: the ticked ones, or by default the newest matching ones up to the limit. */
export function selectedTrips(data: SwpTripsResponse | null, config: SwpConfigState): SwpTrip[] {
  const matches = matchingTrips(data, config);
  if (config.selectedIds === null) return matches.slice(0, data?.max_trips ?? matches.length);
  const picked = new Set(config.selectedIds);
  return matches.filter((t) => picked.has(t.trip_id));
}

/** A trip with the changes made in the app laid over what SWP returned. */
export function withEdit(trip: SwpTrip, edits: TripEdits): SwpTrip & { edited: boolean } {
  const edit = edits[trip.trip_id];
  if (!edit) return { ...trip, edited: false };
  return {
    ...trip,
    status: edit.status ?? trip.status,
    departure: edit.departure ?? trip.departure,
    arrival: edit.arrival ?? trip.arrival,
    edited: true,
  };
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "–";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** ISO text -> the "YYYY-MM-DDTHH:mm" a datetime-local input wants (local time). */
export function toInputValue(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** A datetime-local value -> ISO UTC text ("" if it isn't a valid date). */
export function fromInputValue(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString();
}
