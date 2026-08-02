"""Validation rules: strict, never raising, and deterministic about duplicates."""

from __future__ import annotations

from src.models import EXTRA_COLUMNS_KEY, SOURCE_LINE_KEY, ReasonCode
from src.validate import validate_chunk

GOOD = {
    "student_id": "S1",
    "first_name": "Ava",
    "last_name": "Nguyen",
    "grade_level": "9",
    "school_id": "SCH-01",
    "email": "ava@example.edu",
    "enrollment_status": "active",
    "updated_at": "2026-07-30T08:15:00Z",
    "guardian_contact": "+1-206-555-0101",
}


def run(records):
    return validate_chunk(
        records, source_system="csv", source_object="test.csv", correlation_id="cid"
    )


def test_a_good_record_passes_through_unchanged():
    valid, quarantined = run([GOOD])

    assert valid == [GOOD]
    assert quarantined == []


def test_one_bad_record_does_not_take_the_batch_with_it():
    valid, quarantined = run([GOOD, {**GOOD, "student_id": "S2", "email": "nope"}])

    assert [record["student_id"] for record in valid] == ["S1"]
    assert quarantined[0].reason is ReasonCode.INVALID_EMAIL


def test_missing_required_field_names_the_field():
    _, quarantined = run([{**GOOD, "first_name": "   "}])

    assert quarantined[0].reason is ReasonCode.MISSING_REQUIRED_FIELD
    assert quarantined[0].field_name == "first_name"


def test_extra_columns_are_malformed():
    _, quarantined = run([{**GOOD, EXTRA_COLUMNS_KEY: ["surprise"]}])

    assert quarantined[0].reason is ReasonCode.MALFORMED_ROW


def test_short_csv_row_is_malformed():
    short_row = {**GOOD, "guardian_contact": None, SOURCE_LINE_KEY: 5}
    _, quarantined = run([short_row])

    assert quarantined[0].reason is ReasonCode.MALFORMED_ROW


def test_api_null_optional_field_is_not_malformed():
    """A JSON null for an optional field is normal; only CSV short rows are malformed."""
    valid, quarantined = run([{**GOOD, "guardian_contact": None}])

    assert len(valid) == 1
    assert quarantined == []


def test_bad_grade_status_and_timestamp_each_get_their_own_reason():
    _, quarantined = run(
        [
            {**GOOD, "student_id": "A", "grade_level": "14"},
            {**GOOD, "student_id": "B", "enrollment_status": "enrolled_forever"},
            {**GOOD, "student_id": "C", "updated_at": "30/07/2026"},
        ]
    )

    assert [record.reason for record in quarantined] == [
        ReasonCode.INVALID_GRADE_LEVEL,
        ReasonCode.UNKNOWN_ENROLLMENT_STATUS,
        ReasonCode.INVALID_TIMESTAMP,
    ]


def test_epoch_number_and_impossible_calendar_date_are_invalid_timestamps():
    _, quarantined = run(
        [
            {**GOOD, "student_id": "EPOCH", "updated_at": 1710000000},
            {**GOOD, "student_id": "BAD-DATE", "updated_at": "2026-13-45"},
        ]
    )

    assert [record.reason for record in quarantined] == [
        ReasonCode.INVALID_TIMESTAMP,
        ReasonCode.INVALID_TIMESTAMP,
    ]


def test_fractional_grade_is_invalid():
    _, quarantined = run([{**GOOD, "student_id": "FRACTIONAL", "grade_level": "9.5"}])

    assert quarantined[0].reason is ReasonCode.INVALID_GRADE_LEVEL


def test_future_timestamp_is_invalid():
    valid, quarantined = run([{**GOOD, "student_id": "FUTURE", "updated_at": "2099-01-01"}])

    assert valid == []
    assert quarantined[0].reason is ReasonCode.INVALID_TIMESTAMP
    assert quarantined[0].detail == "updated_at is too far in the future"


def test_over_long_value_is_rejected():
    _, quarantined = run([{**GOOD, "student_id": "x" * 65}])

    assert quarantined[0].reason is ReasonCode.FIELD_TOO_LONG


def test_duplicate_in_chunk_keeps_the_freshest_row():
    older = {**GOOD, "updated_at": "2026-07-30T07:00:00Z", "first_name": "Old"}
    newer = {**GOOD, "updated_at": "2026-07-30T09:00:00Z", "first_name": "New"}

    valid, quarantined = run([newer, older])

    assert [record["first_name"] for record in valid] == ["New"]
    assert quarantined[0].reason is ReasonCode.DUPLICATE_STUDENT_ID
    assert quarantined[0].record["first_name"] == "Old"


def test_duplicate_tie_is_broken_by_the_later_row():
    first = {**GOOD, "first_name": "First"}
    second = {**GOOD, "first_name": "Second"}

    valid, _ = run([first, second])

    assert [record["first_name"] for record in valid] == ["Second"]


def test_survivors_keep_source_order():
    records = [
        {**GOOD, "student_id": "S1"},
        {**GOOD, "student_id": "S2"},
        {**GOOD, "student_id": "S3"},
    ]

    valid, _ = run(records)

    assert [record["student_id"] for record in valid] == ["S1", "S2", "S3"]


def test_garbage_input_is_quarantined_not_raised():
    valid, quarantined = run([{}, {"student_id": None}, {"unexpected": "shape"}])

    assert valid == []
    assert len(quarantined) == 3
    assert all(record.reason is ReasonCode.MISSING_REQUIRED_FIELD for record in quarantined)


def test_quarantine_record_is_machine_readable():
    _, quarantined = run([{**GOOD, "email": "nope"}])
    payload = quarantined[0].to_json_dict()

    assert payload["reason_code"] == "INVALID_EMAIL"
    assert payload["field"] == "email"
    assert payload["source_object"] == "test.csv"
    assert payload["correlation_id"] == "cid"
