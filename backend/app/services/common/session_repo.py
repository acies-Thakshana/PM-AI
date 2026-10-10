"""Persistence for an audit session: the small header (DynamoDB) and its DataFrames (memory).

  header  -- JSON: owner, filename, features, audit events, which frames exist, ...
             DynamoDB table DDB_DOCS, item `SESSIONS`.
  frames  -- the pandas DataFrames (`df`, `pre_feature_df`, `audit_baseline`, `raw_df`, `change_log`).
             There is no S3:
             in DynamoDB mode they live in this process's memory only, so a restart (or a
             request served by another task) loses them and `FramesUnavailable` is raised; the
             API answers 410 and the user uploads the file again. Run ONE task, or turn on ALB
             stickiness, so a session's requests reach the task that holds its data.

Without AWS configured (local dev) the frames are files under data/sessions/<id>/, written as
parquet when the frame round-trips cleanly, else pickled (the header records which).
"""
from __future__ import annotations

import io
import json
import threading
from typing import Any

import pandas as pd

from app.config import DATA_DIR, DDB_DOCS, MEMORY_FRAME_SESSIONS, USE_AWS_STORAGE
from app.services.common.doc_store import (
    ANY,
    VersionConflict,
    blob_get,
    blob_put,
    dumps,
    safe_session_id,
)

_SESSIONS_DIR = DATA_DIR / "sessions"
_local_lock = threading.RLock()

# The header is one item of the docs table, next to the session's other records.
HEADER_DOC = "SESSIONS"


def _header_key(sid: str) -> dict[str, str]:
    return {"session_id": sid, "doc": HEADER_DOC}


# --------------------------------------------------------------------------- header
def load_header(session_id: str) -> tuple[dict | None, int | None]:
    """(header dict, version) or (None, None) if the session does not exist."""
    sid = safe_session_id(session_id)
    if USE_AWS_STORAGE:
        return blob_get(DDB_DOCS, _header_key(sid))
    path = _SESSIONS_DIR / sid / "session.json"
    with _local_lock:
        if not path.exists():
            return None, None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, None
    return wrapper["data"], int(wrapper.get("version", 1))


def save_header(session_id: str, header: dict, *, expected_version: Any = ANY) -> int:
    """Write the header; returns the new version. Raises VersionConflict if
    `expected_version` is given and the stored header has moved on."""
    sid = safe_session_id(session_id)
    if USE_AWS_STORAGE:
        return blob_put(
            DDB_DOCS,
            _header_key(sid),
            header,
            expected_version=expected_version,
            extra={"user_id": str(header.get("user_id", ""))} if header.get("user_id") else None,
        )
    path = _SESSIONS_DIR / sid / "session.json"
    with _local_lock:
        current = 0
        if path.exists():
            try:
                current = int(json.loads(path.read_text(encoding="utf-8")).get("version", 1))
            except (OSError, json.JSONDecodeError):
                current = 0
        if expected_version is not ANY and expected_version != current:
            raise VersionConflict(f"session {sid} changed since it was read")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps({"version": current + 1, "data": header}), encoding="utf-8")
        return current + 1


# --------------------------------------------------------------------------- frames
class FramesUnavailable(Exception):
    """A session's DataFrame is no longer in this process's memory (the app restarted, the
    session fell out of the memory limit, or another task served the upload). The API turns
    this into HTTP 410: the user uploads the file again."""


# DynamoDB mode keeps DataFrames in memory only: {session_id: {frame name: DataFrame}}. The dict
# order is the order of last use, so when more than MEMORY_FRAME_SESSIONS sessions are held the
# first (least recently used) ones are dropped. A frame is copied on the way in and out, so a
# change made to a loaded frame is only kept once the session is saved again.
_mem_lock = threading.RLock()
_mem_frames: dict[str, dict[str, pd.DataFrame]] = {}


def _mem_put(session_id: str, name: str, df: pd.DataFrame) -> None:
    with _mem_lock:
        frames = _mem_frames.pop(session_id, {})
        frames[name] = df.copy()
        _mem_frames[session_id] = frames
        while len(_mem_frames) > max(MEMORY_FRAME_SESSIONS, 1):
            del _mem_frames[next(iter(_mem_frames))]


def _mem_get(session_id: str, name: str) -> pd.DataFrame:
    with _mem_lock:
        frames = _mem_frames.pop(session_id, None)
        if frames is not None:
            _mem_frames[session_id] = frames  # most recently used
        if not frames or name not in frames:
            raise FramesUnavailable(
                "The data of this session is no longer in memory (the server restarted or the session was "
                "moved out). Please upload the file again."
            )
        return frames[name].copy()


def _mem_delete(session_id: str, name: str) -> None:
    with _mem_lock:
        frames = _mem_frames.get(session_id)
        if frames:
            frames.pop(name, None)
            if not frames:
                del _mem_frames[session_id]


def _local_name(name: str, fmt: str) -> str:
    return f"{name}.{'parquet' if fmt == 'parquet' else 'pkl'}"


def _to_bytes(df: pd.DataFrame) -> tuple[bytes, str]:
    """Serialize to parquet if it round-trips cleanly, else to pickle."""
    try:
        buf = io.BytesIO()
        df.to_parquet(buf, engine="pyarrow")
        return buf.getvalue(), "parquet"
    except Exception:
        buf = io.BytesIO()
        df.to_pickle(buf)
        return buf.getvalue(), "pickle"


def _from_bytes(raw: bytes, fmt: str) -> pd.DataFrame:
    if fmt == "parquet":
        return pd.read_parquet(io.BytesIO(raw), engine="pyarrow")
    return pd.read_pickle(io.BytesIO(raw))


def save_frame(session_id: str, name: str, df: pd.DataFrame) -> dict:
    """Store one DataFrame and return its reference, `{"fmt": ..., "rows": ...}`, which the
    caller keeps in the session header. DynamoDB mode: in memory (fmt "memory"). Local mode:
    a file under data/sessions/<id>/."""
    safe_session_id(session_id)
    if USE_AWS_STORAGE:
        _mem_put(session_id, name, df)
        return {"fmt": "memory", "rows": int(len(df))}
    raw, fmt = _to_bytes(df)
    folder = _SESSIONS_DIR / safe_session_id(session_id)
    with _local_lock:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / _local_name(name, fmt)).write_bytes(raw)
        # A frame that switched format leaves the other file behind; remove it.
        (folder / _local_name(name, "pickle" if fmt == "parquet" else "parquet")).unlink(missing_ok=True)
    return {"fmt": fmt, "rows": int(len(df))}


def load_frame(session_id: str, name: str, ref: dict) -> pd.DataFrame:
    safe_session_id(session_id)
    if USE_AWS_STORAGE:
        return _mem_get(session_id, name)
    fmt = ref.get("fmt", "parquet")
    path = _SESSIONS_DIR / safe_session_id(session_id) / _local_name(name, fmt)
    with _local_lock:
        return _from_bytes(path.read_bytes(), fmt)


def delete_frame(session_id: str, name: str, ref: dict | None = None) -> None:
    safe_session_id(session_id)
    if USE_AWS_STORAGE:
        _mem_delete(session_id, name)
        return
    fmts = [ref.get("fmt", "parquet")] if ref else ["parquet", "pickle"]
    for fmt in fmts:
        path = _SESSIONS_DIR / safe_session_id(session_id) / _local_name(name, fmt)
        with _local_lock:
            path.unlink(missing_ok=True)
