import { useState } from "react";
import type { FeatureSuggestion, FeatureSuggestionType } from "../api/audit";
import "./AddKpiForm.css";

interface AddKpiFormProps {
  columns: string[];
  busy: boolean;
  onAdd: (kpi: FeatureSuggestion) => void;
  onCancel: () => void;
}

function buildFormula(
  type: FeatureSuggestionType,
  startColumn: string,
  endColumn: string,
  unit: string,
  numeratorColumns: string[],
  denominatorColumns: string[],
  sourceColumns: string[]
): string {
  if (type === "duration_hours") return `${endColumn || "?"} minus ${startColumn || "?"}, in ${unit}`;
  if (type === "ratio") {
    return `(${numeratorColumns.join(" + ") || "?"}) / (${denominatorColumns.join(" + ") || "?"}) x 100`;
  }
  return `Calendar month of ${sourceColumns.join(" / ") || "?"}`;
}

function toggleInList(list: string[], col: string): string[] {
  return list.includes(col) ? list.filter((c) => c !== col) : [...list, col];
}

export default function AddKpiForm({ columns, busy, onAdd, onCancel }: AddKpiFormProps) {
  const [name, setName] = useState("");
  const [type, setType] = useState<FeatureSuggestionType>("duration_hours");
  const [startColumn, setStartColumn] = useState("");
  const [endColumn, setEndColumn] = useState("");
  const [unit, setUnit] = useState<"hours" | "days">("hours");
  const [numeratorColumns, setNumeratorColumns] = useState<string[]>([]);
  const [denominatorColumns, setDenominatorColumns] = useState<string[]>([]);
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const formula = buildFormula(type, startColumn, endColumn, unit, numeratorColumns, denominatorColumns, sourceColumns);

  const handleSubmit = () => {
    if (!name.trim()) return setError("Give the KPI a name.");
    if (type === "duration_hours" && (!startColumn || !endColumn)) {
      return setError("Pick both a start and end column.");
    }
    if (type === "ratio" && (numeratorColumns.length === 0 || denominatorColumns.length === 0)) {
      return setError("Pick at least one numerator column and one denominator column.");
    }
    if (type === "extract_month" && sourceColumns.length === 0) {
      return setError("Pick at least one source column.");
    }
    setError(null);

    onAdd({
      id: `custom_${Date.now().toString(36)}`,
      name: name.trim(),
      description: "Custom KPI added manually.",
      output_column: name.trim(),
      type,
      formula: buildFormula(type, startColumn, endColumn, unit, numeratorColumns, denominatorColumns, sourceColumns),
      summary: type === "extract_month" ? "distribution" : "stats",
      start_column: type === "duration_hours" ? startColumn : null,
      end_column: type === "duration_hours" ? endColumn : null,
      unit: type === "duration_hours" ? unit : null,
      numerator_columns: type === "ratio" ? numeratorColumns : null,
      denominator_columns: type === "ratio" ? denominatorColumns : null,
      source_columns: type === "extract_month" ? sourceColumns : null,
    });
  };

  return (
    <div className="add-kpi-form">
      <div className="add-kpi-form__row">
        <label className="add-kpi-form__field">
          <span>KPI name</span>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Time in Transit" />
        </label>
        <label className="add-kpi-form__field add-kpi-form__field--narrow">
          <span>Type</span>
          <select value={type} onChange={(e) => setType(e.target.value as FeatureSuggestionType)}>
            <option value="duration_hours">Duration between two columns</option>
            <option value="ratio">Percentage ratio</option>
            <option value="extract_month">Extract calendar month</option>
          </select>
        </label>
      </div>

      <p className="add-kpi-form__formula-preview">
        ƒ {formula}
      </p>

      {type === "duration_hours" && (
        <div className="add-kpi-form__row">
          <label className="add-kpi-form__field">
            <span>Start column</span>
            <select value={startColumn} onChange={(e) => setStartColumn(e.target.value)}>
              <option value="">Select…</option>
              {columns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="add-kpi-form__field">
            <span>End column</span>
            <select value={endColumn} onChange={(e) => setEndColumn(e.target.value)}>
              <option value="">Select…</option>
              {columns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="add-kpi-form__field add-kpi-form__field--narrow">
            <span>Unit</span>
            <select value={unit} onChange={(e) => setUnit(e.target.value as "hours" | "days")}>
              <option value="hours">Hours</option>
              <option value="days">Days</option>
            </select>
          </label>
        </div>
      )}

      {type === "ratio" && (
        <div className="add-kpi-form__row">
          <div className="add-kpi-form__field">
            <span>Numerator column(s)</span>
            <div className="add-kpi-form__checklist">
              {columns.map((c) => (
                <label key={c} className="add-kpi-form__check">
                  <input
                    type="checkbox"
                    checked={numeratorColumns.includes(c)}
                    onChange={() => setNumeratorColumns((prev) => toggleInList(prev, c))}
                  />
                  {c}
                </label>
              ))}
            </div>
          </div>
          <div className="add-kpi-form__field">
            <span>Denominator column(s)</span>
            <div className="add-kpi-form__checklist">
              {columns.map((c) => (
                <label key={c} className="add-kpi-form__check">
                  <input
                    type="checkbox"
                    checked={denominatorColumns.includes(c)}
                    onChange={() => setDenominatorColumns((prev) => toggleInList(prev, c))}
                  />
                  {c}
                </label>
              ))}
            </div>
          </div>
        </div>
      )}

      {type === "extract_month" && (
        <div className="add-kpi-form__field">
          <span>Source column(s)</span>
          <div className="add-kpi-form__checklist">
            {columns.map((c) => (
              <label key={c} className="add-kpi-form__check">
                <input
                  type="checkbox"
                  checked={sourceColumns.includes(c)}
                  onChange={() => setSourceColumns((prev) => toggleInList(prev, c))}
                />
                {c}
              </label>
            ))}
          </div>
        </div>
      )}

      {error && <p className="add-kpi-form__error">{error}</p>}

      <div className="add-kpi-form__actions">
        <button type="button" className="add-kpi-form__btn add-kpi-form__btn--primary" disabled={busy} onClick={handleSubmit}>
          {busy ? "Adding…" : "Add KPI"}
        </button>
        <button type="button" className="add-kpi-form__btn add-kpi-form__btn--secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
