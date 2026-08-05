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
import { fetchSensorSeries, type SensorSeries, type ShipmentSummary } from "../api/client";

interface Props {
  shipments: ShipmentSummary[];
}

export default function TempHumidityChart({ shipments }: Props) {
  const [selected, setSelected] = useState<string>("");
  const [series, setSeries] = useState<SensorSeries | null>(null);

  useEffect(() => {
    if (!selected && shipments.length > 0) {
      const inTransit = shipments.find((s) => s.TransitStatus === "In Transit");
      setSelected((inTransit ?? shipments[0]).ShipmentID);
    }
  }, [shipments, selected]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    const load = () => fetchSensorSeries(selected).then((data) => !cancelled && setSeries(data));
    load();
    const interval = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
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
      Humidity: r.HumidityPct,
      door: r.DoorOpenEvent,
    })) ?? [];

  return (
    <div className="panel">
      <h2>
        Temperature Trend
        <span className="hint">per-shipment sensor trace vs. target band</span>
      </h2>
      <select value={selected} onChange={(e) => setSelected(e.target.value)} style={{ marginBottom: 12 }}>
        {shipments.map((s) => (
          <option key={s.ShipmentID} value={s.ShipmentID}>
            {s.ShipmentID} - {s.Commodity} {s.TransitStatus === "In Transit" ? "(live)" : ""}
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
        <div className="empty-state">No sensor readings yet for this shipment.</div>
      )}
    </div>
  );
}
