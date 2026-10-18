"""Validation of the identifiers that become file paths, S3 keys and SQL table names."""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

from app.errors import InvalidInputError

_DOMAIN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9_]+")


def validate_domain(value: str) -> str:
    """A domain id: lowercase letters, digits and underscores, starting with a letter.

    The restriction is also what keeps a domain from escaping its folder or S3 prefix.
    """
    if not isinstance(value, str) or not _DOMAIN.fullmatch(value):
        raise InvalidInputError(
            "A domain id must be 2 to 40 characters: lowercase letters, digits and underscores, starting with a letter."
        )
    return value


def table_name_from_filename(filename: str) -> str:
    """The SQL table name for an uploaded file: its stem with unsafe characters replaced."""
    base = PureWindowsPath(PurePosixPath(filename).name).name  # drop any directory part, either style
    stem = base.rsplit(".", 1)[0] if "." in base else base
    name = _UNSAFE.sub("_", stem).strip("_")
    if not name:
        raise InvalidInputError(f"Cannot derive a table name from file name {filename!r}.")
    return name if re.match(r"[A-Za-z_]", name) else f"t_{name}"
