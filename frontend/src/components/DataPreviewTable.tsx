import type { DataPreview } from "../api/audit";
import "./DataPreviewTable.css";

interface DataPreviewTableProps {
  preview: DataPreview;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

export default function DataPreviewTable({ preview }: DataPreviewTableProps) {
  return (
    <div className="data-preview">
      <p className="data-preview__caption">
        Showing {preview.preview_row_count.toLocaleString()} of {preview.row_count.toLocaleString()} rows,
        all {preview.columns.length} columns (including the engineered features) -- scroll to see more.
      </p>
      <div className="data-preview__scroll">
        <table className="data-preview__table">
          <thead>
            <tr>
              {preview.columns.map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, idx) => (
              <tr key={idx}>
                {preview.columns.map((col) => (
                  <td key={col}>{formatCell(row[col])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
