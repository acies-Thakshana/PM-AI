"""Request handler used by the SageMaker /invocations endpoint.

The same function runs inside the container and in a SageMaker notebook.
Local mode answers from the bundled sample data without Dataiku or an LLM.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("AIBI_PROJECT_ROOT", str(ROOT))
os.environ.setdefault("AIBI_LLM_MODE", "local")
for item in (str(ROOT / "lib" / "python"), str(ROOT)):
    if item not in sys.path:
        sys.path.insert(0, item)

from ai4bi.knowledge.seed import seed_from_package  # noqa: E402
from ai4bi.pipeline import ask, build_context  # noqa: E402
from ai4bi.semantic.onboarding import onboard_domain  # noqa: E402
from ai4bi.semantic.registry import JsonSemanticRegistryStore  # noqa: E402


def parse_payload(raw: bytes, content_type: str) -> dict[str, Any]:
    """Accept a JSON object or a plain-text question."""
    text = raw.decode("utf-8").strip()
    if not text:
        raise ValueError("Request body is empty. Send a question.")
    kind = (content_type or "application/json").split(";")[0].strip().lower()
    if kind in {"text/plain", "text/csv"}:
        return {"action": "ask", "question": text}
    if kind not in {"application/json", ""}:
        raise ValueError("Content-Type must be application/json or text/plain.")
    import json

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Request body is not valid JSON: {exc}") from exc
    if isinstance(payload, str):
        return {"action": "ask", "question": payload}
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object with a question field.")
    return payload


def invoke(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one SageMaker invocation."""
    action = str(payload.get("action") or "ask").strip().lower()
    if action == "ask":
        return _ask(payload)
    if action == "onboard":
        return _onboard(payload)
    raise ValueError("action must be 'ask' or 'onboard'.")


def _ask(payload: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get("question") or payload.get("input_question") or "").strip()
    if not question:
        raise ValueError("question is required.")
    ctx = build_context(history=bool(payload.get("persist", False)))
    domain = str(payload.get("domain") or ctx.settings.default_domain)
    frames, package = _learned_semantics(ctx, domain)
    result = ask(
        question,
        context=ctx,
        domain=domain,
        session_id=payload.get("session_id") or None,
        persist=bool(payload.get("persist", False)),
        frames=frames,
        semantic_package=package,
    )
    result["action"] = "ask"
    return result


def _onboard(payload: dict[str, Any]) -> dict[str, Any]:
    ctx = build_context(history=False)
    domain = str(payload.get("domain") or ctx.settings.default_domain)
    base = ctx.semantic.load(domain) if ctx.semantic.exists(domain) else None
    names = [entity.physical_dataset for entity in base.entities] if base else None
    frames = ctx.data.load(domain, names)
    store = JsonSemanticRegistryStore(ctx.settings.semantic_registry_root)
    result = onboard_domain(
        domain,
        frames,
        llm=ctx.llm,
        settings=ctx.settings,
        registry=store.load(domain),
        base_package=base,
        force=bool(payload.get("force", False)),
    )
    store.save(domain, result.registry)
    ctx.metadata.save(result.metadata)
    graph = ctx.graphs.load(domain)
    seed_from_package(graph, result.package)
    ctx.graphs.save(graph)
    return {
        "action": "onboard",
        "domain": domain,
        "changed": result.changed,
        "semantic_version": result.semantic_version,
        "fingerprint": result.fingerprint,
        "audit": result.audit,
        "knowledge_graph": graph.stats(),
    }


def _learned_semantics(ctx, domain: str):
    registry = JsonSemanticRegistryStore(ctx.settings.semantic_registry_root).load(domain)
    if not registry.artifacts:
        return None, None
    base = ctx.semantic.load(domain) if ctx.semantic.exists(domain) else None
    names = [entity.physical_dataset for entity in base.entities] if base else None
    frames = ctx.data.load(domain, names)
    package = ctx.semantic.load_with_registry(
        domain, frames, registry, include_drafts=ctx.settings.include_drafts
    )
    return frames, package
