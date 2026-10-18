"""Record what each model call cost in tokens, to the log and the audit trail."""

from __future__ import annotations

import logging

from app.services.common import audit_log

LOGGER = logging.getLogger(__name__)


def record(call_name: str, model: str, *, input_tokens: int, output_tokens: int, latency_ms: int) -> None:
    LOGGER.info(
        "llm call=%s model=%s input_tokens=%d output_tokens=%d latency_ms=%d",
        call_name,
        model,
        input_tokens,
        output_tokens,
        latency_ms,
    )
    audit_log.record(
        "llm_call",
        call=call_name,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )
