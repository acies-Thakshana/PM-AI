"""Domain health checks: configuration, data, chart bindings, and validated SQL."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from ai4bi.config.errors import AI4BIError
from ai4bi.data.preprocessing import drop_restricted, prepare_frames
from ai4bi.pipeline.context import AppContext
from ai4bi.semantic.loader import align_with_frames
from ai4bi.utils.frames import as_number

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
    checks: list[Check] = []
    store = ctx.semantic
    if not store.exists(domain):
        checks.append(Check("semantic_package", False, f"No folder {store.domain_dir(domain)}"))
        return checks
    try:
        pkg = store.load(domain, refresh=True)
        checks.append(
            Check("semantic_package", True, f"{len(pkg.entities)} entities, {len(pkg.metrics)} metrics, "
                  f"{len(pkg.joins)} joins, {len(pkg.glossary)} glossary terms, {len(pkg.rules)} rules")
        )
    except AI4BIError as exc:
        checks.append(Check("semantic_package", False, str(exc)))
        return checks

    try:
        raw = ctx.data.load(domain, [e.physical_dataset for e in pkg.entities])
        frames = drop_restricted(prepare_frames(raw), pkg.restricted_columns())
        pkg = align_with_frames(pkg, raw)
        checks.append(Check("datasets", True, ", ".join(f"{n} ({len(f)} rows)" for n, f in frames.items())))
    except AI4BIError as exc:
        checks.append(Check("datasets", False, str(exc)))
        return checks

    missing = [
        f"{e.physical_dataset}.{c.name}"
        for e in pkg.entities
        if e.physical_dataset in raw
        for c in e.columns
        if c.name not in raw[e.physical_dataset].columns
    ]
    checks.append(
        Check("registered_columns", not missing, "all present" if not missing else "missing in data: " + ", ".join(missing))
    )

    errors = ctx.visuals.validate_bindings(pkg)
    checks.append(Check("visual_bindings", not errors, "ok" if not errors else "; ".join(errors)))

    for entry in pkg.validated_sql:
        validation = ctx.validator.validate(entry.sql, pkg, list(frames))
        if not validation.ok:
            checks.append(Check(f"validated_sql:{entry.id}", False, "; ".join(validation.errors)))
            continue
        result = ctx.executor.execute(validation.sql, frames)
        if not result.ok:
            checks.append(Check(f"validated_sql:{entry.id}", False, result.error))
            continue
        values = [n for n in (as_number(v) for v in result.frame.to_numpy().ravel()) if n is not None]
        matched = _expected_numbers_present(entry.expected_result, values)
        detail = f"{len(result.frame)} rows" + (f", expected {entry.expected_result}" if entry.expected_result else "")
        checks.append(Check(f"validated_sql:{entry.id}", matched, detail if matched else detail + " not found in result"))
    return checks
