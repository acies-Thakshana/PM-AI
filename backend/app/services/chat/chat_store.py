"""The chat's conversation record: one item per turn.

A turn is one PM message and everything that followed it until the next one: the messages (the PM's words,
the assistant's reply and the app's own short notes), what the assistant read, the actions it proposed and what
became of them, the suggestions it made and whether they were accepted. The detail of HOW the answer was made
(every LLM call, every tool call) is not kept here: it is in the audit log, tied to the turn by `chat_id` and
`turn_id` (see audit_log.log_event).

Two backends, chosen by config:

  * AWS   -- the DDB_CHATS table, partition `chat_id`, sort `turn_id` (a time-sortable id made by the browser,
             so the turns of a chat come back in order). Indexes `by-user` and `by-session` (both sorted by
             `started_at`). A turn that has no session yet simply has no `session_id` attribute.
  * local -- one JSON file per chat under data/chats/, so a laptop with no AWS resources keeps working.

A turn is written when the PM's message arrives (status "processing", so the message survives a crash), and
changed afterwards by small read-modify-write updates that never overwrite each other (the same optimistic idea
as doc_store.update). Every public write is best effort: a failure is logged and the chat goes on.
"""
from __future__ import annotations

import functools
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from app.config import CHAT_TTL_DAYS, DATA_DIR, DDB_CHATS

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"
#: Not stored: a turn still "processing" after this long is reported as abandoned (the server died or the tab closed).
ABANDONED = "abandoned"
ABANDON_AFTER = timedelta(minutes=15)

#: What an id made by the browser (or a path parameter) may look like. Ids become keys and file names.
ID_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"
_SAFE_ID = re.compile(ID_PATTERN)

#: Longest message kept whole. A longer one is cut and marked `truncated` (the brief itself is kept elsewhere).
MAX_MESSAGE_CHARS = 50_000

_CHATS_DIR = DATA_DIR / "chats"
_local_lock = threading.RLock()
_serializer = TypeSerializer()
_deserializer = TypeDeserializer()
_RETRIES = 5

Mutation = Callable[[dict], "bool | None"]


# ---------------------------------------------------------------------------------------------- small helpers
def is_safe_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_SAFE_ID.match(value))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _message(role: str, source: str, kind: str, content: Any) -> dict:
    """One message of a turn. `source` says who wrote it: "user", "model" (the assistant) or "app" (a note from the browser)."""
    text = content if isinstance(content, str) else str(content)
    message = {"role": role, "source": source, "kind": kind, "content": text[:MAX_MESSAGE_CHARS]}
    if len(text) > MAX_MESSAGE_CHARS:
        message["truncated"] = True
    return message


def _best_effort(fn: Callable[..., bool]) -> Callable[..., bool]:
    """A chat record must never break the chat: a failure is logged and the write reports False."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> bool:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - recording the conversation is never worth failing a request
            log.warning("chat store: %s failed: %s", fn.__name__, exc)
            return False

    return wrapper


def _plain(value: Any) -> Any:
    """DynamoDB hands numbers back as Decimal; turn them into int / float (recursively)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


# ------------------------------------------------------------------------------------------------ DynamoDB
def _to_ddb(item: dict) -> dict:
    """The item as the low-level client wants it. Floats are not allowed by DynamoDB, so they become Decimal."""
    safe = json.loads(json.dumps(item, default=str), parse_float=Decimal)
    return {name: _serializer.serialize(value) for name, value in safe.items()}


def _ddb_key(chat_id: str, turn_id: str) -> dict:
    return {"chat_id": {"S": chat_id}, "turn_id": {"S": turn_id}}


def _ddb_read(chat_id: str, turn_id: str) -> dict | None:
    from app.services.common import aws_clients

    resp = aws_clients.dynamodb().get_item(TableName=DDB_CHATS, Key=_ddb_key(chat_id, turn_id), ConsistentRead=True)
    raw = resp.get("Item")
    return _plain({k: _deserializer.deserialize(v) for k, v in raw.items()}) if raw else None


def _ddb_write(item: dict, expected_updated_at: str | None) -> bool:
    """Put the item. `expected_updated_at` None: only if the turn does not exist yet. Otherwise only if nobody
    changed it since it was read. False when that condition fails."""
    from app.services.common import aws_clients

    ddb = aws_clients.dynamodb()
    kwargs: dict[str, Any] = {}
    if expected_updated_at is None:
        kwargs["ConditionExpression"] = "attribute_not_exists(turn_id)"
    else:
        kwargs["ConditionExpression"] = "updated_at = :old"
        kwargs["ExpressionAttributeValues"] = {":old": {"S": expected_updated_at}}
    try:
        ddb.put_item(TableName=DDB_CHATS, Item=_to_ddb(item), **kwargs)
    except ddb.exceptions.ConditionalCheckFailedException:
        return False
    return True


