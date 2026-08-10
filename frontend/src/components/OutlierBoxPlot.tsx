import { useState } from "react";
import type { OutlierChart } from "../api/audit";
import "./OutlierBoxPlot.css";

interface OutlierBoxPlotProps {
  chart: OutlierChart;
}

const WIDTH = 560;
const HEIGHT = 108;
const CENTER_Y = 44;
const BOX_HALF_HEIGHT = 13;
const CAP_HALF_HEIGHT = 7;
const AXIS_Y = 88;
const DOT_RADIUS = 3;
const DOT_HIT_RADIUS = 8;

function formatValue(v: number): string {
  return Number.isInteger(v) ? v.toString() : v.toFixed(1);
}

interface TooltipState {
  leftPct: number;
  topPct: number;
  text: string;
}

export default function OutlierBoxPlot({ chart }: OutlierBoxPlotProps) {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const span = chart.max - chart.min || 1;
  const xForValue = (v: number) => ((v - chart.min) / span) * WIDTH;

  const showTip = (e: React.MouseEvent<SVGElement>, text: string) => {
    const svg = e.currentTarget.ownerSVGElement;
    const rect = svg?.getBoundingClientRect();
    if (!rect) return;
    setTooltip({
      leftPct: ((e.clientX - rect.left) / rect.width) * 100,
      topPct: ((e.clientY - rect.top) / rect.height) * 100,
      text,
    });
  };
  const hideTip = () => setTooltip(null);

  const q1X = xForValue(chart.q1);
  const q3X = xForValue(chart.q3);
  const medianX = xForValue(chart.median);
  const lowerX = xForValue(chart.lower_bound);
  const upperX = xForValue(chart.upper_bound);

  return (
    <div className="outlier-box">
      <div className="outlier-box__chart-wrap">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="outlier-box__svg"
          role="img"
          aria-label={`Box plot of ${chart.column}. Median ${formatValue(chart.median)}, middle 50% of values between ${formatValue(
            chart.q1
          )} and ${formatValue(chart.q3)}. ${chart.outlier_values.length} value(s) fall beyond the ${formatValue(
            chart.lower_bound
          )} to ${formatValue(chart.upper_bound)} range flagged as outliers.`}
          preserveAspectRatio="none"
        >
          <line
            x1={lowerX}
            x2={q1X}
            y1={CENTER_Y}
            y2={CENTER_Y}
            className="outlier-box__whisker"
            onMouseMove={(e) => showTip(e, `Lower fence: ${formatValue(chart.lower_bound)}`)}
            onMouseLeave={hideTip}
          />
          <line
            x1={q3X}
            x2={upperX}
            y1={CENTER_Y}
            y2={CENTER_Y}
            className="outlier-box__whisker"
            onMouseMove={(e) => showTip(e, `Upper fence: ${formatValue(chart.upper_bound)}`)}
            onMouseLeave={hideTip}
          />
          <line x1={lowerX} x2={lowerX} y1={CENTER_Y - CAP_HALF_HEIGHT} y2={CENTER_Y + CAP_HALF_HEIGHT} className="outlier-box__cap" />
          <line x1={upperX} x2={upperX} y1={CENTER_Y - CAP_HALF_HEIGHT} y2={CENTER_Y + CAP_HALF_HEIGHT} className="outlier-box__cap" />

          <rect
            x={q1X}
            y={CENTER_Y - BOX_HALF_HEIGHT}
            width={Math.max(q3X - q1X, 1)}
            height={BOX_HALF_HEIGHT * 2}
            className="outlier-box__box"
            onMouseMove={(e) => showTip(e, `Q1 ${formatValue(chart.q1)} – Q3 ${formatValue(chart.q3)} (middle 50% of values)`)}
            onMouseLeave={hideTip}
          />
          <line
            x1={medianX}
            x2={medianX}
            y1={CENTER_Y - BOX_HALF_HEIGHT}
            y2={CENTER_Y + BOX_HALF_HEIGHT}
            className="outlier-box__median"
            onMouseMove={(e) => showTip(e, `Median: ${formatValue(chart.median)}`)}
            onMouseLeave={hideTip}
          />

          {chart.outlier_values.map((v, i) => {
            const jitter = ((i * 37) % 29) - 14;
            const x = xForValue(v);
            const y = CENTER_Y + jitter;
            return (
              <g
                key={i}
                onMouseMove={(e) => showTip(e, `${chart.column}: ${formatValue(v)}`)}
                onMouseLeave={hideTip}
              >
                <circle cx={x} cy={y} r={DOT_HIT_RADIUS} className="outlier-box__dot-hit" />
                <circle cx={x} cy={y} r={DOT_RADIUS} className="outlier-box__dot" />
              </g>
            );
          })}

          <line x1={0} x2={WIDTH} y1={AXIS_Y} y2={AXIS_Y} className="outlier-box__axis" />
        </svg>

        {tooltip && (
          <div className="outlier-box__tooltip" style={{ left: `${tooltip.leftPct}%`, top: `${tooltip.topPct}%` }}>
            {tooltip.text}
          </div>
        )}
      </div>

      <div className="outlier-box__labels">
        <span>{formatValue(chart.min)}</span>
        <span className="outlier-box__legend">
          <span className="outlier-box__legend-dot" />
          {chart.outlier_values.length} outlier value(s)
        </span>
        <span>{formatValue(chart.max)}</span>
      </div>
    </div>
  );
}
