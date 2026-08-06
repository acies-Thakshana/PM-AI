import { useEffect } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { TripSummary } from "../api/client";
import { FLAG_SEVERITY } from "../constants/flags";

interface Props {
  trips: TripSummary[];
  title?: string;
}

const SEVERITY_COLOR: Record<string, string> = {
  ok: "#1b5e20",
  warn: "#f9a825",
  bad: "#b71c1c",
};
const SEVERITY_RANK: Record<string, number> = { ok: 0, warn: 1, bad: 2 };

function FitBounds({ bounds }: { bounds: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (bounds.length > 0) {
      map.fitBounds(bounds, { padding: [32, 32], maxZoom: 7 });
    }
  }, [map, bounds]);
  return null;
}

export default function ShipmentMap({ trips, title = "Shipment Routes" }: Props) {
  const geoTrips = trips.filter(
    (t) => t.OriginLat != null && t.OriginLon != null && t.DestinationLat != null && t.DestinationLon != null
  );

  if (geoTrips.length === 0) {
    return (
      <div className="panel">
        <h2>{title}</h2>
        <div className="empty-state">No geo-located trips yet.</div>
      </div>
    );
  }

  type RouteInfo = { origin: string; destination: string; positions: [number, number][]; count: number; severity: string };
  const routes = new Map<string, RouteInfo>();
  const sites = new Map<string, { lat: number; lon: number; count: number }>();

  for (const t of geoTrips) {
    const origin: [number, number] = [t.OriginLat!, t.OriginLon!];
    const destination: [number, number] = [t.DestinationLat!, t.DestinationLon!];
    const key = `${t.Origin}__${t.Destination}`;
    const severity = FLAG_SEVERITY[t.Flag] ?? "ok";
    const existing = routes.get(key);
    if (existing) {
      existing.count += 1;
      if (SEVERITY_RANK[severity] > SEVERITY_RANK[existing.severity]) existing.severity = severity;
    } else {
      routes.set(key, { origin: t.Origin, destination: t.Destination, positions: [origin, destination], count: 1, severity });
    }

    for (const [site, lat, lon] of [
      [t.Origin, origin[0], origin[1]],
      [t.Destination, destination[0], destination[1]],
    ] as [string, number, number][]) {
      const s = sites.get(site);
      if (s) s.count += 1;
      else sites.set(site, { lat, lon, count: 1 });
    }
  }

  const bounds: [number, number][] = [...sites.values()].map((s) => [s.lat, s.lon]);
  const center: [number, number] = bounds[0] ?? [48, 8];

  return (
    <div className="panel">
      <h2>
        {title}
        <span className="hint">origin - destination lanes, colored by worst flag on the lane</span>
      </h2>
      <div className="shipment-map-wrap">
        <MapContainer center={center} zoom={5} scrollWheelZoom={false} className="shipment-map">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <FitBounds bounds={bounds} />
          {[...routes.values()].map((r, i) => (
            <Polyline
              key={i}
              positions={r.positions}
              pathOptions={{ color: SEVERITY_COLOR[r.severity], weight: Math.min(2 + r.count, 7), opacity: 0.8 }}
            >
              <Tooltip sticky>
                {r.origin} to {r.destination} - {r.count} trip{r.count > 1 ? "s" : ""}
              </Tooltip>
            </Polyline>
          ))}
          {[...sites.entries()].map(([name, s]) => (
            <CircleMarker
              key={name}
              center={[s.lat, s.lon]}
              radius={Math.min(5 + s.count * 1.2, 14)}
              pathOptions={{ color: "#0d47a1", fillColor: "#0d47a1", fillOpacity: 0.85, weight: 1 }}
            >
              <Tooltip>
                {name} - {s.count} trip touchpoint{s.count > 1 ? "s" : ""}
              </Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>
      <div className="map-legend">
        <span>
          <i style={{ background: SEVERITY_COLOR.ok }} /> On track
        </span>
        <span>
          <i style={{ background: SEVERITY_COLOR.warn }} /> Should be closed
        </span>
        <span>
          <i style={{ background: SEVERITY_COLOR.bad }} /> Needs investigation
        </span>
      </div>
    </div>
  );
}
