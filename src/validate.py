"""Strict validation. One broken rule quarantines that whole row; the batch keeps going.

This module never raises on bad data. It answers with (valid rows, quarantined rows).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.models import (
    EXTRA_COLUMNS_KEY,
    INTERNAL_KEYS,
    REQUIRED_FIELDS,
    SOURCE_LINE_KEY,
    QuarantinedRecord,
    ReasonCode,
)
from src.transform import (
    MAX_FIELD_LENGTHS,
    clean_text,
    parse_email,
    parse_enrollment_status,
    parse_grade_level,
    parse_timestamp,
)

Failure = tuple[ReasonCode, str, str | None]
MAX_FUTURE_UPDATED_AT_SKEW = timedelta(days=1)


def _malformed_reason(record: dict[str, Any]) -> Failure | None:
    if EXTRA_COLUMNS_KEY in record:
        return (ReasonCode.MALFORMED_ROW, "row has more values than the header", None)
    # Only the CSV adapter sets a source line, and it fills short rows with None.
    if SOURCE_LINE_KEY in record and any(
        value is None for key, value in record.items() if key not in INTERNAL_KEYS
    ):
        return (ReasonCode.MALFORMED_ROW, "row has fewer values than the header", None)
    return None


def _field_failure(record: dict[str, Any]) -> Failure | None:
    """First broken rule wins, so the reason code is stable for a given record."""
    malformed = _malformed_reason(record)
    if malformed is not None:
        return malformed

    for field in REQUIRED_FIELDS:
        if clean_text(record.get(field)) is None:
            return (ReasonCode.MISSING_REQUIRED_FIELD, f"{field} is missing or blank", field)

    if parse_email(record.get("email")) is None:
        return (ReasonCode.INVALID_EMAIL, "email is not a valid address", "email")

    if parse_enrollment_status(record.get("enrollment_status")) is None:
        return (
            ReasonCode.UNKNOWN_ENROLLMENT_STATUS,
            "enrollment_status does not map to a canonical status",
            "enrollment_status",
        )

    updated_at = parse_timestamp(record.get("updated_at"))
    if updated_at is None:
        return (
            ReasonCode.INVALID_TIMESTAMP,
            "updated_at is not an ISO 8601 timestamp",
            "updated_at",
        )
    if updated_at > datetime.now(UTC) + MAX_FUTURE_UPDATED_AT_SKEW:
        return (
            ReasonCode.INVALID_TIMESTAMP,
            "updated_at is too far in the future",
            "updated_at",
        )

    raw_grade = clean_text(record.get("grade_level"))
    if raw_grade is not None and parse_grade_level(raw_grade) is None:
        return (
            ReasonCode.INVALID_GRADE_LEVEL,
            "grade_level is not a supported grade (PK, K, 1-12)",
            "grade_level",
        )

    for field, limit in MAX_FIELD_LENGTHS.items():
        value = clean_text(record.get(field))
        if value is not None and len(value) > limit:
            return (ReasonCode.FIELD_TOO_LONG, f"{field} is longer than {limit} characters", field)

    return None


def _dedupe(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], datetime, datetime]]]:
    """Keep the freshest record per student_id. Ties go to the later row, so it is deterministic.

    Returns the survivors in source order plus (loser, loser_updated_at, kept_updated_at).
    """
    best: dict[str, tuple[int, datetime, dict[str, Any]]] = {}
    losers: list[tuple[dict[str, Any], datetime, datetime]] = []

    for position, record in enumerate(records):
        student_id = clean_text(record.get("student_id"))
        assert student_id is not None  # guaranteed by _field_failure
        updated_at = parse_timestamp(record.get("updated_at"))
        assert updated_at is not None  # guaranteed by _field_failure

        current = best.get(student_id)
        if current is None:
            best[student_id] = (position, updated_at, record)
            continue
        _, current_updated_at, current_record = current
        if updated_at >= current_updated_at:
            best[student_id] = (position, updated_at, record)
            losers.append((current_record, current_updated_at, updated_at))
        else:
            losers.append((record, updated_at, current_updated_at))

    survivors = [record for _, (_, _, record) in sorted(best.items(), key=lambda kv: kv[1][0])]
    return survivors, losers


def validate_chunk(
    records: list[dict[str, Any]],
    *,
    source_system: str,
    source_object: str | None,
    correlation_id: str,
) -> tuple[list[dict[str, Any]], list[QuarantinedRecord]]:
    """Split one chunk into rows worth persisting and rows to quarantine with a reason code."""
    quarantined: list[QuarantinedRecord] = []
    candidates: list[dict[str, Any]] = []

    def reject(record: dict[str, Any], failure: Failure) -> None:
        reason, detail, field = failure
        quarantined.append(
            QuarantinedRecord(
                reason=reason,
                detail=detail,
                field_name=field,
                record=record,
                source_system=source_system,
                source_object=source_object,
                correlation_id=correlation_id,
            )
        )

    for record in records:
        failure = _field_failure(record)
        if failure is None:
            candidates.append(record)
        else:
            reject(record, failure)

    survivors, losers = _dedupe(candidates)
    for record, loser_updated_at, kept_updated_at in losers:
        reject(
            record,
            (
                ReasonCode.DUPLICATE_STUDENT_ID,
                f"duplicate student_id in the same chunk; kept the row updated at "
                f"{kept_updated_at.isoformat()} instead of {loser_updated_at.isoformat()}",
                "student_id",
            ),
        )

    return survivors, quarantined
