"""HTTP endpoint that uploads a CSV into the landing container."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import default
from pathlib import PurePath

import azure.functions as func

from src.config import load_settings
from src.logging_setup import configure_logging, log_event, new_correlation_id, set_correlation_id
from src.storage import build_object_store

LOG = logging.getLogger(__name__)

bp = func.Blueprint()

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class UploadError(ValueError):
    """The client sent a request we cannot store as a CSV upload."""


@dataclass(frozen=True, slots=True)
class UploadedCsv:
    filename: str
    data: bytes


def _json_response(status_code: int, payload: dict[str, object]) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload),
        status_code=status_code,
        mimetype="application/json",
    )


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def _multipart_message(content_type: str, body: bytes):
    if "multipart/form-data" not in content_type.lower():
        raise UploadError("request must use multipart/form-data")
    raw = (f"Content-Type: {content_type}\r\n" "MIME-Version: 1.0\r\n" "\r\n").encode() + body
    message = BytesParser(policy=default).parsebytes(raw)
    if not message.is_multipart():
        raise UploadError("multipart body is missing file parts")
    return message


def parse_upload(content_type: str, body: bytes) -> UploadedCsv:
    message = _multipart_message(content_type, body)
    matches: list[UploadedCsv] = []
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        if part.get_param("name", header="content-disposition") != "file":
            continue
        filename = part.get_filename()
        data = part.get_payload(decode=True) or b""
        if not filename:
            raise UploadError("file field must include a filename")
        if not data:
            raise UploadError("uploaded CSV is empty")
        matches.append(UploadedCsv(filename=filename, data=data))

    if not matches:
        raise UploadError("multipart request must include a file field")
    if len(matches) > 1:
        raise UploadError("upload exactly one CSV file")
    return matches[0]


def upload_object_name(
    filename: str, now: datetime | None = None, unique_id: str | None = None
) -> str:
    safe_name = PurePath(filename.replace("\\", "/")).name
    safe_name = _SAFE_FILENAME.sub("-", safe_name).strip(".-_")
    if not safe_name:
        raise UploadError("filename is empty")
    if not safe_name.lower().endswith(".csv"):
        raise UploadError("uploaded file must have a .csv extension")

    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    suffix = unique_id or uuid.uuid4().hex
    return f"uploads/{timestamp}-{suffix}-{safe_name}"


@bp.route(route="csv/upload", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def upload_csv(req: func.HttpRequest) -> func.HttpResponse:
    settings = load_settings()
    configure_logging(settings.log_level)
    set_correlation_id(new_correlation_id())

    try:
        upload = parse_upload(_header(req.headers, "content-type"), req.get_body())
        object_name = upload_object_name(upload.filename)
    except UploadError as exc:
        return _json_response(400, {"error": str(exc)})

    store = build_object_store(settings.storage)
    store.ensure_container(settings.storage.landing_container)
    store.write_bytes(settings.storage.landing_container, object_name, upload.data)

    log_event(
        LOG,
        logging.INFO,
        "upload.csv_staged",
        object_name=object_name,
        bytes_written=len(upload.data),
    )
    return _json_response(
        201,
        {
            "container": settings.storage.landing_container,
            "object_name": object_name,
            "bytes_written": len(upload.data),
        },
    )
