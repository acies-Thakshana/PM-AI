import type { ReactNode } from "react";
import "./StatTile.css";

export type StatTileColor = "blue" | "teal" | "purple" | "amber" | "error";

interface StatTileProps {
  icon: ReactNode;
  color: StatTileColor;
  value: string | number;
  label: string;
}

export default function StatTile({ icon, color, value, label }: StatTileProps) {
  return (
    <div className="stat-tile">
      <span className={`stat-tile__icon stat-tile__icon--${color}`}>{icon}</span>
      <div className="stat-tile__body">
        <span className="stat-tile__value">{value}</span>
        <span className="stat-tile__label">{label}</span>
      </div>
    </div>
  );
}
