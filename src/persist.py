"""PostgreSQL persistence: conditional upsert, run bookkeeping, API watermark.

Correctness lives in SQL. Chunks are staged with COPY into a session TEMP table and merged in
one statement, so a 50-row chunk and a 50,000-row chunk take the same code path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar

import psycopg
from azure.identity import DefaultAzureCredential
from psycopg.types.json import Jsonb

from src.config import DatabaseSettings
from src.logging_setup import log_event
from src.models import Student, UpsertResult
from src.retry import RetryableError, Retryer

LOG = logging.getLogger(__name__)

T = TypeVar("T")

# Transient database failures worth retrying. Passed to `Retryer(retry_on=...)`.
DB_RETRY_ERRORS: tuple[type[BaseException], ...] = (RetryableError, psycopg.OperationalError)

# Entra ID token audience for Azure Database for PostgreSQL Flexible Server.
_POSTGRES_TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

# Single source of truth for the staging table, the COPY column list and the merge statement.
_STAGING_COLUMN_TYPES = (
    ("student_id", "text"),
    ("first_name", "text"),
    ("last_name", "text"),
    ("grade_level", "smallint"),
    ("school_id", "text"),
    ("email", "text"),
    ("enrollment_status", "text"),
    ("updated_at", "timestamptz"),
    ("guardian_contact", "text"),
    ("source_system", "text"),
    ("raw_payload", "jsonb"),
)
_COLUMNS = tuple(name for name, _ in _STAGING_COLUMN_TYPES)
_COLUMN_LIST = ", ".join(_COLUMNS)
_UPDATE_SET = ", ".join(f"{name} = EXCLUDED.{name}" for name in _COLUMNS if name != "student_id")

_STAGING_DDL = (
    "CREATE TEMP TABLE IF NOT EXISTS students_staging ("
    + ", ".join(f"{name} {sql_type}" for name, sql_type in _STAGING_COLUMN_TYPES)
    + ") ON COMMIT DELETE ROWS"
)

_COPY_SQL = f"COPY students_staging ({_COLUMN_LIST}) FROM STDIN"

# DISTINCT ON is a safety net: `validate.py` already removes duplicate student_ids inside a
# chunk, and Postgres refuses to update the same row twice in one statement.
_MERGE_SQL = f"""
INSERT INTO students ({_COLUMN_LIST})
SELECT DISTINCT ON (student_id) {_COLUMN_LIST}
FROM students_staging
ORDER BY student_id, updated_at DESC
ON CONFLICT (student_id) DO UPDATE
SET {_UPDATE_SET}, last_written_at = now()
WHERE EXCLUDED.updated_at > students.updated_at
RETURNING (xmax = 0) AS inserted
"""


@dataclass(frozen=True, slots=True)
class RunClaim:
    """Permission to process one unit of work."""

    run_id: int
    resumed: bool
    last_chunk: int


class Database:
    """Creates connections and runs retried transactions."""

    def __init__(self, settings: DatabaseSettings, retryer: Retryer) -> None:
        self._settings = settings
        self._retryer = retryer
        self._credential: DefaultAzureCredential | None = None

    def _password(self) -> str | None:
        if not self._settings.use_managed_identity:
            return self._settings.password
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        # Entra tokens are short-lived, so fetch one per connection rather than caching.
        return self._credential.get_token(_POSTGRES_TOKEN_SCOPE).token

    def connect(self) -> psycopg.Connection:
        conninfo = self._settings.conninfo(self._password())
        connection = self._retryer.call(
            "db.connect", psycopg.connect, conninfo, autocommit=True, connect_timeout=15
        )
        log_event(
            LOG,
            logging.INFO,
            "db.connected",
            host=self._settings.host,
            database=self._settings.database,
            managed_identity=self._settings.use_managed_identity,
        )
        return connection

    @contextmanager
    def session(self) -> Iterator[psycopg.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def in_transaction(
        self, connection: psycopg.Connection, operation: str, fn: Callable[[psycopg.Connection], T]
    ) -> T:
        """Run `fn` inside one transaction, retrying the whole transaction on transient failures."""

        def attempt() -> T:
            with connection.transaction():
                return fn(connection)

        return self._retryer.call(operation, attempt)


def apply_schema(connection: psycopg.Connection, sql_path: str | Path) -> None:
    """Run one `.sql` file unconditionally. Used for fast test bootstrap only.

    Production and CI use `apply_pending_migrations`, which tracks what already ran.
    """
    connection.execute(Path(sql_path).read_text(encoding="utf-8"))


_MIGRATIONS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   text        PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def apply_pending_migrations(
    connection: psycopg.Connection, migrations_dir: str | Path
) -> list[str]:
    """Apply every `db/*.sql` file not yet recorded, in filename order.

    Safe to call on every deploy: a file is applied exactly once, tracked in
    `schema_migrations`. This is how a new `db/NNN_*.sql` file reaches the database, whether
    run locally (`python -m src.cli init-db`) or from CI/CD.
    """
    connection.execute(_MIGRATIONS_TABLE_DDL)
    applied: list[str] = []
    for path in sorted(Path(migrations_dir).glob("*.sql")):
        already_applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE filename = %s", (path.name,)
        ).fetchone()
        if already_applied:
            continue
        with connection.transaction():
            connection.execute(path.read_text(encoding="utf-8"))
            connection.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
        applied.append(path.name)
        log_event(LOG, logging.INFO, "db.migration_applied", filename=path.name)
    return applied


def _row(student: Student) -> tuple[object, ...]:
    return (
        student.student_id,
        student.first_name,
        student.last_name,
        student.grade_level,
        student.school_id,
        student.email,
        student.enrollment_status,
        student.updated_at,
        student.guardian_contact,
        student.source_system,
        Jsonb(student.raw_payload),
    )


def upsert_students(connection: psycopg.Connection, students: Sequence[Student]) -> UpsertResult:
    """Stage the chunk with COPY, then merge it in one conditional upsert.

    Older data never overwrites newer data: the update only fires when the incoming
    `updated_at` is strictly greater than the stored one.
    """
    if not students:
        return UpsertResult(submitted=0, inserted=0, updated=0)

    with connection.cursor() as cursor:
        cursor.execute(_STAGING_DDL)
        with cursor.copy(_COPY_SQL) as copy:
            for student in students:
                copy.write_row(_row(student))
        cursor.execute(_MERGE_SQL)
        outcomes = cursor.fetchall()

    inserted = sum(1 for (was_insert,) in outcomes if was_insert)
    return UpsertResult(
        submitted=len(students), inserted=inserted, updated=len(outcomes) - inserted
    )


def claim_run(
    connection: psycopg.Connection,
    *,
    source: str,
    source_object_id: str,
    source_version: str,
    correlation_id: str,
    stale_after_seconds: int = 3600,
) -> RunClaim | None:
    """Claim a unit of work. Returns None when it is already done or already running.

    A previously failed or stale running run is re-claimed from its last committed chunk.
    """
    if stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be at least 1")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingest_run (source, source_object_id, source_version, correlation_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT ingest_run_identity DO NOTHING
            RETURNING id
            """,
            (source, source_object_id, source_version, correlation_id),
        )
        claimed = cursor.fetchone()
        if claimed is not None:
            return RunClaim(run_id=claimed[0], resumed=False, last_chunk=0)

        cursor.execute(
            """
            SELECT
                id,
                status,
                last_chunk,
                status = 'running'
                    AND started_at <= now() - (%s * interval '1 second') AS is_stale
            FROM ingest_run
            WHERE source = %s AND source_object_id = %s AND source_version = %s
            """,
            (stale_after_seconds, source, source_object_id, source_version),
        )
        existing = cursor.fetchone()
        assert existing is not None  # the conflict above proves the row exists
        run_id, status, last_chunk, is_stale = existing
        if status != "failed" and not is_stale:
            log_event(
                LOG,
                logging.INFO,
                "run.skipped",
                run_id=run_id,
                status=status,
                source=source,
                source_object_id=source_object_id,
            )
            return None

        cursor.execute(
            """
            UPDATE ingest_run
            SET status = 'running',
                correlation_id = %s,
                error = NULL,
                completed_at = NULL,
                started_at = now()
            WHERE id = %s
              AND (
                status = 'failed'
                OR (status = 'running' AND started_at <= now() - (%s * interval '1 second'))
              )
            RETURNING last_chunk
            """,
            (correlation_id, run_id, stale_after_seconds),
        )
        reclaimed = cursor.fetchone()
        if reclaimed is None:
            return None

        event = "run.stale_reclaimed" if is_stale else "run.resumed"
        log_event(LOG, logging.INFO, event, run_id=run_id, from_chunk=reclaimed[0])
        return RunClaim(run_id=run_id, resumed=True, last_chunk=reclaimed[0])


