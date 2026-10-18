// Empty in dev: Vite proxies /api to the backend (see vite.config.js). Set VITE_API_BASE to point elsewhere.
const API = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

export function fetchJson(path, options, timeoutMs = 120000) {
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  const opts = { ...(options || {}) };
  if (controller) opts.signal = controller.signal;
  return fetch(API + path, opts)
    .then((response) => {
      if (timer) clearTimeout(timer);
      return response
        .json()
        .catch(() => ({}))
        .then((data) => {
          if (!response.ok) {
            const err = data && data.error;
            let message = (err && err.message) || (data && data.detail) || "The backend returned " + response.status;
            if (err && err.details && err.details.length) {
              message += " (" + err.details.map((d) => d.field + ": " + d.message).join("; ") + ")";
            }
            throw new Error(message);
          }
          return data;
        });
    })
    .catch((error) => {
      if (timer) clearTimeout(timer);
      if (error && error.name === "AbortError") throw new Error("The backend did not answer in time.");
      if (error instanceof TypeError) {
        throw new Error("Cannot reach the backend at " + (API || window.location.origin) + ". Is it running?");
      }
      throw error;
    });
}

export function postJson(path, body, timeoutMs) {
  return fetchJson(
    path,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) },
    timeoutMs
  );
}

export const getInfo = () => fetchJson("/api/info", { method: "GET" }, 15000);
export const getDomains = () => fetchJson("/api/domains", { method: "GET" }, 30000);
export const getDomain = (domain) => fetchJson("/api/domains/" + encodeURIComponent(domain), { method: "GET" }, 60000);
export const getJob = (id) => fetchJson("/api/jobs/" + encodeURIComponent(id), { method: "GET" }, 30000);
export const startOnboarding = (domain) =>
  postJson("/api/domains/" + encodeURIComponent(domain) + "/onboard", { force: false }, 30000);

export function uploadDataset(domain, file) {
  const form = new FormData();
  form.append("file", file);
  return fetchJson("/api/domains/" + encodeURIComponent(domain) + "/datasets", { method: "POST", body: form }, 300000);
}

/** Ask one question and return the card view model. */
export function askQuestion(question, domain, sessionId) {
  const body = { question, domain };
  if (sessionId) body.session_id = sessionId;
  return postJson("/api/ask", body, 120000).then((data) => toView(question, data));
}

/** Turn one /api/ask response into what the answer card and dashboard need. */
export function toView(question, data) {
  const chart = data.chart || {};
  const table = data.table || { columns: [], rows: [] };
  let viz = { kind: "empty", note: "No chart for this answer." };
  const y = (chart.y && chart.y[0]) || null;
  const unit = chart.unit || "";
  if (chart.template === "kpi_card" && chart.value != null) {
    viz = { kind: "number", label: chart.title || "Value", value: chart.value, unit };
  } else if (chart.x && y && (chart.data || []).length && !chart.series) {
    viz = {
      kind: "bars",
      unit,
      items: chart.data.slice(0, 30).map((row) => ({ label: String(row[chart.x]), value: row[y] }))
    };
  } else if (table.rows && table.rows.length) {
    viz = { kind: "table", columns: table.columns, rows: table.rows };
  }
  const findings = (data.key_findings || []).filter((f) => f && data.answer.indexOf(f) < 0);
  const reasoning = [];
  if (data.interpreted_question) reasoning.push("Interpreted as: " + data.interpreted_question);
  if (data.sql_rationale) reasoning.push(data.sql_rationale);
  const exp = data.explainability || {};
  if (exp.applied_filters && Object.keys(exp.applied_filters).length) {
    reasoning.push(
      "Filters: " +
        Object.keys(exp.applied_filters)
          .map((k) => k + " = " + [].concat(exp.applied_filters[k]).join(", "))
          .join("; ")
    );
  }
  if (data.datasets_used && data.datasets_used.length) reasoning.push("Tables used: " + data.datasets_used.join(", "));
  return {
    question,
    ok: data.status === "success",
    explanation: [data.answer].concat(findings).join("\n"),
    reasoning: reasoning.join("\n"),
    sql: data.sql_query,
    viz,
    confidence: data.confidence,
    warnings: data.warnings || [],
    pathLabel: data.answer_path === "llm" ? "Model-assisted" : "Deterministic planner",
    chart,
    status: data.status
  };
}
