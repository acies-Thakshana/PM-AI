import { createContext } from "react";

/** Whether the trips loaded from SWP are all in the session yet. After "Load" the session first holds the trips fetched so
 * far, so the Planner can start; the rest are fetched in the background and the Audit waits for them. */
export interface TripDataState {
  ready: boolean;
  loaded: number;
  total: number;
  error: string | null;
}

export const TripDataContext = createContext<TripDataState>({ ready: true, loaded: 0, total: 0, error: null });
