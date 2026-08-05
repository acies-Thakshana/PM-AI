import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CommodityRisk } from "../api/client";

interface Props {
  risk: CommodityRisk[];
}

export default function CommodityRiskChart({ risk }: Props) {
  const data = [...risk].sort((a, b) => a.AvgGreenLifeRetentionPct - b.AvgGreenLifeRetentionPct);

  return (
    <div className="panel">
      <h2>
        Green Life Retention by Commodity
        <span className="hint">% of base shelf life remaining at arrival</span>
      </h2>
      {data.length === 0 ? (
        <div className="empty-state">No delivered shipments yet.</div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
            <XAxis dataKey="Commodity" tick={{ fontSize: 10 }} interval={0} angle={-15} textAnchor="end" height={50} />
            <YAxis unit="%" tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: number) => `${v}%`} />
            <Bar dataKey="AvgGreenLifeRetentionPct" radius={[4, 4, 0, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.AvgGreenLifeRetentionPct < 70 ? "#f9a825" : "#0d47a1"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
