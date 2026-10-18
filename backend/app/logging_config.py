"""Logging to stdout (what ECS ships to CloudWatch), with the request id on every record."""

from __future__ import annotations

import json
import logging
import logging.config
import sys
from typing import Any

from app.services.common import request_context

_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"


class RequestContextFilter(logging.Filter):
    """Attach the current request id and user to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_context.current_request_id.get() or "-"
        record.user_id = request_context.current_user_id.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, easy to query in CloudWatch Logs Insights."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", *, json_format: bool = False) -> None:
    """Configure the root logger. Safe to call more than once."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_context": {"()": RequestContextFilter}},
            "formatters": {
                "text": {"format": _TEXT_FORMAT},
                "json": {"()": JsonFormatter},
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": sys.stdout,
                    "formatter": "json" if json_format else "text",
                    "filters": ["request_context"],
                }
            },
            "root": {"level": level, "handlers": ["stdout"]},
        }
    )
