"""LLM Mesh client. Intent / SQL / answer always go through this wrapper."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

LOGGER = logging.getLogger(__name__)


def complete_json(
    system_instruction: str,
    user_prompt: str,
    *,
    task: str = "generic",
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = complete_text(system_instruction, user_prompt)
    payload = _extract_json(text)
    if payload:
        payload["_llm_provider"] = payload.get("_llm_provider") or _provider_name()
        payload["_llm_task"] = task
        return payload
    if fallback is not None:
        out = dict(fallback)
        out["_llm_provider"] = "local_fallback"
        out["_llm_task"] = task
        return out
    raise RuntimeError("LLM did not return JSON for task={0}".format(task))


def complete_text(system_instruction: str, user_prompt: str) -> str:
    llm = _dss_llm()
    if llm is None:
        return ""
    completion = llm.new_completion()
    if system_instruction:
        completion.with_message(system_instruction, role="system")
    completion.with_message(user_prompt, role="user")
    try:
        if hasattr(completion, "settings"):
            completion.settings["temperature"] = 0.0
    except Exception:
        pass
    response = completion.execute()
    return getattr(response, "text", None) or str(response)


def _provider_name() -> str:
    return os.environ.get("NLQ_LLM_CONNECTION") or os.environ.get("AIBI_LLM_CONNECTION") or "llm_mesh"


def _dss_llm() -> Any | None:
    if os.environ.get("AIBI_LLM_MODE", "mesh").lower() == "local":
        return None
    connection = os.environ.get("AIBI_LLM_CONNECTION") or os.environ.get("NLQ_LLM_CONNECTION")
    try:
        import dataiku  # type: ignore

        project = dataiku.api_client().get_default_project()
        if connection:
            return project.get_llm(connection)
        llms = []
        for method in ("list_llms", "list_available_llms"):
            fn = getattr(project, method, None)
            if callable(fn):
                try:
                    llms = fn() or []
                    break
                except Exception:
                    continue
        ids = []
        for item in llms:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict):
                ids.append(str(item.get("id") or item.get("llmId") or ""))
        opus = [i for i in ids if "opus" in i.lower()]
        chosen = (opus[0] if opus else (ids[0] if ids else ""))
        if not chosen:
            return None
        os.environ["AIBI_LLM_CONNECTION"] = chosen
        os.environ["NLQ_LLM_CONNECTION"] = chosen
        return project.get_llm(chosen)
    except Exception as exc:  # noqa: BLE001
        LOGGER.info("LLM Mesh unavailable (%s)", exc)
        return None


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
