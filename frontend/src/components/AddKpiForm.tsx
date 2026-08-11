import { useRef, useState } from "react";
import type { FeatureSuggestion } from "../api/audit";
import "./AddKpiForm.css";

interface AddKpiFormProps {
  columns: string[];
  busy: boolean;
  onAdd: (kpi: FeatureSuggestion) => void;
  onCancel: () => void;
}

// Wraps a column name in backticks for insertion into the formula textarea
// -- mirrors the backend's own auto-quoting (feature_engineering.py's
// _autoquote_columns), so a name with spaces still reads correctly, but
// clicking a chip does it for you instead of requiring you to know the
// backtick syntax.
function quoteColumn(col: string): string {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(col) ? col : `\`${col}\``;
}

export default function AddKpiForm({ columns, busy, onAdd, onCancel }: AddKpiFormProps) {
  const [name, setName] = useState("");
  const [formula, setFormula] = useState("");
  const [error, setError] = useState<string | null>(null);
  const formulaRef = useRef<HTMLTextAreaElement>(null);

  const insertColumn = (col: string) => {
    const el = formulaRef.current;
    const token = quoteColumn(col);
    if (!el) {
      setFormula((prev) => `${prev}${token}`);
      return;
    }
    const start = el.selectionStart ?? formula.length;
    const end = el.selectionEnd ?? formula.length;
    const next = `${formula.slice(0, start)}${token}${formula.slice(end)}`;
    setFormula(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const handleSubmit = () => {
    if (!name.trim()) return setError("Give the KPI a name.");
    if (!formula.trim()) return setError("Write a formula.");
    setError(null);

    onAdd({
      id: `custom_${Date.now().toString(36)}`,
      name: name.trim(),
      description: "Custom KPI added manually.",
      output_column: name.trim(),
      type: "custom_formula",
      formula: formula.trim(),
      summary: "stats",
      start_column: null,
      end_column: null,
      unit: null,
      numerator_columns: null,
      denominator_columns: null,
      source_columns: null,
    });
  };

  return (
    <div className="add-kpi-form">
      <label className="add-kpi-form__field">
        <span>KPI name</span>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Time in Transit" />
      </label>

      <label className="add-kpi-form__field">
        <span>Formula</span>
        <textarea
          ref={formulaRef}
          className="add-kpi-form__formula-input"
          value={formula}
          onChange={(e) => setFormula(e.target.value)}
          rows={3}
          placeholder="e.g. (`Time Below Ideal Hours` + `Time Above Ideal Hours`) / `Time Below Low Hours` * 100"
        />
      </label>

      <div className="add-kpi-form__field">
        <span>Click a column to insert it</span>
        <div className="add-kpi-form__column-chips">
          {columns.map((c) => (
            <button type="button" key={c} className="add-kpi-form__chip" onClick={() => insertColumn(c)}>
              {c}
            </button>
          ))}
        </div>
      </div>

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
