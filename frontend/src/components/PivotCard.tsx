import type { PivotResult } from "../api/audit";
import { IconChevronRight, IconGrid } from "./icons";
import "./PivotCard.css";

interface PivotCardProps {
  pivot: PivotResult;
  onOpen: () => void;
  colorIndex?: number;
}

const ICON_COLORS = ["blue", "teal", "purple", "amber"] as const;

export default function PivotCard({ pivot, onOpen, colorIndex = 0 }: PivotCardProps) {
  const color = ICON_COLORS[colorIndex % ICON_COLORS.length];
  return (
    <button type="button" className="pivot-card" onClick={onOpen}>
      <span className={`pivot-card__icon pivot-card__icon--${color}`}>
        <IconGrid />
      </span>
      <span className="pivot-card__body">
        <span className="pivot-card__top">
          <span className="pivot-card__name">{pivot.name}</span>
          {pivot.id.startsWith("ai_pivot_") && <span className="pivot-card__ai-badge">AI</span>}
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
