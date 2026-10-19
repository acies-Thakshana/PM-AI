import { useEffect, useState } from "react";
import { fetchSessionTrips } from "../api/swp";
import type { SwpSessionTrip, SwpTimesResult } from "../api/swp";
import Modal from "./Modal";
import TripInspectView from "./TripInspectView";
import TripTimesEditor from "./TripTimesEditor";
import { formatDateTime } from "../utils/swpTrips";
import "./TripInspectView.css";

interface TripInspectModalProps {
  sessionId: string;
  /** The trip, by its SWP key (GUID) or by the numeric Trip ID that the outlier tables show. */
  tripKey?: string;
  tripNumber?: string;
  /** Bumped whenever the audited data changed, so the numbers shown here are read again. */
  dataVersion: number;
  onClose: () => void;
  onTimesSaved: (tripKey: string, result: SwpTimesResult) => void;
}

/** One trip in detail: its departure and arrival (editable), the route on a map and every raw sensor reading in one chart. */
export default function TripInspectModal({ sessionId, tripKey, tripNumber, dataVersion, onClose, onTimesSaved }: TripInspectModalProps) {
  const [trip, setTrip] = useState<SwpSessionTrip | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    fetchSessionTrips(sessionId)
      .then((list) => {
        if (!live) return;
        const found = list.find((t) => (tripKey ? t.trip_id === tripKey : t.trip_number === tripNumber));
        if (found) setTrip(found);
        else setError("This trip is not in the audited data any more.");
      })
      .catch((err) => live && setError(err instanceof Error ? err.message : "Could not load the trip."));
    return () => {
      live = false;
    };
  }, [sessionId, tripKey, tripNumber, dataVersion]);

  const title = `Trip ${trip?.trip_number ?? tripNumber ?? tripKey ?? ""}`;
  return (
    <Modal title={title} onClose={onClose} panelClassName="trip-inspect-modal" resetScrollKey={trip?.trip_id ?? tripKey ?? tripNumber}>
      {error && <p className="trip-inspect__error">{error}</p>}
      {!error && !trip && <p className="trip-inspect__note">Loading…</p>}
      {trip && (
        <>
          <p className="trip-inspect__note">
            {trip.status ?? "–"} · departs {formatDateTime(trip.departure)} · arrives {formatDateTime(trip.arrival)}
            {trip.segment_days != null && <> · {trip.segment_days} segment days</>}
            {trip.mean_temp != null && <> · mean {trip.mean_temp} °C</>}
          </p>
          <TripTimesEditor
            key={`${trip.trip_id}:${trip.departure}:${trip.arrival}`}
            sessionId={sessionId}
            tripKey={trip.trip_id}
            departure={trip.departure}
            arrival={trip.arrival}
            onSaved={(result) => {
              setTrip({ ...trip, departure: result.departure, arrival: result.arrival, segment_days: result.segment_days, edited: true });
              onTimesSaved(trip.trip_id, result);
            }}
          />
          <TripInspectView sessionId={sessionId} tripId={trip.trip_id} />
        </>
      )}
    </Modal>
  );
}
