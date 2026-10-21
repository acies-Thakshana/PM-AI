import ChatMessage from "../components/ChatMessage";
import { friendlyAiError } from "../utils/aiError";
import ThinkingLoader from "../components/ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Collapsible from "../components/Collapsible";
import { fetchSuggestions, saveDecisions } from "../api/planner";
import { uploadAnalysisDefinitions, uploadFeatureDefinitions } from "../api/audit";
import type { FilesState } from "../App";
import type { PlannerRecommendation, PlannerRecommendationType, PlannerSuggestResponse, PmDecisionValue } from "../api/planner";
import PlanText from "../components/PlanText";
import { useStoredRef } from "../state/sessionStore";
import "../components/ChatMessage.css";
import "./PlannerPage.css";

type PlannerTab = "features" | "analyses";

// What the PM asked for in the chat and what came back, shown under the suggestions.
interface ChatTurn {
  request: string;
  added: number | null;
  error?: string;
}

// New suggestions are only "analysis" | "feature" | "configuration". A legacy
// "feature_and_analysis" recommendation (old saved sessions) still produces an
// entry on BOTH the Features and Analysis pages when accepted, so it stays in
// both tabs.
// A feature is a calculation: it is only listed once it has a formula. (The backend already
// drops features without one and ranking / top-bottom ideas; this also covers older results.)
function hasFormula(rec: PlannerRecommendation): boolean {
  if (rec.type !== "feature") return true;
  return Boolean((rec.feature_formula_expression ?? rec.generated_feature_formula ?? "").trim());
}

function getTabs(type: PlannerRecommendationType): PlannerTab[] {
  if (type === "feature_and_analysis") return ["features", "analyses"];
  if (type === "analysis") return ["analyses"];
  return ["features"]; // "feature" and "configuration"
}

