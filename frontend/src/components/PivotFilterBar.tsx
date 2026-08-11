import { useRef } from "react";
import { IconChevronDown } from "./icons";
import "./PivotFilterBar.css";

type Selections = Record<string, string[] | undefined>;

interface PivotFilterBarProps {
  filterableColumns: string[];
  filterOptions: Record<string, string[]>;
  /** Deduplicated real combinations of the filterable columns -- lets each
   * column's option list narrow to whatever co-occurs with the OTHER
   * columns' current selection, e.g. picking Italy narrows Carrier down to
   * Italy's carriers instead of showing every carrier. */
  combinations: Record<string, string>[];
  /** Missing/undefined for a column means "all selected". Every change is
   * applied immediately -- there's no separate draft/save step. */
  selected: Selections;
  onSave: (next: Selections) => void;
  saving?: boolean;
}

/** Options for `column` that actually co-occur with every OTHER column's
 * current selection, per the real row combinations from the backend.
 * Falls back to the full option list when there's no combination data. */
function visibleOptionsFor(
  column: string,
  columns: string[],
  combinations: Record<string, string>[],
  selected: Selections,
  filterOptions: Record<string, string[]>
): string[] {
  if (combinations.length === 0) return filterOptions[column] ?? [];
  const others = columns.filter((c) => c !== column);
  const values = new Set<string>();
  for (const combo of combinations) {
    const value = combo[column];
    if (value === undefined) continue;
    const matchesOthers = others.every((oc) => {
      const sel = selected[oc];
      if (sel === undefined) return true;
      const val = combo[oc];
      return val !== undefined && sel.includes(val);
    });
    if (matchesOthers) values.add(value);
  }
  return [...values].sort();
}

export default function PivotFilterBar({ filterableColumns, filterOptions, combinations = [], selected, onSave, saving }: PivotFilterBarProps) {
  const columns = filterableColumns.filter((c) => (filterOptions[c] ?? []).length > 0);
  const detailsRefs = useRef<Record<string, HTMLDetailsElement | null>>({});

  if (columns.length === 0) return null;

  const closeColumn = (column: string) => {
    const el = detailsRefs.current[column];
    if (el) el.open = false;
  };

  const setColumn = (column: string, values: string[] | undefined) => onSave({ ...selected, [column]: values });

  return (
    <div className="pivot-filter-bar">
      <div className="pivot-filter-bar__row">
        {columns.map((column) => {
          const options = visibleOptionsFor(column, columns, combinations, selected, filterOptions);
          const current = selected[column];
          const isAll = current === undefined;
          const activeSet = current === undefined ? new Set(options) : new Set(current.filter((v) => options.includes(v)));

          const toggle = (option: string) => {
            const next = activeSet.has(option) ? [...activeSet].filter((v) => v !== option) : [...activeSet, option];
            setColumn(column, next.length === options.length ? undefined : next);
          };

          return (
            <details key={column} className="pivot-filter-bar__item" ref={(el) => { detailsRefs.current[column] = el; }}>
              <summary className="pivot-filter-bar__summary">
                <span className="pivot-filter-bar__label">{column}</span>
                <span className="pivot-filter-bar__value">{isAll ? "All" : `${activeSet.size} of ${options.length}`}</span>
                <IconChevronDown />
              </summary>
              <div className="pivot-filter-bar__panel">
                <div className="pivot-filter-bar__panel-actions">
                  <button type="button" disabled={saving} onClick={() => setColumn(column, undefined)}>
                    Select all
                  </button>
                  <button type="button" disabled={saving} onClick={() => setColumn(column, [])}>
                    Clear
                  </button>
                  <button
                    type="button"
                    className="pivot-filter-bar__close-btn"
                    onClick={() => closeColumn(column)}
                    aria-label="Close"
                  >
                    ×
                  </button>
                </div>
                <div className="pivot-filter-bar__checklist">
                  {options.map((option) => (
                    <label key={option} className="pivot-filter-bar__check">
                      <input type="checkbox" checked={activeSet.has(option)} disabled={saving} onChange={() => toggle(option)} />
                      {option}
                    </label>
                  ))}
                </div>
              </div>
            </details>
          );
        })}
      </div>
    </div>
  );
}
