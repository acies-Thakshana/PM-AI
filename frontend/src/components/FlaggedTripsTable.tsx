import type { TripSummary } from "../api/client";
import { FLAG_LABELS, FLAG_SEVERITY } from "../constants/flags";

interface Props {
  trips: TripSummary[];
}

export default function FlaggedTripsTable({ trips }: Props) {
  return (
    <div className="panel">
      <h2>
        Flagged Trips
        <span className="hint">trips a PM would need to review before this data goes into a report</span>
      </h2>
      {trips.length === 0 ? (
        <div className="empty-state">No flagged trips.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Trip</th>
              <th>Source</th>
              <th>Product</th>
              <th>Destination</th>
              <th>Issue</th>
              <th>Compliance</th>
            </tr>
          </thead>
          <tbody>
            {trips.map((t) => (
              <tr key={t.TripID}>
                <td>{t.TripID}</td>
                <td>{t.Source}</td>
                <td>{t.Product}</td>
                <td>{t.Destination}</td>
                <td>
                  <span className={`badge ${FLAG_SEVERITY[t.Flag] === "bad" ? "rejected" : "accepted"}`}>
                    {FLAG_LABELS[t.Flag] ?? t.Flag}
                  </span>
                </td>
                <td>{t.CompliancePct != null ? `${t.CompliancePct}%` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
