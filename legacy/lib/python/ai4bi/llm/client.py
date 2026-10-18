"""Model access. The pipeline only depends on ``LlmClient.complete``.

``local`` mode returns no text, so every caller uses its structured fallback.
Platform adapters register other modes (for example ``mesh`` in ai4bi_dataiku).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from ai4bi.config.errors import ConfigError, LlmError
from ai4bi.config.settings import Settings
from ai4bi.logging import get_logger
from ai4bi.utils.text import extract_json

LOGGER = get_logger(__name__)


@runtime_checkable
class LlmClient(Protocol):
    name: str

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        ...


class LocalFallbackClient:
    name = "local_fallback"

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        return ""


_FACTORIES: dict[str, Callable[[Settings], LlmClient]] = {
    "local": lambda settings: LocalFallbackClient(),
}


def register_llm_factory(mode: str, factory: Callable[[Settings], LlmClient]) -> None:
    _FACTORIES[mode] = factory


def get_llm_client(settings: Settings) -> LlmClient:
    factory = _FACTORIES.get(settings.llm_mode)
    if factory is None:
        raise ConfigError(
            f"llm.mode={settings.llm_mode!r} has no client. "
            "Use 'local' outside Dataiku, or import ai4bi_dataiku inside Dataiku."
        )
    return factory(settings)


def complete_json(
    llm: LlmClient,
    system_instruction: str,
    user_prompt: str,
    *,
    task: str,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask for a JSON object. Use ``fallback`` when the model is absent or unusable."""
    text = ""
    try:
        text = llm.complete(system_instruction, user_prompt)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("LLM call failed for task=%s: %s", task, exc)
        if fallback is None:
            raise LlmError(f"LLM call failed for task={task}: {exc}") from exc
    payload = extract_json(text)
    if payload:
        payload["_llm_provider"] = getattr(llm, "name", "llm")
        payload["_llm_task"] = task
        return payload
    if fallback is not None:
        out = dict(fallback)
        out["_llm_provider"] = "local_fallback"
        out["_llm_task"] = task
        return out
    raise LlmError(f"LLM did not return JSON for task={task}")
