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
// Sensors measured in the same unit share an axis; each other kind gets its own axis on the right.
const AXIS_GROUP: Record<string, string> = {
  Temperature: "Temperature (°C)",
  SimulatedTemperature: "Temperature (°C)",
  TemperatureProbe: "Temperature (°C)",
  Humidity: "Humidity (%)",
};
const DASHES = ["solid", "dash", "dot", "dashdot"] as const;
const axisGroup = (sensor: string) => AXIS_GROUP[sensor] ?? sensor;
const AXIS_STEP = 0.09; // width of the plot kept free for each axis beyond the second

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

  // One chart for every sensor of the trip: a line per sensor and logger, one y axis per kind of unit.
  const { chartData, chartLayout } = useMemo(() => {
    const series = raw?.series ?? [];
    const groups = [...new Set(series.map((s) => axisGroup(s.sensor)))].sort((a, b) =>
      a.startsWith("Temperature") ? -1 : b.startsWith("Temperature") ? 1 : 0
    );
    const axisOf = (sensor: string) => groups.indexOf(axisGroup(sensor)) + 1; // 1 = y, 2 = y2, ...
    const multiLogger = new Set(series.map((s) => s.serial_number)).size > 1;
    const loggers = [...new Set(series.map((s) => s.serial_number))];
    const data = series.map((s) => {
      const axis = axisOf(s.sensor);
      const name = multiLogger && s.serial_number ? `${s.sensor} (${s.serial_number})` : s.sensor;
      return {
        type: "scatter" as const,
        mode: "lines" as const,
        name,
        x: s.x,
        y: s.y,
        yaxis: axis === 1 ? "y" : `y${axis}`,
        // A line takes its axis's colour; several loggers on one axis are told apart by their dash.
        line: { width: 1.5, color: CHART_PALETTE[(axis - 1) % CHART_PALETTE.length], dash: DASHES[loggers.indexOf(s.serial_number) % DASHES.length] },
        hovertemplate: `%{x|%d %b %Y %H:%M}<br>%{y} ${UNITS[s.sensor] ?? ""}<extra>${name}</extra>`,
      };
    });
    const extraAxes = Math.max(groups.length - 2, 0);
    const layout: Record<string, unknown> = {
      height: 260,
      margin: { l: 56, r: 24, t: 20, b: 40 },
      font: { family: "inherit", size: 10.5, color: CHART_COLORS.text },
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      hovermode: "x unified",
      showlegend: true,
      legend: { orientation: "h", x: 0, xanchor: "left", y: 1.12 },
      xaxis: { gridcolor: CHART_COLORS.grid, title: { text: "Time (UTC)" }, domain: [0, 1 - AXIS_STEP * extraAxes] },
    };
    groups.forEach((group, k) => {
      const key = k === 0 ? "yaxis" : `yaxis${k + 1}`;
      layout[key] = {
        title: { text: group, font: { size: 11, color: CHART_PALETTE[k % CHART_PALETTE.length] } },
        tickfont: { color: CHART_PALETTE[k % CHART_PALETTE.length] },
        automargin: true,
        gridcolor: CHART_COLORS.grid,
        showgrid: k === 0,
        ...(k === 0 ? {} : k === 1
          ? { overlaying: "y", side: "right" }
          : { overlaying: "y", side: "right", anchor: "free", position: 1 - AXIS_STEP * (groups.length - 1 - k) }),
      };
    });
    return { chartData: data as Plotly.Data[], chartLayout: layout as Partial<Plotly.Layout> };
  }, [raw]);

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
        {sensors.length > 0 && (
          <div className="trip-inspect__box trip-inspect__box--chart">
            <Plot data={chartData} layout={chartLayout} config={PLOTLY_CONFIG} useResizeHandler style={{ width: "100%" }} />
          </div>
        )}
      </section>
    </div>
  );
}
