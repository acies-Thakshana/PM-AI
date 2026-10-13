"""Platform PII tags. Prompts are not a security boundary."""

from __future__ import annotations

from aibi.factory.models import DomainPackage


def restricted_columns(pkg: DomainPackage) -> set[str]:
    names: set[str] = set()
    for entity in pkg.entities:
        for col in entity.columns:
            if col.pii_tag == "restricted" or col.sensitive:
                names.add(col.name)
    for tag in pkg.pii_tags:
        if tag.get("action") in {"deny", "restricted"}:
            names.add(str(tag.get("column")))
    return {n for n in names if n}


def strip_restricted(columns: list[str], pkg: DomainPackage) -> list[str]:
    blocked = restricted_columns(pkg)
    return [c for c in columns if c not in blocked]


def assert_no_restricted_in_sql(sql: str, pkg: DomainPackage) -> None:
    blocked = restricted_columns(pkg)
    lowered = (sql or "").lower()
    hits = [c for c in blocked if c.lower() in lowered]
    if hits:
        raise PermissionError(
            "Restricted columns cannot be selected or sent to the LLM: " + ", ".join(hits)
        )
