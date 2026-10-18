"""Question to plan to SQL. The model drafts; the local planner is the fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.config import CALL_PLAN, CALL_SQL
from app.services.common.llm import LOCAL_PROVIDER, LlmClient, complete_json
from app.services.semantic.models import DomainPackage
from app.services.semantic.store import SemanticStore
from app.services.sql.local_planner import LocalPlanner

PLAN_KEYS = [
    "intent",
    "interpreted_question",
    "entities",
    "metrics",
    "dimensions",
    "filters",
    "calculations",
    "new_terms",
    "confidence",
    "clarification_question",
]


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
            CALL_PLAN,
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
            fallback=local_plan,
        )
        sql = complete_json(
            self.llm,
            CALL_SQL,
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
            fallback=local_sql,
        )
        if not str(sql.get("sql_query") or "").strip():
            sql = {**local_sql, "_llm_provider": LOCAL_PROVIDER, "_llm_task": CALL_SQL}
        return Draft(plan=plan, sql=sql, local_plan=local_plan, local_sql=local_sql)
