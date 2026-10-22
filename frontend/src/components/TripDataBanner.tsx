import { useContext } from "react";
import { TripDataContext } from "../context/tripData";
import "./ApiProgress.css";

/** Shown while the rest of the trip data is still being fetched in the background (nothing when it is complete). */
export default function TripDataBanner({ audit = false }: { audit?: boolean }) {
  const { ready, loaded, total, error } = useContext(TripDataContext);
  if (ready) return null;
  const pct = total ? Math.round((loaded / total) * 100) : 0;
  return (
    <div className="api-progress" role="status" aria-live="polite">
      <div className="api-progress__text">
        {error ? (
          <>Could not finish loading the trip data: {error}. Go back to Configure and load the trips again.</>
        ) : (
          <>
            Loading the rest of the trip data in the background: <strong>{loaded} / {total}</strong> trips.{" "}
            {audit ? "The Audit opens when it is complete." : "You can keep working here; the Audit opens when it is complete."}
          </>
        )}
      </div>
      {!error && (
        <div className="api-progress__bar" aria-hidden="true">
          <div className="api-progress__fill" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}
