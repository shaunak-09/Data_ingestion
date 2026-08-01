"""Structured JSON logging with a correlation ID attached to every line."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_CORRELATION_ID: ContextVar[str] = ContextVar("correlation_id", default="-")

_configured = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "correlation_id": _CORRELATION_ID.get(),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger. Safe to call more than once."""
    global _configured
    root = logging.getLogger()
    root.setLevel(level.upper())
    if _configured:
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    if root.handlers:
        for existing_handler in root.handlers:
            existing_handler.setFormatter(JsonFormatter())
    else:
        root.addHandler(handler)
    _configured = True


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def set_correlation_id(correlation_id: str) -> None:
    _CORRELATION_ID.set(correlation_id)


def get_correlation_id() -> str:
    return _CORRELATION_ID.get()


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Emit one structured event. `event` is a stable dotted name, not a sentence."""
    logger.log(level, event, extra={"fields": fields})
