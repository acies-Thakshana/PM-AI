"""The one LLM client: Amazon Bedrock, via the Converse API.

Every LLM call in the app -- Planner, Feature Agent, Analysis Agent, Drilldown, Audit,
Overall Analysis, Report summary -- goes through `chat_text` / `chat_json` here. Converse
gives one request/response shape for every Bedrock model, so swapping a model is just
changing the id in config.MODEL_BY_CALL (or a `MODEL_<CALL_NAME>` env var).

Compared with the OpenAI-style client this replaces:
  * there is no `response_format=json_object` mode, so JSON-returning prompts rely on the
    prompt text plus `strip_json_fence` (models often wrap JSON in ```json fences);
  * usage comes back as `usage.inputTokens / outputTokens / totalTokens`.

Prompts: `system_prompt(name, fallback, **vars)` returns the Bedrock Prompt Management text
for `name` when one is configured (BEDROCK_PROMPT_IDS), else `fallback` -- the text that
lives in the source. Any lookup failure also falls back, so a Prompt Management outage can
never take the app down.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

from app.config import (
    BEDROCK_PROMPT_IDS,
    DEFAULT_MAX_TOKENS,
    LLM_MODEL,
    NOVA_MAX_OUTPUT_TOKENS,
    GROQ_API_KEY,
    GROQ_MODEL,
    PROMPT_CACHE_SECONDS,
    PROMPTS_BEDROCK_ONLY,
    model_for,
    uses_groq,
)
from app.services.common import aws_clients, prompt_files, token_usage

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- fences
_JSON_FENCE = re.compile(r"^```[a-zA-Z]*\s*(.*?)\s*```$", re.DOTALL)
_CODE_FENCE = re.compile(r"^```[a-zA-Z0-9_+-]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)


_ANY_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\s*(.*?)```", re.DOTALL)


def strip_json_fence(text: str) -> str:
    """Models such as Claude often wrap JSON in ```json fences -- and sometimes add a sentence
    before or after it ("Here is the plan: ..."). Return the bare JSON in all of those cases;
    text that is not recognisably JSON is returned unchanged (the caller's json.loads reports it)."""
    t = (text or "").strip()
    m = _JSON_FENCE.match(t)
    if m:
        return m.group(1).strip()
    if t[:1] in ("{", "["):
        try:
            json.loads(t)
            return t
        except ValueError:
            pass
    for block in _ANY_FENCE.findall(t):  # a fenced block with prose around it
        block = block.strip()
        if block[:1] in ("{", "["):
            return block
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if starts:  # unfenced JSON with prose around it: first opener .. last matching closer
        start = min(starts)
        end = t.rfind("}" if t[start] == "{" else "]")
        if end > start:
            candidate = t[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except ValueError:
                pass
    return t


def strip_code_fence(text: str) -> str:
    """Same for code answers (```python ... ```), including a fenced block surrounded by prose."""
    t = (text or "").strip()
    m = _CODE_FENCE.match(t)
    if m:
        return m.group(1).strip()
    m = _ANY_FENCE.search(t)
    return m.group(1).strip() if m else t


# --------------------------------------------------------------------------- Converse
# Models that rejected a temperature setting (filled in at runtime; see _converse).
_NO_TEMPERATURE: set[str] = set()


class LLMError(RuntimeError):
    """The model call succeeded at the API level but its answer is unusable (blocked by a
    content filter / guardrail, or cut off mid-JSON)."""


def _groq(system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, call_name: str) -> tuple[str, str | None]:
    """One Groq chat-completions call (OpenAI-compatible). Returns (text, stopReason) like _converse."""
    import requests

    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # The free tier limits tokens per minute and says how long to wait ("try again in 21.4s"): wait that
    # long and retry rather than failing the step.
    for attempt in range(4):
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json=body,
            timeout=120,
        )
        if response.status_code != 429 or attempt == 3:
            break
        found = re.search(r"try again in ([0-9.]+)s", response.text)
        wait = float(found.group(1)) + 1 if found else float(response.headers.get("retry-after") or 10)
        log.warning("%s: Groq rate limit, retrying in %.0fs", call_name, min(wait, 60))
        time.sleep(min(wait, 60))
    if response.status_code != 200:
        raise LLMError(f"{call_name}: Groq returned {response.status_code}: {response.text[:300]}")
    data = response.json()
    usage = data.get("usage") or {}
    token_usage.record(call_name, GROQ_MODEL, {
        "inputTokens": usage.get("prompt_tokens", 0), "outputTokens": usage.get("completion_tokens", 0),
        "totalTokens": usage.get("total_tokens", 0),
    })
    choice = (data.get("choices") or [{}])[0]
    stop = "max_tokens" if choice.get("finish_reason") == "length" else choice.get("finish_reason")
    return (choice.get("message") or {}).get("content") or "", stop


def _converse(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    call_name: str,
) -> tuple[str, str | None]:
    """One Converse call. Returns (text, stopReason)."""
    if uses_groq(call_name):
        return _groq(system_prompt, user_prompt, temperature, max_tokens, call_name)
    if "amazon.nova" in model:
        max_tokens = min(max_tokens, NOVA_MAX_OUTPUT_TOKENS)  # Nova rejects longer answers
    client = aws_clients.bedrock_runtime()
    inference: dict = {"maxTokens": max_tokens}
    if model not in _NO_TEMPERATURE:
        inference["temperature"] = temperature
    request = dict(
        modelId=model,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig=inference,
    )
    try:
        response = client.converse(**request)
    except Exception as exc:  # noqa: BLE001 - inspected below, re-raised unless it is the temperature case
        # Some reasoning models (e.g. OpenAI's) accept only their default temperature and reject
        # the field. Remember that for the model and retry once without it.
        if "temperature" in inference and "temperature" in str(exc).lower() and "validation" in str(exc).lower():
            log.warning("%s rejects the temperature setting; retrying without it", model)
            _NO_TEMPERATURE.add(model)
            inference.pop("temperature")
            response = client.converse(**request)
        else:
            raise
    token_usage.record(call_name, model, response.get("usage"))
    stop = response.get("stopReason")
    if stop in ("content_filtered", "guardrail_intervened"):
        raise LLMError(f"{call_name}: the model's answer was blocked ({stop}).")
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    return "".join(b.get("text", "") for b in blocks if "text" in b), stop


_NO_ANSWER = (
    "{call}: the model used all {limit} output tokens before it wrote an answer "
    "(reasoning models spend tokens thinking). Raise LLM_MAX_TOKENS."
)


def _limit(max_tokens: int | None) -> int:
    """The output limit for a call: LLM_MAX_TOKENS is a floor, so raising it always takes effect,
    even for calls that ask for a smaller number of their own."""
    return max(max_tokens or 0, DEFAULT_MAX_TOKENS)


def chat_text(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    call_name: str = "unnamed_chat_text",
    max_tokens: int | None = None,
) -> str:
    """Single-shot call returning plain prose (or code -- strip it with strip_code_fence)."""
    model = model or model_for(call_name, LLM_MODEL)
    limit = _limit(max_tokens)
    text, stop = _converse(system_prompt, user_prompt, model, temperature, limit, call_name)
    if stop == "max_tokens":
        if not (text or "").strip():
            raise LLMError(_NO_ANSWER.format(call=call_name, limit=limit))
        log.warning("%s: answer cut off at max_tokens (%s); raise LLM_MAX_TOKENS if this recurs", call_name, limit)
    return text


def chat_json(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.4,
    call_name: str = "unnamed_chat_json",
    max_tokens: int | None = None,
) -> str:
    """Single-shot call expecting a JSON object. Returns the JSON text with any code fence
    removed ("{}" if the model said nothing); the caller does `json.loads`. Raises LLMError
    when the answer was cut off at max_tokens and is no longer valid JSON, so a truncated
    answer is reported instead of being mistaken for an empty result."""
    model = model or model_for(call_name, LLM_MODEL)
    limit = _limit(max_tokens)
    text, stop = _converse(system_prompt, user_prompt, model, temperature, limit, call_name)
    if stop == "max_tokens" and not (text or "").strip():
        # A reasoning model can spend every token thinking and answer nothing. That must not
        # pass for an empty result ("{}"): the caller would show "0 suggestions".
        raise LLMError(_NO_ANSWER.format(call=call_name, limit=limit))
    cleaned = strip_json_fence(text or "{}")
    if stop == "max_tokens":
        try:
            json.loads(cleaned)
        except ValueError as exc:
            raise LLMError(
                f"{call_name}: the answer was cut off at {limit} tokens (raise LLM_MAX_TOKENS)."
            ) from exc
    return cleaned


# --------------------------------------------------------------------------- prompts
_prompt_lock = threading.Lock()
_prompt_cache: dict[str, tuple[float, str | None]] = {}
_prompt_ids: dict[str, str] | None = None


def _configured_prompts() -> dict[str, str]:
    global _prompt_ids
    if _prompt_ids is None:
        try:
            parsed = json.loads(BEDROCK_PROMPT_IDS) if BEDROCK_PROMPT_IDS.strip() else {}
            _prompt_ids = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            log.warning("BEDROCK_PROMPT_IDS is not valid JSON; using in-source prompts")
            _prompt_ids = {}
    return _prompt_ids


def _fetch_prompt_text(identifier: str) -> str | None:
    """Fetch a Prompt Management prompt ("<ID>" or "<ID>:<VERSION>") and return its text."""
    prompt_id, _, version = identifier.partition(":")
    kwargs = {"promptIdentifier": prompt_id}
    if version:
        kwargs["promptVersion"] = version
    resp = aws_clients.bedrock_agent().get_prompt(**kwargs)
    variants = resp.get("variants") or []
    if not variants:
        return None
    cfg = variants[0].get("templateConfiguration", {})
    if "text" in cfg:
        return cfg["text"].get("text")
    if "chat" in cfg:
        system = cfg["chat"].get("system") or []
        return "\n".join(s.get("text", "") for s in system if "text" in s) or None
    return None


class PromptNotFound(LLMError):
    """No system prompt could be found for a call (not in Bedrock, and no local file)."""


def _bedrock_prompt(name: str) -> str | None:
    """The prompt text from Prompt Management, or None if `name` is not configured or the
    lookup failed (cached for PROMPT_CACHE_SECONDS; a failed lookup only briefly)."""
    identifier = _configured_prompts().get(name)
    if not identifier:
        return None
    now = time.time()
    with _prompt_lock:
        cached = _prompt_cache.get(name)
    if cached and now - cached[0] < PROMPT_CACHE_SECONDS:
        return cached[1]
    failed = False
    try:
        text = _fetch_prompt_text(identifier)
    except Exception as exc:  # noqa: BLE001
        log.warning("Prompt Management lookup for %s failed: %s", name, exc)
        text = None
        failed = True
    with _prompt_lock:
        # A failed lookup is only remembered briefly, so a transient error does not pin the
        # fallback for the whole cache period.
        _prompt_cache[name] = (now - PROMPT_CACHE_SECONDS + 30 if failed else now, text)
    return text


def _fill(text: str, variables: dict) -> str:
    if not variables:
        return text
    # One pass, so a substituted value that itself contains "{{other}}" is left alone.
    return re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: str(variables[m.group(1)]) if m.group(1) in variables else m.group(0),
        text,
    )


def system_prompt(name: str, fallback: str | None = None, **variables: object) -> str:
    """The system prompt for the call `name`, with `{{variable}}` placeholders filled from
    `variables`.

    Order: Amazon Bedrock Prompt Management (when `name` is in BEDROCK_PROMPT_IDS) -> `fallback`
    if the caller gave one -> backend/prompts/<name>.txt. With PROMPTS_BEDROCK_ONLY=1 only
    Bedrock counts. If none has it, PromptNotFound says what to set.
    """
    text = _bedrock_prompt(name)
    if not text and not PROMPTS_BEDROCK_ONLY:
        text = fallback or prompt_files.load(name)
    if not text:
        configured = name in _configured_prompts()
        raise PromptNotFound(
            f"No system prompt for '{name}': "
            + (
                "Bedrock Prompt Management could not be read for it (check the id/version in "
                "BEDROCK_PROMPT_IDS and the task role's bedrock:GetPrompt)."
                if configured
                else "add it to BEDROCK_PROMPT_IDS (create the prompts with "
                "`python scripts/bedrock_prompts.py create`)."
            )
        )
    return _fill(text, variables)
