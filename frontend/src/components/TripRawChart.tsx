import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import { useEffect, useMemo, useState } from "react";
import { fetchSessionTrips, fetchTripRaw } from "../api/swp";
import type { SwpSessionTrip, SwpTripRaw } from "../api/swp";
import { CHART_COLORS, CHART_PALETTE } from "../utils/chartTheme";
import "./TripRawChart.css";

const Plot = createPlotlyComponent(Plotly);

const UNITS: Record<string, string> = {
  Temperature: "°C",
  SimulatedTemperature: "°C",
  TemperatureProbe: "°C",
  Humidity: "%",
};
const PLOTLY_CONFIG: Partial<Plotly.Config> = { displayModeBar: "hover", displaylogo: false, responsive: true };

interface TripRawChartProps {
  sessionId: string;
}

/** The raw sensor readings of one trip as read from the API (before any audit change): a chart per
 * sensor, one line per logger. A trip is picked from the list of the trips loaded into this session. */
export default function TripRawChart({ sessionId }: TripRawChartProps) {
  const [trips, setTrips] = useState<SwpSessionTrip[] | null>(null);
  const [tripId, setTripId] = useState<string>("");
  const [raw, setRaw] = useState<SwpTripRaw | null>(null);
  const [hidden, setHidden] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let live = true;
    setTrips(null);
    setRaw(null);
    setError(null);
    fetchSessionTrips(sessionId)
      .then((list) => {
        if (!live) return;
        setTrips(list);
        setTripId(list[0]?.trip_id ?? "");
      })
      .catch((err) => live && setError(err instanceof Error ? err.message : "Could not list the trips."));
    return () => {
      live = false;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!tripId) return;
    let live = true;
    setLoading(true);
    setError(null);
    setHidden([]);
    fetchTripRaw(sessionId, tripId)
      .then((data) => live && setRaw(data))
      .catch((err) => live && setError(err instanceof Error ? err.message : "Could not load the readings."))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [sessionId, tripId]);

  const sensors = useMemo(() => [...new Set((raw?.series ?? []).map((s) => s.sensor))], [raw]);
  const current = trips?.find((t) => t.trip_id === tripId);

  if (trips && trips.length === 0) {
    return <p className="trip-raw__note">The loaded trips have no raw sensor readings.</p>;
  }

  return (
    <div className="trip-raw">
      <div className="trip-raw__controls">
        <label className="trip-raw__field">
          <span className="trip-raw__label">Trip</span>
          <select className="trip-raw__select" value={tripId} onChange={(e) => setTripId(e.target.value)} disabled={!trips}>
            {(trips ?? []).map((t, i) => (
              <option key={t.trip_id} value={t.trip_id}>
                {i + 1}. {t.trip_id}
              </option>
            ))}
          </select>
        </label>
        {sensors.length > 1 && (
          <div className="trip-raw__sensors" role="group" aria-label="Sensors">
            {sensors.map((s) => (
              <label key={s} className="trip-raw__check">
                <input
                  type="checkbox"
                  checked={!hidden.includes(s)}
                  onChange={() => setHidden((h) => (h.includes(s) ? h.filter((x) => x !== s) : [...h, s]))}
                />
                {s}
              </label>
            ))}
          </div>
        )}
        {current && <span className="trip-raw__count">{current.readings.toLocaleString()} readings</span>}
      </div>

      {error && <p className="trip-raw__error">{error}</p>}
      {(loading || (!trips && !error)) && <p className="trip-raw__note">Loading readings…</p>}

      {raw &&
        !loading &&
        sensors
          .filter((sensor) => !hidden.includes(sensor))
          .map((sensor) => {
            const series = raw.series.filter((s) => s.sensor === sensor);
            const unit = UNITS[sensor];
            return (
              <div key={sensor} className="trip-raw__chart">
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
                    height: 280,
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
    </div>
  );
}
