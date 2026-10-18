"""The single question pipeline used by every entry point.

guardrails -> domain view (data + semantics) -> catalog -> knowledge graph slice
-> plan + SQL -> validation -> execution (one repair) -> answer -> chart
-> follow-ups -> graph episode + history

Configuration problems raise (the API maps them to HTTP errors); problems with the question
itself come back as a response with a ``status`` such as ``validation_failed``.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.config import Settings
from app.errors import AI4BIError, ConfigError, DataNotFoundError, DomainNotFoundError
from app.services.ask.domain_view import DomainView, resolve_domain
from app.services.common import audit_log, request_context
from app.services.common.frames import preview as frame_preview
from app.services.common.llm import LOCAL_PROVIDER
from app.services.common.text import stable_id
from app.services.context import AppContext
from app.services.data.preprocessing import build_catalog
from app.services.guardrails.input_validation import GuardrailResult, check_restricted_request, validate_question
from app.services.knowledge.documents import ingest_documents
from app.services.knowledge.graph import KnowledgeGraph
from app.services.knowledge.retrieval import prior_sql_patterns, subgraph_for_question
from app.services.knowledge.seed import seed_from_package
from app.services.semantic.models import DomainPackage
from app.services.semantic.schema import schema_for_llm
from app.services.sql.executor import QueryResult, SqlExecutor
from app.services.sql.repair import ground_sql, problem_with, repair_sql

LOGGER = logging.getLogger(__name__)

CONFIG_ERRORS = (ConfigError, DomainNotFoundError, DataNotFoundError)
ANSWER_PATH_LLM = "llm"
ANSWER_PATH_DETERMINISTIC = "deterministic"


def _base(request_id: str, domain: str, question: str, status: str) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "domain": domain,
        "question": question,
        "status": status,
        "answer_path": ANSWER_PATH_DETERMINISTIC,
        "answer": "",
        "key_findings": [],
        "intent": None,
        "confidence": None,
        "interpreted_question": question,
        "metrics": [],
        "calculations": [],
        "sql_query": "",
        "sql_rationale": "",
        "datasets_used": [],
        "joins_used": [],
        "table": {"columns": [], "rows": [], "n": 0},
        "truncated": False,
        "chart": {},
        "follow_up_questions": [],
        "warnings": [],
        "explainability": {},
        "llm": {},
        "repairs": 0,
        "latency_seconds": 0.0,
    }


def _guardrail_response(
    ctx: AppContext, request_id: str, domain: str, question: str, guard: GuardrailResult, pkg: DomainPackage | None
) -> dict[str, Any]:
    response = _base(request_id, domain, question, guard.status)
    response["answer"] = guard.reason
    response["intent"] = guard.status
    if pkg is not None:
        response["follow_up_questions"] = ctx.followups.starter_questions(pkg)
    LOGGER.info("Guardrail %s: %s", guard.status, guard.reason)
    return response


def _seed_graph(ctx: AppContext, graph: KnowledgeGraph, pkg: DomainPackage) -> None:
    if graph.nodes:
        return
    seed_from_package(graph, pkg)
    if ctx.semantic.exists(pkg.domain):
        ingest_documents(graph, ctx.semantic.domain_dir(pkg.domain) / "documents")


@dataclass
class Attempt:
    sql: str
    errors: list[str] = field(default_factory=list)
    result: QueryResult | None = None
    joins_used: list[str] = field(default_factory=list)
    problem: str = ""

    @property
    def rank(self) -> int:
        """0 rejected, 1 failed to run, 2 ran but unusable, 3 usable."""
        if self.errors or self.result is None:
            return 0
        if not self.result.ok:
            return 1
        return 2 if self.problem else 3


def _attempt(
    ctx: AppContext,
    executor: SqlExecutor,
    sql: str,
    pkg: DomainPackage,
    frames: dict[str, pd.DataFrame],
    profiles: list,
) -> Attempt:
    validation = ctx.validator.validate(sql, pkg, list(frames))
    if not validation.ok:
        return Attempt(sql=sql, errors=validation.errors, problem=" ".join(validation.errors))
    result = executor.execute(validation.sql, frames)
    return Attempt(
        sql=validation.sql,
        result=result,
        joins_used=validation.joins_used,
        problem=problem_with(validation.sql, profiles, result.frame, result.error),
    )


def ask(
    question: str,
    *,
    context: AppContext,
    domain: str,
    view: DomainView | None = None,
    graph: KnowledgeGraph | None = None,
    session_id: str | None = None,
    conversation: list[dict[str, Any]] | None = None,
    persist: bool | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Answer one question.

    ``view`` and ``graph`` let a batch run share one resolved domain and one accumulating graph.
    ``persist`` defaults to ``Settings.persist_episodes``.
    """
    question = (question or "").strip()
    request_id = request_id or request_context.current_request_id.get() or str(uuid.uuid4())
    persist = context.settings.persist_episodes if persist is None else persist
    started = time.perf_counter()
    with request_context.request_scope(request_id):
        try:
            response = _ask(context, request_id, domain, question, view, graph, session_id, conversation, persist)
        except CONFIG_ERRORS:
            raise
        except AI4BIError as exc:
            LOGGER.warning("Question failed: %s", exc)
            response = _base(request_id, domain, question, "error")
            response["answer"] = str(exc)
            response["warnings"] = [exc.code]
        except Exception:  # noqa: BLE001 - never leak internals to the caller; the log has the traceback
            LOGGER.exception("Unexpected failure while answering")
            response = _base(request_id, domain, question, "error")
            response["answer"] = "The question could not be answered because of an internal error."
            response["warnings"] = ["internal_error"]
        response["latency_seconds"] = round(time.perf_counter() - started, 3)
        LOGGER.info("status=%s latency=%.3fs", response["status"], response["latency_seconds"])
        audit_log.record(
            "ask",
            question=question,
            status=response["status"],
            answer_path=response["answer_path"],
            latency_seconds=response["latency_seconds"],
        )
        return response


