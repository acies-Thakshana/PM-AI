import type { ReactNode } from "react";
import "./StatTile.css";

export type StatTileColor = "blue" | "teal" | "purple" | "amber" | "error";

interface StatTileProps {
  icon: ReactNode;
  color: StatTileColor;
  value: string | number;
  label: string;
}

// Purely decorative flourish -- an abstract wave, not a rendering of any
// real value, so it can never be mistaken for a trend line.
const FLOURISH_PATH = "M0 20 C 14 4, 24 30, 38 14 S 60 2, 74 18 S 96 28, 110 12";

export default function StatTile({ icon, color, value, label }: StatTileProps) {
  return (
    <div className="stat-tile">
      <span className={`stat-tile__icon stat-tile__icon--${color}`}>{icon}</span>
      <div className="stat-tile__body">
        <span className="stat-tile__value">{value}</span>
        <span className="stat-tile__label">{label}</span>
      </div>
      <svg className={`stat-tile__flourish stat-tile__flourish--${color}`} viewBox="0 0 110 32" aria-hidden="true" focusable="false">
        <path d={FLOURISH_PATH} fill="none" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    </div>
  );
}
