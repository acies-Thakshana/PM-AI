"""In-memory audit session store. Single-process demo scope -- same pattern
as the prior IngestionStore: no persistence, no multi-user isolation, just a
thread-safe dict keyed by session id."""
import threading
import uuid
from dataclasses import dataclass, field

import pandas as pd

from app.schemas import AuditIssue, FeatureResult, OverallAnalysisReport, PivotResult, ReportSlide


@dataclass
class AuditSession:
    session_id: str
    source: str
    filename: str
    df: pd.DataFrame
    issues: list[AuditIssue] = field(default_factory=list)
    summary: str = ""
    features: list[FeatureResult] = field(default_factory=list)
    feature_skipped_notes: list[str] = field(default_factory=list)
    # Undo support for resolved issues that actually mutated `df` (dropped
    # columns / removed rows). `mutation_stack` is a LIFO of issue ids -- only
    # the most recent one is safe to revert without re-deriving every
    # decision after it, since row/column removal isn't commutative once a
    # later decision's mask was computed against the mutated frame.
    # "Keep as-is" resolutions never touch `df` so they're excluded and can
    # be reverted in any order.
    mutation_stack: list[str] = field(default_factory=list)
    pre_mutation_snapshots: dict[str, pd.DataFrame] = field(default_factory=dict)
    # Snapshot of `df` taken the first time features are computed, i.e. the
    # fully-audited data before any feature columns were appended. Every
    # subsequent feature computation (e.g. accepting another AI suggestion)
    # re-runs from this snapshot rather than layering on top of `df`, so
    # re-applying the same definitions twice can't double up or drift.
    pre_feature_df: pd.DataFrame | None = None
    # Last-computed pivot tables for the Analysis step (see routers/analysis.py).
    # Pivots only ever READ `df` (post-feature-engineering) -- they never
    # mutate it, so there's no snapshot/undo bookkeeping needed here.
    pivots: list[PivotResult] = field(default_factory=list)
    pivot_skipped_notes: list[str] = field(default_factory=list)
    # The AI-suggested/custom pivot definitions last applied on top of the
    # uploaded Analysis Profile -- remembered so a caller that only wants to
    # change slicer filters (e.g. the Report page) can recompute without
    # having to resend every AI/custom pivot the Analysis page already added.
    extra_pivot_defs: list[dict] = field(default_factory=list)
    # Currently-active runtime slicer filters per pivot id (see
    # ApplyPivotsRequest.pivot_filters) -- merged (not replaced) on each
    # apply_pivots call so a caller touching one pivot's filters, or adding
    # a filter shared across several, can't silently wipe filters saved for
    # pivots it didn't mention.
    pivot_filter_state: dict[str, list[dict]] = field(default_factory=dict)
    # The explicit, user-editable report slide list (see report_slides.py's
    # sync_slides) -- report-time only, never affects a pivot's own computed
    # rows/table. Empty until the Report page is first visited for this
    # session, at which point it's seeded with one slide per pivot.
    report_slides: list[ReportSlide] = field(default_factory=list)
    # Last-computed overall analysis (see routers/analysis.py's /overall
    # endpoint) -- kept here so the report generator can reuse the exact
    # highlights/narrative the user already saw on screen instead of
    # triggering another Groq call at export time.
    overall_analysis: OverallAnalysisReport | None = None


class AuditStore:
    def __init__(self):
        self._sessions: dict[str, AuditSession] = {}
        self._lock = threading.Lock()

    def create(self, source: str, filename: str, df: pd.DataFrame, issues: list[AuditIssue], summary: str) -> AuditSession:
        session = AuditSession(
            session_id=uuid.uuid4().hex, source=source, filename=filename, df=df, issues=issues, summary=summary
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> AuditSession | None:
        with self._lock:
            return self._sessions.get(session_id)


store = AuditStore()
