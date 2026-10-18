"""Natural-language answers bound to the executed result."""

from __future__ import annotations

import json
import re
from typing import Any

from ai4bi.llm.client import LlmClient, complete_json
from ai4bi.utils.frames import as_number

ANSWER_INSTRUCTION = (
    "You are a BI analyst. Answer only from the executed result. "
    "If the result has no rows or only null measures, say which filter missed "
    "and quote the closest catalog members from the diagnosis. Do not invent figures. "
    "Output JSON only with keys answer, key_findings."
)
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.\-])-?\d[\d,]*(?:\.\d+)?")
MAX_LISTED_ROWS = 5


def _format(value: Any) -> str:
    number = as_number(value)
    if number is None:
        return str(value)
    number = round(float(number), 6)
    if number.is_integer() and abs(number) < 1e15:
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _split_columns(preview: dict[str, Any]) -> tuple[list[str], list[str]]:
    rows = preview.get("rows") or []
    columns = preview.get("columns") or []
    numeric = [c for c in columns if rows and all(as_number(r.get(c)) is not None or r.get(c) is None for r in rows)
               and any(as_number(r.get(c)) is not None for r in rows)]
    labels = [c for c in columns if c not in numeric]
    return labels, numeric


def local_answer(
    question: str,
    plan: dict[str, Any],
    preview: dict[str, Any],
    diagnosis: str = "",
) -> dict[str, Any]:
    rows = preview.get("rows") or []
    metric = (plan.get("metrics") or [{}])[0] if plan.get("metrics") else {}
    name = str(metric.get("name") or "The result")
    unit = f" {metric['unit']}" if metric.get("unit") else ""
    if not rows:
        reason = diagnosis.splitlines()[0] if diagnosis else "The query returned no rows."
        hint = " ".join(diagnosis.splitlines()[1:]) if diagnosis else ""
        return {"answer": f"No figures are available for this question. {reason} {hint}".strip(), "key_findings": []}
    labels, numeric = _split_columns(preview)
    scope = [
        f"{column} is {' or '.join(map(str, values))}"
        for column, values in (plan.get("filters") or {}).items()
        if values and column not in labels and not all(str(v).lower() in name.lower() for v in values)
    ]
    subject = name + (" where " + " and ".join(scope) if scope else "")
    if len(rows) == 1 and not labels and numeric:
        value = rows[0][numeric[0]]
        if value is None:
            return {"answer": f"{subject} has no stored value.", "key_findings": []}
        return {"answer": f"{subject} is {_format(value)}{unit}.", "key_findings": [f"{numeric[0]} = {_format(value)}"]}
    findings: list[str] = []
    for row in rows[:MAX_LISTED_ROWS]:
        label = ", ".join(str(row.get(c)) for c in labels) or "row"
        figures = ", ".join(f"{_format(row.get(c))}{unit}" for c in numeric)
        findings.append(f"{label}: {figures}" if figures else label)
    total = int(preview.get("n") or len(rows))
    lead = f"{subject} by {', '.join(labels)}" if labels else subject
    answer = f"{lead}: " + "; ".join(findings) + "."
    if total > MAX_LISTED_ROWS:
        answer += f" Showing {MAX_LISTED_ROWS} of {total} rows."
    return {"answer": answer, "key_findings": findings}


def unverified_figures(answer: str, preview: dict[str, Any], question: str = "") -> list[str]:
    """Numbers in the answer that are not in the result or the question."""
    known: list[float] = []
    texts = [question or ""]
    for row in preview.get("rows") or []:
        for value in row.values():
            number = as_number(value)
            if number is not None:
                known.append(number)
            elif value is not None:
                texts.append(str(value))
    for token in (t for text in texts for t in re.findall(r"\d[\d,]*(?:\.\d+)?", text)):
        number = as_number(token)
        if number is not None:
            known.append(number)
    known.append(float(len(preview.get("rows") or [])))
    known.append(float(preview.get("n") or 0))
    missing: list[str] = []
    for token in _NUMBER.findall(answer or ""):
        number = as_number(token.rstrip(".,"))
        if number is None:
            continue
        close = any(
            abs(number - k) <= max(0.01, 0.005 * abs(k)) or abs(number - k * 100) <= max(0.05, 0.005 * abs(k * 100))
            for k in known
        )
        if not close:
            missing.append(token.rstrip(".,"))
    return missing


class AnswerGenerator:
    def __init__(self, llm: LlmClient) -> None:
        self.llm = llm

    def generate(
        self,
        question: str,
        *,
        plan: dict[str, Any],
        sql: str,
        preview: dict[str, Any],
        diagnosis: str = "",
    ) -> dict[str, Any]:
        payload = complete_json(
            self.llm,
            ANSWER_INSTRUCTION,
            json.dumps(
                {
                    "question": question,
                    "interpreted_question": plan.get("interpreted_question"),
                    "sql_query": sql,
                    "result": preview,
                    "diagnosis": diagnosis,
                    "metrics": plan.get("metrics"),
                    "calculations": plan.get("calculations"),
                },
                default=str,
            ),
            task="answer",
            fallback=local_answer(question, plan, preview, diagnosis),
        )
        answer = str(payload.get("answer") or "").strip()
        findings = payload.get("key_findings") or []
        if not isinstance(findings, list):
            findings = [str(findings)]
        return {
            "answer": answer,
            "key_findings": [str(f) for f in findings],
            "unverified_figures": unverified_figures(answer, preview, question),
            "_llm_provider": payload.get("_llm_provider"),
        }
