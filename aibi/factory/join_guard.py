"""SQL may only use joins that are already in the registry."""

from __future__ import annotations

import re

from aibi.factory.models import DomainPackage, RegisteredJoin

_JOIN = re.compile(r"\bjoin\b", re.IGNORECASE)
_DML = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke)\b",
    re.IGNORECASE,
)


def registered_conditions(pkg: DomainPackage) -> list[str]:
    return [_normalize(j.condition) for j in pkg.joins if j.allowed_for_nlq]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def assert_select_only(sql: str) -> None:
    stripped = (sql or "").strip()
    if not stripped:
        raise PermissionError("Empty SQL is not allowed")
    if _DML.search(stripped):
        raise PermissionError("Only read-only SELECT is allowed")
    if ";" in stripped.rstrip(";"):
        raise PermissionError("Multiple SQL statements are not allowed")


def assert_registered_joins(sql: str, pkg: DomainPackage) -> list[RegisteredJoin]:
    """If the SQL joins, every join condition must match the registry."""
    assert_select_only(sql)
    if not _JOIN.search(sql or ""):
        return []
    normalized = _normalize(sql)
    used: list[RegisteredJoin] = []
    for join in pkg.joins:
        if not join.allowed_for_nlq:
            continue
        cond = _normalize(join.condition)
        key_bits = [f"{k.left_column} = {k.right_column}" for k in join.keys]
        key_bits += [f"{k.right_column} = {k.left_column}" for k in join.keys]
        matched = cond and cond in normalized
        matched = matched or any(_normalize(bit) in normalized for bit in key_bits)
        if matched:
            used.append(join)
    if not used:
        raise PermissionError(
            "SQL contains JOIN but no registered join condition matched. "
            "Register the relationship in joins.yaml; do not infer it."
        )
    return used
