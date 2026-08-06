import { NavLink, Outlet } from "react-router-dom";

const TABS = [
  { to: "summary", label: "Executive Summary" },
  { to: "portfolio", label: "Shipment Portfolio" },
  { to: "assessment", label: "Shipment Assessment" },
  { to: "rca", label: "RCA" },
  { to: "report-studio", label: "Report Studio" },
];

export default function Dashboard() {
  return (
    <div className="app-shell">
      <div className="app-header">
        <div>
          <h1>Cold Chain Program Dashboard</h1>
          <div className="subtitle">
            <span className="live-dot" />
            Live from uploaded trip data
          </div>
        </div>
      </div>

      <nav className="dashboard-subnav">
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => (isActive ? "active" : "")}>
            {t.label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </div>
  );
}
