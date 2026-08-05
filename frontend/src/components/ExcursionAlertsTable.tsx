import type { ShipmentSummary } from "../api/client";

interface Props {
  alerts: ShipmentSummary[];
}

export default function ExcursionAlertsTable({ alerts }: Props) {
  return (
    <div className="panel">
      <h2>
        Excursion Alerts
        <span className="hint">shipments exceeding excursion or door-open thresholds</span>
      </h2>
      {alerts.length === 0 ? (
        <div className="empty-state">No active alerts.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Shipment</th>
              <th>Commodity</th>
              <th>Facility</th>
              <th>Excursion (deg-hrs)</th>
              <th>Door Opens</th>
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.ShipmentID}>
                <td>{a.ShipmentID}</td>
                <td>{a.Commodity}</td>
                <td>{a.DestinationFacility}</td>
                <td>{a.ExcursionDegHours?.toFixed(1) ?? "-"}</td>
                <td>{a.DoorOpenEvents ?? "-"}</td>
                <td>
                  {a.RejectionReason && a.RejectionReason !== "None - Accepted" ? (
                    <span className="badge rejected">{a.RejectionReason}</span>
                  ) : a.TransitStatus === "In Transit" ? (
                    <span className="badge accepted">In Transit</span>
                  ) : (
                    <span className="badge accepted">Accepted</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
