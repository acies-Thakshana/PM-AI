"""Append-only audit trail: who asked what, which model answered, what was changed.

Locally events go to ``<data dir>/local/audit.jsonl``. On AWS they go to the audit DynamoDB table
(partition ``session_id``; sort ``ts_event`` = timestamp, event name and a random suffix, so two
events in the same millisecond never overwrite each other; a ``by_user`` index). Writing an audit
event must never fail the request that caused it, so ``record`` logs and swallows every error.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services.common import dynamo, request_context

LOGGER = logging.getLogger(__name__)

_file_lock = threading.Lock()
_MAX_FIELD_CHARS = 2000


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_FIELD_CHARS:
        return value[:_MAX_FIELD_CHARS] + "…"
    return value


def record(event: str, **fields: Any) -> None:
    """Record one event with the current request id, user and domain attached."""
    try:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        entry = {
            "ts": now.isoformat(timespec="milliseconds"),
            "event": event,
            "request_id": request_context.current_request_id.get() or "-",
            "user_id": request_context.current_user_id.get() or "anonymous",
            "domain": request_context.current_domain.get() or "-",
            "fields": {key: _clip(value) for key, value in fields.items()},
        }
        if settings.use_aws_storage:
            dynamo.put_item(
                settings.ddb_audit,
                {
                    "session_id": entry["request_id"],
                    "ts_event": f"{entry['ts']}#{event}#{uuid.uuid4().hex[:8]}",
                    "user_id": entry["user_id"],
                    "event": event,
                    "domain": entry["domain"],
                    "payload": json.dumps(entry["fields"], default=str),
                    "expires_at": dynamo.expiry(settings.audit_ttl_days),
                },
            )
        else:
            path = settings.local_state_root / "audit.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with _file_lock, path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
    except Exception:  # noqa: BLE001 - auditing is best effort by design
        LOGGER.warning("Could not write audit event %s", event, exc_info=True)
