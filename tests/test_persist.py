"""Run bookkeeping and the API watermark. Requires PostgreSQL (see tests/conftest.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from src.persist import (
    apply_pending_migrations,
    claim_run,
    complete_run,
    fail_run,
    get_watermark,
    record_chunk_progress,
    set_watermark,
)

pytestmark = pytest.mark.db

WATERMARK = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)


def claim(
    connection,
    *,
    object_id="students.csv",
    version="v1",
    correlation_id="cid",
    stale_after_seconds=3600,
):
    return claim_run(
        connection,
        source="csv",
        source_object_id=object_id,
        source_version=version,
        correlation_id=correlation_id,
        stale_after_seconds=stale_after_seconds,
    )


def test_a_new_unit_of_work_is_claimed(db_connection):
    run = claim(db_connection)

    assert run is not None
    assert (run.resumed, run.last_chunk) == (False, 0)


def test_the_same_blob_version_is_never_processed_twice(db_connection):
    first = claim(db_connection)
    assert first is not None

    assert claim(db_connection) is None  # still running
    complete_run(db_connection, first.run_id)
    assert claim(db_connection) is None  # completed


def test_a_new_blob_version_is_new_work(db_connection):
    first = claim(db_connection, version="v1")
    assert first is not None
    complete_run(db_connection, first.run_id)

    second = claim(db_connection, version="v2")

    assert second is not None
    assert second.run_id != first.run_id


def test_a_failed_run_resumes_from_its_last_committed_chunk(db_connection):
    first = claim(db_connection)
    assert first is not None
    record_chunk_progress(
        db_connection, first.run_id, chunk_index=3, read=30, valid=28, quarantined=2, written=28
    )
    fail_run(db_connection, first.run_id, "database went away")

    resumed = claim(db_connection, correlation_id="cid-2")

    assert resumed is not None
    assert (resumed.run_id, resumed.resumed, resumed.last_chunk) == (first.run_id, True, 3)


def test_a_stale_running_run_resumes_from_its_last_committed_chunk(db_connection):
    first = claim(db_connection)
    assert first is not None
    record_chunk_progress(
        db_connection, first.run_id, chunk_index=2, read=20, valid=19, quarantined=1, written=19
    )
    db_connection.execute(
        "UPDATE ingest_run SET started_at = now() - interval '2 hours' WHERE id = %s",
        (first.run_id,),
    )

    resumed = claim(db_connection, correlation_id="cid-2", stale_after_seconds=3600)

    assert resumed is not None
    assert (resumed.run_id, resumed.resumed, resumed.last_chunk) == (first.run_id, True, 2)
    row = db_connection.execute(
        """
        SELECT
            status,
            correlation_id,
            completed_at IS NULL,
            started_at > now() - interval '5 minutes'
        FROM ingest_run
        WHERE id = %s
        """,
        (first.run_id,),
    ).fetchone()
    assert row == ("running", "cid-2", True, True)


def test_progress_accumulates_across_chunks(db_connection):
    run = claim(db_connection)
    assert run is not None

    record_chunk_progress(
        db_connection, run.run_id, chunk_index=1, read=10, valid=9, quarantined=1, written=9
    )
    record_chunk_progress(
        db_connection, run.run_id, chunk_index=2, read=10, valid=10, quarantined=0, written=10
    )

    row = db_connection.execute(
        "SELECT last_chunk, rows_read, rows_valid, rows_quarantined, rows_written FROM ingest_run"
    ).fetchone()
    assert row == (2, 20, 19, 1, 19)


def test_watermark_round_trip(db_connection):
    assert get_watermark(db_connection, "api") is None

    set_watermark(db_connection, "api", WATERMARK)

    assert get_watermark(db_connection, "api") == WATERMARK


def test_watermark_never_moves_backwards(db_connection):
    set_watermark(db_connection, "api", WATERMARK)

    set_watermark(db_connection, "api", WATERMARK - timedelta(days=1))

    assert get_watermark(db_connection, "api") == WATERMARK


def test_pending_migrations_apply_once_each_in_order(db_connection, tmp_path: Path):
    migrations_dir = tmp_path / "db"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text("CREATE TABLE mig_probe (id int);")
    (migrations_dir / "002_second.sql").write_text("ALTER TABLE mig_probe ADD COLUMN name text;")

    first_pass = apply_pending_migrations(db_connection, migrations_dir)
    second_pass = apply_pending_migrations(db_connection, migrations_dir)

    assert first_pass == ["001_first.sql", "002_second.sql"]
    assert second_pass == []  # already recorded in schema_migrations; nothing re-runs

    columns = db_connection.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'mig_probe' ORDER BY column_name
        """
    ).fetchall()
    assert columns == [("id",), ("name",)]


def test_a_broken_migration_is_not_recorded_as_applied(db_connection, tmp_path: Path):
    migrations_dir = tmp_path / "db"
    migrations_dir.mkdir()
    (migrations_dir / "001_broken.sql").write_text("THIS IS NOT VALID SQL;")

    with pytest.raises(psycopg.Error):
        apply_pending_migrations(db_connection, migrations_dir)

    row = db_connection.execute(
        "SELECT 1 FROM schema_migrations WHERE filename = '001_broken.sql'"
    ).fetchone()
    assert row is None
