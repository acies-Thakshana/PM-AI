"""Files the app produces for people to download, kept per session.

Two kinds only: the outlier-comparison (change log) Excel, and the finished report (.pptx).
  * S3_BUCKET set -- objects `users/<user id>/sessions/<session id>/<name>` in that bucket (the
    signed-in user's id, or `local` while sign-in is off), so a file outlives the backend task
    (a restart does not lose it), is not held in memory, and each user's files sit under their own
    prefix.
  * otherwise    -- plain files under data/sessions/<session id>/files/ (local development).

Storing never fails a request: a problem is logged and the caller simply serves the file it just
built. An S3 lifecycle rule on the `users/` prefix expires old files.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

from app.config import DATA_DIR, S3_BUCKET
from app.services.common.doc_store import safe_session_id

log = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-./]{1,200}$")
_LOCAL_DIR = DATA_DIR / "sessions"
_lock = threading.Lock()


def _name(name: str) -> str:
    if not _SAFE_NAME.match(name) or ".." in name or name.startswith("/"):
        raise ValueError(f"Invalid file name: {name!r}")
    return name


_SAFE_USER = re.compile(r"[^A-Za-z0-9_.@-]")


def _user() -> str:
    """The user the current request belongs to, made safe for use in an object key."""
    from app.services.common import request_context

    return _SAFE_USER.sub("_", request_context.user_id())[:128] or "local"


def _key(session_id: str, name: str) -> str:
    return f"users/{_user()}/sessions/{safe_session_id(session_id)}/{_name(name)}"


def _local_path(session_id: str, name: str) -> Path:
    return _LOCAL_DIR / safe_session_id(session_id) / "files" / _name(name)


def put(session_id: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> bool:
    """Store `data`; True if it was stored."""
    try:
        if S3_BUCKET:
            from app.services.common import aws_clients

            aws_clients.s3().put_object(Bucket=S3_BUCKET, Key=_key(session_id, name), Body=data, ContentType=content_type)
            return True
        path = _local_path(session_id, name)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return True
    except Exception as exc:  # noqa: BLE001 - serving the file matters more than keeping a copy
        log.warning("could not store %s for session %s: %s", name, session_id, exc)
        return False


def get(session_id: str, name: str) -> bytes | None:
    """The stored file, or None if there is none (or it could not be read)."""
    try:
        if S3_BUCKET:
            from app.services.common import aws_clients

            s3 = aws_clients.s3()
            try:
                return s3.get_object(Bucket=S3_BUCKET, Key=_key(session_id, name))["Body"].read()
            except s3.exceptions.NoSuchKey:
                return None
        path = _local_path(session_id, name)
        with _lock:
            return path.read_bytes() if path.is_file() else None
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read %s for session %s: %s", name, session_id, exc)
        return None


def delete(session_id: str, name: str) -> None:
    """Remove a stored file (no error if there is none)."""
    try:
        if S3_BUCKET:
            from app.services.common import aws_clients

            aws_clients.s3().delete_object(Bucket=S3_BUCKET, Key=_key(session_id, name))
            return
        path = _local_path(session_id, name)
        with _lock:
            path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not delete %s for session %s: %s", name, session_id, exc)
