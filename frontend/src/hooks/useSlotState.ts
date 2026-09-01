import { useCallback, useState } from "react";
import type { UploadSlotId } from "../types/upload";

export type SlotState<T> = Partial<Record<UploadSlotId, T>>;

/** Wraps one `Partial<Record<UploadSlotId, T>>` state slice with per-slot
 * get/set/update helpers -- replaces the repeated
 * `setXxx((prev) => ({ ...prev, [id]: value }))` boilerplate that
 * AnalysisPage/FeaturesPage/ReportPage each redeclared independently for
 * their per-upload-slot state (loading flags, errors, fetched reports, etc). */
export function useSlotState<T>(initial: SlotState<T> = {}) {
  const [state, setState] = useState<SlotState<T>>(initial);

  const set = useCallback((id: UploadSlotId, value: T | undefined) => {
    setState((prev) => ({ ...prev, [id]: value }));
  }, []);

  const update = useCallback((id: UploadSlotId, updater: (prev: T | undefined) => T) => {
    setState((prev) => ({ ...prev, [id]: updater(prev[id]) }));
  }, []);

  return [state, { set, update, setState }] as const;
}
