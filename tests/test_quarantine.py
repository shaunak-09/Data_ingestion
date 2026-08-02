"""Quarantine files are deterministic by run and chunk."""

from __future__ import annotations

import json

from src.models import QuarantinedRecord, ReasonCode
from src.quarantine import QuarantineWriter
from src.storage import LocalObjectStore


def rejected(student_id: str, detail: str) -> QuarantinedRecord:
    return QuarantinedRecord(
        reason=ReasonCode.INVALID_EMAIL,
        detail=detail,
        field_name="email",
        record={"student_id": student_id, "email": "bad"},
        source_system="csv",
        source_object="students.csv",
        correlation_id="cid",
    )


def test_rewriting_the_same_bad_chunk_overwrites_the_quarantine_file(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.ensure_container("quarantine")
    writer = QuarantineWriter(store, "quarantine")

    first_name = writer.write(
        [rejected("S1", "first")],
        source_system="csv",
        run_id="42",
        chunk_index=3,
    )
    second_name = writer.write(
        [rejected("S1", "second")],
        source_system="csv",
        run_id="42",
        chunk_index=3,
    )

    objects = store.list_objects("quarantine")
    assert first_name == second_name == "csv/42/chunk-00003.jsonl"
    assert [info.name for info in objects] == ["csv/42/chunk-00003.jsonl"]
    with store.open_stream("quarantine", objects[0].name) as stream:
        lines = stream.read().decode("utf-8").splitlines()
    assert [json.loads(line)["detail"] for line in lines] == ["second"]
