import { useRef, useState } from "react";
import { getJob, startOnboarding, uploadDataset } from "../api.js";

const ALLOWED = [".csv", ".tsv", ".xlsx", ".xlsm", ".parquet", ".json", ".jsonl"];
const DOMAIN_RE = /^[a-z][a-z0-9_]{1,39}$/;

function extension(name) {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i).toLowerCase();
}

function slug(name) {
  const base = name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return /^[a-z]/.test(base) ? base.slice(0, 40) : base ? ("d_" + base).slice(0, 40) : "";
}

function size(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

/**
 * First page of the app. Pick one file or many, name the domain they belong to, upload them,
 * let the backend learn their semantics, then open the dashboard automatically. Until then the
 * dashboard and ask pages stay locked.
 * Phases: "select" -> "uploading" -> "onboarding" -> "done".
 */
export function Upload({ hidden, domains, onFinished }) {
  const [items, setItems] = useState([]); // { id, file, state: "ready"|"uploading"|"done"|"failed", message }
  const [domain, setDomain] = useState("");
  const [domainTouched, setDomainTouched] = useState(false);
  const [phase, setPhase] = useState("select");
  const [status, setStatus] = useState("");
  const [result, setResult] = useState(null);
  const [rejected, setRejected] = useState([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);
  const nextId = useRef(0);

  const busy = phase === "uploading" || phase === "onboarding";
  const domainId = domain.trim().toLowerCase();
  const domainValid = DOMAIN_RE.test(domainId);

  function addFiles(fileList) {
    const files = Array.from(fileList || []);
    const bad = [];
    const good = [];
    files.forEach((file) => {
      if (!ALLOWED.includes(extension(file.name))) bad.push(file.name);
      else good.push(file);
    });
    setRejected(bad);
    if (!good.length) return;
    setItems((current) => {
      const names = new Set(current.map((i) => i.file.name));
      const added = good
        .filter((f) => !names.has(f.name))
        .map((file) => ({ id: nextId.current++, file, state: "ready", message: "" }));
      return [...current, ...added];
    });
    if (!domainTouched && !domain) setDomain(slug(good[0].name));
    setPhase("select");
    setResult(null);
    setStatus("");
  }

  function removeItem(id) {
    setItems((current) => current.filter((i) => i.id !== id));
  }

  function patch(id, change) {
    setItems((current) => current.map((i) => (i.id === id ? { ...i, ...change } : i)));
  }

  async function pollJob(jobId) {
    for (;;) {
      const job = await getJob(jobId);
      setStatus("Learning the data: " + job.status + "…");
      if (job.status !== "queued" && job.status !== "running") return job;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }

  async function run() {
    if (!items.length || !domainValid || busy) return;
    setPhase("uploading");
    setResult(null);
    setStatus("Uploading " + items.length + " file" + (items.length === 1 ? "" : "s") + "…");
    let uploaded = 0;
    for (const item of items) {
      if (item.state === "done") {
        uploaded += 1;
        continue;
      }
      patch(item.id, { state: "uploading", message: "" });
      try {
        const info = await uploadDataset(domainId, item.file);
        uploaded += 1;
        patch(item.id, { state: "done", message: `table ${info.table} · ${info.rows} rows · ${info.columns.length} columns` });
      } catch (error) {
        patch(item.id, { state: "failed", message: error.message || String(error) });
      }
    }
    if (!uploaded) {
      setPhase("select");
      setStatus("No file could be uploaded. Fix the problems below and try again.");
      return;
    }
    setPhase("onboarding");
    setStatus("Learning the data…");
    try {
      const started = await startOnboarding(domainId);
      const job = await pollJob(started.job_id);
      if (job.status === "succeeded") {
        setResult(job.result);
        setStatus("");
        setPhase("done");
        onFinished(domainId, true); // opens the dashboard
      } else {
        setStatus("Analysis failed: " + (job.error || "unknown error") + ". The files are uploaded; you can still open the dashboard.");
        setPhase("done");
        onFinished(domainId, false);
      }
    } catch (error) {
      setStatus((error.message || String(error)) + " The files are uploaded; you can still open the dashboard.");
      setPhase("done");
      onFinished(domainId, false);
    }
  }

  function reset() {
    setItems([]);
    setDomain("");
    setDomainTouched(false);
    setPhase("select");
    setStatus("");
    setResult(null);
    setRejected([]);
    if (inputRef.current) inputRef.current.value = "";
  }

  const stepClass = (n) => {
    const current = phase === "select" ? 1 : phase === "done" ? 4 : phase === "uploading" ? 2 : 3;
    return "step" + (n < current ? " done" : n === current ? " current" : "");
  };

  return (
    <section id="upload-view" className="upload-view" hidden={hidden}>
      <header className="topbar">
        <div>
          <p className="eyebrow">Carrier · NL2SQL workspace</p>
          <h1>Bring your data</h1>
          <p className="dash-lede">
            Upload one file or several. Each file becomes a table you can ask questions about. Related files in the same
            domain can be joined.
          </p>
        </div>
      </header>

      <div className="upload-body">
        <ol className="steps" aria-label="Progress">
          <li className={stepClass(1)}>Choose files</li>
          <li className={stepClass(2)}>Upload</li>
          <li className={stepClass(3)}>Learn the data</li>
          <li className={stepClass(4)}>Dashboard</li>
        </ol>

        <article className="dash-card">
          <div
            className={"dropzone" + (dragging ? " dragging" : "") + (busy ? " disabled" : "")}
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              if (!busy) addFiles(e.dataTransfer.files);
            }}
            onClick={() => !busy && inputRef.current && inputRef.current.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !busy) {
                e.preventDefault();
                inputRef.current.click();
              }
            }}
          >
            <p className="dropzone-title">Drag and drop files here, or click to browse</p>
            <p className="dash-note">CSV, TSV, Excel, Parquet or JSON · one file or many at once</p>
            <input
              ref={inputRef}
              type="file"
              multiple
              hidden
              accept={ALLOWED.join(",")}
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
          {rejected.length > 0 && (
            <p className="upload-warning">Skipped (unsupported type): {rejected.join(", ")}</p>
          )}

          {items.length > 0 && (
            <ul className="file-list">
              {items.map((item) => (
                <li key={item.id} className={"file-row " + item.state}>
                  <div className="file-main">
                    <strong>{item.file.name}</strong>
                    <span>{size(item.file.size)}</span>
                  </div>
                  <div className="file-state">
                    {item.state === "ready" && <span>Ready</span>}
                    {item.state === "uploading" && <span>Uploading…</span>}
                    {item.state === "done" && <span className="ok-text">✓ {item.message}</span>}
                    {item.state === "failed" && <span className="bad-text">✗ {item.message}</span>}
                  </div>
                  {!busy && item.state !== "done" && (
                    <button type="button" className="link-btn" onClick={() => removeItem(item.id)} aria-label={"Remove " + item.file.name}>
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          <div className="upload-actions">
            <label className="field grow">
              <span>Domain name (groups these files together)</span>
              <input
                list="domain-options"
                type="text"
                placeholder="e.g. finance_ops"
                autoComplete="off"
                value={domain}
                disabled={busy}
                onChange={(e) => {
                  setDomain(e.target.value);
                  setDomainTouched(true);
                }}
              />
              <datalist id="domain-options">
                {domains.map((d) => (
                  <option key={d.id} value={d.id} />
                ))}
              </datalist>
              {domain && !domainValid && (
                <small className="bad-text">
                  Use 2 to 40 characters: lowercase letters, digits and underscores, starting with a letter.
                </small>
              )}
              {domainValid && domains.some((d) => d.id === domainId) && (
                <small>This domain exists. The files are added to it, and a file with the same name replaces that table.</small>
              )}
            </label>
            <button type="button" className="primary-btn" disabled={!items.length || !domainValid || busy} onClick={run}>
              {busy ? "Working…" : items.length > 1 ? "Upload " + items.length + " files" : "Upload file"}
            </button>
          </div>

          {status && <p className="dash-note onboard-status">{status}</p>}

          {phase === "done" && (
            <div className="done-box">
              {result && (
                <p>
                  Learned <strong>{result.metrics ? result.metrics.active : 0}</strong> metric(s) and{" "}
                  <strong>{result.joins ? result.joins.active : 0}</strong> join(s) across{" "}
                  <strong>{(result.datasets || []).length}</strong> table(s).
                </p>
              )}
              <div className="done-actions">
                <button type="button" className="primary-btn" onClick={() => onFinished(domainId, true)}>
                  Open dashboard
                </button>
                <button type="button" className="secondary-btn" onClick={reset}>
                  Upload more
                </button>
              </div>
            </div>
          )}
        </article>

      </div>
    </section>
  );
}