def record_chunk_progress(
    connection: psycopg.Connection,
    run_id: int,
    *,
    chunk_index: int,
    read: int,
    valid: int,
    quarantined: int,
    written: int,
) -> None:
    """Commit progress with the chunk it belongs to, so a resume never redoes finished work."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE ingest_run
            SET last_chunk = %s,
                rows_read = rows_read + %s,
                rows_valid = rows_valid + %s,
                rows_quarantined = rows_quarantined + %s,
                rows_written = rows_written + %s
            WHERE id = %s
            """,
            (chunk_index, read, valid, quarantined, written, run_id),
        )


def complete_run(connection: psycopg.Connection, run_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ingest_run SET status = 'completed', completed_at = now() WHERE id = %s",
            (run_id,),
        )


def fail_run(connection: psycopg.Connection, run_id: int, error: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE ingest_run
            SET status = 'failed', completed_at = now(), error = %s
            WHERE id = %s
            """,
            (error[:2000], run_id),
        )


def get_watermark(connection: psycopg.Connection, source: str) -> datetime | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT watermark FROM api_checkpoint WHERE source = %s", (source,))
        row = cursor.fetchone()
    return row[0] if row else None


def set_watermark(connection: psycopg.Connection, source: str, watermark: datetime) -> None:
    """GREATEST keeps the watermark monotonic, so a late run cannot rewind it."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO api_checkpoint (source, watermark)
            VALUES (%s, %s)
             ON CONFLICT (source) DO UPDATE
            SET watermark = GREATEST(api_checkpoint.watermark, EXCLUDED.watermark),
                updated_at = now()
            """,
            (source, watermark),
        )
