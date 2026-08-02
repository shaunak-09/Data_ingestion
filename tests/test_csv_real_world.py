"""CSV exports from spreadsheet tools: quoting, CRLF, blanks, and duplicate headers."""

from __future__ import annotations

from src.ingest.csv_source import read_csv_chunks
from src.storage import LocalObjectStore
from src.transform import to_student
from src.validate import validate_chunk


def test_excel_style_csv_export_parses_without_mangling_rows(tmp_path, samples_dir):
    body = (samples_dir / "students_excel_export.csv").read_text(encoding="utf-8")
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    store = LocalObjectStore(tmp_path)
    store.ensure_container("landing")
    store.write_bytes(
        "landing",
        "students_excel_export.csv",
        body.replace("\n", "\r\n").encode("utf-8"),
    )

    records = [
        record
        for chunk in read_csv_chunks(
            store,
            "landing",
            "students_excel_export.csv",
            chunk_size=2,
        )
        for record in chunk
    ]
    valid, quarantined = validate_chunk(
        records,
        source_system="csv",
        source_object="students_excel_export.csv",
        correlation_id="cid",
    )
    students = [to_student(record, "csv") for record in valid]

    assert quarantined == []
    assert [student.student_id for student in students] == ["S9001", "S9002", "S9003"]
    assert students[0].last_name == "Nguyen, Jr."
    assert students[0].guardian_contact == "123 Main St\r\nApt 4"
    assert students[0].email == "ava.nguyen@example.edu"
    assert students[1].first_name == "José"
    assert students[1].last_name == "García"
    assert students[1].grade_level == 9
    assert students[2].last_name == "Öztürk"
    assert students[2].grade_level == 0
