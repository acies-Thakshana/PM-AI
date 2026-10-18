import { formatValue, toNumber } from "../format.js";

export function Bars({ items, unit }) {
  const rows = items || [];
  if (!rows.length) return <p className="dash-note">No grouped values.</p>;
  const max = Math.max(0, ...rows.map((item) => Math.abs(toNumber(item.value) || 0)));
  return (
    <div className="bars">
      {rows.map((item, i) => {
        const width = max ? Math.max(4, (Math.abs(toNumber(item.value) || 0) / max) * 100) : 0;
        return (
          <div className="bar-row" key={i}>
            <span>{item.label}</span>
            <div className="track">
              <div className="fill" style={{ width: width + "%" }} />
            </div>
            <span className="bar-value">{formatValue(item.value, unit)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function DataTable({ columns, rows }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {(columns || []).map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(rows || []).map((record, i) => (
            <tr key={i}>
              {(columns || []).map((c) => (
                <td key={c}>{record[c] == null ? "" : String(record[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Viz({ viz }) {
  if (!viz || viz.kind === "empty") return <p className="dash-note">{(viz && viz.note) || "No chart for this answer."}</p>;
  if (viz.kind === "number") {
    return (
      <div className="part-row">
        <span>{viz.label || "Value"}</span>
        <strong className="viz-number">{formatValue(viz.value, viz.unit)}</strong>
      </div>
    );
  }
  if (viz.kind === "bars") return <Bars items={viz.items} unit={viz.unit} />;
  if (viz.kind === "table") return <DataTable columns={viz.columns} rows={viz.rows} />;
  return null;
}
