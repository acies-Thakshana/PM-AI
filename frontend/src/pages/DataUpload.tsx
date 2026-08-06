import { Link } from "react-router-dom";
import UploadCard from "../components/UploadCard";

export default function DataUpload() {
  return (
    <div className="app-shell">
      <div className="app-header">
        <div>
          <h1>Data Upload</h1>
          <div className="subtitle">
            Load the raw sources a Program Manager pulls together before any analysis can start.
          </div>
        </div>
        <Link className="nav-link" to="/dashboard">
          Continue to Dashboard &rarr;
        </Link>
      </div>

      <div className="upload-grid">
        <UploadCard
          source="sensiwatch"
          title="1. SensiWatch Trip Export"
          description="The real-time monitoring platform export: trip headers plus sensor readings (temperature, humidity, light, GPS). Includes trips still marked 'In Transit' that may actually have arrived - flagged automatically by comparing the last known GPS position to the destination."
          accept=".xlsx"
        />
        <UploadCard
          source="coldstream"
          title="2. ColdStream Export"
          description="A second monitoring platform, simpler periodic data logger (no GPS/light). Checked for statistical outliers: trips that are implausibly short or long, or readings with impossible temperature/humidity values."
          accept=".xlsx"
        />
        <UploadCard
          source="customer-profile"
          title="3. Customer-Specific Context"
          description="Unstructured context for this customer: product catalog, shipping lanes, branding preferences, and a confirmed delivery log used to resolve ambiguous 'stuck' trips - the same source of truth a PM would check by hand."
          accept=".md,.txt"
        />
        <UploadCard
          source="business-rules"
          title="4. Business Rules, Thresholds & KPIs"
          description="Machine-readable config: acceptable temperature/humidity ranges per product, abnormal-value detection thresholds, and the standard + customer-specific KPI catalog applied to every trip."
          accept=".json"
        />
      </div>
    </div>
  );
}
