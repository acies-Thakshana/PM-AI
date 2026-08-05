import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { FacilityRanking } from "../api/client";

interface Props {
  facilities: FacilityRanking[];
}

export default function FacilityRankingChart({ facilities }: Props) {
  const data = facilities.map((f) => ({
    name: f.DestinationFacility.replace(" Distribution Center", " DC").replace(" Cold Storage Hub", " CSH"),
    spoilage: f.AvgSpoilagePct,
    system: f.RefrigerationSystemType,
    year: f.InstallYear,
  }));

  return (
    <div className="panel">
      <h2>
        Facility Performance
        <span className="hint">avg. arrival spoilage % by destination facility</span>
      </h2>
      {data.length === 0 ? (
        <div className="empty-state">No delivered shipments yet.</div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} layout="vertical" margin={{ left: 10, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" horizontal={false} />
            <XAxis type="number" unit="%" tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: number) => `${v}%`} />
            <Bar dataKey="spoilage" radius={[0, 4, 4, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.spoilage > 8 ? "#b71c1c" : "#1b5e20"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