// Mirrors feature_repository.py's `_planner_entries` derivation
// (re.sub(r"\W+", "_", name.strip().lower()).strip("_")) -- the Planner
// never proposes an output-column name of its own for a feature, one is
// always derived from the recommendation's name, so this is the only way
// to tell whether a missing column IS one of the features being suggested
// alongside it, before either has actually been accepted/computed.
function deriveOutputColumn(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

// {derived output column -> recommendation name} for every feature-producing
// recommendation in this batch, so a sibling analysis's missing_fields can
// be resolved to "this needs feature X" instead of a bare column name.
function buildFeatureColumnMap(recs: PlannerRecommendation[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const r of recs) {
    if (r.type === "feature" || r.type === "feature_and_analysis") {
      map.set(deriveOutputColumn(r.name), r.name);
    }
  }
  return map;
}

type DecisionsMap = Record<number, PmDecisionValue>;

// The Planner's suggestions, the PM's accept/reject choices and the open tab, kept per session so
// going to another page and coming back shows the same thing instead of calling the AI again.
// A new upload creates a new session id, so it starts fresh; a full page reload clears this.
interface PlannerCacheEntry {
  result: PlannerSuggestResponse;
  decisions: DecisionsMap;
}

function friendlyError(err: unknown): string {
  const text = err instanceof Error ? err.message : "";
  const fallback = text.startsWith("Planner suggest failed") ? "The Planner could not draft suggestions this time. Try again in a moment." : text || "Planner failed.";
  return friendlyAiError(text, fallback);
}

/** The Planner's state for one session: its suggestions, the PM's decisions and the requests made in the chat. */
export function usePlannerChat(sessionId: string | null, files: FilesState) {
  const navigate = useNavigate();
  // Lives in the shared session store (like every other page's cross-navigation
  // state) instead of a module-level Map, so it also survives whatever Features/
  // Analysis/Report already rely on this store for -- same Map objects, same
  // get/set/has/delete semantics, just held here instead of at module scope.
  const plannerCache = useStoredRef<Map<string, PlannerCacheEntry>>("planner.cache", () => new Map());
  // A request still running when the PM leaves the page, so coming back joins it instead of starting another.
  const plannerInflight = useStoredRef<Map<string, Promise<PlannerSuggestResponse>>>("planner.inflight", () => new Map());
  const cached = sessionId ? plannerCache.get(sessionId) : undefined;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PlannerSuggestResponse | null>(cached?.result ?? null);
  const [decisions, setDecisions] = useState<DecisionsMap>(cached?.decisions ?? {});
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  // Goes up when the PM asks to try again after a failure, which runs the first request once more.
  const [attempt, setAttempt] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);
  const [moreLoading, setMoreLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const fetched = useRef(Boolean(cached));

  // Keep the cache in step with what is on screen.
  useEffect(() => {
    if (sessionId && result) plannerCache.set(sessionId, { result, decisions });
  }, [sessionId, result, decisions]);

  // A new chat turn scrolls into view; the first suggestions, and accepting or rejecting a card, do not.
  const messageCount = turns.length + (moreLoading ? 1 : 0);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messageCount]);

  useEffect(() => {
    if (!sessionId || fetched.current) return;
    fetched.current = true;
    setLoading(true);
    setError(null);
    let mounted = true;
    // The customer KPI profile and analysis profile are only held by the
    // backend once uploaded, and the Features/Analysis pages come AFTER this
    // one -- so send them now, or the Planner can't check them for reuse.
    // A failed upload just means the Planner runs without that profile.
    const profileUploads = [
      files.customerKpis ? uploadFeatureDefinitions(files.customerKpis) : null,
      files.analysisProfile ? uploadAnalysisDefinitions(files.analysisProfile) : null,
    ].filter((upload) => upload !== null);
    const request =
      plannerInflight.get(sessionId) ??
      Promise.allSettled(profileUploads)
        .then(() => fetchSuggestions(sessionId))
        .finally(() => plannerInflight.delete(sessionId));
    plannerInflight.set(sessionId, request);
    request
      .then((res) => {
        // Recommendations stored on the server come back with the PM's earlier accept/reject choices.
        const saved: DecisionsMap = {};
        res.recommendations.forEach((r, i) => {
          if (r.pm_decision && r.pm_decision !== "pending") saved[i] = r.pm_decision;
        });
        if (!plannerCache.has(sessionId)) plannerCache.set(sessionId, { result: res, decisions: saved });
        if (mounted) {
          setResult(res);
          setDecisions((prev) => (Object.keys(prev).length ? prev : saved));
        }
      })
      .catch((err) => {
        if (mounted) setError(friendlyError(err));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
      // Leaving mid-request: let the next visit run its own effect and join the same request.
      fetched.current = false;
    };
  }, [sessionId, attempt]);

  const retry = () => {
    fetched.current = false;
    setError(null);
    setAttempt((a) => a + 1);
  };

  const setDecision = (index: number, value: PmDecisionValue) => {
    setDecisions((prev) => ({
      ...prev,
      [index]: prev[index] === value ? "pending" : value,
    }));
  };

  const setAllInTab = (tab: PlannerTab, value: PmDecisionValue) => {
    if (!result) return;
    setDecisions((prev) => {
      const next = { ...prev };
      result.recommendations.forEach((r, i) => {
        if (getTabs(r.type).includes(tab) && hasFormula(r)) next[i] = value;
      });
      return next;
    });
  };

  // `request` is what the PM typed in the chat; without it the Planner adds 4 more of each kind.
  const handleRequestMore = async (request?: string) => {
    if (!sessionId || !result || moreLoading) return;
    setMoreLoading(true);
    setError(null);
    const existingNames = result.recommendations.map((r) => r.name).join(", ");
    const ask = request
      ? `The PM asks: ${request}. Generate suggestions that answer this.`
      : "Generate 4 additional feature suggestions and 4 additional analysis suggestions.";
    const context = `${ask} These must be DIFFERENT from the ones already shown: ${existingNames}. Do not repeat any of those.`;
    try {
      const res = await fetchSuggestions(sessionId, context);
      setTurns((prev) => [...prev, { request: request ?? "Suggest more features and analyses", added: res.recommendations.length }]);
      setResult((prev) => {
        if (!prev) return res;
        return {
          ...prev,
          recommendations: [...prev.recommendations, ...res.recommendations],
        };
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to get more suggestions.";
      setTurns((prev) => [...prev, { request: request ?? "Suggest more features and analyses", added: null, error: message }]);
    } finally {
      setMoreLoading(false);
    }
  };

  const handleProceed = async () => {
    if (!sessionId || !result) return;
    setSaving(true);
    try {
      const decisionList = result.recommendations.map((_, i) => ({
        recommendation_index: i,
        pm_decision: decisions[i] ?? "pending",
        pm_notes: "",
      }));
      await saveDecisions(sessionId, decisionList);
      navigate("/audit");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save decisions.");
    } finally {
      setSaving(false);
    }
  };

  return {
    sessionId,
    loading,
    error,
    result,
    decisions,
    turns,
    endRef,
    moreLoading,
    saving,
    setDecision,
    setAllInTab,
    handleRequestMore,
    handleProceed,
    retry,
  };
}

export type PlannerChat = ReturnType<typeof usePlannerChat>;

/** The Planner's messages: what it read, the suggested features and analyses to accept or reject, and what the PM
 * asked for afterwards. Shown inside the Configure conversation. */
export function PlannerThread({ planner }: { planner: PlannerChat }) {
  const { loading, error, result, decisions, turns, moreLoading } = planner;
  const recs = result?.recommendations ?? [];
  const featureColumnMap = buildFeatureColumnMap(recs);
  const shown = recs.map((rec, i) => ({ rec, i })).filter(({ rec }) => hasFormula(rec));
  const sections: { tab: PlannerTab; title: string; items: typeof shown }[] = [
    { tab: "features", title: "Features", items: shown.filter(({ rec }) => getTabs(rec.type).includes("features")) },
    { tab: "analyses", title: "Analyses", items: shown.filter(({ rec }) => getTabs(rec.type).includes("analyses")) },
  ];
  const reviewed = shown.filter(({ i }) => (decisions[i] ?? "pending") !== "pending").length;
  const acceptedCount = shown.filter(({ i }) => decisions[i] === "accepted").length;
  const featureCount = sections[0].items.length;
  const analysisCount = sections[1].items.length;

  return (
    <>
      <ChatMessage>
        <p>
          I read your client brief against your data&apos;s columns. I will suggest the features to build and the
          analyses to run. Accept or reject each one, and ask me here if you want something different.
        </p>
      </ChatMessage>

      {loading && (
        <ChatMessage>
          <ThinkingLoader
            messages={LOADING.planner}
            hint="The Planner reads your brief against your data's column details. This usually takes 20 to 40 seconds."
            intervalMs={4000}
            showElapsed
          />
        </ChatMessage>
      )}

      {error && (
        <ChatMessage>
          <div className="planner-page__error">{error}</div>
        </ChatMessage>
      )}

      {result && (
        <ChatMessage>
          <p>
            I have <b>{featureCount}</b> feature{featureCount === 1 ? "" : "s"} and <b>{analysisCount}</b>{" "}
            analys{analysisCount === 1 ? "is" : "es"} for you to review.
          </p>
          {sections.map(({ tab, title, items }) => (
            <section key={tab} className="planner-chat__section">
              <div className="planner-chat__section-head">
                <h2>
                  {title} <span className="count-pill">{items.length}</span>
                </h2>
                {items.length > 0 && (
                  <div className="planner-page__bulk-btns">
                    <button type="button" className="btn btn--sm btn--secondary" onClick={() => planner.setAllInTab(tab, "accepted")}>
                      Accept all
                    </button>
                    <button type="button" className="btn btn--sm btn--secondary" onClick={() => planner.setAllInTab(tab, "rejected")}>
                      Reject all
                    </button>
                  </div>
                )}
              </div>
              <div className="planner-page__list">
                {items.map(({ rec, i }) => (
                  <RecommendationCard
                    key={i}
                    rec={rec}
                    index={i}
                    decision={decisions[i] ?? "pending"}
                    onDecide={planner.setDecision}
                    featureColumnMap={featureColumnMap}
                    dependencyWarning={dependencyWarningFor(rec, decisions[i] ?? "pending", recs, decisions)}
                  />
                ))}
                {items.length === 0 && (
                  <div className="planner-page__empty-tab">
                    {tab === "features" && recs.some((r) => r.type === "analysis")
                      ? "No new features needed. The analyses reuse existing features or customer KPIs, or use the existing columns directly."
                      : `No ${tab === "features" ? "feature" : "analysis"} suggestions yet.`}
                  </div>
                )}
              </div>
            </section>
          ))}
          <div className="planner-chat__bar">
            <span className="planner-chat__progress">
              {reviewed} of {shown.length} reviewed · {acceptedCount} accepted
            </span>
          </div>
        </ChatMessage>
      )}

      {turns.map((turn, n) => (
        <div key={n} className="chat-page__turn">
          <ChatMessage from="user">{turn.request}</ChatMessage>
          <ChatMessage>
            {turn.error ? (
              <div className="planner-page__error">{turn.error}</div>
            ) : (
              <p>Done. I added {turn.added} suggestion{turn.added === 1 ? "" : "s"} to the lists above.</p>
            )}
          </ChatMessage>
        </div>
      ))}

      {moreLoading && (
        <ChatMessage>
          <ThinkingLoader messages={LOADING.planner} variant="inline" />
        </ChatMessage>
      )}
      <div ref={planner.endRef} />
    </>
  );
}

interface RecCardProps {
  rec: PlannerRecommendation;
  index: number;
  decision: PmDecisionValue;
  onDecide: (index: number, value: PmDecisionValue) => void;
  featureColumnMap: Map<string, string>;
  dependencyWarning?: string | null;
}

interface RequirementNote {
  text: string;
  kind: "ok" | "blocked" | "missing";
}

// Whether this recommendation needs any column it doesn't already have --
// missing_fields is required_fields minus whatever's already in the
// uploaded data (see planner.py's DATA AVAILABILITY guardrail). Resolving a
// missing field to a sibling feature recommendation (by its derived
// output_column) tells the PM WHY it's missing: not absent data, but a
// column that only exists once that feature is accepted and computed.
function requirementNote(rec: PlannerRecommendation, ownName: string, featureColumnMap: Map<string, string>): RequirementNote {
  const missing = rec.missing_fields ?? [];
  if (missing.length === 0) {
    return { text: "No required column", kind: "ok" };
  }
  const neededFeatures = new Set<string>();
  const unresolved: string[] = [];
  for (const field of missing) {
    const featureName = featureColumnMap.get(deriveOutputColumn(field));
    if (featureName && featureName !== ownName) {
      neededFeatures.add(featureName);
    } else {
      unresolved.push(field);
    }
  }
  if (neededFeatures.size > 0 && unresolved.length === 0) {
    return { text: `Can only be done once the feature "${[...neededFeatures].join('", "')}" is computed.`, kind: "blocked" };
  }
  if (neededFeatures.size > 0) {
    return {
      text: `Can only be done once the feature "${[...neededFeatures].join('", "')}" is computed. Still missing: ${unresolved.join(", ")}.`,
      kind: "blocked",
    };
  }
  return { text: `Missing required column${unresolved.length > 1 ? "s" : ""}: ${unresolved.join(", ")}`, kind: "missing" };
}

// A legacy "feature_and_analysis" is shown as an analysis (plus its required
// feature), the same as the current model -- never as a combined type.
function typeLabel(type: string): string {
  if (type === "analysis" || type === "feature_and_analysis") return "Analysis";
  if (type === "configuration") return "Configuration";
  return "Feature";
}

function typeSlug(type: string): string {
  return type === "feature_and_analysis" ? "analysis" : type.replace(/_/g, "-");
}

// A rejected feature that an accepted/pending analysis needs would leave that
// analysis blocked on the Analysis page. Warn only -- Proceed is not blocked.
function dependencyWarningFor(
  rec: PlannerRecommendation,
  decision: PmDecisionValue,
  recs: PlannerRecommendation[],
  decisions: DecisionsMap
): string | null {
  if (rec.type !== "feature" || decision !== "rejected") return null;
  const names = new Set(rec.required_for_analysis ?? []);
  if (names.size === 0) return null;
  const blocked = recs
    .map((r, i) => ({ r, d: decisions[i] ?? "pending" }))
    .filter(({ r, d }) => (r.type === "analysis" || r.type === "feature_and_analysis") && names.has(r.name) && d !== "rejected")
    .map(({ r }) => r.name);
  if (blocked.length === 0) return null;
  return `${blocked.join(", ")} depend${blocked.length === 1 ? "s" : ""} on this feature - it will be blocked until the feature is selected.`;
}

// Colour = meaning: grey = new, teal = reused, amber = needs attention.
function statusTagClass(status: string): string {
  if (status === "existing") return "existing";
  if (status === "needs_clarification") return "attention";
  return "new";
}

function statusLabel(status: string): string {
  if (status === "existing") return "Existing";
  if (status === "needs_clarification") return "Needs Clarification";
  return "New";
}

function RecommendationCard({ rec, index, decision, onDecide, featureColumnMap, dependencyWarning }: RecCardProps) {
  // Defensive fallbacks: an older cached suggestion, a dev-server hot-reload
  // that preserved stale state from before this schema changed, or an LLM
  // response that omitted an array field should never blank the whole page.
  const clarifications = rec.clarifications_required ?? [];
  const hasClarifications = clarifications.length > 0;
  const columns = rec.required_fields ?? [];
  const generatedFormula = rec.generated_feature_formula;
  const generatedAnalysisFormula = rec.generated_analysis_formula;
  const requirement = requirementNote(rec, rec.name, featureColumnMap);
  const isAnalysis = rec.type === "analysis" || rec.type === "feature_and_analysis";
  const requiredFor = rec.type === "feature" ? (rec.required_for_analysis ?? []) : [];
  const guardrails = rec.guardrail_warnings ?? [];
  const kpiDeps = rec.kpi_dependencies ?? [];
  const featureDeps = rec.feature_dependencies ?? [];

  return (
    <div
      className={`planner-page__card${decision === "accepted" ? " planner-page__card--accepted" : ""}${decision === "rejected" ? " planner-page__card--rejected" : ""}`}
    >
      <div className="planner-page__card-head">
        <div className="planner-page__card-meta">
          <div className="planner-page__card-badges">
            <span className={`tag tag--${typeSlug(rec.type)}`}>
              {typeLabel(rec.type)}
            </span>
            <span className={`tag tag--${statusTagClass(rec.status)}`}>
              {statusLabel(rec.status)}
            </span>
          </div>
          <h3 className="planner-page__card-name">{rec.name}</h3>
          <p className="planner-page__card-desc">{rec.reason || rec.description}</p>
          {requiredFor.length > 0 && (
            <div className="planner-page__needed-by">Needed by: {requiredFor.join(", ")}</div>
          )}
          {rec.feature_formula_expression && (
            <div className="planner-page__spec planner-page__spec--feature">
              <span className="planner-page__spec-label">Feature formula</span>
              <code className="planner-page__spec-code">{rec.feature_formula_expression}</code>
              {rec.feature_output_dtype && (
                <span className="planner-page__spec-meta">Output type: {rec.feature_output_dtype}</span>
              )}
            </div>
          )}
          {generatedFormula && (
            <Collapsible label="feature plan">
              <PlanText plan={generatedFormula} label="Feature computation plan" hideLabel className="planner-page__formula" />
            </Collapsible>
          )}
          {(rec.analysis_logic || (rec.analysis_group_by?.length ?? 0) > 0 || (rec.analysis_metrics?.length ?? 0) > 0) && (
            <div className="planner-page__spec planner-page__spec--analysis">
              <span className="planner-page__spec-label">Analysis spec / logic</span>
              {rec.analysis_logic && <code className="planner-page__spec-code">{rec.analysis_logic}</code>}
              <span className="planner-page__spec-meta">
                Group by: {(rec.analysis_group_by?.length ?? 0) > 0 ? rec.analysis_group_by!.join(", ") : "none (overall)"}
              </span>
              {(rec.analysis_metrics?.length ?? 0) > 0 && (
                <span className="planner-page__spec-meta">Metrics: {rec.analysis_metrics!.join("; ")}</span>
              )}
            </div>
          )}
          {generatedAnalysisFormula && (
            <Collapsible label="analysis plan">
              <PlanText plan={generatedAnalysisFormula} label="Analysis plan" hideLabel className="planner-page__formula" />
            </Collapsible>
          )}
          {columns.length > 0 && (
            <div className="planner-page__columns">
              <span className="planner-page__columns-label">Columns used:</span>
              {columns.map((col) => (
                <span key={col} className="planner-page__col-tag">{col}</span>
              ))}
            </div>
          )}
          {isAnalysis && (
            <div className="planner-page__deps">
              {kpiDeps.map((k) => (
                <div key={`kpi-${k.name}`} className="planner-page__dep planner-page__dep--reuse">
                  Uses customer KPI: {k.name} ({k.source})
                </div>
              ))}
              {featureDeps.map((d) => (
                <div
                  key={`feat-${d.feature_name}`}
                  className={`planner-page__dep planner-page__dep--${d.action === "create_new" ? "new" : "reuse"}`}
                >
                  {d.action === "create_new" ? "New feature required" : "Reuse existing feature"}: {d.feature_name}
                  {d.reason ? ` - ${d.reason}` : ""}
                </div>
              ))}
              {rec.analysis_source === "analysis_profile" && (
                <div className="planner-page__dep planner-page__dep--reuse">
                  Reuses analysis profile entry: {rec.existing_analysis_name ?? rec.name}
                </div>
              )}
              {rec.feature_required === false && (
                <div className="planner-page__dep planner-page__dep--none">
                  No feature needed - computed directly from existing columns
                </div>
              )}
            </div>
          )}
          {requirement.kind !== "ok" && (
            <div className={`planner-page__requirement planner-page__requirement--${requirement.kind}`}>
              {requirement.text}
            </div>
          )}
          {guardrails.length > 0 && (
            <div className="planner-page__guardrail" role="alert">
              {guardrails.map((w, i) => (
                <div key={i}>&#9888; {w}</div>
              ))}
            </div>
          )}
          {dependencyWarning && (
            <div className="planner-page__guardrail" role="alert">
              &#9888; {dependencyWarning}
            </div>
          )}
        </div>
      </div>

      {hasClarifications && (
        <div className="planner-page__clarifications">
          <p>Needs clarification:</p>
          <ul>
            {clarifications.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="planner-page__card-foot">
        <div className="planner-page__actions">
          <button
            type="button"
            className="btn btn--sm btn--primary"
            aria-pressed={decision === "accepted"}
            onClick={() => onDecide(index, "accepted")}
          >
            {decision === "accepted" ? "Accepted" : "Accept"}
          </button>
          <button
            type="button"
            className={`btn btn--sm btn--secondary${decision === "rejected" ? " btn--selected" : ""}`}
            aria-pressed={decision === "rejected"}
            onClick={() => onDecide(index, "rejected")}
          >
            {decision === "rejected" ? "Rejected" : "Reject"}
          </button>
        </div>
      </div>
    </div>
  );
}
