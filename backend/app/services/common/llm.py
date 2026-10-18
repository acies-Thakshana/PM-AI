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

# AWS-DISABLED: from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings
from app.errors import LlmError
from app.services.common import prompt_files, token_usage  # AWS-DISABLED: aws_clients
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


# AWS-DISABLED: class BedrockClient:
# AWS-DISABLED:     """Bedrock Converse. Stateless apart from the shared boto3 client."""

# AWS-DISABLED:     name = "bedrock"

# AWS-DISABLED:     def __init__(self, settings: Settings) -> None:
# AWS-DISABLED:         self._settings = settings

# AWS-DISABLED:     def complete(self, call_name: str, system_prompt: str, user_prompt: str) -> str:
# AWS-DISABLED:         model = self._settings.model_for(call_name)
# AWS-DISABLED:         if not model:
# AWS-DISABLED:             raise LlmError(f"No Bedrock model is configured for {call_name}. Set BEDROCK_DEFAULT_MODEL.")
# AWS-DISABLED:         started = time.monotonic()
# AWS-DISABLED:         response = self._converse(model, system_prompt, user_prompt, with_temperature=True)

# AWS-DISABLED:         stop_reason = response.get("stopReason", "")
# AWS-DISABLED:         if stop_reason in {"content_filtered", "guardrail_intervened"}:
# AWS-DISABLED:             raise LlmError(f"Bedrock blocked the response for {call_name} ({stop_reason}).")
# AWS-DISABLED:         usage = response.get("usage") or {}
# AWS-DISABLED:         token_usage.record(
# AWS-DISABLED:             call_name,
# AWS-DISABLED:             model,
# AWS-DISABLED:             input_tokens=int(usage.get("inputTokens", 0)),
# AWS-DISABLED:             output_tokens=int(usage.get("outputTokens", 0)),
# AWS-DISABLED:             latency_ms=int((time.monotonic() - started) * 1000),
# AWS-DISABLED:         )
# AWS-DISABLED:         blocks = (response.get("output") or {}).get("message", {}).get("content") or []
# AWS-DISABLED:         return "".join(block.get("text", "") for block in blocks)

# AWS-DISABLED:     def _converse(self, model: str, system_prompt: str, user_prompt: str, *, with_temperature: bool) -> dict[str, Any]:
# AWS-DISABLED:         inference: dict[str, Any] = {"maxTokens": self._settings.llm_max_tokens}
# AWS-DISABLED:         if with_temperature:
# AWS-DISABLED:             inference["temperature"] = self._settings.llm_temperature
# AWS-DISABLED:         try:
# AWS-DISABLED:             return aws_clients.bedrock_runtime().converse(
# AWS-DISABLED:                 modelId=model,
# AWS-DISABLED:                 system=[{"text": system_prompt}],
# AWS-DISABLED:                 messages=[{"role": "user", "content": [{"text": user_prompt}]}],
# AWS-DISABLED:                 inferenceConfig=inference,
# AWS-DISABLED:             )
# AWS-DISABLED:         except ClientError as exc:
# AWS-DISABLED:             error = exc.response.get("Error", {})
# AWS-DISABLED:             # Some newer models reject an explicit temperature. Retry once without it.
# AWS-DISABLED:             if (
# AWS-DISABLED:                 with_temperature
# AWS-DISABLED:                 and error.get("Code") == "ValidationException"
# AWS-DISABLED:                 and "temperature" in str(error.get("Message", "")).lower()
# AWS-DISABLED:             ):
# AWS-DISABLED:                 LOGGER.info("Model %s rejects temperature; retrying without it", model)
# AWS-DISABLED:                 return self._converse(model, system_prompt, user_prompt, with_temperature=False)
# AWS-DISABLED:             raise LlmError(f"Bedrock call failed ({error.get('Code', 'error')}): {error.get('Message', exc)}") from exc
# AWS-DISABLED:         except BotoCoreError as exc:
# AWS-DISABLED:             raise LlmError(f"Bedrock call failed: {exc}") from exc


def get_llm_client(settings: Settings) -> LlmClient:
    # AWS-DISABLED: return BedrockClient(settings) if settings.llm_mode == "bedrock" else LocalFallbackClient()
    return LocalFallbackClient()


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
