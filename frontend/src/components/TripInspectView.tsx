import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import { useEffect, useMemo, useState } from "react";
import { fetchTripRaw } from "../api/swp";
import type { SwpMapPoint, SwpTripRaw } from "../api/swp";
import { CHART_COLORS, CHART_PALETTE } from "../utils/chartTheme";
import "./TripInspectView.css";

const Plot = createPlotlyComponent(Plotly);

const UNITS: Record<string, string> = {
  Temperature: "°C",
  SimulatedTemperature: "°C",
  TemperatureProbe: "°C",
  Humidity: "%",
};
const PLOTLY_CONFIG: Partial<Plotly.Config> = { displayModeBar: "hover", displaylogo: false, responsive: true };
const START_COLOR = "#2E7D32";
const END_COLOR = "#C62828";

/** Zoom level that fits the route in the map box (Web Mercator: the whole world is 360 degrees wide at zoom 0). */
function zoomFor(points: SwpMapPoint[]): number {
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  const span = Math.max(Math.max(...lats) - Math.min(...lats), Math.max(...lngs) - Math.min(...lngs), 0.005);
  return Math.max(1, Math.min(13, Math.log2(360 / span) - 0.6));
}

function RouteMap({ route, start, end }: { route: SwpMapPoint[]; start: SwpMapPoint | null; end: SwpMapPoint | null }) {
  const all = route.length ? route : [start, end].filter((p): p is SwpMapPoint => p !== null);
  if (all.length === 0) return <p className="trip-inspect__note">This trip has no GPS points.</p>;
  const center = {
    lat: (Math.min(...all.map((p) => p.lat)) + Math.max(...all.map((p) => p.lat))) / 2,
    lon: (Math.min(...all.map((p) => p.lng)) + Math.max(...all.map((p) => p.lng))) / 2,
  };
  const ends = [start, end].filter((p): p is SwpMapPoint => p !== null);
  // scattermap is Plotly's MapLibre trace (open street map tiles, no token needed); the bundled type
  // definitions predate it, so the spec is passed through untyped.
  const data = [
    { type: "scattermap", mode: "lines", lat: all.map((p) => p.lat), lon: all.map((p) => p.lng), line: { width: 3, color: CHART_PALETTE[0] }, hoverinfo: "skip", name: "Route" },
    {
      type: "scattermap",
      mode: "markers+text",
      lat: ends.map((p) => p.lat),
      lon: ends.map((p) => p.lng),
      text: ends.length === 2 ? ["Start", "End"] : ["Start"],
      textposition: "top right",
      marker: { size: 13, color: ends.length === 2 ? [START_COLOR, END_COLOR] : [START_COLOR] },
      hovertext: ends.map((p, i) => `${i === 0 ? "Start" : "End"}: ${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}${p.time ? `<br>${p.time}` : ""}`),
      hoverinfo: "text",
      name: "Start / End",
    },
  ] as unknown as Plotly.Data[];
  const layout = {
    height: 360,
    margin: { l: 0, r: 0, t: 0, b: 0 },
    showlegend: false,
    map: { style: "open-street-map", center, zoom: zoomFor(all) },
  } as unknown as Partial<Plotly.Layout>;
  return <Plot data={data} layout={layout} config={PLOTLY_CONFIG} useResizeHandler style={{ width: "100%" }} />;
}

interface TripInspectViewProps {
  sessionId: string;
  tripId: string;
}

/** One trip's raw sensor readings (a chart per sensor, one line per logger) and its GPS route from the
 * first point to the last, on a map. */
export default function TripInspectView({ sessionId, tripId }: TripInspectViewProps) {
  const [raw, setRaw] = useState<SwpTripRaw | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setRaw(null);
    setError(null);
    fetchTripRaw(sessionId, tripId)
      .then((data) => live && setRaw(data))
      .catch((err) => live && setError(err instanceof Error ? err.message : "Could not load the trip."));
    return () => {
      live = false;
    };
  }, [sessionId, tripId]);

  const sensors = useMemo(() => [...new Set((raw?.series ?? []).map((s) => s.sensor))], [raw]);

  if (error) return <p className="trip-inspect__error">{error}</p>;
  if (!raw) return <p className="trip-inspect__note">Loading…</p>;

  return (
    <div className="trip-inspect">
      <section>
        <h4 className="trip-inspect__heading">Route</h4>
        <div className="trip-inspect__box trip-inspect__box--map">
          <RouteMap route={raw.route} start={raw.start} end={raw.end} />
        </div>
        {raw.start && raw.end && (
          <p className="trip-inspect__note">
            Start {raw.start.lat.toFixed(4)}, {raw.start.lng.toFixed(4)} → End {raw.end.lat.toFixed(4)}, {raw.end.lng.toFixed(4)}
          </p>
        )}
      </section>

      <section>
        <h4 className="trip-inspect__heading">Raw sensor data</h4>
        {sensors.length === 0 && <p className="trip-inspect__note">No sensor readings were loaded for this trip.</p>}
        {sensors.map((sensor) => {
          const series = raw.series.filter((s) => s.sensor === sensor);
          const unit = UNITS[sensor];
          return (
            <div key={sensor} className="trip-inspect__box trip-inspect__box--chart">
              <Plot
                data={series.map((s, i) => ({
                  type: "scatter" as const,
                  mode: "lines" as const,
                  name: s.serial_number ?? sensor,
                  x: s.x,
                  y: s.y,
                  line: { width: 1.5, color: CHART_PALETTE[i % CHART_PALETTE.length] },
                  hovertemplate: `%{x|%d %b %Y %H:%M}<br>%{y}${unit ? ` ${unit}` : ""}<extra>${s.serial_number ?? sensor}</extra>`,
                }))}
                layout={{
                  height: 260,
                  margin: { l: 56, r: 24, t: 36, b: 40 },
                  title: { text: unit ? `${sensor} (${unit})` : sensor, font: { size: 13, color: CHART_COLORS.text }, x: 0.01 },
                  font: { family: "inherit", size: 10.5, color: CHART_COLORS.text },
                  paper_bgcolor: "transparent",
                  plot_bgcolor: "transparent",
                  hovermode: "x unified",
                  showlegend: series.length > 1,
                  legend: { orientation: "h", x: 1, xanchor: "right", y: 1.12 },
                  xaxis: { gridcolor: CHART_COLORS.grid, title: { text: "Time (UTC)" } },
                  yaxis: { gridcolor: CHART_COLORS.grid, automargin: true },
                }}
                config={PLOTLY_CONFIG}
                useResizeHandler
                style={{ width: "100%" }}
              />
            </div>
          );
        })}
      </section>
    </div>
  );
}
