import { useState } from "react";
import { patchTripTimes } from "../api/swp";
import type { SwpTimesResult } from "../api/swp";
import { toInputValue } from "../utils/swpTrips";
import "./TripTimesEditor.css";

interface TripTimesEditorProps {
  sessionId: string;
  tripKey: string;
  departure: string | null;
  arrival: string | null;
  /** Called after the change was saved, with the new times. */
  onSaved: (result: SwpTimesResult) => void;
}

/** Departure and arrival time (CET) of one trip, editable. Saving changes the trip's times and segment length in
 * the audit data; nothing is sent to SWP. */
export default function TripTimesEditor({ sessionId, tripKey, departure, arrival, onSaved }: TripTimesEditorProps) {
  const [draft, setDraft] = useState({ departure: toInputValue(departure), arrival: toInputValue(arrival) });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const changed = draft.departure !== toInputValue(departure) || draft.arrival !== toInputValue(arrival);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const times: { departure?: string; arrival?: string } = {};
      if (draft.departure && draft.departure !== toInputValue(departure)) times.departure = draft.departure;
      if (draft.arrival && draft.arrival !== toInputValue(arrival)) times.arrival = draft.arrival;
      onSaved(await patchTripTimes(sessionId, tripKey, times));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the times.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="trip-times">
      <label className="trip-times__field">
        <span>Departure (CET)</span>
        <input type="datetime-local" value={draft.departure} onChange={(e) => setDraft({ ...draft, departure: e.target.value })} />
      </label>
      <label className="trip-times__field">
        <span>Arrival (CET)</span>
        <input type="datetime-local" value={draft.arrival} onChange={(e) => setDraft({ ...draft, arrival: e.target.value })} />
      </label>
      <button type="button" className="btn btn--primary btn--small" onClick={save} disabled={!changed || saving}>
        {saving ? "Saving…" : "Save times"}
      </button>
      <span className="trip-times__hint">Changes this app's data only; nothing is sent to SWP.</span>
      {error && <span className="trip-times__error">{error}</span>}
    </div>
  );
}
