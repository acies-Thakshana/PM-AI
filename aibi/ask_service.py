"""Orchestrate Ask: semantic-first (deterministic), LLM NL-to-SQL second.

Pipeline (AI-for-BI template across BUs/projects):
  1. Authenticate + BU RLS
  2. Build semantic query plan
  3. Deterministic semantic executor (certified metrics on registered data products)
  4. Only if semantic cannot handle → optional LLM NL-to-SQL on allowlisted products
  5. Clarify / refuse when required (never invent metrics)
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any

from aibi.audit import write_audit
from aibi.auth import LocalAuthUser, authenticate
from aibi.kpi_data import default_kpi_path
from aibi.query_plan import build_semantic_query_plan
from aibi.semantic_executor import execute_semantic_question
from aibi.semantic_service import load_semantic_core, sample_questions_for_user
from aibi.settings import get_settings


def _ensure_nl2sql_on_path() -> str:
    root = str(get_settings().nl2sql_root)
    src = os.path.join(root, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    os.environ.setdefault("AI_BI_NL2SQL_ROOT", root)
    return src


def _configure_nlq_env(user: LocalAuthUser) -> None:
    """Point the existing engine at this project's semantic core and registered datasets."""
    settings = get_settings()
    from aibi.data_product_registry import list_registered_products, resolve_product_path

    paths: list[str] = []
    names: list[str] = []
    for entry in list_registered_products():
        path = resolve_product_path(entry)
        if path.exists():
            paths.append(str(path))
            names.append(str(entry.get("physical_dataset") or entry["id"]))
    if not paths:
        paths = [str(default_kpi_path())]
        names = ["KPI_data"]

    os.environ["NLQ_SEMANTIC_ENABLED"] = "true"
    os.environ["NLQ_SEMANTIC_CORE"] = str(settings.semantic_core_path)
    os.environ["NLQ_SEMANTIC_EXTENSIONS"] = str(
        settings.project_root / "semantic" / "business_units"
    )
    os.environ["NLQ_SEMANTIC_INCLUDE_EXAMPLES"] = "false"
    os.environ["NLQ_DATA_PATHS"] = ",".join(paths)
    os.environ["NLQ_DATA_DATASETS"] = ",".join(names)
    os.environ["NLQ_ALLOW_LOCAL_FALLBACK"] = "true"
    os.environ["NLQ_EXECUTION_BACKEND"] = os.environ.get("NLQ_EXECUTION_BACKEND", "local")
    os.environ["NLQ_LLM_MODE"] = settings.llm_mode
    os.environ["NLQ_LLM_MODEL_ID"] = settings.llm_model_id
    if settings.llm_connection:
        os.environ["NLQ_LLM_CONNECTION"] = settings.llm_connection
    if user.can_query_cross_bu:
        os.environ["NLQ_CAN_QUERY_CROSS_BU"] = "true"
        os.environ.pop("NLQ_AUTHORIZED_BUS", None)
    else:
        os.environ["NLQ_CAN_QUERY_CROSS_BU"] = "false"
        os.environ["NLQ_AUTHORIZED_BUS"] = ",".join(user.authorized_bu_codes)


def _require_mesh_in_dss() -> None:
    """Fail in Dataiku if the configured Mesh LLM (Opus) cannot be loaded."""
    try:
        import dataiku  # noqa: F401
    except Exception:
        return
    try:
        from nlq.config.settings import get_settings as nlq_get_settings
        from nlq.dataiku_adapters.llm_mesh import LLMMeshClient

        nlq_get_settings.cache_clear()
        client = LLMMeshClient()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Could not load Dataiku LLM Mesh client: {0}".format(exc)) from exc
    if not client.is_available:
        raise RuntimeError(
            "LLM Mesh is not available. Set project variable AIBI_LLM_CONNECTION "
            "to the exact Opus Mesh id (Project → LLM Mesh). Current "
            "NLQ_LLM_CONNECTION={0!r}.".format(os.environ.get("NLQ_LLM_CONNECTION"))
        )


def _call_nl2sql(question: str, user: LocalAuthUser) -> dict[str, Any]:
    _ensure_nl2sql_on_path()
    _configure_nlq_env(user)
    if get_settings().force_llm:
        _require_mesh_in_dss()
    try:
        from nlq.config.settings import get_settings as nlq_get_settings

        nlq_get_settings.cache_clear()
    except Exception:
        pass
    try:
        from nlq.graph.runner import run_nlq

        result = run_nlq(question)
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if isinstance(result, dict):
            return result
        return {"answer": str(result), "query_status": "success"}
    except Exception as exc:  # noqa: BLE001
        return {
            "answer": "",
            "query_status": "execution_failed",
            "warnings": [f"NL-to-SQL call failed: {exc}"],
            "sql_query": "",
            "datasets_used": [],
            "chart_spec": {},
        }


