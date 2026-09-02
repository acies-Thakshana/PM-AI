// Pure helpers for shaping ReportPage's shared/per-pivot filter state.
// Kept free of React state so they're independently testable.
import type { PivotFilter, PivotResult } from "../api/types";

// The raw column the data uses for a shipment's departure -- not one of the
// categorical filterable_columns slicers, so it gets its own date-range
// control alongside them.
export const DEPARTURE_COLUMN = "Actual Departure Time CET";
// Mirrors the backend's report_generator.MAX_COMBOS_PER_PIVOT.
export const MAX_COMBOS = 12;

export function selectionsFromFilters(filters: PivotFilter[], filterableColumns: string[]): Record<string, string[] | undefined> {
  const selections: Record<string, string[] | undefined> = {};
  for (const f of filters) {
    if (f.op === "in" && filterableColumns.includes(f.column)) {
      selections[f.column] = (Array.isArray(f.value) ? f.value : [f.value]).map(String);
    }
  }
  return selections;
}

export function globalColumnsFor(pivots: PivotResult[]): string[] {
  const columns = new Set<string>();
  for (const p of pivots) for (const c of p.filterable_columns) columns.add(c);
  return [...columns];
}

export function globalOptionsFor(pivots: PivotResult[], columns: string[]): Record<string, string[]> {
  const options: Record<string, string[]> = {};
  for (const column of columns) {
    const values = new Set<string>();
    for (const p of pivots) for (const v of p.filter_options[column] ?? []) values.add(v);
    options[column] = [...values].sort();
  }
  return options;
}

export function globalCombinationsFor(pivots: PivotResult[]): Record<string, string>[] {
  return pivots.flatMap((p) => p.filter_combinations);
}

export function rangeFromFilters(filters: PivotFilter[]): { start: string; end: string } {
  const gte = filters.find((f) => f.column === DEPARTURE_COLUMN && f.op === "gte");
  const lte = filters.find((f) => f.column === DEPARTURE_COLUMN && f.op === "lte");
  return {
    start: typeof gte?.value === "string" ? gte.value.slice(0, 10) : "",
    end: typeof lte?.value === "string" ? lte.value.slice(0, 10) : "",
  };
}

// Which columns the shared filter is actually constraining right now --
// only these are worth a per-pivot "apply this to me?" toggle.
export function activeColumns(filters: PivotFilter[]): string[] {
  return [...new Set(filters.map((f) => f.column))];
}

export function columnLabel(column: string): string {
  return column === DEPARTURE_COLUMN ? "Departure time" : column;
}

// Mirrors the backend's report_generator._report_filter_combos + _combo_label
// exactly, so the UI shows one row per ACTUAL output slide instead of
// collapsing them into a single "N slides" summary -- e.g. 2 selected
// Origins -> 2 rows, each labeled with the specific Origin it resolves to.
export function pivotSlidePreviews(filters: PivotFilter[], allowed: string[] | undefined): string[] {
  const scoped = allowed === undefined ? filters : filters.filter((f) => allowed.includes(f.column));
  const multipliers = scoped.filter((f) => f.op === "in" && Array.isArray(f.value) && f.value.length > 1);
  if (multipliers.length === 0) return [""];
  let combos: string[][] = [[]];
  for (const f of multipliers) {
    const values = (f.value as unknown[]).map(String);
    combos = combos.flatMap((c) => values.map((v) => [...c, v]));
  }
  return combos.slice(0, MAX_COMBOS).map((c) => c.join(" / "));
}
