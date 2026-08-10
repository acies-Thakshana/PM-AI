import { useEffect, useState } from "react";
import { IconChevronDown } from "./icons";
import "./PivotFilterBar.css";

type Selections = Record<string, string[] | undefined>;

interface PivotFilterBarProps {
  filterableColumns: string[];
  filterOptions: Record<string, string[]>;
  /** The last-SAVED selections, i.e. what the pivot's current rows reflect. Missing/undefined for a column means "all selected". */
  selected: Selections;
  /** Called once, with the full draft, when the user clicks "Save Filters". */
  onSave: (next: Selections) => void;
  saving?: boolean;
}

function sameSelections(a: Selections, b: Selections, columns: string[]): boolean {
  return columns.every((c) => JSON.stringify([...(a[c] ?? [])].sort()) === JSON.stringify([...(b[c] ?? [])].sort()));
}

export default function PivotFilterBar({ filterableColumns, filterOptions, selected, onSave, saving }: PivotFilterBarProps) {
  const columns = filterableColumns.filter((c) => (filterOptions[c] ?? []).length > 0);
  const [draft, setDraft] = useState<Selections>(selected);

  // Re-sync the draft whenever the saved selections change underneath us
  // (e.g. right after a save completes) so checkboxes reflect reality.
  useEffect(() => {
    setDraft(selected);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(selected)]);

  if (columns.length === 0) return null;

  const dirty = !sameSelections(draft, selected, columns);

  const setColumn = (column: string, values: string[] | undefined) => setDraft((prev) => ({ ...prev, [column]: values }));

  return (
    <div className="pivot-filter-bar">
      <div className="pivot-filter-bar__row">
        {columns.map((column) => {
          const options = filterOptions[column] ?? [];
          const current = draft[column];
          const isAll = current === undefined;
          const activeSet = new Set(current ?? options);

          const toggle = (option: string) => {
            const next = activeSet.has(option) ? [...activeSet].filter((v) => v !== option) : [...activeSet, option];
            setColumn(column, next.length === options.length ? undefined : next);
          };

          return (
            <details key={column} className="pivot-filter-bar__item">
              <summary className="pivot-filter-bar__summary">
                <span className="pivot-filter-bar__label">{column}</span>
                <span className="pivot-filter-bar__value">{isAll ? "All" : `${activeSet.size} of ${options.length}`}</span>
                <IconChevronDown />
              </summary>
              <div className="pivot-filter-bar__panel">
                <div className="pivot-filter-bar__panel-actions">
                  <button type="button" onClick={() => setColumn(column, undefined)}>
                    Select all
                  </button>
                  <button type="button" onClick={() => setColumn(column, [])}>
                    Clear
                  </button>
                </div>
                <div className="pivot-filter-bar__checklist">
                  {options.map((option) => (
                    <label key={option} className="pivot-filter-bar__check">
                      <input type="checkbox" checked={activeSet.has(option)} onChange={() => toggle(option)} />
                      {option}
                    </label>
                  ))}
                </div>
              </div>
            </details>
          );
        })}
      </div>

      <div className="pivot-filter-bar__save-row">
        {dirty && !saving && <span className="pivot-filter-bar__unsaved">Unsaved filter changes</span>}
        <button type="button" className="pivot-filter-bar__discard-btn" disabled={!dirty || saving} onClick={() => setDraft(selected)}>
          Discard
        </button>
        <button type="button" className="pivot-filter-bar__save-btn" disabled={!dirty || saving} onClick={() => onSave(draft)}>
          {saving ? "Saving…" : "Save Filters"}
        </button>
      </div>
    </div>
  );
}
