"""Settings. This is the only module that reads the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """A required setting is missing or unusable."""


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _get_required(name: str) -> str:
    value = _get(name)
    if value is None:
        raise ConfigError(f"{name} is required but not set")
    return value


def _get_int(name: str, default: int) -> int:
    raw = _get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = _get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class StorageSettings:
    landing_container: str
    processed_container: str
    quarantine_container: str
    account_name: str | None = None
    local_root: str | None = None

    @property
    def use_local(self) -> bool:
        """A local folder replaces Blob Storage when LOCAL_STORAGE_ROOT is set."""
        return self.local_root is not None


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str | None
    sslmode: str
    use_managed_identity: bool

    def conninfo(self, password: str | None = None) -> str:
        """Build a libpq connection string. Never log the result."""
        secret = password if password is not None else self.password
        parts = [
            f"host={self.host}",
            f"port={self.port}",
            f"dbname={self.database}",
            f"user={self.user}",
            f"sslmode={self.sslmode}",
        ]
        if secret:
            parts.append(f"password={secret}")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class ApiSettings:
    base_url: str
    students_path: str
    auth_type: str
    token_url: str | None
    client_id: str | None
    client_secret: str | None
    static_token: str | None
    token_expiry_skew_seconds: int
    page_size: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class RetrySettings:
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float


@dataclass(frozen=True, slots=True)
class Settings:
    storage: StorageSettings
    database: DatabaseSettings
    api: ApiSettings
    retry: RetrySettings
    chunk_size: int
    run_stale_after_seconds: int
    log_level: str
    csv_schedule_cron: str
    api_schedule_cron: str


def load_settings() -> Settings:
    """Read every setting from the environment once."""
    storage = StorageSettings(
        landing_container=_get("BLOB_LANDING_CONTAINER", "landing") or "landing",
        processed_container=_get("BLOB_PROCESSED_CONTAINER", "processed") or "processed",
        quarantine_container=_get("BLOB_QUARANTINE_CONTAINER", "quarantine") or "quarantine",
        account_name=_get("STORAGE_ACCOUNT_NAME"),
        local_root=_get("LOCAL_STORAGE_ROOT"),
    )
    if not storage.use_local and storage.account_name is None:
        raise ConfigError("set STORAGE_ACCOUNT_NAME, or LOCAL_STORAGE_ROOT for local runs")

    database = DatabaseSettings(
        host=_get("PG_HOST", "localhost") or "localhost",
        port=_get_int("PG_PORT", 5432),
        database=_get("PG_DATABASE", "students") or "students",
        user=_get_required("PG_USER"),
        password=_get("PG_PASSWORD"),
        sslmode=_get("PG_SSLMODE", "prefer") or "prefer",
        use_managed_identity=_get_bool("PG_USE_MANAGED_IDENTITY", False),
    )

    api = ApiSettings(
        base_url=(_get("API_BASE_URL", "") or "").rstrip("/"),
        students_path=_get("API_STUDENTS_PATH", "/students") or "/students",
        auth_type=(_get("API_AUTH_TYPE", "oauth2_client_credentials") or "").lower(),
        token_url=_get("API_TOKEN_URL"),
        client_id=_get("API_CLIENT_ID"),
        client_secret=_get("API_CLIENT_SECRET"),
        static_token=_get("API_STATIC_TOKEN"),
        token_expiry_skew_seconds=_get_int("API_TOKEN_EXPIRY_SKEW_SECONDS", 30),
        page_size=_get_int("API_PAGE_SIZE", 100),
        timeout_seconds=_get_float("API_TIMEOUT_SECONDS", 30.0),
    )

    retry = RetrySettings(
        max_attempts=_get_int("RETRY_MAX_ATTEMPTS", 5),
        base_delay_seconds=_get_float("RETRY_BASE_DELAY_SECONDS", 1.0),
        max_delay_seconds=_get_float("RETRY_MAX_DELAY_SECONDS", 60.0),
    )

    return Settings(
        storage=storage,
        database=database,
        api=api,
        retry=retry,
        chunk_size=_get_int("CHUNK_SIZE", 5000),
        run_stale_after_seconds=_get_int("RUN_STALE_AFTER_SECONDS", 3600),
        log_level=_get("LOG_LEVEL", "INFO") or "INFO",
        csv_schedule_cron=_get("CSV_SCHEDULE_CRON", "0 0 2 * * *") or "0 0 2 * * *",
        api_schedule_cron=_get("API_SCHEDULE_CRON", "0 0 * * * *") or "0 0 * * * *",
    )
