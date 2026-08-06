import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchTripSensorSeries, type TripSensorSeries, type TripSummary } from "../api/client";

interface Props {
  trips: TripSummary[];
  selected?: string;
  onSelectChange?: (tripId: string) => void;
}

export default function TripTempChart({ trips, selected: controlledSelected, onSelectChange }: Props) {
  const [internalSelected, setInternalSelected] = useState<string>("");
  const selected = controlledSelected ?? internalSelected;
  const setSelected = onSelectChange ?? setInternalSelected;
  const [series, setSeries] = useState<TripSensorSeries | null>(null);

  useEffect(() => {
    if (!selected && trips.length > 0) {
      const flagged = trips.find((t) => t.Flag !== "closed" && t.Flag !== "clean" && t.Flag !== "active");
      setSelected((flagged ?? trips[0]).TripID);
    }
  }, [trips, selected]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    fetchTripSensorSeries(selected).then((data) => !cancelled && setSeries(data));
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const chartData =
    series?.readings.map((r) => ({
      time: new Date(r.Timestamp).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
      Temperature: r.TemperatureC,
    })) ?? [];

  return (
    <div className="panel">
      <h2>
        Trip Temperature Trend
        <span className="hint">per-trip sensor trace vs. product target band</span>
      </h2>
      <select value={selected} onChange={(e) => setSelected(e.target.value)} style={{ marginBottom: 12 }}>
        {trips.map((t) => (
          <option key={t.TripID} value={t.TripID}>
            {t.TripID} - {t.Product} ({t.Source})
          </option>
        ))}
      </select>
      {series && chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
            <XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={30} />
            <YAxis tick={{ fontSize: 11 }} unit="C" />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceArea
              y1={series.target_temp_min}
              y2={series.target_temp_max}
              fill="#1b5e20"
              fillOpacity={0.08}
              label={{ value: "target band", position: "insideTopLeft", fontSize: 10, fill: "#1b5e20" }}
            />
            <Line type="monotone" dataKey="Temperature" stroke="#0d47a1" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="empty-state">No sensor readings yet for this trip.</div>
      )}
    </div>
  );
}