def _ddb_query(chat_id: str) -> list[dict]:
    from app.services.common import aws_clients

    ddb = aws_clients.dynamodb()
    kwargs: dict[str, Any] = {
        "TableName": DDB_CHATS,
        "ConsistentRead": True,
        "KeyConditionExpression": "chat_id = :c",
        "ExpressionAttributeValues": {":c": {"S": chat_id}},
    }
    items: list[dict] = []
    while True:
        resp = ddb.query(**kwargs)
        items.extend(_plain({k: _deserializer.deserialize(v) for k, v in raw.items()}) for raw in resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


# ---------------------------------------------------------------------------------------------- local files
def _local_path(chat_id: str) -> Path:
    return _CHATS_DIR / f"{chat_id}.json"


def _local_turns(chat_id: str) -> dict[str, dict]:
    path = _local_path(chat_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("turns", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _local_save(chat_id: str, turns: dict[str, dict]) -> None:
    path = _local_path(chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"chat_id": chat_id, "turns": turns}, ensure_ascii=False, default=str), encoding="utf-8")


def _local_write(item: dict, expected_updated_at: str | None) -> bool:
    chat_id, turn_id = item["chat_id"], item["turn_id"]
    with _local_lock:
        turns = _local_turns(chat_id)
        current = turns.get(turn_id)
        if expected_updated_at is None:
            if current is not None:
                return False
        elif current is None or current.get("updated_at") != expected_updated_at:
            return False
        turns[turn_id] = json.loads(json.dumps(item, default=str))
        _local_save(chat_id, turns)
        return True


# --------------------------------------------------------------------------------------- backend-neutral core
def _read(chat_id: str, turn_id: str) -> dict | None:
    if DDB_CHATS:
        return _ddb_read(chat_id, turn_id)
    with _local_lock:
        item = _local_turns(chat_id).get(turn_id)
        return json.loads(json.dumps(item)) if item else None


def _write(item: dict, expected_updated_at: str | None) -> bool:
    return _ddb_write(item, expected_updated_at) if DDB_CHATS else _local_write(item, expected_updated_at)


def _modify(chat_id: str, turn_id: str, user_id: str, mutate: Mutation) -> bool:
    """Read the turn, let `mutate` change it, write it back only if nobody else changed it meanwhile (else try
    again on fresh data). `mutate` returning False means "nothing to change". Only the turn's owner may change it."""
    if not (is_safe_id(chat_id) and is_safe_id(turn_id)):
        return False
    for attempt in range(_RETRIES):
        item = _read(chat_id, turn_id)
        if item is None or item.get("user_id") != user_id:
            return False
        expected = item["updated_at"]
        if mutate(item) is False:
            return False
        item["updated_at"] = _now()
        if _write(item, expected):
            return True
        time.sleep(0.02 * (attempt + 1))
    log.warning("chat store: gave up changing %s/%s after %d attempts", chat_id, turn_id, _RETRIES)
    return False


def _present(item: dict) -> dict:
    """A stored turn as it is reported: one left "processing" for too long is shown as abandoned."""
    if item.get("status") == PROCESSING:
        try:
            started = datetime.strptime(item["started_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            return item
        if datetime.now(timezone.utc) - started > ABANDON_AFTER:
            return {**item, "status": ABANDONED}
    return item


# --------------------------------------------------------------------------------------------------- writes
@_best_effort
def start_turn(
    chat_id: str,
    turn_id: str,
    *,
    user_id: str,
    user_text: str,
    handled_by: str,
    session_id: str | None = None,
    page: str = "",
    phase: str = "",
    hidden: bool = False,
) -> bool:
    """Write the turn as soon as the PM's message is accepted. False if the turn already exists (a retry) or
    the ids are not usable; the existing turn is never overwritten."""
    if not (is_safe_id(chat_id) and is_safe_id(turn_id)):
        return False
    now = _now()
    item: dict[str, Any] = {
        "chat_id": chat_id,
        "turn_id": turn_id,
        "user_id": user_id,
        "handled_by": handled_by,
        "status": PROCESSING,
        "messages": [_message("user", "user", "hidden" if hidden else "text", user_text)],
        "started_at": now,
        "updated_at": now,
        "schema_version": SCHEMA_VERSION,
        "ttl": int(time.time()) + 86400 * CHAT_TTL_DAYS,
    }
    # Optional attributes are left out when unknown: an index key may not be empty, so no `session_id` at all.
    for name, value in (("session_id", session_id), ("page", page), ("phase", phase)):
        if value:
            item[name] = value
    return _write(item, None)


@_best_effort
def complete_turn(
    chat_id: str,
    turn_id: str,
    *,
    user_id: str,
    reply: str,
    intent: str,
    phase: str,
    reads: list[dict],
    actions: list[dict],
    next_questions: list[str],
    understanding: dict | None = None,
    assumptions: list[dict] | None = None,
) -> bool:
    """The assistant answered: keep its reply and what it read and proposed. `understanding` and `assumptions`
    are given only when this turn changed them."""

    def apply(item: dict) -> None:
        item["messages"].append(_message("assistant", "model", "text", reply))
        item.update(intent=intent, reads=reads, actions=actions, next_questions=next_questions)
        if phase:
            item["phase"] = phase
        if understanding is not None:
            item["understanding"] = understanding
        if assumptions is not None:
            item["assumptions"] = assumptions
        item["status"] = COMPLETED
        item["completed_at"] = _now()

    return _modify(chat_id, turn_id, user_id, apply)


@_best_effort
def fail_turn(chat_id: str, turn_id: str, *, user_id: str, error_code: str) -> bool:
    def apply(item: dict) -> None:
        item["status"] = FAILED
        item["error_code"] = error_code
        item["completed_at"] = _now()

    return _modify(chat_id, turn_id, user_id, apply)


@_best_effort
def finish_turn(
    chat_id: str,
    turn_id: str,
    *,
    user_id: str,
    status: str | None = None,
    error_code: str | None = None,
    notes: list[dict] | None = None,
    outcomes: list[dict] | None = None,
    app_actions: list[dict] | None = None,
    suggestions: list[dict] | None = None,
) -> bool:
    """What the browser adds after the reply: its own short notes, what became of each proposed action (by
    position), actions it took itself, and the suggestions it made. `status` only moves a turn that is still
    "processing" (a turn the browser answered itself); the server already settled the others."""

    def apply(item: dict) -> None:
        for note in notes or []:
            item["messages"].append(_message("assistant", "app", note.get("kind", "notice"), note.get("content", "")))
        actions = item.setdefault("actions", [])
        for outcome in outcomes or []:
            if 0 <= outcome.get("index", -1) < len(actions):
                target = actions[outcome["index"]]
                target["status"] = outcome["status"]
                target["executed_at"] = _now()
                if outcome.get("entry_id"):
                    target["entry_id"] = outcome["entry_id"]
        actions.extend({**action, "source": "app", "executed_at": _now()} for action in app_actions or [])
        known = {s.get("entry_id") for s in item.get("suggestions", [])}
        fresh = [{**s, "status": "pending"} for s in suggestions or [] if s.get("entry_id") not in known]
        if fresh:
            item.setdefault("suggestions", []).extend(fresh)
        if status and item.get("status") == PROCESSING:
            item["status"] = status
            item["completed_at"] = _now()
            if error_code:
                item["error_code"] = error_code

    return _modify(chat_id, turn_id, user_id, apply)


@_best_effort
def mark_suggestion(chat_id: str, turn_id: str, *, user_id: str, entry_id: str, status: str) -> bool:
    """The PM accepted or rejected a suggestion this turn made. False if the turn made no such suggestion."""

    def apply(item: dict) -> bool:
        for suggestion in item.get("suggestions", []):
            if suggestion.get("entry_id") == entry_id:
                suggestion["status"] = status
                suggestion["decided_at"] = _now()
                return True
        return False

    return _modify(chat_id, turn_id, user_id, apply)


# ---------------------------------------------------------------------------------------------------- reads
def get_turn(chat_id: str, turn_id: str) -> dict | None:
    """One turn, or None. Raises on a storage error (unlike the writes)."""
    if not (is_safe_id(chat_id) and is_safe_id(turn_id)):
        return None
    item = _read(chat_id, turn_id)
    return _present(item) if item else None


def list_turns(chat_id: str) -> list[dict]:
    """Every turn of a chat in order (oldest first). Raises on a storage error (unlike the writes)."""
    if not is_safe_id(chat_id):
        return []
    if DDB_CHATS:
        items = _ddb_query(chat_id)
    else:
        with _local_lock:
            items = list(_local_turns(chat_id).values())
    return [_present(item) for item in sorted(items, key=lambda i: i["turn_id"])]
