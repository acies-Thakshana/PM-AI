import { useState } from "react";
import type { CustomPivot, PivotAgg, PivotFilter, PivotMetric } from "../api/audit";
import "./AddPivotForm.css";

interface AddPivotFormProps {
  columns: string[];
  busy: boolean;
  onAdd: (pivot: CustomPivot) => void;
  onCancel: () => void;
}

const AGG_OPTIONS: { value: PivotAgg; label: string }[] = [
  { value: "count", label: "Count" },
  { value: "sum", label: "Sum" },
  { value: "mean", label: "Average" },
  { value: "median", label: "Median" },
  { value: "min", label: "Min" },
  { value: "max", label: "Max" },
  { value: "distinct_count", label: "Distinct count" },
  { value: "pct_of_total", label: "% of total" },
];

const FILTER_OPS: { value: PivotFilter["op"]; label: string }[] = [
  { value: "eq", label: "equals" },
  { value: "neq", label: "not equals" },
  { value: "in", label: "is one of" },
  { value: "gt", label: ">" },
  { value: "gte", label: ">=" },
  { value: "lt", label: "<" },
  { value: "lte", label: "<=" },
];

function toggleInList(list: string[], col: string): string[] {
  return list.includes(col) ? list.filter((c) => c !== col) : [...list, col];
}

function emptyMetric(firstColumn: string): PivotMetric {
  return { column: firstColumn, agg: "count", output_label: "" };
}

export default function AddPivotForm({ columns, busy, onAdd, onCancel }: AddPivotFormProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [groupBy, setGroupBy] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<PivotMetric[]>([emptyMetric(columns[0] ?? "")]);
  const [useFilter, setUseFilter] = useState(false);
  const [filterColumn, setFilterColumn] = useState(columns[0] ?? "");
  const [filterOp, setFilterOp] = useState<PivotFilter["op"]>("eq");
  const [filterValue, setFilterValue] = useState("");
  const [sortMetric, setSortMetric] = useState("");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [topN, setTopN] = useState("");
  const [error, setError] = useState<string | null>(null);

  const updateMetric = (idx: number, patch: Partial<PivotMetric>) => {
    setMetrics((prev) => prev.map((m, i) => (i === idx ? { ...m, ...patch } : m)));
  };

  const addMetricRow = () => setMetrics((prev) => [...prev, emptyMetric(columns[0] ?? "")]);
  const removeMetricRow = (idx: number) => setMetrics((prev) => prev.filter((_, i) => i !== idx));

  const handleSubmit = () => {
    if (!name.trim()) return setError("Give the analysis a name.");
    if (groupBy.length === 0) return setError("Pick at least one group-by column.");
    const cleanMetrics = metrics.filter((m) => m.column && m.output_label.trim());
    if (cleanMetrics.length === 0) return setError("Add at least one metric with a label.");
    if (useFilter && (!filterColumn || !filterValue.trim())) {
      return setError("Fill in the filter column and value, or turn the filter off.");
    }
    setError(null);

    const labels = new Set(cleanMetrics.map((m) => m.output_label));
    const sortBy = sortMetric && labels.has(sortMetric) ? { metric: sortMetric, direction: sortDirection } : null;
    const parsedTopN = topN.trim() ? parseInt(topN, 10) : null;

    const filterValueParsed =
      filterOp === "in" ? filterValue.split(",").map((v) => v.trim()).filter(Boolean) : filterValue.trim();

    onAdd({
      id: `custom_pivot_${Date.now().toString(36)}`,
      name: name.trim(),
      description: description.trim() || "Custom analysis added manually.",
      group_by: groupBy,
      metrics: cleanMetrics,
      filters: useFilter ? [{ column: filterColumn, op: filterOp, value: filterValueParsed }] : [],
      sort_by: sortBy,
      top_n: parsedTopN && parsedTopN > 0 ? parsedTopN : null,
    });
  };

  return (
    <div className="add-pivot-form">
      <div className="add-pivot-form__row">
        <label className="add-pivot-form__field">
          <span>Analysis name</span>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Performance by Carrier" />
        </label>
      </div>

      <label className="add-pivot-form__field">
        <span>Description (optional)</span>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What does this analysis show?"
        />
      </label>

      <div className="add-pivot-form__field">
        <span>Group by column(s)</span>
        <div className="add-pivot-form__checklist">
          {columns.map((c) => (
            <label key={c} className="add-pivot-form__check">
              <input type="checkbox" checked={groupBy.includes(c)} onChange={() => setGroupBy((prev) => toggleInList(prev, c))} />
              {c}
            </label>
          ))}
        </div>
      </div>

      <div className="add-pivot-form__field">
        <span>Metrics</span>
        {metrics.map((metric, idx) => (
          <div className="add-pivot-form__metric-row" key={idx}>
            <select value={metric.column} onChange={(e) => updateMetric(idx, { column: e.target.value })}>
              {columns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <select value={metric.agg} onChange={(e) => updateMetric(idx, { agg: e.target.value as PivotAgg })}>
              {AGG_OPTIONS.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={metric.output_label}
              onChange={(e) => updateMetric(idx, { output_label: e.target.value })}
              placeholder="Display label"
            />
            {metrics.length > 1 && (
              <button type="button" className="add-pivot-form__remove-btn" onClick={() => removeMetricRow(idx)}>
                ×
              </button>
            )}
          </div>
        ))}
        <button type="button" className="add-pivot-form__add-metric-btn" onClick={addMetricRow}>
          + Add metric
        </button>
      </div>

      <div className="add-pivot-form__field">
        <label className="add-pivot-form__check">
          <input type="checkbox" checked={useFilter} onChange={(e) => setUseFilter(e.target.checked)} />
          Only include rows where…
        </label>
        {useFilter && (
          <div className="add-pivot-form__row">
            <select value={filterColumn} onChange={(e) => setFilterColumn(e.target.value)}>
              {columns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <select value={filterOp} onChange={(e) => setFilterOp(e.target.value as PivotFilter["op"])}>
              {FILTER_OPS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={filterValue}
              onChange={(e) => setFilterValue(e.target.value)}
              placeholder={filterOp === "in" ? "Value1, Value2, Value3…" : "Value"}
            />
          </div>
        )}
      </div>

      <div className="add-pivot-form__row">
        <label className="add-pivot-form__field add-pivot-form__field--narrow">
          <span>Sort by (optional)</span>
          <select value={sortMetric} onChange={(e) => setSortMetric(e.target.value)}>
            <option value="">No sort</option>
            {metrics.filter((m) => m.output_label.trim()).map((m) => (
              <option key={m.output_label} value={m.output_label}>
                {m.output_label}
              </option>
            ))}
          </select>
        </label>
        <label className="add-pivot-form__field add-pivot-form__field--narrow">
          <span>Direction</span>
          <select value={sortDirection} onChange={(e) => setSortDirection(e.target.value as "asc" | "desc")}>
            <option value="desc">High to low</option>
            <option value="asc">Low to high</option>
          </select>
        </label>
        <label className="add-pivot-form__field add-pivot-form__field--narrow">
          <span>Top N rows (optional)</span>
          <input type="number" min="1" value={topN} onChange={(e) => setTopN(e.target.value)} placeholder="All" />
        </label>
      </div>

      {error && <p className="add-pivot-form__error">{error}</p>}

      <div className="add-pivot-form__actions">
        <button type="button" className="add-pivot-form__btn add-pivot-form__btn--primary" disabled={busy} onClick={handleSubmit}>
          {busy ? "Adding…" : "Add Analysis"}
        </button>
        <button type="button" className="add-pivot-form__btn add-pivot-form__btn--secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
