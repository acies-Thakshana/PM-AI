"""Reading uploaded files from a request without trusting their size."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from fastapi import UploadFile

from app.errors import InvalidInputError

_CHUNK = 1024 * 1024


def read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """The whole upload, or an error as soon as it exceeds ``max_bytes`` (never buffers more)."""
    chunks: list[bytes] = []
    total = 0
    while chunk := upload.file.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise InvalidInputError(f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows as JSON-safe dicts (NaN and NaT become null)."""
    return json.loads(frame.to_json(orient="records", date_format="iso"))
