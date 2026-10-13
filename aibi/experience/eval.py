"""Excel Escape evaluation — the primary AI4BI regression library."""

from __future__ import annotations

from typing import Any

from aibi.factory.catalog import resolve_metric
from aibi.factory.catalog_executor import execute_catalog_metric
from aibi.factory.loader import load_domain
from aibi.settings import PROJECT_ROOT, load_yaml


def load_excel_escape(domain: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "evaluation" / "excel_escape" / f"{domain}.yaml"
    return load_yaml(path) or {}


def run_excel_escape(domain: str) -> dict[str, Any]:
    doc = load_excel_escape(domain)
    pkg = load_domain(domain)
    results: list[dict[str, Any]] = []
    passed = 0
    for case in doc.get("cases") or []:
        question = case.get("user_question") or ""
        expected = case.get("expected_answer") or {}
        validation = case.get("validation") or {}
        kind = validation.get("type") or "metric_value"
        executed = execute_catalog_metric(question, domain=domain)
        ok = False
        detail = ""
        if kind == "metric_value":
            got_id = (executed or {}).get("metric_ids") or []
            want_id = expected.get("metric_id")
            rows = ((executed or {}).get("table") or {}).get("rows") or []
            got_value = rows[0][3] if rows else None
            want = expected.get("value")
            tol = float(expected.get("tolerance") or 0)
            ok = bool(
                executed
                and want_id in got_id
                and got_value is not None
                and abs(float(got_value) - float(want)) <= tol
            )
            detail = f"got {got_id} value={got_value} want {want_id}={want}"
        elif kind == "metric_family":
            family = validation.get("family")
            resolved = resolve_metric(question, pkg)
            ok = resolved is not None and resolved.family == family
            detail = f"family={getattr(resolved, 'family', None)}"
        results.append(
            {
                "id": case.get("id"),
                "user_question": question,
                "data_sources": case.get("data_sources") or [],
                "validation": kind,
                "passed": ok,
                "detail": detail,
            }
        )
        passed += int(ok)
    total = len(results)
    return {
        "domain": domain,
        "library": "excel_escape",
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "results": results,
    }
