import { useRef, useState } from "react";
import { loadSampleData, uploadData, type IngestResult, type IngestSource } from "../api/client";

interface Props {
  source: IngestSource;
  title: string;
  description: string;
  accept: string;
}

export default function UploadCard({ source, title, description, accept }: Props) {
  const [result, setResult] = useState<IngestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleResult = (data: IngestResult) => {
    setResult(data);
    setError(null);
  };

  const handleLoadSample = async () => {
    setLoading(true);
    setError(null);
    try {
      handleResult(await loadSampleData(source));
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.message ?? "Failed to load sample data");
    } finally {
      setLoading(false);
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      handleResult(await uploadData(source, file));
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.message ?? "Failed to upload file");
    } finally {
      setLoading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className={`upload-card ${result ? "loaded" : ""}`}>
      <div className="upload-card-header">
        <h3>{title}</h3>
        {result && <span className="loaded-pill">Loaded</span>}
      </div>
      <p className="upload-card-description">{description}</p>

      <div className="upload-card-actions">
        <button onClick={handleLoadSample} disabled={loading}>
          {loading ? "Loading..." : "Load Simulated Sample"}
        </button>
        <label className="file-input-label">
          Upload file
          <input ref={fileInputRef} type="file" accept={accept} onChange={handleFileChange} disabled={loading} />
        </label>
      </div>

      {error && <div className="error-box">{error}</div>}

      {result && (
        <div className="upload-card-result">
          {"trip_count" in result && (
            <div className="result-line">
              {result.trip_count} trips, {result.reading_count} sensor readings loaded - see the Dashboard for
              analysis
            </div>
          )}
          {"char_count" in result && (
            <div className="result-line">
              {result.section_count} sections loaded - {result.confirmed_trip_count} trip confirmations found
            </div>
          )}
          {"standard_kpi_count" in result && (
            <div className="result-line">
              {result.product_count} product specs, {result.standard_kpi_count} standard KPIs, {result.customer_kpi_count} customer KPIs
            </div>
          )}
        </div>
      )}
    </div>
  );
}
