"""Quarantine sink. Rejected records land in object storage as JSON Lines."""

from __future__ import annotations

import json
import logging
from collections import Counter

from src.logging_setup import log_event
from src.models import QuarantinedRecord
from src.storage import ObjectStore

LOG = logging.getLogger(__name__)


class QuarantineWriter:
    """One file per chunk, named from the run id so a re-run overwrites instead of duplicating."""

    def __init__(self, store: ObjectStore, container: str) -> None:
        self._store = store
        self._container = container

    def write(
        self,
        records: list[QuarantinedRecord],
        *,
        source_system: str,
        run_id: str,
        chunk_index: int,
    ) -> str | None:
        if not records:
            return None
        name = f"{source_system}/{run_id}/chunk-{chunk_index:05d}.jsonl"
        body = (
            "\n".join(
                json.dumps(record.to_json_dict(), default=str, sort_keys=True) for record in records
            )
            + "\n"
        )
        self._store.write_text(self._container, name, body)
        reasons = Counter(record.reason.value for record in records)
        log_event(
            LOG,
            logging.WARNING,
            "quarantine.written",
            object_name=name,
            records=len(records),
            reasons=dict(reasons),
        )
        return name
