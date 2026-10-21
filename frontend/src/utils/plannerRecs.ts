import type { PlannerRecommendation, PlannerRecommendationType } from "../api/planner";

// Shared by the Planner page (read-only details) and the assistant (where the PM accepts or rejects).

export type PlannerTab = "features" | "analyses";

// New suggestions are only "analysis" | "feature" | "configuration". A legacy
// "feature_and_analysis" recommendation (old saved sessions) still produces an
// entry on BOTH the Features and Analysis pages when accepted, so it stays in
// both tabs.
export function getTabs(type: PlannerRecommendationType): PlannerTab[] {
  if (type === "feature_and_analysis") return ["features", "analyses"];
  if (type === "analysis") return ["analyses"];
  return ["features"]; // "feature" and "configuration"
}

// A feature is a calculation: it is only listed once it has a formula. (The backend already
// drops features without one and ranking / top-bottom ideas; this also covers older results.)
export function hasFormula(rec: PlannerRecommendation): boolean {
  if (rec.type !== "feature") return true;
  return Boolean((rec.feature_formula_expression ?? rec.generated_feature_formula ?? "").trim());
}

/** The keys under which the Planner's result and the PM's decisions live in the shared session store. */
export const plannerResultKey = (sessionId: string | null) => `planner.result:${sessionId ?? "none"}`;
export const plannerDecisionsKey = (sessionId: string | null) => `planner.decisions:${sessionId ?? "none"}`;
