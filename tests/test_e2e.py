"""End to end, with no Azure: local folder storage, mock vendor API, real PostgreSQL.

Requires PostgreSQL (see tests/conftest.py).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.persist import claim_run, complete_run
from src.pipeline import (
    CSV_SOURCE_SYSTEM,
    JobError,
    build_context,
    csv_source_version,
    is_csv_source_object,
    run_api_job,
    run_csv_job,
)
from src.retry import RetryableError
from tests.mock_api import DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET, MockApiState, mock_api
from tests.mock_api.server import sample_students

pytestmark = pytest.mark.db

CSV_HEADER = (
    "student_id,first_name,last_name,grade_level,school_id,email,"
    "enrollment_status,updated_at,guardian_contact"
)


def stage_csv(context, samples_dir, *names: str) -> None:
    context.store.ensure_container(context.settings.storage.landing_container)
    for name in names:
        context.store.write_text(
            context.settings.storage.landing_container,
            name,
            (samples_dir / name).read_text(encoding="utf-8"),
        )


def write_landing_csv(context, name: str, rows: list[str]) -> None:
    context.store.ensure_container(context.settings.storage.landing_container)
    context.store.write_text(
        context.settings.storage.landing_container,
        name,
        f"{CSV_HEADER}\n" + "\n".join(rows) + "\n",
    )


def student_ids(connection) -> list[str]:
    return [row[0] for row in connection.execute("SELECT student_id FROM students ORDER BY 1")]


def snapshot(connection) -> list[tuple]:
    return connection.execute(
        "SELECT student_id, updated_at, enrollment_status, grade_level, ingested_at,"
        " last_written_at FROM students ORDER BY student_id"
    ).fetchall()


def quarantine_reasons(context) -> list[str]:
    reasons = []
    container = context.settings.storage.quarantine_container
    for info in context.store.list_objects(container):
        with context.store.open_stream(container, info.name) as stream:
            for line in stream.read().decode("utf-8").splitlines():
                reasons.append(json.loads(line)["reason_code"])
    return reasons


def api_context(pipeline_settings, base_url):
    return build_context(
        replace(
            pipeline_settings,
            api=replace(
                pipeline_settings.api,
                base_url=base_url,
                token_url=f"{base_url}/oauth2/token",
                client_id=DEFAULT_CLIENT_ID,
                client_secret=DEFAULT_CLIENT_SECRET,
            ),
        )
    )


def test_csv_source_object_filter_accepts_only_csv_names():
    assert is_csv_source_object("students.csv")
    assert is_csv_source_object("uploads/STUDENTS.CSV")
    assert not is_csv_source_object("students.xlsx")
    assert not is_csv_source_object("students.pdf")
    assert not is_csv_source_object("students.png")
    assert not is_csv_source_object("folder/")


def test_csv_job_writes_valid_rows_quarantines_the_rest_and_archives_the_file(
    pipeline_settings, samples_dir, db_connection
):
    context = build_context(pipeline_settings)
    stage_csv(context, samples_dir, "students_valid.csv", "students_malformed.csv")

    summaries = run_csv_job(context)

    assert len(summaries) == 2
    assert student_ids(db_connection) == ["S1001", "S1002", "S1003", "S1004", "S1005", "S2008"]

    reasons = quarantine_reasons(context)
    assert sorted(set(reasons)) == [
        "INVALID_EMAIL",
        "INVALID_GRADE_LEVEL",
        "INVALID_TIMESTAMP",
        "MALFORMED_ROW",
        "MISSING_REQUIRED_FIELD",
        "UNKNOWN_ENROLLMENT_STATUS",
    ]
    assert len(reasons) == 7

    assert {info.name for info in context.store.list_objects("processed")} == {
        "students_valid.csv",
        "students_malformed.csv",
    }
    assert context.store.list_objects("landing") == []

    runs = db_connection.execute("SELECT status, last_chunk FROM ingest_run ORDER BY id").fetchall()
    assert [status for status, _ in runs] == ["completed", "completed"]
    assert all(last_chunk > 1 for _, last_chunk in runs)  # chunk_size=2, so several chunks


def test_wrong_schema_file_is_quarantined_without_stopping_a_good_file(
    pipeline_settings, samples_dir, db_connection
):
    context = build_context(pipeline_settings)
    stage_csv(context, samples_dir, "students_valid.csv", "students_wrong_schema.csv")

    summaries = run_csv_job(context)

    assert len(summaries) == 2
    assert student_ids(db_connection) == ["S1001", "S1002", "S1003", "S1004", "S1005"]
    assert quarantine_reasons(context) == ["MISSING_REQUIRED_FIELD", "MISSING_REQUIRED_FIELD"]
    runs = db_connection.execute(
        """
        SELECT source_object_id, status, rows_read, rows_valid, rows_quarantined, rows_written
        FROM ingest_run
        ORDER BY source_object_id
        """
    ).fetchall()
    assert runs == [
        ("students_valid.csv", "completed", 5, 5, 0, 5),
        ("students_wrong_schema.csv", "completed", 2, 0, 2, 0),
    ]


def test_csv_job_ignores_non_csv_objects_in_landing(pipeline_settings, samples_dir, db_connection):
    context = build_context(pipeline_settings)
    stage_csv(context, samples_dir, "students_valid.csv")
    landing = context.settings.storage.landing_container
    context.store.write_bytes(landing, "students.xlsx", b"not a csv")
    context.store.write_bytes(landing, "report.pdf", b"not a csv")
    context.store.write_bytes(landing, "photo.png", b"not a csv")
    context.store.write_bytes(landing, "docs/students.docx", b"not a csv")

    summaries = run_csv_job(context)

    assert len(summaries) == 1
    assert student_ids(db_connection) == ["S1001", "S1002", "S1003", "S1004", "S1005"]
    assert {info.name for info in context.store.list_objects("processed")} == {"students_valid.csv"}
    assert {info.name for info in context.store.list_objects(landing)} == {
        "docs/students.docx",
        "photo.png",
        "report.pdf",
        "students.xlsx",
    }
    assert quarantine_reasons(context) == []


def test_reprocessing_the_same_data_changes_nothing(pipeline_settings, samples_dir, db_connection):
    context = build_context(pipeline_settings)
    stage_csv(context, samples_dir, "students_valid.csv")
    run_csv_job(context)
    before = snapshot(db_connection)

    stage_csv(context, samples_dir, "students_valid.csv")
    summaries = run_csv_job(context)

    assert snapshot(db_connection) == before
    assert summaries[0].inserted == 0
    assert summaries[0].updated == 0
    assert summaries[0].skipped == 5


def test_changed_csv_fails_without_stopping_other_files(
    pipeline_settings, samples_dir, db_connection, monkeypatch
):
    context = build_context(pipeline_settings)
    landing = context.settings.storage.landing_container
    context.store.ensure_container(landing)
    body = (samples_dir / "students_valid.csv").read_text(encoding="utf-8")
    context.store.write_text(landing, "a_changed.csv", body)
    context.store.write_text(landing, "z_good.csv", body)

    original_open_stream = context.store.open_stream
    changed = False

    def open_stream(container, name, *, expected_version=None):
        nonlocal changed
        if name == "a_changed.csv" and expected_version is not None and not changed:
            changed = True
            context.store.write_text(container, name, "student_id\nchanged\n")
        return original_open_stream(
            container,
            name,
            expected_version=expected_version,
        )

    monkeypatch.setattr(context.store, "open_stream", open_stream)

    with pytest.raises(JobError, match="a_changed.csv"):
        run_csv_job(context)

    assert {info.name for info in context.store.list_objects("processed")} == {"z_good.csv"}
    assert {info.name for info in context.store.list_objects("landing")} == {"a_changed.csv"}
    assert student_ids(db_connection) == ["S1001", "S1002", "S1003", "S1004", "S1005"]
    statuses = db_connection.execute(
        "SELECT source_object_id, status FROM ingest_run ORDER BY source_object_id"
    ).fetchall()
    assert statuses == [("a_changed.csv", "failed"), ("z_good.csv", "completed")]


def test_api_job_pages_upserts_quarantines_and_advances_the_watermark(
    pipeline_settings, db_connection
):
    with mock_api(MockApiState(students=sample_students(), page_size=2)) as (base_url, state):
        context = api_context(pipeline_settings, base_url)

        summary = run_api_job(context)

        assert state.updated_since_seen[0] is None
        assert summary.quarantined == 1
        assert student_ids(db_connection) == ["S1001", "S1003", "S3001", "S3002"]
        assert quarantine_reasons(context) == ["INVALID_EMAIL"]
        assert db_connection.execute("SELECT watermark FROM api_checkpoint").fetchone()[0] == (
            datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
        )

        before = snapshot(db_connection)
        second = run_api_job(context)

        assert state.updated_since_seen[-1] == "2026-07-31T12:00:00+00:00"
        assert snapshot(db_connection) == before
        assert (second.inserted, second.updated) == (0, 0)


def test_a_completed_blob_version_is_skipped_without_being_read(
    pipeline_settings, samples_dir, db_connection
):
    """Covers the case in `pipeline._archive`'s comment: the DB commit for a version
    succeeded but the archive-move did not run (or failed), so the file is still sitting in
    `landing/`. The next scan must not re-read or re-persist it.
    """
    context = build_context(pipeline_settings)
    stage_csv(context, samples_dir, "students_valid.csv")
    version = context.store.list_objects(context.settings.storage.landing_container)[0].version

    claim = claim_run(
        db_connection,
        source=CSV_SOURCE_SYSTEM,
        source_object_id="students_valid.csv",
        source_version=csv_source_version(version, pipeline_settings.chunk_size),
        correlation_id="pre-existing-run",
    )
    assert claim is not None
    complete_run(db_connection, claim.run_id)

    summaries = run_csv_job(context)

    assert summaries == []
    assert student_ids(db_connection) == []
    landing_names = {info.name for info in context.store.list_objects("landing")}
    assert landing_names == {"students_valid.csv"}  # left untouched, not archived again


def test_archive_version_mismatch_keeps_completed_file_in_landing(
    pipeline_settings, samples_dir, db_connection, monkeypatch
):
    context = build_context(pipeline_settings)
    landing = context.settings.storage.landing_container
    stage_csv(context, samples_dir, "students_valid.csv")

    original_move = context.store.move
    changed = False

    def move(container, name, dest_container, *, expected_version=None):
        nonlocal changed
        if name == "students_valid.csv" and not changed:
            changed = True
            context.store.write_text(container, name, "student_id\nchanged\n")
        return original_move(
            container,
            name,
            dest_container,
            expected_version=expected_version,
        )

    monkeypatch.setattr(context.store, "move", move)

    summaries = run_csv_job(context)

    assert len(summaries) == 1
    assert student_ids(db_connection) == ["S1001", "S1002", "S1003", "S1004", "S1005"]
    assert {info.name for info in context.store.list_objects(landing)} == {"students_valid.csv"}
    assert context.store.list_objects(context.settings.storage.processed_container) == []
    assert db_connection.execute("SELECT status FROM ingest_run").fetchone()[0] == "completed"


def test_changed_chunk_size_reclaims_csv_from_the_start(
    pipeline_settings, samples_dir, db_connection, monkeypatch
):
    context = build_context(pipeline_settings)
    stage_csv(context, samples_dir, "students_valid.csv")

    original_persist_chunk = context.database.in_transaction

    def fail_second_chunk(connection, operation, fn):
        if operation == "db.persist_chunk" and fn.keywords["chunk_index"] == 2:
            raise RuntimeError("stop after chunk one")
        return original_persist_chunk(connection, operation, fn)

    monkeypatch.setattr(context.database, "in_transaction", fail_second_chunk)

    with pytest.raises(JobError):
        run_csv_job(context)

    assert student_ids(db_connection) == ["S1001", "S1002"]
    assert db_connection.execute("SELECT status, last_chunk FROM ingest_run").fetchone() == (
        "failed",
        1,
    )

    monkeypatch.setattr(context.database, "in_transaction", original_persist_chunk)
    context = replace(context, settings=replace(context.settings, chunk_size=3))

    summaries = run_csv_job(context)

    assert len(summaries) == 1
    assert student_ids(db_connection) == ["S1001", "S1002", "S1003", "S1004", "S1005"]
    assert summaries[0].inserted == 3
    assert summaries[0].skipped == 2


def test_a_failed_later_page_does_not_lose_earlier_pages_or_skip_data_on_retry(
    pipeline_settings, db_connection
):
    """Page 1 must land even though page 2 fails, and the retry must not skip anything.

    The watermark only advances after a full sync succeeds (ITD-006), so a failed later page
    can never cause the next run to skip records - even though this run's `ingest_run` failed.
    """
    state = MockApiState(students=sample_students(), page_size=2, server_error_pages={2})
    with mock_api(state) as (base_url, _):
        context = api_context(pipeline_settings, base_url)

        with pytest.raises(RetryableError):
            run_api_job(context)

        # Page 1 (2 records) was committed before page 2 failed.
        assert student_ids(db_connection) == ["S1001", "S1003"]
        assert db_connection.execute("SELECT * FROM api_checkpoint").fetchall() == []
        assert db_connection.execute("SELECT status FROM ingest_run").fetchone()[0] == "failed"

        state.server_error_pages.clear()
        summary = run_api_job(context)

    # The retry re-fetches from the same (unmoved) watermark - S1001/S1003 are reapplied as a
    # no-op, and the run now reaches the records that page 2 previously blocked.
    assert student_ids(db_connection) == ["S1001", "S1003", "S3001", "S3002"]
    assert summary.max_updated_at is not None
    assert db_connection.execute("SELECT watermark FROM api_checkpoint").fetchone()[0] == (
        datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    )


def test_api_updates_csv_rows_only_when_the_api_data_is_fresher(
    pipeline_settings, samples_dir, db_connection
):
    with mock_api(MockApiState(students=sample_students(), page_size=2)) as (base_url, _):
        context = api_context(pipeline_settings, base_url)
        stage_csv(context, samples_dir, "students_valid.csv")
        run_csv_job(context)

        run_api_job(context)

    rows = dict(
        db_connection.execute(
            "SELECT student_id, enrollment_status FROM students"
            " WHERE student_id IN ('S1001','S1003')"
        ).fetchall()
    )
    # API S1001 is newer than the CSV row, API S1003 is older, so only S1001 changes.
    assert rows == {"S1001": "inactive", "S1003": "graduated"}


def test_duplicates_across_chunks_and_files_end_with_the_newest_record(
    pipeline_settings, db_connection
):
    context = build_context(pipeline_settings)
    write_landing_csv(
        context,
        "a_same_file_duplicates.csv",
        [
            "S5001,Old,InFile,4,SCH-01,old.infile@example.edu,active,"
            "2026-07-30T08:00:00Z,+1-206-555-0501",
            "S5003,Other,Student,5,SCH-01,other.student@example.edu,active,"
            "2026-07-30T08:05:00Z,+1-206-555-0503",
            "S5001,New,InFile,4,SCH-01,new.infile@example.edu,active,"
            "2026-07-30T09:00:00Z,+1-206-555-0501",
        ],
    )
    write_landing_csv(
        context,
        "b_cross_file_newer.csv",
        [
            "S5002,Newer,CrossFile,6,SCH-02,newer.cross@example.edu,active,"
            "2026-07-30T10:00:00Z,+1-206-555-0502",
        ],
    )
    write_landing_csv(
        context,
        "c_cross_file_older.csv",
        [
            "S5002,Older,CrossFile,6,SCH-02,older.cross@example.edu,active,"
            "2026-07-30T07:00:00Z,+1-206-555-0502",
        ],
    )

    summaries = run_csv_job(context)

    rows = dict(
        db_connection.execute(
            """
            SELECT student_id, first_name
            FROM students
            WHERE student_id IN ('S5001', 'S5002', 'S5003')
            ORDER BY student_id
            """
        ).fetchall()
    )
    assert rows == {"S5001": "New", "S5002": "Newer", "S5003": "Other"}
    assert quarantine_reasons(context) == []
    assert sum(summary.inserted for summary in summaries) == 3
    assert sum(summary.updated for summary in summaries) == 1
    assert sum(summary.skipped for summary in summaries) == 1


def test_future_updated_at_is_quarantined_so_later_real_update_can_land(
    pipeline_settings, db_connection
):
    context = build_context(pipeline_settings)
    write_landing_csv(
        context,
        "a_future.csv",
        [
            "S5100,Future,Student,7,SCH-01,future.student@example.edu,active,"
            "2099-01-01T00:00:00Z,+1-206-555-5100",
        ],
    )
    first = run_csv_job(context)
    write_landing_csv(
        context,
        "b_real_update.csv",
        [
            "S5100,Real,Student,7,SCH-01,real.student@example.edu,inactive,"
            "2026-08-01T00:00:00Z,+1-206-555-5100",
        ],
    )

    second = run_csv_job(context)

    row = db_connection.execute(
        "SELECT first_name, enrollment_status, updated_at FROM students WHERE student_id = 'S5100'"
    ).fetchone()
    assert first[0].inserted == 0
    assert first[0].quarantined == 1
    assert second[0].inserted == 1
    assert row == ("Real", "inactive", datetime(2026, 8, 1, tzinfo=UTC))
    assert quarantine_reasons(context) == ["INVALID_TIMESTAMP"]


def test_large_csv_batch_loads_all_rows_and_counts_chunks(pipeline_settings, db_connection):
    context = build_context(replace(pipeline_settings, chunk_size=5000))
    rows = [
        f"S{index:05d},First{index},Last{index},{index % 13},SCH-{index % 10:02d},"
        f"student{index}@example.edu,active,2026-07-30T00:00:00Z,+1-206-555-0000"
        for index in range(50_000)
    ]
    write_landing_csv(context, "large_batch.csv", rows)

    summaries = run_csv_job(context)

    assert len(summaries) == 1
    assert summaries[0].chunks == 10
    assert summaries[0].read == 50_000
    assert summaries[0].valid == 50_000
    assert summaries[0].quarantined == 0
    assert summaries[0].inserted == 50_000
    assert summaries[0].updated == 0
    assert summaries[0].skipped == 0
    assert db_connection.execute("SELECT count(*) FROM students").fetchone()[0] == 50_000
