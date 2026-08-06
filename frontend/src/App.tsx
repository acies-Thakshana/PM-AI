import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import DataUpload from "./pages/DataUpload";
import Dashboard from "./pages/Dashboard";
import ExecutiveSummary from "./pages/dashboard/ExecutiveSummary";
import RCA from "./pages/dashboard/RCA";
import ReportStudio from "./pages/dashboard/ReportStudio";
import ShipmentAssessment from "./pages/dashboard/ShipmentAssessment";
import ShipmentPortfolio from "./pages/dashboard/ShipmentPortfolio";

function TopNav() {
  return (
    <nav className="top-nav">
      <NavLink to="/upload" className={({ isActive }) => (isActive ? "active" : "")}>
        1. Data Upload
      </NavLink>
      <NavLink to="/dashboard" className={({ isActive }) => (isActive ? "active" : "")}>
        2. Dashboard
      </NavLink>
    </nav>
  );
}

function App() {
  return (
    <>
      <TopNav />
      <Routes>
        <Route path="/" element={<Navigate to="/upload" replace />} />
        <Route path="/upload" element={<DataUpload />} />
        <Route path="/dashboard" element={<Dashboard />}>
          <Route index element={<Navigate to="summary" replace />} />
          <Route path="summary" element={<ExecutiveSummary />} />
          <Route path="portfolio" element={<ShipmentPortfolio />} />
          <Route path="assessment" element={<ShipmentAssessment />} />
          <Route path="rca" element={<RCA />} />
          <Route path="report-studio" element={<ReportStudio />} />
        </Route>
      </Routes>
    </>
  );
}

export default App;
