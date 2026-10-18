"""Checks that run before any model call or SQL."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings
from app.services.common.text import phrase_in
from app.services.semantic.models import DomainPackage

OK = "ok"


@dataclass
class GuardrailResult:
    status: str = OK
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK


def validate_question(question: str | None, settings: Settings) -> GuardrailResult:
    text = (question or "").strip()
    if not text:
        return GuardrailResult("clarification_needed", "Please type a question about the data.")
    if len(text) < settings.min_question_length:
        return GuardrailResult(
            "clarification_needed", "The question is too short. Add the metric or the period you need."
        )
    if len(text) > settings.max_question_length:
        return GuardrailResult(
            "refuse_unsupported",
            f"The question is longer than {settings.max_question_length} characters. Shorten it to one request.",
        )
    if not re.search(r"[A-Za-z]", text):
        return GuardrailResult("clarification_needed", "The question has no words. Ask about a metric or a dataset.")
    for rule in settings.blocked_patterns:
        pattern = rule.get("pattern") or ""
        if pattern and re.search(pattern, text, flags=re.IGNORECASE):
            return GuardrailResult(rule.get("status") or "refuse_unsupported", rule.get("reason") or "Not supported.")
    return GuardrailResult()


def check_restricted_request(question: str, pkg: DomainPackage) -> GuardrailResult:
    """Refuse when the question names a column tagged restricted."""
    for column in sorted(pkg.restricted_columns()):
        spoken = column.replace("_", " ")
        if phrase_in(question, column) or phrase_in(question, spoken):
            return GuardrailResult(
                "refuse_unauthorized",
                f"'{column}' is a restricted field. It cannot be returned or used in an answer.",
            )
    return GuardrailResult()
