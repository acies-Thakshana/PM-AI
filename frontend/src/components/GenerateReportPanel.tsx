import { useEffect, useRef, useState } from "react";
import { downloadReportUrl, fetchReportStatus, startReportGeneration, type ReportJob } from "../api/client";

const STEPS = [
  { key: "analyzing", label: "Agent 1 - Insight Analyst" },
  { key: "composing", label: "Agent 2 - Report Composer" },
  { key: "complete", label: "Deck Ready" },
];

export default function GenerateReportPanel() {
  const [job, setJob] = useState<ReportJob | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const handleGenerate = async () => {
    const jobId = await startReportGeneration();
    setJob({
      job_id: jobId,
      status: "queued",
      stage: "queued",
      stage_label: "Queued...",
      created_at: new Date().toISOString(),
      file_path: null,
      file_name: null,
      error: null,
    });

    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      const status = await fetchReportStatus(jobId);
      setJob(status);
      if (status.status === "done" || status.status === "error") {
        if (pollRef.current) clearInterval(pollRef.current);
      }
    }, 1500);
  };

  const isRunning = job && job.status !== "done" && job.status !== "error";
  const stepIndex = job ? STEPS.findIndex((s) => s.key === job.stage) : -1;

  return (
    <div className="generate-panel">
      <div className="row">
        <div>
          <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 4 }}>
            Cold Chain Post-Harvest Assessment Report
          </div>
          <div className="status-line">
            {job ? job.stage_label : "Generate the formatted PPTX deck from the current data + domain knowledge."}
          </div>
        </div>
        <button onClick={handleGenerate} disabled={!!isRunning}>
          {isRunning ? "Generating..." : "Generate PPT Report"}
        </button>
        {job?.status === "done" && job.file_name && (
          <a className="download-link" href={downloadReportUrl(job.job_id)} download>
            Download {job.file_name}
          </a>
        )}
      </div>

      {job && (
        <div className="agent-steps">
          {STEPS.map((s, i) => (
            <span
              key={s.key}
              className={`agent-step ${
                job.status === "done" || i < stepIndex ? "done" : i === stepIndex ? "active" : ""
              }`}
            >
              {s.label}
            </span>
          ))}
        </div>
      )}

      {job?.status === "error" && <div className="error-box">{job.error}</div>}
    </div>
  );
}
