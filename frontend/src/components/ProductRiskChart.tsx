import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ProductRisk } from "../api/client";

interface Props {
  products: ProductRisk[];
}

export default function ProductRiskChart({ products }: Props) {
  const data = [...products].sort((a, b) => a.AvgCompliancePct - b.AvgCompliancePct);

  return (
    <div className="panel">
      <h2>
        % Time In Spec by Product
        <span className="hint">avg. share of transit time within target temperature band</span>
      </h2>
      {data.length === 0 ? (
        <div className="empty-state">No trips loaded yet.</div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
            <XAxis dataKey="Product" tick={{ fontSize: 10 }} interval={0} angle={-15} textAnchor="end" height={50} />
            <YAxis unit="%" tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v) => `${v}%`} />
            <Bar dataKey="AvgCompliancePct" radius={[4, 4, 0, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.AvgCompliancePct < 90 ? "#f9a825" : "#0d47a1"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
