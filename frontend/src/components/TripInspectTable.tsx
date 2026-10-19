import { useEffect, useState } from "react";
import { fetchSessionTrips } from "../api/swp";
import type { SwpSessionTrip } from "../api/swp";
import { formatDateTime } from "../utils/swpTrips";
import Modal from "./Modal";
import TripInspectView from "./TripInspectView";
import "./TripInspectTable.css";

interface TripInspectTableProps {
  sessionId: string;
}

/** The trips of the audited data, each with its mean temperature and segment days and an Inspect button
 * that opens the trip's raw sensor graph and route map. */
export default function TripInspectTable({ sessionId }: TripInspectTableProps) {
  const [trips, setTrips] = useState<SwpSessionTrip[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);

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

  return (
    <div className="trip-table">
      <div className="trip-table__wrap">
        <table>
          <thead>
            <tr>
              <th>Trip ID</th>
              <th>Status</th>
              <th>Departure</th>
              <th>Arrival</th>
              <th className="trip-table__num">Mean Temp (°C)</th>
              <th className="trip-table__num">Segment Days</th>
              <th aria-label="Inspect" />
            </tr>
          </thead>
          <tbody>
            {trips.map((t) => (
              <tr key={t.trip_id}>
                <td className="trip-table__id">{t.trip_id}</td>
                <td>
                  {t.status ?? "–"}
                  {t.edited && <span className="trip-table__edited"> edited</span>}
                </td>
                <td>{formatDateTime(t.departure)}</td>
                <td>{formatDateTime(t.arrival)}</td>
                <td className="trip-table__num">{t.mean_temp ?? "–"}</td>
                <td className="trip-table__num">{t.segment_days ?? "–"}</td>
                <td>
                  <button
                    type="button"
                    className="btn btn--secondary btn--small"
                    onClick={() => setInspecting(t.trip_id)}
                    disabled={t.readings === 0 && t.gps_points === 0}
                    title={t.readings === 0 && t.gps_points === 0 ? "No sensor readings or GPS points for this trip" : undefined}
                  >
                    Inspect
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {inspecting && (
        <Modal title={`Trip ${inspecting}`} onClose={() => setInspecting(null)} panelClassName="trip-inspect-modal" resetScrollKey={inspecting}>
          <TripInspectView sessionId={sessionId} tripId={inspecting} />
        </Modal>
      )}
    </div>
  );
}
