"""CSV upload endpoint tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.config import ApiSettings, DatabaseSettings, RetrySettings, Settings, StorageSettings
from triggers import upload


@pytest.fixture
def upload_settings(tmp_path: Path) -> Settings:
    return Settings(
        storage=StorageSettings(
            landing_container="landing",
            processed_container="processed",
            quarantine_container="quarantine",
            local_root=str(tmp_path / "store"),
        ),
        database=DatabaseSettings(
            host="localhost",
            port=5432,
            database="students",
            user="postgres",
            password=None,
            sslmode="prefer",
            use_managed_identity=False,
        ),
        api=ApiSettings(
            base_url="",
            students_path="/students",
            auth_type="oauth2_client_credentials",
            token_url=None,
            client_id=None,
            client_secret=None,
            static_token=None,
            token_expiry_skew_seconds=0,
            page_size=100,
            timeout_seconds=5.0,
        ),
        retry=RetrySettings(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02),
        chunk_size=5000,
        run_stale_after_seconds=3600,
        log_level="WARNING",
        csv_schedule_cron="0 0 2 * * *",
        api_schedule_cron="0 0 * * * *",
    )


class FakeRequest:
    def __init__(self, content_type: str, body: bytes) -> None:
        self.headers = {"Content-Type": content_type}
        self._body = body

    def get_body(self) -> bytes:
        return self._body


def multipart_body(filename: str, data: bytes, content_type: str = "text/csv") -> tuple[str, bytes]:
    boundary = "----student-ingest-test"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n"
            "\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return f"multipart/form-data; boundary={boundary}", body


def response_json(response) -> dict:
    return json.loads(response.get_body().decode("utf-8"))


def test_upload_object_name_sanitizes_filename():
    now = datetime(2026, 8, 1, 8, 30, tzinfo=UTC)

    name = upload.upload_object_name("../bad path/students final.csv", now=now, unique_id="abc")

    assert name == "uploads/20260801T083000Z-abc-students-final.csv"


def test_upload_csv_writes_file_to_landing(monkeypatch, upload_settings):
    monkeypatch.setattr(upload, "load_settings", lambda: upload_settings)
    content_type, body = multipart_body("students.csv", b"student_id,email\n1,a@example.com\n")

    response = upload.upload_csv(FakeRequest(content_type, body))

    assert response.status_code == 201
    payload = response_json(response)
    assert payload["container"] == "landing"
    assert payload["bytes_written"] == 33
    stored = (
        Path(upload_settings.storage.local_root)
        / upload_settings.storage.landing_container
        / payload["object_name"]
    )
    assert stored.read_bytes() == b"student_id,email\n1,a@example.com\n"


def test_upload_csv_rejects_non_multipart_request(monkeypatch, upload_settings):
    monkeypatch.setattr(upload, "load_settings", lambda: upload_settings)

    response = upload.upload_csv(FakeRequest("text/csv", b"student_id,email\n"))

    assert response.status_code == 400
    assert response_json(response) == {"error": "request must use multipart/form-data"}


def test_upload_csv_rejects_non_csv_filename(monkeypatch, upload_settings):
    monkeypatch.setattr(upload, "load_settings", lambda: upload_settings)
    content_type, body = multipart_body("students.txt", b"student_id,email\n")

    response = upload.upload_csv(FakeRequest(content_type, body))

    assert response.status_code == 400
    assert response_json(response) == {"error": "uploaded file must have a .csv extension"}
