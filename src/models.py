"""Canonical data shapes shared by every stage."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

CANONICAL_FIELDS = (
    "student_id",
    "first_name",
    "last_name",
    "grade_level",
    "school_id",
    "email",
    "enrollment_status",
    "updated_at",
    "guardian_contact",
)

REQUIRED_FIELDS = (
    "student_id",
    "first_name",
    "last_name",
    "school_id",
    "email",
    "enrollment_status",
    "updated_at",
)

ENROLLMENT_STATUSES = ("active", "inactive", "graduated", "transferred", "withdrawn")

# Keys the adapters add for internal bookkeeping. They never reach the database columns.
EXTRA_COLUMNS_KEY = "_extra_columns"
SOURCE_LINE_KEY = "_source_line"
INTERNAL_KEYS = (EXTRA_COLUMNS_KEY, SOURCE_LINE_KEY)


class ReasonCode(str, Enum):
    """Machine-readable quarantine reasons. Values are stable; never rename in place."""

    MALFORMED_ROW = "MALFORMED_ROW"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_EMAIL = "INVALID_EMAIL"
    INVALID_GRADE_LEVEL = "INVALID_GRADE_LEVEL"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    UNKNOWN_ENROLLMENT_STATUS = "UNKNOWN_ENROLLMENT_STATUS"
    FIELD_TOO_LONG = "FIELD_TOO_LONG"
    DUPLICATE_STUDENT_ID = "DUPLICATE_STUDENT_ID"
    TRANSFORM_FAILED = "TRANSFORM_FAILED"


@dataclass(frozen=True, slots=True)
class Student:
    """One canonical student record, ready to persist."""

    student_id: str
    first_name: str
    last_name: str
    grade_level: int | None
    school_id: str
    email: str
    enrollment_status: str
    updated_at: datetime
    guardian_contact: str | None
    source_system: str
    raw_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class QuarantinedRecord:
    """A rejected source record plus why it was rejected."""

    reason: ReasonCode
    detail: str
    field_name: str | None
    record: dict[str, Any]
    source_system: str
    source_object: str | None
    correlation_id: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason.value,
            "detail": self.detail,
            "field": self.field_name,
            "source_system": self.source_system,
            "source_object": self.source_object,
            "correlation_id": self.correlation_id,
            "record": self.record,
        }


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """Outcome of one conditional upsert batch."""

    submitted: int
    inserted: int
    updated: int

    @property
    def skipped(self) -> int:
        """Rows the database refused to overwrite because it already held newer data."""
        return self.submitted - self.inserted - self.updated


@dataclass(slots=True)
class RunSummary:
    """Counts for one pipeline run. Logged and returned to the trigger."""

    source_system: str
    correlation_id: str
    chunks: int = 0
    read: int = 0
    valid: int = 0
    quarantined: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    max_updated_at: datetime | None = None

    def add_upsert(self, result: UpsertResult) -> None:
        self.inserted += result.inserted
        self.updated += result.updated
        self.skipped += result.skipped

    def observe(self, students: Sequence[Student]) -> None:
        """Track the freshest record seen. The API watermark is advanced from this."""
        for student in students:
            if self.max_updated_at is None or student.updated_at > self.max_updated_at:
                self.max_updated_at = student.updated_at

    def as_fields(self) -> dict[str, Any]:
        return {
            "source_system": self.source_system,
            "chunks": self.chunks,
            "read": self.read,
            "valid": self.valid,
            "quarantined": self.quarantined,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
        }
