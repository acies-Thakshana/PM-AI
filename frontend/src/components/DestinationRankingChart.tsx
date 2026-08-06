import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DestinationRanking } from "../api/client";

interface Props {
  destinations: DestinationRanking[];
}

export default function DestinationRankingChart({ destinations }: Props) {
  const data = [...destinations].sort((a, b) => a.AvgCompliancePct - b.AvgCompliancePct);

  return (
    <div className="panel">
      <h2>
        Destination Performance
        <span className="hint">avg. % time in spec by destination site</span>
      </h2>
      {data.length === 0 ? (
        <div className="empty-state">No trips loaded yet.</div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} layout="vertical" margin={{ left: 10, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" horizontal={false} />
            <XAxis type="number" unit="%" tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="Destination" width={140} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v) => `${v}%`} />
            <Bar dataKey="AvgCompliancePct" radius={[0, 4, 4, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.AvgCompliancePct < 90 ? "#b71c1c" : "#1b5e20"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
