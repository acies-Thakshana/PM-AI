import { useMemo, useState } from "react";
import type { PivotResult } from "../api/audit";
import "./PivotChart.css";

interface PivotChartProps {
  pivot: PivotResult;
}

const CHART_HEIGHT = 320;
const CHART_TOP_PAD = 24;
const BAR_MAX_WIDTH = 36;
const MAX_POINTS = 30;

function isTrend(pivot: PivotResult): boolean {
  return pivot.group_by.length === 1 && pivot.group_by[0].toLowerCase().includes("month");
}

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0];
  const step = Math.pow(10, Math.floor(Math.log10(max / count)));
  const rounded = Math.ceil(max / count / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= max + rounded * 0.001; v += rounded) ticks.push(Math.round(v * 100) / 100);
  return ticks;
}

export default function PivotChart({ pivot }: PivotChartProps) {
  const [metric, setMetric] = useState(pivot.metric_labels[0]);
  const [hover, setHover] = useState<number | null>(null);

  const points = useMemo(() => {
    return pivot.rows
      .filter((r) => typeof r[metric] === "number")
      .slice(0, MAX_POINTS)
      .map((r) => ({
        label: pivot.group_by.map((c) => String(r[c] ?? "—")).join(" / "),
        value: r[metric] as number,
      }));
  }, [pivot.rows, pivot.group_by, metric]);

  if (points.length === 0) {
    return <p className="pivot-chart__empty">No numeric data to chart for this metric.</p>;
  }

  const trend = isTrend(pivot);
  const maxValue = Math.max(...points.map((p) => p.value), 0);
  const ticks = niceTicks(maxValue);
  const axisMax = ticks[ticks.length - 1] || 1;

  const width = Math.max(points.length * 56, 480);
  const plotHeight = CHART_HEIGHT - CHART_TOP_PAD - 32;
  const yFor = (v: number) => CHART_TOP_PAD + plotHeight - (v / axisMax) * plotHeight;
  const barWidth = Math.min(BAR_MAX_WIDTH, (width / points.length) * 0.6);

  return (
    <div className="pivot-chart">
      {pivot.metric_labels.length > 1 && (
        <div className="pivot-chart__toggle" role="tablist">
          {pivot.metric_labels.map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={m === metric}
              className={`pivot-chart__toggle-btn ${m === metric ? "pivot-chart__toggle-btn--active" : ""}`}
              onClick={() => setMetric(m)}
            >
              {m}
            </button>
          ))}
        </div>
      )}

      <div className="pivot-chart__scroll">
        <svg
          className="pivot-chart__svg"
          width={width}
          height={CHART_HEIGHT}
          viewBox={`0 0 ${width} ${CHART_HEIGHT}`}
          role="img"
          aria-label={`${trend ? "Line" : "Bar"} chart of ${metric} by ${pivot.group_by.join(", ")}`}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={0}
                x2={width}
                y1={yFor(t)}
                y2={yFor(t)}
                className="pivot-chart__gridline"
              />
              <text x={4} y={yFor(t) - 4} className="pivot-chart__tick-label">
                {t.toLocaleString()}
              </text>
            </g>
          ))}

          {trend ? (
            <>
              <polyline
                className="pivot-chart__line"
                points={points
                  .map((p, i) => `${(i + 0.5) * (width / points.length)},${yFor(p.value)}`)
                  .join(" ")}
              />
              {points.map((p, i) => {
                const cx = (i + 0.5) * (width / points.length);
                const cy = yFor(p.value);
                return (
                  <g key={i}>
                    <circle
                      cx={cx}
                      cy={cy}
                      r={5}
                      className="pivot-chart__marker"
                      onMouseEnter={() => setHover(i)}
                      onMouseLeave={() => setHover(null)}
                    />
                    <text x={cx} y={CHART_HEIGHT - 10} textAnchor="middle" className="pivot-chart__cat-label">
                      {p.label}
                    </text>
                  </g>
                );
              })}
            </>
          ) : (
            points.map((p, i) => {
              const slot = width / points.length;
              const cx = (i + 0.5) * slot;
              const barH = plotHeight - (yFor(p.value) - CHART_TOP_PAD);
              const y = yFor(p.value);
              return (
                <g key={i}>
                  <rect
                    x={cx - barWidth / 2}
                    y={y}
                    width={barWidth}
                    height={Math.max(barH, 1)}
                    rx={4}
                    className={`pivot-chart__bar ${hover === i ? "pivot-chart__bar--hover" : ""}`}
                    onMouseEnter={() => setHover(i)}
                    onMouseLeave={() => setHover(null)}
                  />
                  <text x={cx} y={CHART_HEIGHT - 10} textAnchor="middle" className="pivot-chart__cat-label">
                    {p.label.length > 14 ? `${p.label.slice(0, 13)}…` : p.label}
                  </text>
                </g>
              );
            })
          )}

          {hover !== null && (
            <g>
              {(() => {
                const p = points[hover];
                const slot = width / points.length;
                const cx = (hover + 0.5) * slot;
                const cy = yFor(p.value);
                const tipW = 120;
                const tipX = Math.min(Math.max(cx - tipW / 2, 2), width - tipW - 2);
                return (
                  <g transform={`translate(${tipX}, ${Math.max(cy - 46, 2)})`}>
                    <rect width={tipW} height={38} rx={6} className="pivot-chart__tooltip-bg" />
                    <text x={8} y={15} className="pivot-chart__tooltip-label">
                      {p.label.length > 18 ? `${p.label.slice(0, 17)}…` : p.label}
                    </text>
                    <text x={8} y={31} className="pivot-chart__tooltip-value">
                      {p.value.toLocaleString()}
                    </text>
                  </g>
                );
              })()}
            </g>
          )}
        </svg>
      </div>
    </div>
  );
}
