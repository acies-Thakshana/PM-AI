"""Question to plan to SQL. The model drafts; the local planner is the fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ai4bi.llm.client import LlmClient, complete_json
from ai4bi.semantic.models import DomainPackage
from ai4bi.semantic.store import SemanticStore
from ai4bi.sql.local_planner import LocalPlanner

PLAN_INSTRUCTION = (
    "You are the AI4BI planner. Infer intent, metrics, dimensions, filters, and calculations "
    "from the question, the schema, the retrieved knowledge graph, and the business context. "
    "Prefer a certified metric when one matches; its compute block is the definition. "
    "Apply business rules that match the question. Do not invent joins. "
    "If no metric, measure, or count in the schema fits the question, set clarification_question "
    "to a short question naming the closest available metrics; otherwise leave it empty. Output JSON only."
)
PLAN_KEYS = [
    "intent", "interpreted_question", "entities", "metrics", "dimensions",
    "filters", "calculations", "new_terms", "confidence", "clarification_question",
]
SQL_INSTRUCTION = (
    "You write SQLite SQL. Use only listed physical_dataset names and columns. "
    "If you need a JOIN, its ON keys MUST be one of registered_joins keys. "
    "Never select restricted/PII columns. Filter values must be copied from the "
    "catalog members. Never use a column that was omitted for having no data. "
    "Additive measures use SUM unless asked for avg/count. "
    "Durations in hours are (julianday(end) - julianday(start)) * 24.0. "
    "Reuse validated_sql_examples and prior_sql_patterns when they answer the same shape. "
    "Output JSON only with sql_query, datasets_used, columns_used, rationale."
)


@dataclass
class Draft:
    plan: dict[str, Any]
    sql: dict[str, Any]
    local_plan: dict[str, Any]
    local_sql: dict[str, Any]


class SqlGenerator:
    def __init__(self, llm: LlmClient, store: SemanticStore) -> None:
        self.llm = llm
        self.local = LocalPlanner(store)

    def draft(
        self,
        question: str,
        *,
        pkg: DomainPackage,
        frames: dict[str, pd.DataFrame],
        schema: dict[str, Any],
        catalog: str,
        subgraph: dict[str, Any],
        patterns: list[dict[str, Any]],
        context: dict[str, Any],
        conversation: list[dict[str, Any]] | None = None,
    ) -> Draft:
        local_plan, local_sql = self.local.draft(question, pkg, frames)
        plan = complete_json(
            self.llm,
            PLAN_INSTRUCTION,
            json.dumps(
                {
                    "question": question,
                    "conversation": conversation or [],
                    "schema": schema,
                    "knowledge_graph_slice": subgraph,
                    "business_context": context,
                    "required_keys": PLAN_KEYS,
                },
                default=str,
            ),
            task="intent",
            fallback=local_plan,
        )
        sql = complete_json(
            self.llm,
            SQL_INSTRUCTION,
            json.dumps(
                {
                    "question": question,
                    "plan": {k: plan.get(k) for k in PLAN_KEYS if k not in {"new_terms", "clarification_question"}},
                    "schema": schema,
                    "catalog": catalog,
                    "business_rules": context.get("business_rules") or [],
                    "validated_sql_examples": context.get("validated_sql_examples") or [],
                    "prior_sql_patterns": patterns,
                },
                default=str,
            ),
            task="sql",
            fallback=local_sql,
        )
        if not str(sql.get("sql_query") or "").strip():
            sql = {**local_sql, "_llm_provider": "local_fallback", "_llm_task": "sql"}
        return Draft(plan=plan, sql=sql, local_plan=local_plan, local_sql=local_sql)
