"""The core promise: the same input twice changes zero rows, and old data never wins.

Requires PostgreSQL. See tests/conftest.py for PG_TEST_DSN.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.models import Student
from src.persist import upsert_students

pytestmark = pytest.mark.db

BASE_TIME = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)


def student(
    student_id: str = "S1",
    *,
    updated_at: datetime = BASE_TIME,
    first_name: str = "Ava",
    status: str = "active",
) -> Student:
    return Student(
        student_id=student_id,
        first_name=first_name,
        last_name="Nguyen",
        grade_level=9,
        school_id="SCH-01",
        email="ava@example.edu",
        enrollment_status=status,
        updated_at=updated_at,
        guardian_contact=None,
        source_system="csv",
        raw_payload={"student_id": student_id},
    )


def snapshot(connection) -> list[tuple]:
    """Every column that a write could possibly disturb."""
    return connection.execute(
        """
        SELECT student_id, first_name, last_name, grade_level, school_id, email,
               enrollment_status, updated_at, guardian_contact, source_system,
               raw_payload, ingested_at, last_written_at
        FROM students ORDER BY student_id
        """
    ).fetchall()


def upsert(connection, records):
    """Match the production transaction boundary so the temp staging table is cleared."""
    with connection.transaction():
        return upsert_students(connection, records)


def test_running_the_same_input_twice_changes_zero_rows(db_connection):
    records = [student("S1"), student("S2")]

    first = upsert(db_connection, records)
    after_first = snapshot(db_connection)
    second = upsert(db_connection, records)

    assert (first.inserted, first.updated, first.skipped) == (2, 0, 0)
    assert (second.inserted, second.updated, second.skipped) == (0, 0, 2)
    assert snapshot(db_connection) == after_first


def test_newer_data_updates_the_row(db_connection):
    upsert(db_connection, [student(first_name="Ava")])

    result = upsert(
        db_connection,
        [student(first_name="Ava-Marie", updated_at=BASE_TIME + timedelta(hours=1))],
    )

    assert (result.inserted, result.updated, result.skipped) == (0, 1, 0)
    assert db_connection.execute("SELECT first_name FROM students").fetchone()[0] == "Ava-Marie"


def test_older_data_never_overwrites_newer_data(db_connection):
    upsert(db_connection, [student(first_name="Current")])

    result = upsert(
        db_connection,
        [student(first_name="Stale", updated_at=BASE_TIME - timedelta(days=1))],
    )

    assert (result.inserted, result.updated, result.skipped) == (0, 0, 1)
    assert db_connection.execute("SELECT first_name FROM students").fetchone()[0] == "Current"


def test_equal_timestamps_are_treated_as_already_applied(db_connection):
    upsert(db_connection, [student(first_name="Current")])

    result = upsert(db_connection, [student(first_name="Same time, new name")])

    assert result.skipped == 1
    assert db_connection.execute("SELECT first_name FROM students").fetchone()[0] == "Current"


def test_duplicate_ids_inside_one_chunk_do_not_break_the_statement(db_connection):
    """Postgres refuses to update a row twice in one statement, so the merge de-duplicates."""
    records = [
        student(first_name="Older", updated_at=BASE_TIME),
        student(first_name="Newer", updated_at=BASE_TIME + timedelta(hours=2)),
    ]

    result = upsert(db_connection, records)

    assert result.inserted == 1
    assert db_connection.execute("SELECT first_name FROM students").fetchone()[0] == "Newer"


def test_empty_chunk_is_a_no_op(db_connection):
    result = upsert(db_connection, [])

    assert (result.submitted, result.inserted, result.updated) == (0, 0, 0)
    assert snapshot(db_connection) == []


def test_a_large_chunk_uses_the_same_path(db_connection):
    records = [student(f"S{index:05d}") for index in range(5_000)]

    first = upsert(db_connection, records)
    second = upsert(db_connection, records)

    assert first.inserted == 5_000
    assert (second.inserted, second.updated, second.skipped) == (0, 0, 5_000)
