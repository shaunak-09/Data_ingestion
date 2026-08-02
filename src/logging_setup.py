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


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _plural(count: int | None, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural or f"{singular}s"


def _human_message(event: str, fields: dict[str, Any]) -> str:
    """Short text for humans. `event` stays stable for alerts and automation."""
    if event == "csv.scan_complete":
        candidates = _count(fields.get("candidates"))
        return f"CSV scan found {candidates} {_plural(candidates, 'candidate file')}."
    if event == "db.connected":
        return f"Connected to database {fields.get('database')} on {fields.get('host')}."
    if event == "chunk.persisted":
        return (
            f"Persisted chunk {fields.get('chunk')} for run {fields.get('run_id')}: "
            f"read {fields.get('read')}, valid {fields.get('valid')}, "
            f"quarantined {fields.get('quarantined')}, inserted {fields.get('inserted')}, "
            f"updated {fields.get('updated')}, skipped {fields.get('skipped_stale')} stale."
        )
    if event in {"csv.file_complete", "api.sync_complete", "trigger.csv_finished"}:
        return (
            f"{event.replace('.', ' ').replace('_', ' ').capitalize()}: "
            f"read {fields.get('read')}, valid {fields.get('valid')}, "
            f"quarantined {fields.get('quarantined')}, inserted {fields.get('inserted')}, "
            f"updated {fields.get('updated')}, skipped {fields.get('skipped')}."
        )
    if event == "cli.csv_done":
        files = _count(fields.get("files"))
        return f"CSV job finished; processed {files} {_plural(files, 'file')}."
    if event == "api.sync_start":
        since = fields.get("since") or "the beginning"
        return f"API sync started from {since}."
    if event == "api.auth.token_issued":
        return f"API token issued; valid for {fields.get('lifetime_seconds')} seconds."
    if event == "api.page_fetched":
        return f"Fetched API page {fields.get('page')} with {fields.get('records')} records."
    if event == "quarantine.written":
        records = _count(fields.get("records"))
        return (
            f"Wrote {records} {_plural(records, 'quarantined record')} "
            f"to {fields.get('object_name')}."
        )
    if event == "api.pagination_complete":
        pages = _count(fields.get("pages"))
        return f"API pagination finished after {pages} {_plural(pages, 'page')}."
    if event == "api.watermark_advanced":
        return f"API watermark advanced to {fields.get('watermark')}."
    if event.endswith("_failed") or event.endswith(".job_failed"):
        return f"{event.replace('.', ' ').replace('_', ' ').capitalize()}."
    return f"{event.replace('.', ' ').replace('_', ' ').capitalize()}."


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = record.getMessage()
        fields = getattr(record, "fields", None) or {}
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": event,
            "message": _human_message(event, fields),
            "correlation_id": _CORRELATION_ID.get(),
        }
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
