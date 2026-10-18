"""Domain health checks: configuration, data, chart bindings, and validated SQL."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from app.errors import ConfigError
from app.services.ask.domain_view import resolve_domain
from app.services.common.frames import as_number
from app.services.context import AppContext
from app.services.semantic.models import DomainPackage, ValidatedSql
from app.services.sql.executor import SqlExecutor

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _expected_numbers_present(expected: str, values: list[float]) -> bool:
    for token in _NUMBER.findall(expected or ""):
        target = float(token)
        if not any(abs(target - v) <= 0.01 + 0.001 * abs(target) for v in values):
            return False
    return True


def check_domain(ctx: AppContext, domain: str) -> list[Check]:
    """Run every check for one domain.

    A missing domain or missing data raises (the API reports 404). A broken semantic package is
    reported as a failed check so the other checks can still run.
    """
    try:
        view = resolve_domain(ctx, domain)
    except ConfigError as exc:
        return [Check("semantic_package", False, str(exc))]
    pkg, tables = view.pkg, view.tables

    origin = "baseline package" if ctx.semantic.exists(domain) else "inferred from the data"
    checks = [
        Check(
            "semantic_package",
            True,
            f"{origin}: {len(pkg.entities)} entities, {len(pkg.metrics)} metrics, {len(pkg.joins)} joins, "
            f"{len(pkg.glossary)} glossary terms, {len(pkg.rules)} rules",
        ),
        Check("datasets", True, ", ".join(f"{name} ({len(frame)} rows)" for name, frame in view.raw.items())),
    ]

    missing = [
        f"{e.physical_dataset}.{c.name}"
        for e in pkg.entities
        if e.physical_dataset in view.raw
        for c in e.columns
        if c.name not in view.raw[e.physical_dataset].columns
    ]
    checks.append(
        Check(
            "registered_columns",
            not missing,
            "all present" if not missing else "missing in data: " + ", ".join(missing),
        )
    )

    errors = ctx.visuals.validate_bindings(pkg)
    checks.append(Check("visual_bindings", not errors, "ok" if not errors else "; ".join(errors)))

    executor = ctx.new_executor()
    try:
        for entry in pkg.validated_sql:
            checks.append(run_validated_sql(ctx, executor, entry, pkg, tables))
    finally:
        executor.close()
    return checks


def run_validated_sql(
    ctx: AppContext,
    executor: SqlExecutor,
    entry: ValidatedSql,
    pkg: DomainPackage,
    tables: dict[str, pd.DataFrame],
) -> Check:
    """Validate and run one stored query and compare its result with the expected figures."""
    name = f"validated_sql:{entry.id}"
    validation = ctx.validator.validate(entry.sql, pkg, list(tables))
    if not validation.ok:
        return Check(name, False, "; ".join(validation.errors))
    result = executor.execute(validation.sql, tables)
    if not result.ok:
        return Check(name, False, result.error)
    values = [n for n in (as_number(v) for v in result.frame.to_numpy().ravel()) if n is not None]
    matched = _expected_numbers_present(entry.expected_result, values)
    detail = f"{len(result.frame)} rows" + (f", expected {entry.expected_result}" if entry.expected_result else "")
    return Check(name, matched, detail if matched else detail + " not found in result")
