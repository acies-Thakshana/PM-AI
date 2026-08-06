import { useMemo, useState } from "react";
import type { TripSummary } from "../api/client";
import { FLAG_LABELS, FLAG_SEVERITY } from "../constants/flags";

interface Props {
  trips: TripSummary[];
}

const ALL = "All";

export default function TripsTable({ trips }: Props) {
  const [source, setSource] = useState(ALL);
  const [product, setProduct] = useState(ALL);
  const [flag, setFlag] = useState(ALL);

  const sources = useMemo(() => [ALL, ...new Set(trips.map((t) => t.Source))], [trips]);
  const products = useMemo(() => [ALL, ...new Set(trips.map((t) => t.Product))], [trips]);
  const flags = useMemo(() => [ALL, ...new Set(trips.map((t) => t.Flag))], [trips]);

  const filtered = trips.filter(
    (t) => (source === ALL || t.Source === source) && (product === ALL || t.Product === product) && (flag === ALL || t.Flag === flag)
  );

  return (
    <div className="panel">
      <h2>
        All Shipments
        <span className="hint">{filtered.length} of {trips.length} trips</span>
      </h2>
      <div className="filter-row">
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          {sources.map((s) => (
            <option key={s} value={s}>
              Source: {s}
            </option>
          ))}
        </select>
        <select value={product} onChange={(e) => setProduct(e.target.value)}>
          {products.map((p) => (
            <option key={p} value={p}>
              Product: {p}
            </option>
          ))}
        </select>
        <select value={flag} onChange={(e) => setFlag(e.target.value)}>
          {flags.map((f) => (
            <option key={f} value={f}>
              Status: {FLAG_LABELS[f] ?? f}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">No trips match these filters.</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Trip</th>
                <th>Source</th>
                <th>Product</th>
                <th>Origin</th>
                <th>Destination</th>
                <th>Status</th>
                <th>Flag</th>
                <th>% In Spec</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.TripID}>
                  <td>{t.TripID}</td>
                  <td>{t.Source}</td>
                  <td>{t.Product}</td>
                  <td>{t.Origin}</td>
                  <td>{t.Destination}</td>
                  <td>{t.Status}</td>
                  <td>
                    <span className={`badge ${FLAG_SEVERITY[t.Flag] === "bad" ? "rejected" : FLAG_SEVERITY[t.Flag] === "warn" ? "warn" : "accepted"}`}>
                      {FLAG_LABELS[t.Flag] ?? t.Flag}
                    </span>
                  </td>
                  <td>{t.CompliancePct != null ? `${t.CompliancePct}%` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
