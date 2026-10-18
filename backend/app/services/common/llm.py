"""Model access. The pipeline depends only on ``LlmClient`` and ``complete_json``.

Two clients exist:

* ``BedrockClient`` calls the Bedrock Converse API. The model comes from the call name
  (``Settings.model_for``) and the system prompt from ``prompt_files.resolve_prompt``.
* ``LocalFallbackClient`` returns no text, so every caller uses its deterministic fallback. It is
  what runs on a laptop without AWS access and in tests.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol, runtime_checkable

from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings
from app.errors import LlmError
from app.services.common import aws_clients, prompt_files, token_usage
from app.services.common.text import extract_json

LOGGER = logging.getLogger(__name__)

LOCAL_PROVIDER = "local_fallback"


@runtime_checkable
class LlmClient(Protocol):
    name: str

    def complete(self, call_name: str, system_prompt: str, user_prompt: str) -> str:
        """Return the model's text for one named call."""
        ...


class LocalFallbackClient:
    name = LOCAL_PROVIDER

    def complete(self, call_name: str, system_prompt: str, user_prompt: str) -> str:
        return ""


class BedrockClient:
    """Bedrock Converse. Stateless apart from the shared boto3 client."""

    name = "bedrock"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def complete(self, call_name: str, system_prompt: str, user_prompt: str) -> str:
        model = self._settings.model_for(call_name)
        if not model:
            raise LlmError(f"No Bedrock model is configured for {call_name}. Set BEDROCK_DEFAULT_MODEL.")
        started = time.monotonic()
        response = self._converse(model, system_prompt, user_prompt, with_temperature=True)

        stop_reason = response.get("stopReason", "")
        if stop_reason in {"content_filtered", "guardrail_intervened"}:
            raise LlmError(f"Bedrock blocked the response for {call_name} ({stop_reason}).")
        usage = response.get("usage") or {}
        token_usage.record(
            call_name,
            model,
            input_tokens=int(usage.get("inputTokens", 0)),
            output_tokens=int(usage.get("outputTokens", 0)),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        blocks = (response.get("output") or {}).get("message", {}).get("content") or []
        return "".join(block.get("text", "") for block in blocks)

    def _converse(self, model: str, system_prompt: str, user_prompt: str, *, with_temperature: bool) -> dict[str, Any]:
        inference: dict[str, Any] = {"maxTokens": self._settings.llm_max_tokens}
        if with_temperature:
            inference["temperature"] = self._settings.llm_temperature
        try:
            return aws_clients.bedrock_runtime().converse(
                modelId=model,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig=inference,
            )
        except ClientError as exc:
            error = exc.response.get("Error", {})
            # Some newer models reject an explicit temperature. Retry once without it.
            if (
                with_temperature
                and error.get("Code") == "ValidationException"
                and "temperature" in str(error.get("Message", "")).lower()
            ):
                LOGGER.info("Model %s rejects temperature; retrying without it", model)
                return self._converse(model, system_prompt, user_prompt, with_temperature=False)
            raise LlmError(f"Bedrock call failed ({error.get('Code', 'error')}): {error.get('Message', exc)}") from exc
        except BotoCoreError as exc:
            raise LlmError(f"Bedrock call failed: {exc}") from exc


def get_llm_client(settings: Settings) -> LlmClient:
    return BedrockClient(settings) if settings.llm_mode == "bedrock" else LocalFallbackClient()


def complete_json(
    llm: LlmClient,
    call_name: str,
    user_prompt: str,
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask for a JSON object. Use ``fallback`` when the model is absent or unusable.

    The result carries ``_llm_provider`` (``bedrock`` or ``local_fallback``) so callers can say
    honestly which path produced it.
    """
    text = ""
    try:
        text = llm.complete(call_name, prompt_files.resolve_prompt(call_name), user_prompt)
    except LlmError as exc:
        LOGGER.warning("LLM call %s failed: %s", call_name, exc)
        if fallback is None:
            raise
    payload = extract_json(text)
    if payload:
        payload["_llm_provider"] = llm.name
        payload["_llm_task"] = call_name
        return payload
    if fallback is not None:
        if text:
            LOGGER.warning("LLM call %s returned no usable JSON; using the deterministic fallback", call_name)
        return {**fallback, "_llm_provider": LOCAL_PROVIDER, "_llm_task": call_name}
    raise LlmError(f"The model did not return JSON for {call_name}.")
