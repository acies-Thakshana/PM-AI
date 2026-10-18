"""System prompts for the LLM calls.

Each call has a prompt file, ``prompts/<call name>.txt``, kept in git so changes are reviewed like
code. When ``BEDROCK_PROMPT_IDS`` maps a call name to a Bedrock Prompt Management prompt, the
managed text wins and prompts can change without a deploy; if Bedrock cannot be reached the file
is used, so a Prompt Management outage never takes the service down.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import cache

from app.config import get_settings
from app.errors import ConfigError
# AWS-DISABLED: from app.services.common import aws_clients

LOGGER = logging.getLogger(__name__)

_managed_lock = threading.Lock()
_managed_cache: dict[str, tuple[float, str]] = {}


@cache
def read_prompt_file(name: str) -> str:
    """The text of ``prompts/<name>.txt``. Cached for the life of the process."""
    path = get_settings().prompts_dir / f"{name}.txt"
    if not path.is_file():
        raise ConfigError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


# AWS-DISABLED: Bedrock Prompt Management lookup.
# def _managed_prompt(prompt_id: str) -> str:
#     response = aws_clients.bedrock_agent().get_prompt(promptIdentifier=prompt_id)
#     variants = response.get("variants") or []
#     text = ((variants[0].get("templateConfiguration") or {}).get("text") or {}).get("text") if variants else None
#     if not text or not text.strip():
#         raise ValueError(f"prompt {prompt_id} has no text variant")
#     return text.strip()


def resolve_prompt(name: str) -> str:
    """The system prompt for one call: managed text when configured, else the file."""
    settings = get_settings()
    # AWS-DISABLED: managed prompts. Prompts always come from prompts/<name>.txt while AWS is off.
    return read_prompt_file(name)
    prompt_id = settings.bedrock_prompt_ids.get(name)  # unreachable until re-enabled
    if not prompt_id or settings.llm_mode != "bedrock":
        return read_prompt_file(name)

    now = time.monotonic()
    with _managed_lock:
        cached = _managed_cache.get(name)
    if cached and now - cached[0] < settings.prompt_cache_seconds:
        return cached[1]
    try:
        text = _managed_prompt(prompt_id)
    except Exception as exc:  # noqa: BLE001 - any failure falls back to the file
        LOGGER.warning("Prompt Management lookup failed for %s (%s); using prompts/%s.txt", name, exc, name)
        return cached[1] if cached else read_prompt_file(name)
    with _managed_lock:
        _managed_cache[name] = (now, text)
    return text


def clear_cache() -> None:
    """Forget cached prompts. Used by tests."""
    read_prompt_file.cache_clear()
    with _managed_lock:
        _managed_cache.clear()
