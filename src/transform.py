"""Source record -> canonical `Student`.

Deterministic by rule: no clock reads, no randomness, no network. Same input, same output.

The small parsers here are the single source of truth for "what is a valid value". `validate.py`
calls them to decide pass/fail, so the two modules can never disagree.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from src.models import INTERNAL_KEYS, Student

EMAIL_PATTERN = re.compile(r"^[^@\s,;]+@[^@\s,;.]+(\.[^@\s,;.]+)+$")

MAX_FIELD_LENGTHS = {
    "student_id": 64,
    "first_name": 100,
    "last_name": 100,
    "school_id": 64,
    "email": 255,
    "guardian_contact": 255,
    "enrollment_status": 32,
}

MIN_GRADE_LEVEL = -1  # pre-kindergarten
MAX_GRADE_LEVEL = 12

_STATUS_ALIASES = {
    "active": "active",
    "enrolled": "active",
    "enrolled_active": "active",
    "inactive": "inactive",
    "unenrolled": "inactive",
    "not_enrolled": "inactive",
    "on_leave": "inactive",
    "graduated": "graduated",
    "grad": "graduated",
    "transferred": "transferred",
    "transfer": "transferred",
    "transferred_out": "transferred",
    "withdrawn": "withdrawn",
    "withdrew": "withdrawn",
    "dropped": "withdrawn",
}

_GRADE_ALIASES = {
    "pk": -1,
    "prek": -1,
    "pre_k": -1,
    "k": 0,
    "kg": 0,
    "kindergarten": 0,
}

# Only unambiguous formats are accepted. `03/04/2026` is rejected on purpose - it could be
# March 4th or April 3rd, and guessing would silently corrupt freshness comparisons.
_TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


class TransformError(ValueError):
    """A record reached the transform with a value the validator should have rejected."""


def clean_text(value: Any) -> str | None:
    """Trim to a non-empty string, or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_email(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    lowered = text.lower()
    return lowered if EMAIL_PATTERN.match(lowered) else None


def parse_grade_level(value: Any) -> int | None:
    """Returns the grade as an int. None means 'not a usable grade'."""
    text = clean_text(value)
    if text is None:
        return None
    alias = _GRADE_ALIASES.get(text.lower().replace("-", "_").replace(" ", "_"))
    if alias is not None:
        return alias
    try:
        grade = int(float(text)) if "." in text else int(text)
    except ValueError:
        return None
    if MIN_GRADE_LEVEL <= grade <= MAX_GRADE_LEVEL:
        return grade
    return None


def parse_enrollment_status(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    key = text.lower().replace("-", "_").replace(" ", "_")
    return _STATUS_ALIASES.get(key)


def parse_timestamp(value: Any) -> datetime | None:
    """Parse to a timezone-aware UTC datetime. Naive input is assumed to be UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = clean_text(value)
        if text is None:
            return None
        candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = None
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            for fmt in _TIMESTAMP_FORMATS:
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def raw_payload(record: dict[str, Any]) -> dict[str, Any]:
    """The source record as received, minus our own bookkeeping keys."""
    return {key: value for key, value in record.items() if key not in INTERNAL_KEYS}


def _required(record: dict[str, Any], field: str) -> str:
    value = clean_text(record.get(field))
    if value is None:
        raise TransformError(f"missing required field: {field}")
    return value


def to_student(record: dict[str, Any], source_system: str) -> Student:
    """Map one validated record. Raises `TransformError` if a value is still unusable."""
    email = parse_email(record.get("email"))
    if email is None:
        raise TransformError("email is not usable")
    status = parse_enrollment_status(record.get("enrollment_status"))
    if status is None:
        raise TransformError("enrollment_status is not usable")
    updated_at = parse_timestamp(record.get("updated_at"))
    if updated_at is None:
        raise TransformError("updated_at is not usable")

    return Student(
        student_id=_required(record, "student_id"),
        first_name=_required(record, "first_name"),
        last_name=_required(record, "last_name"),
        grade_level=parse_grade_level(record.get("grade_level")),
        school_id=_required(record, "school_id"),
        email=email,
        enrollment_status=status,
        updated_at=updated_at,
        guardian_contact=clean_text(record.get("guardian_contact")),
        source_system=source_system,
        raw_payload=raw_payload(record),
    )
