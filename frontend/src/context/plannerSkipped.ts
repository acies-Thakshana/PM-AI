import { createContext } from "react";
import type { BriefState } from "../components/ClientBriefInput";

/** True when the PM gave no client brief, so the Planner has nothing to plan and
 * the flow goes straight from Upload to the data Audit. */
export const PlannerSkippedContext = createContext(false);

/** Where the trip data comes from: the SWP API (Configure -> Trips -> ...) or uploaded files (no Trips step). */
export type DataSource = "api" | "upload";
export const DataSourceContext = createContext<DataSource>("api");

/** Whether the client brief has any text (translated or as typed). */
export function hasBrief(brief: BriefState): boolean {
  return (brief.finalText || brief.rawText || "").trim().length > 0;
}
