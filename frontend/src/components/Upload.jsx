import { useRef, useState } from "react";
import { getJob, startOnboarding, uploadDataset } from "../api.js";

export function Upload({ hidden, domains, onUploaded, onOnboarded }) {
  const [domain, setDomain] = useState("");
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState([]); // { ok, text }
  const [uploadedDomain, setUploadedDomain] = useState("");
  const [status, setStatus] = useState("");
  const [onboarding, setOnboarding] = useState(false);
  const [onboardResult, setOnboardResult] = useState(null);
  const filesRef = useRef(null);

  async function submit(event) {
    event.preventDefault();
    const id = domain.trim().toLowerCase();
    const files = Array.from((filesRef.current && filesRef.current.files) || []);
    if (!id || !files.length) return;
    setUploading(true);
    setResults([]);
    setOnboardResult(null);
    setStatus("");
    let uploaded = 0;
    for (const file of files) {
      try {
        const info = await uploadDataset(id, file);
        uploaded += 1;
        setResults((r) => [
          ...r,
          { ok: true, text: `${file.name} → table ${info.table} (${info.rows} rows, ${info.columns.length} columns)` }
        ]);
      } catch (error) {
        setResults((r) => [...r, { ok: false, text: `${file.name}: ${error.message || error}` }]);
      }
    }
    setUploading(false);
    if (!uploaded) return;
    setUploadedDomain(id);
    filesRef.current.value = "";
    setStatus(`Uploaded to ${id}. Run onboarding to learn its metrics and joins, or open the dashboard now.`);
    onUploaded(id);
  }

  async function pollJob(jobId) {
    for (;;) {
      const job = await getJob(jobId);
      setStatus(`Onboarding ${uploadedDomain}: ${job.status}…`);
      if (job.status !== "queued" && job.status !== "running") return job;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }

  async function onboard() {
    if (!uploadedDomain) return;
    setOnboarding(true);
    setOnboardResult(null);
    setStatus(`Starting onboarding for ${uploadedDomain}…`);
    try {
      const started = await startOnboarding(uploadedDomain);
      const job = await pollJob(started.job_id);
      if (job.status === "succeeded") {
        setStatus(`Onboarding finished for ${uploadedDomain}.`);
        setOnboardResult(job.result);
        onOnboarded(uploadedDomain);
      } else {
        setStatus("Onboarding failed: " + (job.error || "unknown error"));
      }
    } catch (error) {
      setStatus(error.message || String(error));
    }
    setOnboarding(false);
  }

  return (
    <section id="upload-view" className="upload-view" hidden={hidden}>
      <header className="topbar">
        <div>
          <p className="eyebrow">Carrier · NL2SQL workspace</p>
          <h1>Upload data</h1>
        </div>
      </header>
      <div className="upload-body">
        <article className="dash-card">
          <h2>1. Add files to a domain</h2>
          <p className="dash-note">
            CSV, TSV, Excel, Parquet or JSON. Each file becomes one table named after the file. A new domain id creates a new
            domain.
          </p>
          <form className="upload-form" onSubmit={submit}>
            <label className="field">
              <span>Domain id</span>
              <input
                list="domain-options"
                type="text"
                placeholder="e.g. finance_ops"
                autoComplete="off"
                required
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              />
              <datalist id="domain-options">
                {domains.map((d) => (
                  <option key={d.id} value={d.id} />
                ))}
              </datalist>
            </label>
            <label className="field">
              <span>Files</span>
              <input ref={filesRef} type="file" multiple required accept=".csv,.tsv,.xlsx,.xlsm,.parquet,.json,.jsonl" />
            </label>
            <button type="submit" className="primary-btn" disabled={uploading}>
              Upload
            </button>
          </form>
          <ul className="upload-results">
            {results.map((r, i) => (
              <li key={i} className={r.ok ? "ok" : "bad"}>
                {r.text}
              </li>
            ))}
          </ul>
        </article>
        <article className="dash-card">
          <h2>2. Learn the semantics</h2>
          <p className="dash-note">
            Onboarding reads the uploaded tables and proposes metrics, joins and glossary terms. Without a model it uses local
            rules. Run it once after uploading.
          </p>
          <button type="button" className="primary-btn" disabled={!uploadedDomain || onboarding} onClick={onboard}>
            Run onboarding
          </button>
          <p className="dash-note onboard-status">{status}</p>
          {onboardResult && <pre className="sql">{JSON.stringify(onboardResult, null, 2)}</pre>}
        </article>
      </div>
    </section>
  );
}
