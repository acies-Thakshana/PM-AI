import { useEffect, useState } from "react";
import { fetchTrips, type TripSummary } from "../../api/client";
import ShipmentMap from "../../components/ShipmentMap";
import TripTempChart from "../../components/TripTempChart";
import { FLAG_DESCRIPTIONS, FLAG_LABELS, FLAG_SEVERITY } from "../../constants/flags";

export default function ShipmentAssessment() {
  const [trips, setTrips] = useState<TripSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchTrips()
      .then(setTrips)
      .catch((err) => setLoadError(`Failed to load trips: ${err?.message ?? err}`));
  }, []);

  useEffect(() => {
    if (!selected && trips.length > 0) {
      const flagged = trips.find((t) => t.Flag !== "closed" && t.Flag !== "clean" && t.Flag !== "active");
      setSelected((flagged ?? trips[0]).TripID);
    }
  }, [trips, selected]);

  if (loadError) return <div className="error-box">{loadError}</div>;
  if (trips.length === 0) return <div className="empty-state">No trips loaded yet.</div>;

  const trip = trips.find((t) => t.TripID === selected);
  const severity = trip ? FLAG_SEVERITY[trip.Flag] ?? "ok" : "ok";

  return (
    <div>
      <div className="panel-grid">
        <TripTempChart trips={trips} selected={selected} onSelectChange={setSelected} />

        <div className="panel">
          <h2>
            Trip Detail
            <span className="hint">key facts + root cause for the selected trip</span>
          </h2>
          {trip && (
            <div className="fact-list">
              <div className="fact-row">
                <span>Trip</span>
                <strong>{trip.TripID}</strong>
              </div>
              <div className="fact-row">
                <span>Source</span>
                <strong>{trip.Source}</strong>
              </div>
              <div className="fact-row">
                <span>Product</span>
                <strong>{trip.Product}</strong>
              </div>
              <div className="fact-row">
                <span>Lane</span>
                <strong>
                  {trip.Origin} to {trip.Destination}
                </strong>
              </div>
              <div className="fact-row">
                <span>Status</span>
                <strong>{trip.Status}</strong>
              </div>
              <div className="fact-row">
                <span>% Time In Spec</span>
                <strong>{trip.CompliancePct != null ? `${trip.CompliancePct}%` : "-"}</strong>
              </div>
              <div className="fact-row">
                <span>% Humidity In Spec</span>
                <strong>{trip.HumidityCompliancePct != null ? `${trip.HumidityCompliancePct}%` : "-"}</strong>
              </div>
              {trip.DistanceToDestinationKm != null && (
                <div className="fact-row">
                  <span>Distance To Destination</span>
                  <strong>{trip.DistanceToDestinationKm} km</strong>
                </div>
              )}
              {trip.CustomerConfirmation && (
                <div className="fact-row">
                  <span>Customer Confirmation</span>
                  <strong>{trip.CustomerConfirmation.replace("_", " ")}</strong>
                </div>
              )}
              <div className="fact-row">
                <span>Flag</span>
                <span className={`badge ${severity === "bad" ? "rejected" : severity === "warn" ? "warn" : "accepted"}`}>
                  {FLAG_LABELS[trip.Flag] ?? trip.Flag}
                </span>
              </div>
              <p className="flag-explanation">{FLAG_DESCRIPTIONS[trip.Flag]}</p>
            </div>
          )}
        </div>
      </div>

      {trip && <ShipmentMap trips={[trip]} title="Trip Lane" />}
    </div>
  );
}
