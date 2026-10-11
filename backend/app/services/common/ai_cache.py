"""Stored answers of AI calls that are cheap to keep and costly to repeat.

`get_or_make(session_id, doc, key_data, make)` returns the answer stored under a fingerprint of
`key_data` (whatever the answer was made from), and only calls `make()` -- the AI -- when there is
none yet. The same inputs therefore never run the agent a second time; a changed input (a new
analysis finished, a different selection) has a new fingerprint and runs it once. Answers are kept
in one document per session (`doc`), the newest MAX_KEPT of them.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from app.services.common import doc_store

MAX_KEPT = 10


def fingerprint(key_data: Any) -> str:
    return hashlib.sha1(doc_store.dumps(key_data).encode("utf-8")).hexdigest()


def get_or_make(session_id: str, doc: str, key_data: Any, make: Callable[[], Any]) -> Any:
    key = fingerprint(key_data)
    stored = doc_store.get(session_id, doc) or {}
    answers = stored.get("answers") if isinstance(stored, dict) else None
    if isinstance(answers, dict) and key in answers:
        return answers[key]

    value = make()  # may raise: nothing is stored then

    def add(current: Any) -> Any:
        data = current if isinstance(current, dict) else {}
        kept = dict(data.get("answers") or {})
        kept.pop(key, None)
        kept[key] = value  # newest last
        while len(kept) > MAX_KEPT:
            kept.pop(next(iter(kept)))
        return {"answers": kept}

    doc_store.update(session_id, doc, add, default={})
    return value
