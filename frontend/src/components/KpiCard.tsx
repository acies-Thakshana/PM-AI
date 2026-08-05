interface Props {
  label: string;
  value: string;
  target: string;
  status: "on_target" | "at_risk";
}

export default function KpiCard({ label, value, target, status }: Props) {
  return (
    <div className={`kpi-card ${status}`}>
      <div className="value">{value}</div>
      <div className="label">{label}</div>
      <div className="target">Target: {target}</div>
    </div>
  );
}