def _base_response(
    *,
    request_id: str,
    plan: dict[str, Any],
    model: dict[str, Any],
    status: str,
    answer_path: str,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "status": status,
        "answer_path": answer_path,  # semantic | llm_nl2sql | clarify | refuse
        "answer": "",
        "clarification": None,
        "table": {"columns": [], "rows": []},
        "chart_spec": {},
        "metric_ids": [m["id"] for m in plan.get("metrics") or []],
        "metric_versions": plan.get("metric_versions") or [],
        "data_products": plan.get("approved_data_product_ids") or [],
        "bu_scope": plan.get("authorized_bu_scope") or [],
        "freshness": {"items": model.get("data_freshness") or []},
        "plan": plan,
        "sql_query": "",
        "warnings": [],
    }


def ask_business_data(
    question: str,
    *,
    user_id: str | None = None,
    ui_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask API: LLM (Opus Mesh) when AIBI_FORCE_LLM=true; otherwise semantic first."""
    request_id = str(uuid.uuid4())
    settings = get_settings()
    user: LocalAuthUser = authenticate(user_id)
    model = load_semantic_core()
    plan = build_semantic_query_plan(question, user, model)
    ui_context = ui_context or {}
    ui_filters = ui_context.get("filters") or {}
    apply_ui_filters = bool(ui_context.get("apply_dashboard_filters"))
    force_llm = settings.force_llm

    # --- Stage 0: hard authorization from plan ---
    if plan.get("unauthorized_reason"):
        response = _base_response(
            request_id=request_id,
            plan={**plan, "executor": "refuse"},
            model=model,
            status="refuse_unauthorized",
            answer_path="refuse",
        )
        response["answer"] = plan["unauthorized_reason"]
        write_audit(
            {
                "request_id": request_id,
                "status": response["status"],
                "answer_path": "refuse",
                "question": question,
                "user_id": user.user_id,
            }
        )
        return response

    # --- Stage 1a: onboarded catalog metrics (skipped when forcing LLM) ---
    catalog = None
    if not force_llm:
        try:
            from aibi.factory.catalog_executor import execute_catalog_metric

            catalog = execute_catalog_metric(question)
        except Exception:  # noqa: BLE001
            catalog = None
    if catalog and catalog.get("handled"):
        response = _base_response(
            request_id=request_id,
            plan={
                **plan,
                "executor": "catalog",
                "intent": "kpi",
                "clarification_required": False,
                "requested_measures": catalog.get("metric_ids") or [],
            },
            model=model,
            status="success",
            answer_path="semantic",
        )
        response["answer"] = catalog.get("answer") or ""
        response["table"] = catalog.get("table") or {"columns": [], "rows": []}
        response["chart_spec"] = catalog.get("chart_spec") or {}
        response["metric_ids"] = catalog.get("metric_ids") or []
        response["metric_versions"] = catalog.get("metric_versions") or []
        response["data_products"] = catalog.get("datasets_used") or []
        response["sql_query"] = catalog.get("sql_query") or ""
        response["warnings"] = catalog.get("warnings") or []
        response["record_count"] = catalog.get("record_count")
        write_audit(
            {
                "request_id": request_id,
                "status": "success",
                "answer_path": "catalog",
                "question": question,
                "user_id": user.user_id,
                "metric_ids": response["metric_ids"],
                "sql_query": response["sql_query"],
                "executor": "catalog",
            }
        )
        return response

    # --- Stage 1b: deterministic semantic executor (skipped when forcing LLM) ---
    semantic: dict[str, Any] = {}
    if not force_llm:
        semantic = execute_semantic_question(
            question,
            user=user,
            model=model,
            ui_filters=ui_filters,
            apply_ui_filters=apply_ui_filters,
        )

    if semantic.get("handled"):
        status = semantic.get("status") or "success"
        if status == "clarification_needed":
            answer_path = "clarify"
            response = _base_response(
                request_id=request_id,
                plan={**plan, "executor": "semantic", "intent": "clarify"},
                model=model,
                status=status,
                answer_path=answer_path,
            )
            response["clarification"] = semantic.get("clarification")
            response["metric_ids"] = semantic.get("metric_ids") or []
            response["warnings"] = semantic.get("warnings") or []
            response["suggested_questions"] = [
                q.get("question") for q in sample_questions_for_user(model, user.roles)[:5]
            ]
        elif status in {"refuse_unauthorized", "refuse_unsupported"}:
            answer_path = "refuse"
            response = _base_response(
                request_id=request_id,
                plan={**plan, "executor": "semantic", "intent": status},
                model=model,
                status=status,
                answer_path=answer_path,
            )
            response["answer"] = semantic.get("answer") or ""
            response["metric_ids"] = semantic.get("metric_ids") or []
        else:
            answer_path = "semantic"
            response = _base_response(
                request_id=request_id,
                plan={
                    **plan,
                    "executor": "semantic",
                    "intent": status,
                    "clarification_required": False,
                    "requested_measures": semantic.get("metric_ids")
                    or plan.get("requested_measures"),
                },
                model=model,
                status=status,
                answer_path=answer_path,
            )
            response["answer"] = semantic.get("answer") or ""
            response["clarification"] = semantic.get("clarification")
            response["table"] = semantic.get("table") or {"columns": [], "rows": []}
            response["chart_spec"] = semantic.get("chart_spec") or {}
            response["metric_ids"] = semantic.get("metric_ids") or response["metric_ids"]
            response["data_products"] = semantic.get("datasets_used") or response["data_products"]
            response["sql_query"] = semantic.get("sql_query") or ""
            response["warnings"] = semantic.get("warnings") or []
            response["record_count"] = semantic.get("record_count")
            response["interpreted_question"] = question

        write_audit(
            {
                "request_id": request_id,
                "status": response["status"],
                "answer_path": answer_path,
                "question": question,
                "user_id": user.user_id,
                "metric_ids": response.get("metric_ids"),
                "sql_query": response.get("sql_query"),
                "executor": "semantic",
                "semantic_version": plan.get("semantic_version"),
            }
        )
        return response

    # --- Stage 2: LLM NL-to-SQL (Opus Mesh when AIBI_FORCE_LLM=true) ---
    if not force_llm and not settings.enable_llm_fallback:
        response = _base_response(
            request_id=request_id,
            plan={**plan, "executor": "semantic_no_llm"},
            model=model,
            status="clarification_needed",
            answer_path="clarify",
        )
        response["clarification"] = (
            "No certified semantic pattern matched this question, and LLM fallback "
            "is disabled (AIBI_ENABLE_LLM_FALLBACK=false). Rephrase using a known "
            "metric, or enable LLM fallback for long-tail questions."
        )
        response["warnings"] = list(semantic.get("warnings") or [])
        response["suggested_questions"] = [
            q.get("question") for q in sample_questions_for_user(model, user.roles)[:5]
        ]
        write_audit(
            {
                "request_id": request_id,
                "status": response["status"],
                "answer_path": "clarify",
                "question": question,
                "user_id": user.user_id,
            }
        )
        return response

    if (
        not force_llm
        and plan.get("clarification_required")
        and not semantic.get("delegate_to_llm")
    ):
        clarify = " ".join(
            plan.get("ambiguities") or ["Please clarify the metric, BU, and period."]
        )
        response = _base_response(
            request_id=request_id,
            plan=plan,
            model=model,
            status="clarification_needed",
            answer_path="clarify",
        )
        response["clarification"] = clarify
        response["warnings"] = plan.get("ambiguities") or []
        response["suggested_questions"] = [
            q.get("question") for q in sample_questions_for_user(model, user.roles)[:5]
        ]
        write_audit(
            {
                "request_id": request_id,
                "status": response["status"],
                "answer_path": "clarify",
                "question": question,
                "user_id": user.user_id,
            }
        )
        return response

    nl = _call_nl2sql(question, user)
    status = nl.get("query_status") or "success"
    if status in {"validation_failed", "execution_failed", "metadata_failed"}:
        mapped = status
    else:
        mapped = "success"

    response = _base_response(
        request_id=request_id,
        plan={**plan, "executor": "llm_nl2sql"},
        model=model,
        status=mapped,
        answer_path="llm_nl2sql",
    )
    response["answer"] = nl.get("answer") or ""
    response["table"] = {"columns": nl.get("columns_used") or [], "rows": []}
    response["chart_spec"] = nl.get("chart_spec") or {}
    response["data_products"] = (
        plan.get("approved_data_product_ids") or nl.get("datasets_used") or []
    )
    response["sql_query"] = nl.get("sql_query") or ""
    response["warnings"] = (
        list(semantic.get("warnings") or [])
        + list(nl.get("warnings") or [])
        + list(nl.get("assumptions") or [])
    )
    response["interpreted_question"] = nl.get("interpreted_question") or ""
    response["intent"] = nl.get("intent") or plan.get("intent")

    write_audit(
        {
            "request_id": request_id,
            "status": response["status"],
            "answer_path": "llm_nl2sql",
            "question": question,
            "user_id": user.user_id,
            "metric_ids": response["metric_ids"],
            "sql_query": response["sql_query"],
            "executor": "llm_nl2sql",
            "semantic_version": plan.get("semantic_version"),
        }
    )
    return response
