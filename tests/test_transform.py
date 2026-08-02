"""Transform rules: deterministic, normalising, and never guessing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.transform import (
    TransformError,
    parse_email,
    parse_enrollment_status,
    parse_grade_level,
    parse_timestamp,
    to_student,
)

BASE_RECORD = {
    "student_id": " S1001 ",
    "first_name": "Ava",
    "last_name": "Nguyen",
    "grade_level": "9",
    "school_id": "SCH-01",
    "email": "AVA.Nguyen@Example.EDU",
    "enrollment_status": "Enrolled",
    "updated_at": "2026-07-30T08:15:00Z",
    "guardian_contact": " +1-206-555-0101 ",
    "_source_line": 2,
}


def test_to_student_normalises_every_field():
    student = to_student(BASE_RECORD, "csv")

    assert student.student_id == "S1001"
    assert student.email == "ava.nguyen@example.edu"
    assert student.enrollment_status == "active"
    assert student.grade_level == 9
    assert student.updated_at == datetime(2026, 7, 30, 8, 15, tzinfo=UTC)
    assert student.guardian_contact == "+1-206-555-0101"
    assert student.source_system == "csv"


def test_transform_is_deterministic():
    assert to_student(BASE_RECORD, "csv") == to_student(BASE_RECORD, "csv")


def test_raw_payload_keeps_source_values_and_drops_internal_keys():
    student = to_student(BASE_RECORD, "csv")

    assert student.raw_payload["email"] == "AVA.Nguyen@Example.EDU"
    assert "_source_line" not in student.raw_payload


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("K", 0), ("k", 0), ("PK", -1), ("pre-k", -1), ("12", 12), ("3.0", 3), ("0", 0)],
)
def test_grade_level_aliases(raw, expected):
    assert parse_grade_level(raw) == expected


@pytest.mark.parametrize("raw", ["13", "-2", "grade nine", "", None, "1st"])
def test_unusable_grade_levels_return_none(raw):
    assert parse_grade_level(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.0", 10),
        ("9.5", None),
        ("09", 9),
        ("TK", None),
        ("Grade 9", None),
        ("9th", None),
        ("-2", None),
        ("999", None),
    ],
)
def test_real_system_grade_values_pin_current_behavior(raw, expected):
    assert parse_grade_level(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("active", "active"),
        ("ENROLLED", "active"),
        ("Transferred Out", "transferred"),
        ("withdrew", "withdrawn"),
        ("graduated", "graduated"),
    ],
)
def test_enrollment_status_aliases(raw, expected):
    assert parse_enrollment_status(raw) == expected


def test_unknown_enrollment_status_returns_none():
    assert parse_enrollment_status("enrolled_forever") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-07-30T08:15:00Z", datetime(2026, 7, 30, 8, 15, tzinfo=UTC)),
        ("2026-07-29T16:45:00+02:00", datetime(2026, 7, 29, 14, 45, tzinfo=UTC)),
        ("2026-07-30 09:00:00", datetime(2026, 7, 30, 9, 0, tzinfo=UTC)),
        ("2026-07-28", datetime(2026, 7, 28, 0, 0, tzinfo=UTC)),
    ],
)
def test_timestamps_land_in_utc(raw, expected):
    assert parse_timestamp(raw) == expected


@pytest.mark.parametrize("raw", ["30/07/2026", "07/30/2026", "yesterday", "", None])
def test_ambiguous_or_unparseable_timestamps_are_rejected(raw):
    """Guessing between day-first and month-first would silently corrupt freshness checks."""
    assert parse_timestamp(raw) is None


def test_future_timestamp_is_currently_accepted():
    assert parse_timestamp("2099-01-01") == datetime(2099, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("raw", [1710000000, "2026-13-45"])
def test_bad_real_system_dates_return_none(raw):
    assert parse_timestamp(raw) is None


def test_mixed_timezone_timestamps_land_in_utc():
    assert parse_timestamp("2026-07-30T08:00:00-04:00") == datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "raw", ["ivy.chen(at)example.edu", "priya.nair@example", "a b@example.com", "@example.com", ""]
)
def test_invalid_emails_return_none(raw):
    assert parse_email(raw) is None


def test_transform_refuses_a_record_that_never_passed_validation():
    with pytest.raises(TransformError):
        to_student({**BASE_RECORD, "email": "not-an-email"}, "csv")
