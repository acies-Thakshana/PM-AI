"""Onboard a domain: read its datasets, learn the semantics, store the registry and the catalog."""

from __future__ import annotations

from typing import Any

from app.errors import DataNotFoundError
from app.services.common import audit_log
from app.services.context import AppContext
from app.services.onboarding.onboarding import onboard_domain


def _count(audit: list[dict[str, Any]], artifact_type: str, active: bool) -> int:
    return sum(1 for item in audit if item["artifact_type"] == artifact_type and bool(item["active"]) is active)


def run_onboarding(ctx: AppContext, domain: str, *, force: bool = False) -> dict[str, Any]:
    """Learn and store the semantics of ``domain``. Safe to repeat: unchanged data is a no-op.

    Returns a JSON-serialisable summary. ``changed`` is false when the data's structure matches
    a previous run and ``force`` was not set.
    """
    tables = ctx.source.list_tables(domain)
    if not tables:
        raise DataNotFoundError(f"Domain {domain!r} has no datasets. Upload files for it first.")
    frames = ctx.cache.raw(domain, tables)
    registry = ctx.registry.load(domain)
    baseline = ctx.semantic.load(domain) if ctx.semantic.exists(domain) else None

    result = onboard_domain(
        domain,
        frames,
        llm=ctx.llm,
        settings=ctx.settings,
        registry=registry,
        base_package=baseline,
        force=force,
    )
    written = ctx.registry.save(domain, registry)
    if result.changed:
        ctx.catalogs.save(domain, result.metadata)

    summary = {
        "domain": domain,
        "changed": result.changed,
        "semantic_version": result.semantic_version,
        "fingerprint": result.fingerprint,
        "provider": result.provider,
        "datasets": sorted(frames),
        "artifacts_written": written,
        "metrics": {"active": _count(result.audit, "metric", True), "draft": _count(result.audit, "metric", False)},
        "joins": {"active": _count(result.audit, "join", True), "draft": _count(result.audit, "join", False)},
        "findings": result.audit,
    }
    audit_log.record(
        "onboard",
        changed=result.changed,
        semantic_version=result.semantic_version,
        provider=result.provider,
        artifacts_written=written,
    )
    return summary
