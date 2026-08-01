"""CSV adapter: chunking, header cleanup, malformed markers, and streaming."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from src.ingest.csv_source import read_csv_chunks
from src.models import EXTRA_COLUMNS_KEY, SOURCE_LINE_KEY
from src.storage import LocalObjectStore, ObjectVersionMismatchError

HEADER = (
    "student_id,first_name,last_name,grade_level,school_id,email,"
    "enrollment_status,updated_at,guardian_contact"
)


def write_csv(root: Path, name: str, body: str) -> LocalObjectStore:
    store = LocalObjectStore(root)
    store.ensure_container("landing")
    store.write_text("landing", name, body)
    return store


def test_rows_arrive_in_chunks_of_the_configured_size(tmp_path):
    rows = "\n".join(
        f"S{index},A,B,1,SCH,a{index}@example.edu,active,2026-07-30T00:00:00Z,x"
        for index in range(5)
    )
    store = write_csv(tmp_path, "students.csv", f"{HEADER}\n{rows}\n")

    chunks = list(read_csv_chunks(store, "landing", "students.csv", chunk_size=2))

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]


def test_headers_are_trimmed_lowercased_and_bom_stripped(tmp_path):
    body = "\ufeff Student_ID , First_Name \nS1,Ava\n"
    store = write_csv(tmp_path, "odd_header.csv", body)

    chunk = next(iter(read_csv_chunks(store, "landing", "odd_header.csv", chunk_size=10)))

    assert chunk[0]["student_id"] == "S1"
    assert chunk[0]["first_name"] == "Ava"


def test_extra_and_missing_values_are_marked_for_the_validator(tmp_path):
    body = f"{HEADER}\nS1,A,B,1,SCH,a@example.edu,active,2026-07-30T00:00:00Z,x,extra\nS2,A,B\n"
    store = write_csv(tmp_path, "broken.csv", body)

    chunk = next(iter(read_csv_chunks(store, "landing", "broken.csv", chunk_size=10)))

    assert chunk[0][EXTRA_COLUMNS_KEY] == ["extra"]
    assert chunk[1]["email"] is None
    assert chunk[1][SOURCE_LINE_KEY] == 3


def test_empty_file_yields_nothing(tmp_path):
    store = write_csv(tmp_path, "empty.csv", "")

    assert list(read_csv_chunks(store, "landing", "empty.csv", chunk_size=10)) == []


def test_chunk_size_must_be_positive(tmp_path):
    store = write_csv(tmp_path, "students.csv", f"{HEADER}\n")

    with pytest.raises(ValueError):
        next(iter(read_csv_chunks(store, "landing", "students.csv", chunk_size=0)))


class _CountingStore:
    """Wraps a store and counts how many bytes actually leave storage."""

    def __init__(self, inner: LocalObjectStore) -> None:
        self._inner = inner
        self.bytes_read = 0

    def open_stream(self, container: str, name: str, *, expected_version: str | None = None):
        source = self._inner.open_stream(container, name, expected_version=expected_version)
        counter = self

        class _Counting(io.RawIOBase):
            def readable(self) -> bool:
                return True

            def readinto(self, buffer) -> int:
                data = source.read(len(buffer))
                if not data:
                    return 0
                buffer[: len(data)] = data
                counter.bytes_read += len(data)
                return len(data)

            def close(self) -> None:
                source.close()
                super().close()

        return io.BufferedReader(_Counting(), buffer_size=8192)


def test_large_file_is_streamed_not_loaded(tmp_path):
    """The first chunk must be usable long before the whole file has been read."""
    rows = "\n".join(
        f"S{index},Firstname,Lastname,7,SCH-01,student{index}@example.edu,"
        f"active,2026-07-30T00:00:00Z,+1-206-555-0100"
        for index in range(20_000)
    )
    body = f"{HEADER}\n{rows}\n"
    inner = write_csv(tmp_path, "big.csv", body)
    store = _CountingStore(inner)

    chunks = read_csv_chunks(store, "landing", "big.csv", chunk_size=10)
    first_chunk = next(iter(chunks))

    assert len(first_chunk) == 10
    assert store.bytes_read < len(body.encode("utf-8")) / 10


def test_file_version_mismatch_stops_the_read(tmp_path):
    store = write_csv(tmp_path, "students.csv", f"{HEADER}\n")
    listed_version = store.list_objects("landing")[0].version
    store.write_text(
        "landing",
        "students.csv",
        f"{HEADER}\nS1,A,B,1,SCH,a@example.edu,active,2026-07-30T00:00:00Z,x\n",
    )

    chunks = read_csv_chunks(
        store,
        "landing",
        "students.csv",
        chunk_size=10,
        expected_version=listed_version,
    )

    with pytest.raises(ObjectVersionMismatchError, match="changed before it could be read"):
        next(chunks)
