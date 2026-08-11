import { useEffect, useState } from "react";
import type { PivotFilter, PivotResult, ReportSlide } from "../api/audit";
import PivotFilterBar from "./PivotFilterBar";
import { IconGrid } from "./icons";
import "./ReportSlideCard.css";

const DEPARTURE_COLUMN = "Actual Departure Time CET";

function selectionsFromFilters(filters: PivotFilter[], filterableColumns: string[]): Record<string, string[] | undefined> {
  const selections: Record<string, string[] | undefined> = {};
  for (const f of filters) {
    if (f.op === "in" && filterableColumns.includes(f.column)) {
      selections[f.column] = (Array.isArray(f.value) ? f.value : [f.value]).map(String);
    }
  }
  return selections;
}

function rangeFromFilters(filters: PivotFilter[]): { start: string; end: string } {
  const gte = filters.find((f) => f.column === DEPARTURE_COLUMN && f.op === "gte");
  const lte = filters.find((f) => f.column === DEPARTURE_COLUMN && f.op === "lte");
  return {
    start: typeof gte?.value === "string" ? gte.value.slice(0, 10) : "",
    end: typeof lte?.value === "string" ? lte.value.slice(0, 10) : "",
  };
}

interface ReportSlideCardProps {
  slide: ReportSlide;
  pivot: PivotResult | undefined;
  label: string;
  onSaveTitle: (title: string) => void;
  onSaveFilters: (filters: PivotFilter[]) => void;
  onDuplicate: () => void;
  onDelete?: () => void;
  saving?: boolean;
}

export default function ReportSlideCard({
  slide,
  pivot,
  label,
  onSaveTitle,
  onSaveFilters,
  onDuplicate,
  onDelete,
  saving,
}: ReportSlideCardProps) {
  const [titleDraft, setTitleDraft] = useState(slide.title);
  const [rangeDraft, setRangeDraft] = useState(rangeFromFilters(slide.filters));

  // Re-sync from the slide's saved state -- title only ever saves on blur
  // and range only on an explicit click, so this never fights active typing.
  useEffect(() => setTitleDraft(slide.title), [slide.title]);
  useEffect(() => setRangeDraft(rangeFromFilters(slide.filters)), [JSON.stringify(slide.filters)]);

  const handleFilterSave = (nextSelections: Record<string, string[] | undefined>) => {
    const inFilters: PivotFilter[] = [];
    for (const [column, values] of Object.entries(nextSelections)) {
      if (values !== undefined) inFilters.push({ column, op: "in", value: values });
    }
    const preservedRange = slide.filters.filter((f) => f.column === DEPARTURE_COLUMN);
    onSaveFilters([...inFilters, ...preservedRange]);
  };

  const handleApplyRange = () => {
    const { start, end } = rangeDraft;
    const rangeFilters: PivotFilter[] =
      start && end
        ? [
            { column: DEPARTURE_COLUMN, op: "gte", value: `${start} 00:00:00` },
            { column: DEPARTURE_COLUMN, op: "lte", value: `${end} 23:59:59` },
          ]
        : [];
    const preservedIn = slide.filters.filter((f) => f.column !== DEPARTURE_COLUMN);
    onSaveFilters([...preservedIn, ...rangeFilters]);
  };

  const handleClearRange = () => {
    setRangeDraft({ start: "", end: "" });
    onSaveFilters(slide.filters.filter((f) => f.column !== DEPARTURE_COLUMN));
  };

  return (
    <div className="report-slide-card">
      <div className="report-slide-card__head">
        <span className="report-slide-card__label">{label}</span>
        <input
          className="report-slide-card__title"
          value={titleDraft}
          disabled={saving}
          onChange={(e) => setTitleDraft(e.target.value)}
          onBlur={() => {
            if (titleDraft.trim() && titleDraft !== slide.title) onSaveTitle(titleDraft.trim());
          }}
        />
        <div className="report-slide-card__head-actions">
          <button type="button" className="report-slide-card__dup-btn" onClick={onDuplicate} title="Analyze this same table again with a different filter, as a new slide">
            + Add slide
          </button>
          {onDelete && (
            <button type="button" className="report-slide-card__delete-btn" onClick={onDelete} aria-label="Remove this slide">
              ×
            </button>
          )}
        </div>
      </div>

      {pivot ? (
        <>
          <span className="report-slide-card__metrics">
            <IconGrid /> {pivot.metric_labels.join(", ")}
          </span>
          <PivotFilterBar
            filterableColumns={pivot.filterable_columns}
            filterOptions={pivot.filter_options}
            combinations={pivot.filter_combinations}
            selected={selectionsFromFilters(slide.filters, pivot.filterable_columns)}
            onSave={handleFilterSave}
            saving={saving}
          />
          <div className="report-slide-card__range">
            <span className="report-slide-card__range-label">Departure time</span>
            <input
              type="date"
              value={rangeDraft.start}
              disabled={saving}
              onChange={(e) => setRangeDraft((prev) => ({ ...prev, start: e.target.value }))}
              aria-label="Departure start date"
            />
            <span className="report-slide-card__range-sep">to</span>
            <input
              type="date"
              value={rangeDraft.end}
              disabled={saving}
              onChange={(e) => setRangeDraft((prev) => ({ ...prev, end: e.target.value }))}
              aria-label="Departure end date"
            />
            <button
              type="button"
              className="report-slide-card__range-btn"
              disabled={saving || !rangeDraft.start || !rangeDraft.end}
              onClick={handleApplyRange}
            >
              Apply
            </button>
            {(rangeDraft.start || rangeDraft.end) && (
              <button type="button" className="report-slide-card__range-btn" disabled={saving} onClick={handleClearRange}>
                Clear
              </button>
            )}
          </div>
        </>
      ) : (
        <p className="report-slide-card__missing">This table is no longer part of the analysis.</p>
      )}
    </div>
  );
}