def _ask(
    ctx: AppContext,
    request_id: str,
    domain: str,
    question: str,
    view: DomainView | None,
    graph: KnowledgeGraph | None,
    session_id: str | None,
    conversation: list[dict[str, Any]] | None,
    persist: bool,
) -> dict[str, Any]:
    settings = ctx.settings
    store = ctx.semantic

    guard = validate_question(question, settings)
    if not guard.ok:
        pkg = store.load(domain) if store.exists(domain) else None
        return _guardrail_response(ctx, request_id, domain, question, guard, pkg)

    view = view or resolve_domain(ctx, domain)
    pkg, tables = view.pkg, view.tables

    guard = check_restricted_request(question, pkg)
    if not guard.ok:
        return _guardrail_response(ctx, request_id, domain, question, guard, pkg)

    graph = graph if graph is not None else ctx.graphs.load(domain)
    _seed_graph(ctx, graph, pkg)

    aliases = store.filter_aliases(pkg)
    catalog = build_catalog(view.prepared.profiles, question, notes=store.column_notes(pkg), aliases=aliases)
    schema = schema_for_llm(pkg, tables=list(tables))
    subgraph = subgraph_for_question(graph, question, settings.graph_slice_limit)
    patterns = prior_sql_patterns(subgraph, settings.prior_sql_patterns)
    semantic_context = store.relevant_context(pkg, question)
    if conversation is None and session_id:
        conversation = ctx.history.recent(domain, session_id, settings.history_turns)

    def make_draft(text: str):
        return ctx.generator.draft(
            text,
            pkg=pkg,
            frames=tables,
            schema=schema,
            catalog=catalog.text,
            subgraph=subgraph,
            patterns=patterns,
            context=semantic_context,
            conversation=conversation,
        )

    draft = make_draft(question)
    subject = _conversation_subject(conversation)
    if str(draft.plan.get("clarification_question") or "").strip() and subject:
        draft = make_draft(f"{question} {subject}")
    plan, sql_payload = draft.plan, draft.sql
    clarification = str(plan.get("clarification_question") or "").strip()
    if clarification:
        return _guardrail_response(
            ctx, request_id, domain, question, GuardrailResult("clarification_needed", clarification), pkg
        )

    warnings: list[str] = []
    repairs = 0
    executor = ctx.new_executor()
    try:

        def ground(text: str) -> str:
            return ground_sql(text, catalog.profiles, question, aliases)

        best = _attempt(ctx, executor, ground(str(sql_payload.get("sql_query") or "")), pkg, tables, catalog.profiles)
        if best.rank < 3:
            candidates: list[tuple[str, str]] = []
            if settings.max_repairs > 0:
                repairs += 1
                repaired = repair_sql(ctx.llm, question, best.sql, catalog.text, best.problem, schema)
                candidates.append(("sql_repaired", ground(repaired)))
            candidates.append(("used_local_planner_sql", ground(str(draft.local_sql.get("sql_query") or ""))))
            for label, candidate in candidates:
                if not candidate or candidate == best.sql:
                    continue
                alternative = _attempt(ctx, executor, candidate, pkg, tables, catalog.profiles)
                if alternative.rank > best.rank:
                    best = alternative
                    warnings.append(label)
                if best.rank == 3:
                    break
    finally:
        executor.close()
    sql, errors, result, joins_used, problem = best.sql, best.errors, best.result, best.joins_used, best.problem

    if errors:
        response = _base(request_id, domain, question, "validation_failed")
        response.update(_plan_fields(plan, sql, sql_payload))
        response["answer"] = "The generated SQL was rejected by the safety checks: " + " ".join(errors)
        response["warnings"] = warnings + errors
        response["repairs"] = repairs
        _finish_llm(response, settings, plan, sql_payload, None)
        _record(ctx, graph, pkg, question, plan, sql, "validation_failed", response["answer"], [], persist, session_id)
        return response
    if result is None or not result.ok:
        response = _base(request_id, domain, question, "execution_failed")
        response.update(_plan_fields(plan, sql, sql_payload))
        response["answer"] = f"The query could not run: {result.error if result else 'no result'}"
        response["warnings"] = warnings + ["execution_failed"]
        response["repairs"] = repairs
        _finish_llm(response, settings, plan, sql_payload, None)
        _record(ctx, graph, pkg, question, plan, sql, "execution_failed", response["answer"], [], persist, session_id)
        return response

    table = frame_preview(result.frame, settings.preview_rows)
    if result.truncated:
        warnings.append(f"result_truncated_to_{settings.row_limit}_rows")
    if problem:
        warnings.append("empty_or_null_result")
    answer = ctx.answers.generate(question, plan=plan, sql=sql, preview=table, diagnosis=problem)
    if answer["unverified_figures"]:
        warnings.append("answer_mentions_figures_not_in_result: " + ", ".join(answer["unverified_figures"]))

    chart = ctx.visuals.build(plan, table, pkg)
    datasets_used = [t for t in tables if t.lower() in sql.lower()]
    available_columns = {str(c) for frame in tables.values() for c in frame.columns}
    followups = ctx.followups.suggest(question, pkg=pkg, plan=plan, graph=graph, available_columns=available_columns)

    _record(ctx, graph, pkg, question, plan, sql, "success", answer["answer"], datasets_used, persist, session_id)

    response = _base(request_id, domain, question, "success")
    response.update(_plan_fields(plan, sql, sql_payload))
    response.update(
        {
            "answer": answer["answer"],
            "key_findings": answer["key_findings"],
            "datasets_used": datasets_used,
            "joins_used": joins_used,
            "table": table,
            "truncated": result.truncated,
            "chart": chart,
            "follow_up_questions": followups,
            "warnings": warnings,
            "repairs": repairs,
            "explainability": {
                "metric_definition": plan.get("metrics") or [],
                "calculations": plan.get("calculations") or [],
                "applied_filters": plan.get("filters") or {},
                "business_rules": [r.get("id") for r in semantic_context.get("business_rules") or []],
                "business_unit": (pkg.business_unit.code if pkg.business_unit else None),
                "source_attribution": {
                    "extracts": list(pkg.contract.extracts),
                    "source_system": pkg.contract.source_system,
                    "datasets": datasets_used,
                },
                "sql": sql,
                "knowledge_graph": graph.stats(),
            },
        }
    )
    _finish_llm(response, settings, plan, sql_payload, answer)
    return response


