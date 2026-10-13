"""Local stand-in for the DSS KPI validation recipe I/O contract."""

from __future__ import annotations

import os

import pandas as pd

# Keep this contract test on the deterministic path; the DSS recipe forces Opus.
os.environ["AIBI_FORCE_LLM"] = "false"

from aibi.ask_service import ask_business_data


def test_validation_output_has_required_columns():
    questions = pd.DataFrame(
        {
            "input_question": ["What is the total productivity achieved so far?"],
            "Expected_SQL_Query": ['SELECT SUM("Actual Productivity") FROM KPI_data'],
        }
    )
    rows = []
    for question, expected in zip(
        questions["input_question"].tolist(),
        questions["Expected_SQL_Query"].tolist(),
    ):
        result = ask_business_data(question, user_id="local.cross_bu")
        rows.append(
            {
                "question": question,
                "Expected_SQL_Query": expected,
                "LLM_generated_SQL": result.get("sql_query") or "",
                "LLM_generated_answer": result.get("answer")
                or result.get("clarification")
                or "",
            }
        )
    out = pd.DataFrame(
        rows,
        columns=[
            "question",
            "Expected_SQL_Query",
            "LLM_generated_SQL",
            "LLM_generated_answer",
        ],
    )
    assert list(out.columns) == [
        "question",
        "Expected_SQL_Query",
        "LLM_generated_SQL",
        "LLM_generated_answer",
    ]
    assert len(out) == 1
    assert out.loc[0, "Expected_SQL_Query"]
    assert out.loc[0, "LLM_generated_answer"]
