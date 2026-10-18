"""Small text helpers shared across modules."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
        "you", "your", "what", "which", "how", "is", "of", "in", "on", "by", "to",
        "a", "an", "me", "show", "give", "tell", "per", "our", "we", "all", "do",
        "does", "did", "be", "it", "its", "as", "at", "or", "can", "please",
    }
)


def slug(text: str, limit: int = 80) -> str:
    keep: list[str] = []
    for ch in (text or "").lower():
        if ch.isalnum():
            keep.append(ch)
        elif keep and keep[-1] != "_":
            keep.append("_")
    return "".join(keep).strip("_")[:limit]


def norm_key(text: Any) -> str:
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def content_tokens(text: str) -> set[str]:
    return {t for t in tokens(text) if len(t) > 2 and t not in STOPWORDS}


def overlap_score(question: str, blob: str) -> int:
    words = content_tokens(question)
    lowered = (blob or "").lower()
    return sum(1 for word in words if word in lowered)


def phrase_in(text: str, phrase: str) -> bool:
    phrase = (phrase or "").strip().lower()
    if not phrase:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", (text or "").lower()) is not None


def stable_id(prefix: str, text: str, length: int = 12) -> str:
    return f"{prefix}." + hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:length]


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply."""
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except ValueError:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else {}
    except ValueError:
        return {}


def quote_ident(name: str) -> str:
    raw = str(name or "").strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", raw):
        return raw
    return '"' + raw.replace('"', '""') + '"'


def sql_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"
