"""CSV adapter. Streams rows out of object storage in bounded chunks."""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterator
from typing import Any

from src.logging_setup import log_event
from src.models import EXTRA_COLUMNS_KEY, SOURCE_LINE_KEY
from src.storage import ObjectStore

LOG = logging.getLogger(__name__)


def read_csv_chunks(
    store: ObjectStore,
    container: str,
    name: str,
    chunk_size: int,
    expected_version: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield at most `chunk_size` rows at a time.

    The file is never held in memory: the blob is read through a buffered stream and rows are
    handed over as soon as a chunk fills.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")

    with store.open_stream(container, name, expected_version=expected_version) as raw:
        # utf-8-sig strips the BOM that Excel exports add.
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text, restkey=EXTRA_COLUMNS_KEY, restval=None)
        if reader.fieldnames is None:
            log_event(LOG, logging.WARNING, "csv.empty_file", object_name=name)
            return
        reader.fieldnames = [header.strip().lower() for header in reader.fieldnames]

        chunk: list[dict[str, Any]] = []
        for row in reader:
            row[SOURCE_LINE_KEY] = reader.line_num
            chunk.append(row)
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk
