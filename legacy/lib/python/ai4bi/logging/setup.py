"""Logging from config/logging.yaml with the request id on every record."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import logging.config
from pathlib import Path
from typing import Any, Iterator

import yaml

_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("ai4bi_request_id", default="-")
_CONFIGURED = False


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _REQUEST_ID.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


@contextlib.contextmanager
def request_context(request_id: str) -> Iterator[None]:
    token = _REQUEST_ID.set(request_id)
    try:
        yield
    finally:
        _REQUEST_ID.reset(token)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("ai4bi") else f"ai4bi.{name}")


def setup_logging(
    config_path: Path | None = None,
    *,
    project_root: Path | None = None,
    level: str | None = None,
    force: bool = False,
) -> None:
    """Apply the YAML config once. File handlers resolve under ``project_root``."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return
    if config_path is None or not config_path.exists():
        logging.basicConfig(
            level=level or "INFO",
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        _CONFIGURED = True
        return
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    for handler in (config.get("handlers") or {}).values():
        filename = handler.get("filename")
        if filename:
            target = Path(filename)
            if not target.is_absolute() and project_root is not None:
                target = project_root / target
            target.parent.mkdir(parents=True, exist_ok=True)
            handler["filename"] = str(target)
    if level:
        for logger in (config.get("loggers") or {}).values():
            logger["level"] = level
    logging.config.dictConfig(config)
    _CONFIGURED = True
