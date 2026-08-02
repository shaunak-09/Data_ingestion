"""Orchestration. Both sources hand chunks to the same core: validate -> transform -> persist.

Each chunk is validated, quarantined, transformed and committed before the next chunk is read,
so memory does not grow with the size of the source and a failure never redoes finished work.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any

import psycopg
import requests

from src.config import Settings
from src.ingest.api_auth import build_auth
from src.ingest.api_source import StudentApiClient
from src.ingest.csv_source import read_csv_chunks
from src.logging_setup import log_event, new_correlation_id, set_correlation_id
from src.models import QuarantinedRecord, ReasonCode, RunSummary, Student, UpsertResult
from src.persist import (
    DB_RETRY_ERRORS,
    Database,
    RunClaim,
    claim_run,
    complete_run,
    fail_run,
    get_watermark,
    record_chunk_progress,
    set_watermark,
    upsert_students,
)
from src.quarantine import QuarantineWriter
from src.retry import Retryer, RetryPolicy
from src.storage import ObjectStore, build_object_store
from src.transform import TransformError, to_student
from src.validate import validate_chunk

LOG = logging.getLogger(__name__)

CSV_SOURCE_SYSTEM = "csv"
API_SOURCE_SYSTEM = "api"


def csv_source_version(blob_version: str, chunk_size: int) -> str:
    return f"{blob_version}:{chunk_size}"


def is_csv_source_object(name: str) -> bool:
    """Only CSV source objects are eligible for the CSV pipeline."""
    return name.lower().endswith(".csv")


class JobError(RuntimeError):
    """A job finished with at least one unit of work unprocessed."""


@dataclass(frozen=True, slots=True)
class PipelineContext:
    """Everything a job needs, built once per invocation."""

    settings: Settings
    database: Database
    store: ObjectStore
    quarantine: QuarantineWriter


def build_context(settings: Settings) -> PipelineContext:
    store = build_object_store(settings.storage)
    policy = RetryPolicy.from_settings(settings.retry)
    return PipelineContext(
        settings=settings,
        database=Database(settings.database, Retryer(policy, retry_on=DB_RETRY_ERRORS)),
        store=store,
        quarantine=QuarantineWriter(store, settings.storage.quarantine_container),
    )


def _to_students(
    records: list[dict[str, Any]],
    *,
    source_system: str,
    source_object: str | None,
    correlation_id: str,
) -> tuple[list[Student], list[QuarantinedRecord]]:
    """Transform validated rows. A record that still fails is quarantined, not raised."""
    students: list[Student] = []
    failures: list[QuarantinedRecord] = []
    for record in records:
        try:
            students.append(to_student(record, source_system))
        except TransformError as exc:
            failures.append(
                QuarantinedRecord(
                    reason=ReasonCode.TRANSFORM_FAILED,
                    detail=str(exc),
                    field_name=None,
                    record=record,
                    source_system=source_system,
                    source_object=source_object,
                    correlation_id=correlation_id,
                )
            )
    return students, failures


def _persist_chunk(
    connection: psycopg.Connection,
    *,
    run_id: int,
    chunk_index: int,
    students: list[Student],
    read: int,
    quarantined: int,
) -> UpsertResult:
    """Upsert and progress land in the same transaction, so a resume point is always accurate."""
    result = upsert_students(connection, students)
    record_chunk_progress(
        connection,
        run_id,
        chunk_index=chunk_index,
        read=read,
        valid=len(students),
        quarantined=quarantined,
        written=result.inserted + result.updated,
    )
    return result


def process_chunks(
    chunks: Iterator[list[dict[str, Any]]],
    *,
    context: PipelineContext,
    connection: psycopg.Connection,
    run: RunClaim,
    source_system: str,
    source_object: str | None,
    correlation_id: str,
) -> RunSummary:
    """Run the shared core over every chunk of one unit of work."""
    summary = RunSummary(source_system=source_system, correlation_id=correlation_id)

    for chunk_index, chunk in enumerate(chunks, start=1):
        if chunk_index <= run.last_chunk:
            log_event(
                LOG,
                logging.INFO,
                "chunk.skipped_already_committed",
                run_id=run.run_id,
                chunk=chunk_index,
            )
            summary.chunks = chunk_index
            continue

        valid_records, quarantined = validate_chunk(
            chunk,
            source_system=source_system,
            source_object=source_object,
            correlation_id=correlation_id,
        )
        students, transform_failures = _to_students(
            valid_records,
            source_system=source_system,
            source_object=source_object,
            correlation_id=correlation_id,
        )
        quarantined.extend(transform_failures)

        context.quarantine.write(
            quarantined,
            source_system=source_system,
            run_id=str(run.run_id),
            chunk_index=chunk_index,
        )

        result = context.database.in_transaction(
            connection,
            "db.persist_chunk",
            partial(
                _persist_chunk,
                run_id=run.run_id,
                chunk_index=chunk_index,
                students=students,
                read=len(chunk),
                quarantined=len(quarantined),
            ),
        )

        summary.chunks = chunk_index
        summary.read += len(chunk)
        summary.valid += len(students)
        summary.quarantined += len(quarantined)
        summary.add_upsert(result)
        summary.observe(students)

        log_event(
            LOG,
            logging.INFO,
            "chunk.persisted",
            run_id=run.run_id,
            chunk=chunk_index,
            read=len(chunk),
            valid=len(students),
            quarantined=len(quarantined),
            inserted=result.inserted,
            updated=result.updated,
            skipped_stale=result.skipped,
        )

    return summary


def run_csv_job(context: PipelineContext, correlation_id: str | None = None) -> list[RunSummary]:
    """Scan the landing container and process every CSV blob version exactly once."""
    storage = context.settings.storage
    for container in (
        storage.landing_container,
        storage.processed_container,
        storage.quarantine_container,
    ):
        context.store.ensure_container(container)

    objects = [
        info
        for info in context.store.list_objects(storage.landing_container)
        if is_csv_source_object(info.name)
    ]
    log_event(LOG, logging.INFO, "csv.scan_complete", candidates=len(objects))

    summaries: list[RunSummary] = []
    failed: list[str] = []

    with context.database.session() as connection:
        for info in objects:
            file_correlation_id = correlation_id or new_correlation_id()
            set_correlation_id(file_correlation_id)

            claim = context.database.in_transaction(
                connection,
                "db.claim_run",
                partial(
                    claim_run,
                    source=CSV_SOURCE_SYSTEM,
                    source_object_id=info.name,
                    source_version=csv_source_version(info.version, context.settings.chunk_size),
                    correlation_id=file_correlation_id,
                    stale_after_seconds=context.settings.run_stale_after_seconds,
                ),
            )
            if claim is None:
                continue

            try:
                chunks = read_csv_chunks(
                    context.store,
                    storage.landing_container,
                    info.name,
                    context.settings.chunk_size,
                    expected_version=info.version,
                )
                summary = process_chunks(
                    chunks,
                    context=context,
                    connection=connection,
                    run=claim,
                    source_system=CSV_SOURCE_SYSTEM,
                    source_object=info.name,
                    correlation_id=file_correlation_id,
                )
                complete_run(connection, claim.run_id)
                summaries.append(summary)
                log_event(LOG, logging.INFO, "csv.file_complete", **summary.as_fields())
                _archive(context, info.name, info.version)
            except Exception as exc:
                fail_run(connection, claim.run_id, repr(exc))
                failed.append(info.name)
                LOG.exception("csv.file_failed", extra={"fields": {"object_name": info.name}})

    if failed:
        raise JobError(f"{len(failed)} CSV file(s) failed: {', '.join(failed)}")
    return summaries


def _archive(context: PipelineContext, name: str, version: str) -> None:
    """Move a finished file out of landing. The database, not the move, decides re-processing."""
    storage = context.settings.storage
    try:
        context.store.move(
            storage.landing_container,
            name,
            storage.processed_container,
            expected_version=version,
        )
    except Exception as exc:
        log_event(
            LOG,
            logging.WARNING,
            "csv.archive_failed",
            object_name=name,
            error=str(exc),
            note="run is committed; the next scan will skip this file",
        )


def run_api_job(context: PipelineContext, correlation_id: str | None = None) -> RunSummary:
    """Pull incremental updates from the API and advance the watermark only on full success."""
    run_correlation_id = correlation_id or new_correlation_id()
    set_correlation_id(run_correlation_id)

    settings = context.settings
    context.store.ensure_container(settings.storage.quarantine_container)

    policy = RetryPolicy.from_settings(settings.retry)
    http_retryer = Retryer(policy)
    session = requests.Session()
    auth = build_auth(settings.api, session, http_retryer)
    client = StudentApiClient(settings.api, auth, http_retryer, session)

    with context.database.session() as connection:
        since = get_watermark(connection, API_SOURCE_SYSTEM)
        claim = context.database.in_transaction(
            connection,
            "db.claim_run",
            partial(
                claim_run,
                source=API_SOURCE_SYSTEM,
                source_object_id=settings.api.students_path,
                source_version=run_correlation_id,
                correlation_id=run_correlation_id,
                stale_after_seconds=settings.run_stale_after_seconds,
            ),
        )
        assert claim is not None  # a fresh correlation id can never collide

        log_event(
            LOG,
            logging.INFO,
            "api.sync_start",
            run_id=claim.run_id,
            since=since.isoformat() if since else None,
        )
        try:
            summary = process_chunks(
                client.fetch_chunks(since),
                context=context,
                connection=connection,
                run=claim,
                source_system=API_SOURCE_SYSTEM,
                source_object=settings.api.students_path,
                correlation_id=run_correlation_id,
            )
            _advance_watermark(context, connection, summary.max_updated_at)
            complete_run(connection, claim.run_id)
        except Exception as exc:
            fail_run(connection, claim.run_id, repr(exc))
            LOG.exception("api.sync_failed", extra={"fields": {"run_id": claim.run_id}})
            raise

    log_event(LOG, logging.INFO, "api.sync_complete", **summary.as_fields())
    return summary


def _advance_watermark(
    context: PipelineContext, connection: psycopg.Connection, watermark: datetime | None
) -> None:
    """Only reached after every page succeeded, so no page can be skipped on the next run."""
    if watermark is None:
        return
    context.database.in_transaction(
        connection,
        "db.set_watermark",
        partial(set_watermark, source=API_SOURCE_SYSTEM, watermark=watermark),
    )
    log_event(LOG, logging.INFO, "api.watermark_advanced", watermark=watermark.isoformat())
