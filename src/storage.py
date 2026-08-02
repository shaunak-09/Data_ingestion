"""Object storage access. One interface, two backends: Azure Blob and a local folder.

The local backend is what makes `AGENTS.md` rule 5 (testable without Azure) possible.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from azure.core import MatchConditions
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from src.config import StorageSettings
from src.logging_setup import log_event

LOG = logging.getLogger(__name__)

_READ_BUFFER_BYTES = 1024 * 1024


class ObjectVersionMismatchError(RuntimeError):
    """The object changed after it was listed for processing."""


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    """Identity of one stored object. `version` changes whenever the content changes."""

    name: str
    version: str
    size: int


class ObjectStore(Protocol):
    def ensure_container(self, container: str) -> None: ...

    def list_objects(self, container: str, prefix: str = "") -> list[ObjectInfo]: ...

    def open_stream(
        self, container: str, name: str, *, expected_version: str | None = None
    ) -> BinaryIO: ...

    def write_bytes(self, container: str, name: str, data: bytes) -> None: ...

    def write_text(self, container: str, name: str, text: str) -> None: ...

    def move(
        self,
        container: str,
        name: str,
        dest_container: str,
        *,
        expected_version: str | None = None,
    ) -> None: ...


class LocalObjectStore:
    """Containers are folders under `root`. Used for local runs and tests."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _path(self, container: str, name: str) -> Path:
        target = (self._root / container / name).resolve()
        container_root = (self._root / container).resolve()
        if container_root != target and container_root not in target.parents:
            raise ValueError(f"object name escapes its container: {name!r}")
        return target

    def ensure_container(self, container: str) -> None:
        (self._root / container).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _version(stat: os.stat_result) -> str:
        return f"{stat.st_size}-{stat.st_mtime_ns}"

    def list_objects(self, container: str, prefix: str = "") -> list[ObjectInfo]:
        base = self._root / container
        if not base.is_dir():
            return []
        found = []
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(base).as_posix()
            if not name.startswith(prefix):
                continue
            stat = path.stat()
            found.append(ObjectInfo(name=name, version=self._version(stat), size=stat.st_size))
        return found

    def open_stream(
        self, container: str, name: str, *, expected_version: str | None = None
    ) -> BinaryIO:
        # The caller owns and closes the returned stream.
        source = open(  # noqa: SIM115
            self._path(container, name), "rb", buffering=_READ_BUFFER_BYTES
        )
        actual_version = self._version(os.fstat(source.fileno()))
        if expected_version is not None and actual_version != expected_version:
            source.close()
            raise ObjectVersionMismatchError(
                f"{name!r} changed before it could be read "
                f"(expected {expected_version!r}, found {actual_version!r})"
            )
        return source

    def write_bytes(self, container: str, name: str, data: bytes) -> None:
        path = self._path(container, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_text(self, container: str, name: str, text: str) -> None:
        path = self._path(container, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def move(
        self,
        container: str,
        name: str,
        dest_container: str,
        *,
        expected_version: str | None = None,
    ) -> None:
        source = self._path(container, name)
        if expected_version is not None:
            actual_version = self._version(source.stat())
            if actual_version != expected_version:
                raise ObjectVersionMismatchError(
                    f"{name!r} changed before it could be moved "
                    f"(expected {expected_version!r}, found {actual_version!r})"
                )
        destination = self._path(dest_container, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))


class _DownloaderStream(io.RawIOBase):
    """Adapts an Azure downloader (which only offers `read(n)`) to a readable raw stream."""

    def __init__(self, downloader: object) -> None:
        self._downloader = downloader

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
        chunk = self._downloader.read(len(buffer))  # type: ignore[attr-defined]
        if not chunk:
            return 0
        buffer[: len(chunk)] = chunk
        return len(chunk)


class BlobObjectStore:
    """Azure Blob Storage via Managed Identity (no account keys, no connection strings)."""

    def __init__(self, account_name: str, credential: object | None = None) -> None:
        self._client = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=credential or DefaultAzureCredential(),
        )

    def ensure_container(self, container: str) -> None:
        client = self._client.get_container_client(container)
        if not client.exists():
            client.create_container()

    def list_objects(self, container: str, prefix: str = "") -> list[ObjectInfo]:
        client = self._client.get_container_client(container)
        blobs = client.list_blobs(name_starts_with=prefix or None)
        found = [
            ObjectInfo(
                name=blob.name,
                version=blob.etag or "",
                size=blob.size or 0,
            )
            for blob in blobs
        ]
        return sorted(found, key=lambda item: item.name)

    def open_stream(
        self, container: str, name: str, *, expected_version: str | None = None
    ) -> BinaryIO:
        options = (
            {"etag": expected_version, "match_condition": MatchConditions.IfNotModified}
            if expected_version
            else {}
        )
        downloader = self._client.get_blob_client(container, name).download_blob(**options)
        return io.BufferedReader(_DownloaderStream(downloader), buffer_size=_READ_BUFFER_BYTES)

    def write_text(self, container: str, name: str, text: str) -> None:
        self._client.get_blob_client(container, name).upload_blob(
            text.encode("utf-8"), overwrite=True
        )

    def write_bytes(self, container: str, name: str, data: bytes) -> None:
        self._client.get_blob_client(container, name).upload_blob(data, overwrite=True)

    def move(
        self,
        container: str,
        name: str,
        dest_container: str,
        *,
        expected_version: str | None = None,
    ) -> None:
        # Streamed copy, not a server-side copy: server-side copy needs a SAS or a source
        # authorization header, which we avoid so plain RBAC is the only permission needed.
        # Memory stays bounded because both sides stream.
        source = self._client.get_blob_client(container, name)
        options = (
            {"etag": expected_version, "match_condition": MatchConditions.IfNotModified}
            if expected_version
            else {}
        )
        with io.BufferedReader(
            _DownloaderStream(source.download_blob(**options)), buffer_size=_READ_BUFFER_BYTES
        ) as stream:
            self._client.get_blob_client(dest_container, name).upload_blob(stream, overwrite=True)
        source.delete_blob(**options)
        log_event(LOG, logging.INFO, "storage.moved", name=name, to_container=dest_container)


def build_object_store(settings: StorageSettings) -> ObjectStore:
    """Local folder when LOCAL_STORAGE_ROOT is set, Azure Blob otherwise."""
    if settings.use_local:
        assert settings.local_root is not None
        return LocalObjectStore(settings.local_root)
    assert settings.account_name is not None
    return BlobObjectStore(settings.account_name)