def normalize_confidence(value: Any) -> float | None:
    """A confidence in [0, 1], or ``None`` when the value is not a usable number (percentages are scaled)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    if 1 < number <= 100:
        number /= 100.0
    return min(1.0, max(0.0, number))


def _plan_fields(plan: dict[str, Any], sql: str, sql_payload: dict[str, Any]) -> dict[str, Any]:
    """The plan as reported to callers. Model output is untrusted, so types are coerced here."""
    intent = plan.get("intent")
    metrics, calculations = plan.get("metrics"), plan.get("calculations")
    # A confidence only means something when the model produced it. The local planner has none.
    from_model = plan.get("_llm_provider") != LOCAL_PROVIDER
    return {
        "intent": None if intent is None else str(intent),
        "confidence": normalize_confidence(plan.get("confidence")) if from_model else None,
        "interpreted_question": str(plan.get("interpreted_question") or ""),
        "metrics": metrics if isinstance(metrics, list) else [],
        "calculations": calculations if isinstance(calculations, list) else [],
        "sql_query": sql,
        "sql_rationale": str(sql_payload.get("rationale") or ""),
    }


def _finish_llm(
    response: dict[str, Any],
    settings: Settings,
    plan: dict[str, Any],
    sql_payload: dict[str, Any],
    answer: dict[str, Any] | None,
) -> None:
    """Say which parts the model produced and which fell back to the deterministic path."""
    providers = {
        "planner": plan.get("_llm_provider"),
        "sql": sql_payload.get("_llm_provider"),
        "answer": answer.get("_llm_provider") if answer else None,
    }
    response["llm"] = providers
    used_model = any(p not in (None, LOCAL_PROVIDER) for p in providers.values())
    response["answer_path"] = ANSWER_PATH_LLM if used_model else ANSWER_PATH_DETERMINISTIC
    fell_back = [name for name, provider in providers.items() if provider == LOCAL_PROVIDER]
    if settings.llm_mode == "bedrock" and fell_back:
        response["warnings"].append("llm_fallback_used: " + ", ".join(fell_back))


def _record(
    ctx: AppContext,
    graph: KnowledgeGraph,
    pkg: DomainPackage,
    question: str,
    plan: dict[str, Any],
    sql: str,
    status: str,
    answer: str,
    datasets: list[str],
    persist: bool,
    session_id: str | None,
) -> None:
    graph.record_episode(
        {
            "question_id": stable_id("q", question),
            "question": question,
            "intent": plan.get("intent"),
            "interpreted_question": plan.get("interpreted_question"),
            "metrics": plan.get("metrics") or [],
            "calculations": plan.get("calculations") or [],
            "new_terms": plan.get("new_terms") or [],
            "sql": sql,
            "datasets": datasets,
            "status": status,
            "answer_excerpt": answer[:400],
        }
    )
    if not persist:
        return
    ctx.graphs.save(graph)
    if session_id:
        metric = next((m for m in plan.get("metrics") or [] if isinstance(m, dict)), {})
        ctx.history.append(
            pkg.domain,
            session_id,
            {
                "question": question,
                "metric": metric.get("name") or "",
                "answer": answer,
                "sql_query": sql,
                "status": status,
            },
        )


def _conversation_subject(conversation: list[dict[str, Any]] | None) -> str:
    """The metric of the latest answered turn, without its scope, e.g. 'First Response Time'."""
    for turn in reversed(conversation or []):
        name = str(turn.get("metric") or "").strip()
        if name and turn.get("status", "success") == "success":
            return re.sub(r"\s*\([^)]*\)", "", name).strip()
    return ""
