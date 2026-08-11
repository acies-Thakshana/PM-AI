import { useState } from "react";
import type { PivotResult } from "../api/audit";
import { IconChevronDown } from "./icons";
import PivotFilterBar from "./PivotFilterBar";
import "./PivotTableCard.css";

interface PivotTableCardProps {
  pivot: PivotResult;
  filterSelections: Record<string, string[] | undefined>;
  onSaveFilters: (next: Record<string, string[] | undefined>) => void;
  savingFilters?: boolean;
  hideHeader?: boolean;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

export default function PivotTableCard({ pivot, filterSelections, onSaveFilters, savingFilters, hideHeader }: PivotTableCardProps) {
  const [sort, setSort] = useState<{ column: string; direction: "asc" | "desc" } | null>(null);
  const columns = [...pivot.group_by, ...pivot.metric_labels];

  const rows = [...pivot.rows];
  if (sort) {
    rows.sort((a, b) => {
      const av = a[sort.column];
      const bv = b[sort.column];
      if (av === bv) return 0;
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
      return sort.direction === "asc" ? cmp : -cmp;
    });
  }

  const toggleSort = (column: string) => {
    setSort((prev) => {
      if (prev?.column !== column) return { column, direction: "desc" };
      return { column, direction: prev.direction === "desc" ? "asc" : "desc" };
    });
  };

  return (
    <div className="pivot-table-card">
      {!hideHeader && (
        <div className="pivot-table-card__head">
          <div>
            <h3 className="pivot-table-card__name">{pivot.name}</h3>
            <p className="pivot-table-card__description">{pivot.description}</p>
          </div>
          {pivot.id.startsWith("ai_pivot_") && <span className="pivot-table-card__ai-badge">AI</span>}
          {pivot.id.startsWith("custom_pivot_") && <span className="pivot-table-card__custom-badge">Custom</span>}
        </div>
      )}

      <PivotFilterBar
        filterableColumns={pivot.filterable_columns}
        filterOptions={pivot.filter_options}
        combinations={pivot.filter_combinations ?? []}
        selected={filterSelections}
        onSave={onSaveFilters}
        saving={savingFilters}
      />

      {pivot.row_count === 0 ? (
        <p className="pivot-table-card__empty">No rows match the current filter selection.</p>
      ) : (
      <div className="pivot-table-card__scroll">
        <table className="pivot-table-card__table">
          <thead>
            <tr>
              {columns.map((col) => {
                const isMetric = pivot.metric_labels.includes(col);
                const active = sort?.column === col;
                return (
                  <th key={col} className={isMetric ? "pivot-table-card__th--metric" : ""}>
                    <button type="button" className="pivot-table-card__sort-btn" onClick={() => toggleSort(col)}>
                      {col}
                      <IconChevronDown />
                      {active && <span className="pivot-table-card__sort-dir">{sort!.direction === "asc" ? "▲" : "▼"}</span>}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={idx}>
                {columns.map((col) => (
                  <td key={col} className={pivot.metric_labels.includes(col) ? "pivot-table-card__td--metric" : ""}>
                    {formatCell(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
      {pivot.row_count > 0 && <p className="pivot-table-card__row-count">{pivot.row_count.toLocaleString()} row(s)</p>}
    </div>
  );
}
