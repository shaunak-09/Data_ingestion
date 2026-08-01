"""The committed samples must produce exactly the committed expected output.

This keeps `samples/expected_students.json` honest: if the rules change, this test fails.
"""

from __future__ import annotations

from pathlib import Path

from src.ingest.csv_source import read_csv_chunks
from src.storage import LocalObjectStore
from src.transform import to_student
from src.validate import validate_chunk


def process(samples_dir: Path, file_name: str):
    store = LocalObjectStore(samples_dir.parent)
    records = [
        record
        for chunk in read_csv_chunks(store, samples_dir.name, file_name, chunk_size=100)
        for record in chunk
    ]
    valid, quarantined = validate_chunk(
        records, source_system="csv", source_object=file_name, correlation_id="sample"
    )
    return [to_student(record, "csv") for record in valid], quarantined


def as_dict(student) -> dict:
    return {
        "student_id": student.student_id,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "grade_level": student.grade_level,
        "school_id": student.school_id,
        "email": student.email,
        "enrollment_status": student.enrollment_status,
        "updated_at": student.updated_at.isoformat(),
        "guardian_contact": student.guardian_contact,
        "source_system": student.source_system,
        "raw_payload": student.raw_payload,
    }


def test_valid_sample_matches_expected_output(samples_dir, expected_output):
    expected = expected_output["valid_file"]

    students, quarantined = process(samples_dir, expected["file"])

    assert [as_dict(student) for student in students] == expected["students"]
    assert quarantined == []


def test_malformed_sample_matches_expected_output(samples_dir, expected_output):
    expected = expected_output["malformed_file"]

    students, quarantined = process(samples_dir, expected["file"])

    assert [as_dict(student) for student in students] == expected["students"]
    assert [
        {
            "student_id": record.record.get("student_id"),
            "reason_code": record.reason.value,
            "field": record.field_name,
        }
        for record in quarantined
    ] == expected["quarantined"]
