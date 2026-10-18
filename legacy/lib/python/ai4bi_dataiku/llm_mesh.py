"""Dataiku LLM Mesh client implementing ``ai4bi.llm.client.LlmClient``."""

from __future__ import annotations

from typing import Any

from ai4bi.config.errors import ConfigError, LlmError
from ai4bi.config.settings import Settings
from ai4bi.logging import get_logger

LOGGER = get_logger(__name__)
PREFERRED_MODEL_HINT = "opus"


def _default_project() -> Any:
    import dataiku

    return dataiku.api_client().get_default_project()


def list_llm_ids(project: Any) -> list[str]:
    found: list[str] = []
    for method in ("list_llms", "list_available_llms"):
        fn = getattr(project, method, None)
        if not callable(fn):
            continue
        try:
            for item in fn() or []:
                if isinstance(item, str):
                    found.append(item)
                elif isinstance(item, dict):
                    found.append(str(item.get("id") or item.get("llmId") or item.get("name") or ""))
                else:
                    found.append(str(getattr(item, "id", "") or ""))
            break
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not list LLMs via %s: %s", method, exc)
    return [item for item in found if item]


def resolve_llm_id(connection: str = "", project: Any | None = None) -> str:
    """The configured connection, otherwise the first Opus connection in the project."""
    if connection:
        return connection
    available = list_llm_ids(project or _default_project())
    preferred = [item for item in available if PREFERRED_MODEL_HINT in item.lower()]
    if not preferred:
        raise ConfigError(
            f"No Opus LLM Mesh connection found. Set project variable AIBI_LLM_CONNECTION. Available: {available}"
        )
    return preferred[0]


class DataikuMeshClient:
    def __init__(self, llm_id: str, *, temperature: float = 0.0, project: Any | None = None) -> None:
        self.name = llm_id
        self.temperature = temperature
        self._project = project
        self._llm: Any | None = None

    def _handle(self) -> Any:
        if self._llm is None:
            project = self._project or _default_project()
            self._llm = project.get_llm(self.name)
        return self._llm

    def complete(self, system_instruction: str, user_prompt: str) -> str:
        completion = self._handle().new_completion()
        if system_instruction:
            completion.with_message(system_instruction, role="system")
        completion.with_message(user_prompt, role="user")
        settings = getattr(completion, "settings", None)
        if isinstance(settings, dict):
            settings["temperature"] = self.temperature
        response = completion.execute()
        if getattr(response, "success", True) is False:
            raise LlmError(f"LLM Mesh call failed: {getattr(response, 'errorMessage', '') or 'no detail'}")
        return str(getattr(response, "text", "") or "")


def mesh_client_factory(settings: Settings) -> DataikuMeshClient:
    llm_id = resolve_llm_id(settings.llm_connection)
    LOGGER.info("LLM Mesh connection: %s", llm_id)
    return DataikuMeshClient(llm_id, temperature=settings.llm_temperature)
