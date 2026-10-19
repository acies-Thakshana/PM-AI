import { useEffect, useState } from "react";
import { fetchSessionTrips, patchTripTimes } from "../api/swp";
import type { SwpSessionTrip, SwpTimesResult } from "../api/swp";
import { formatDateTime, toInputValue } from "../utils/swpTrips";
import "./TripInspectTable.css";

interface TripInspectTableProps {
  sessionId: string;
  onInspect: (tripKey: string) => void;
  onTimesSaved: (tripKey: string, result: SwpTimesResult) => void;
}

/** Every trip of the audited data with its mean temperature and segment days, an Inspect button (graph and map)
 * and an Edit times button for its departure and arrival (CET; the app's data only, nothing goes to SWP). */
export default function TripInspectTable({ sessionId, onInspect, onTimesSaved }: TripInspectTableProps) {
  const [trips, setTrips] = useState<SwpSessionTrip[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState({ departure: "", arrival: "" });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setTrips(null);
    setError(null);
    fetchSessionTrips(sessionId)
      .then((list) => live && setTrips(list))
      .catch((err) => live && setError(err instanceof Error ? err.message : "Could not list the trips."));
    return () => {
      live = false;
    };
  }, [sessionId]);

  if (error) return <p className="trip-table__error">{error}</p>;
  if (!trips) return <p className="trip-table__note">Loading trips…</p>;
  if (trips.length === 0) return <p className="trip-table__note">No trips are left in the audited data.</p>;

  const startEdit = (t: SwpSessionTrip) => {
    setEditing(t.trip_id);
    setSaveError(null);
    setDraft({ departure: toInputValue(t.departure), arrival: toInputValue(t.arrival) });
  };

  const save = async (t: SwpSessionTrip) => {
    const times: { departure?: string; arrival?: string } = {};
    if (draft.departure && draft.departure !== toInputValue(t.departure)) times.departure = draft.departure;
    if (draft.arrival && draft.arrival !== toInputValue(t.arrival)) times.arrival = draft.arrival;
    if (Object.keys(times).length === 0) {
      setEditing(null);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const result = await patchTripTimes(sessionId, t.trip_id, times);
      setTrips((list) =>
        (list ?? []).map((x) =>
          x.trip_id === t.trip_id ? { ...x, departure: result.departure, arrival: result.arrival, segment_days: result.segment_days, edited: true } : x
        )
      );
      setEditing(null);
      onTimesSaved(t.trip_id, result);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not change the times.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="trip-table">
      {saveError && <p className="trip-table__error">{saveError}</p>}
      <div className="trip-table__wrap">
        <table>
          <thead>
            <tr>
              <th>Trip ID</th>
              <th>Status</th>
              <th>Departure (CET)</th>
              <th>Arrival (CET)</th>
              <th className="trip-table__num">Mean Temp (°C)</th>
              <th className="trip-table__num">Segment Days</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {trips.map((t) => {
              const isEditing = editing === t.trip_id;
              const noData = t.readings === 0 && t.gps_points === 0;
              return (
                <tr key={t.trip_id}>
                  <td className="trip-table__id" title={t.trip_id}>{t.trip_number ?? t.trip_id}</td>
                  <td>
                    {t.status ?? "–"}
                    {t.edited && <span className="trip-table__edited"> edited</span>}
                  </td>
                  <td>
                    {isEditing ? (
                      <input type="datetime-local" aria-label="Departure" value={draft.departure} onChange={(e) => setDraft({ ...draft, departure: e.target.value })} />
                    ) : (
                      formatDateTime(t.departure)
                    )}
                  </td>
                  <td>
                    {isEditing ? (
                      <input type="datetime-local" aria-label="Arrival" value={draft.arrival} onChange={(e) => setDraft({ ...draft, arrival: e.target.value })} />
                    ) : (
                      formatDateTime(t.arrival)
                    )}
                  </td>
                  <td className="trip-table__num">{t.mean_temp ?? "–"}</td>
                  <td className="trip-table__num">{t.segment_days ?? "–"}</td>
                  <td className="trip-table__actions">
                    {isEditing ? (
                      <>
                        <button type="button" className="btn btn--primary btn--small" onClick={() => save(t)} disabled={saving}>
                          {saving ? "Saving…" : "Save"}
                        </button>
                        <button type="button" className="btn btn--secondary btn--small" onClick={() => setEditing(null)} disabled={saving}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="btn btn--secondary btn--small"
                          onClick={() => onInspect(t.trip_id)}
                          disabled={noData}
                          title={noData ? "No sensor readings or GPS points for this trip" : "Graph and map"}
                        >
                          Inspect
                        </button>
                        <button type="button" className="btn btn--secondary btn--small" onClick={() => startEdit(t)}>
                          Edit times
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
