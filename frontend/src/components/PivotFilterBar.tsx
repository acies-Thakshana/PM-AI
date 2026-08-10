import { IconChevronDown } from "./icons";
import "./PivotFilterBar.css";

interface PivotFilterBarProps {
  filterableColumns: string[];
  filterOptions: Record<string, string[]>;
  /** Missing/undefined for a column means "all selected" (no filter applied). */
  selected: Record<string, string[] | undefined>;
  onChange: (column: string, values: string[] | undefined) => void;
}

export default function PivotFilterBar({ filterableColumns, filterOptions, selected, onChange }: PivotFilterBarProps) {
  const columns = filterableColumns.filter((c) => (filterOptions[c] ?? []).length > 0);
  if (columns.length === 0) return null;

  return (
    <div className="pivot-filter-bar">
      {columns.map((column) => {
        const options = filterOptions[column] ?? [];
        const current = selected[column];
        const isAll = current === undefined;
        const activeSet = new Set(current ?? options);

        const toggle = (option: string) => {
          const next = activeSet.has(option) ? [...activeSet].filter((v) => v !== option) : [...activeSet, option];
          onChange(column, next.length === options.length ? undefined : next);
        };

        return (
          <details key={column} className="pivot-filter-bar__item">
            <summary className="pivot-filter-bar__summary">
              <span className="pivot-filter-bar__label">{column}</span>
              <span className="pivot-filter-bar__value">
                {isAll ? "All" : `${activeSet.size} of ${options.length}`}
              </span>
              <IconChevronDown />
            </summary>
            <div className="pivot-filter-bar__panel">
              <div className="pivot-filter-bar__panel-actions">
                <button type="button" onClick={() => onChange(column, undefined)}>
                  Select all
                </button>
                <button type="button" onClick={() => onChange(column, [])}>
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
  );
}
