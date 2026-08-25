import type { PivotResult } from "../api/audit";
import { IconChevronRight, IconBarChart, IconCalendar, IconPercent, IconLayers } from "./icons";
import "./PivotCard.css";

interface PivotCardProps {
  pivot: PivotResult;
  onOpen: () => void;
  colorIndex?: number;
}

const ICON_COLORS = ["blue", "teal", "purple", "amber"] as const;

// Pick an icon from the pivot's actual shape (what it groups by, what it
// measures) instead of just cycling color on the same glyph -- a monthly
// trend, a compliance %, and a cross-tab all look/behave differently.
function iconForPivot(pivot: PivotResult) {
  const groupByLabel = pivot.group_by.join(" ");
  const metricLabel = pivot.metric_labels.join(" ");
  if (/month|date|year/i.test(groupByLabel)) return IconCalendar;
  if (/%|percent|share|spec/i.test(metricLabel)) return IconPercent;
  if (pivot.group_by.length > 1) return IconLayers;
  return IconBarChart;
}

export default function PivotCard({ pivot, onOpen, colorIndex = 0 }: PivotCardProps) {
  const color = ICON_COLORS[colorIndex % ICON_COLORS.length];
  const PivotIcon = iconForPivot(pivot);
  return (
    <button type="button" className="pivot-card" onClick={onOpen}>
      <span className={`pivot-card__icon pivot-card__icon--${color}`}>
        <PivotIcon />
      </span>
      <span className="pivot-card__body">
        <span className="pivot-card__top">
          <span className="pivot-card__name">{pivot.name}</span>
          {pivot.id.startsWith("custom_pivot_") && <span className="pivot-card__custom-badge">Custom</span>}
        </span>
        <span className="pivot-card__description">{pivot.description}</span>
        <span className="pivot-card__meta">
          {pivot.group_by.join(" × ")} · {pivot.metric_labels.join(", ")} · {pivot.row_count.toLocaleString()} row(s)
        </span>
      </span>
      <IconChevronRight />
    </button>
  );
}
