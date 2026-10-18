const DASHBOARD_QUESTIONS = 4;

export function pretty(name) {
  const text = String(name || "").replace(/[_\-.]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

export function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatValue(value, unit) {
  if (value == null || value === "") return "—";
  let n = toNumber(value);
  if (n == null) return String(value);
  if (unit === "percent" || unit === "%") {
    if (Math.abs(n) <= 1) n = n * 100;
    return n.toLocaleString(undefined, { maximumFractionDigits: 1 }) + "%";
  }
  if (unit === "usd" || unit === "$" || unit === "currency") {
    return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  }
  const text = n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return unit ? text + " " + unit : text;
}

/** Questions to run for the dashboard: the domain's own, else simple ones built from its columns. */
export function dashboardQuestions(detail) {
  const d = detail || {};
  const own = (d.starter_questions || []).slice(0, DASHBOARD_QUESTIONS);
  if (own.length) return own;
  const out = [];
  (d.tables || []).forEach((table) => {
    const measures = table.columns.filter(
      (c) => !c.restricted && /int|float/.test(c.dtype) && c.role !== "key" && c.role !== "foreign_key" && !/id$/i.test(c.name)
    );
    const dims = table.columns.filter(
      (c) => !c.restricted && c.dtype === "object" && c.role !== "key" && c.role !== "foreign_key" && c.role !== "timestamp"
    );
    measures.slice(0, 2).forEach((m) => {
      const label = String(m.name).replace(/_/g, " ");
      out.push("What is the total " + label + "?");
      if (dims.length) out.push("What is the total " + label + " by " + String(dims[0].name).replace(/_/g, " ") + "?");
    });
  });
  return out.slice(0, DASHBOARD_QUESTIONS);
}
