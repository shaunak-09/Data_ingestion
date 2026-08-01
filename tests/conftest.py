"""Shared fixtures.

Everything runs with no Azure account and no network.

Database tests additionally need a PostgreSQL you are happy to write to. They are skipped
unless `PG_TEST_DSN` is set, for example:

    $env:PG_TEST_DSN = "postgresql://postgres:<password>@localhost:5432/postgres"

They create (and drop) a scratch database called `students_test` on that server.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from src.config import ApiSettings, DatabaseSettings, RetrySettings, Settings, StorageSettings
from src.persist import DB_RETRY_ERRORS, Database, apply_schema
from src.retry import Retryer, RetryPolicy

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = REPO_ROOT / "samples"
SCHEMA_FILE = REPO_ROOT / "db" / "001_schema.sql"
TEST_DATABASE = "students_test"


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    return SAMPLES_DIR


@pytest.fixture(scope="session")
def expected_output() -> dict:
    return json.loads((SAMPLES_DIR / "expected_students.json").read_text(encoding="utf-8"))


@pytest.fixture
def fast_retryer() -> Retryer:
    """Same policy shape as production, but it never actually sleeps."""
    return Retryer(
        RetryPolicy(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02),
        retry_on=DB_RETRY_ERRORS,
        sleep=lambda _: None,
    )


@pytest.fixture(scope="session")
def db_settings() -> DatabaseSettings:
    dsn = os.environ.get("PG_TEST_DSN")
    if not dsn:
        pytest.skip("set PG_TEST_DSN to run database tests")

    params = conninfo_to_dict(dsn)
    try:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)")
            admin.execute(f"CREATE DATABASE {TEST_DATABASE}")
    except psycopg.Error as exc:
        pytest.skip(f"PG_TEST_DSN is not usable: {exc}")

    settings = DatabaseSettings(
        host=str(params.get("host") or "localhost"),
        port=int(params.get("port") or 5432),
        database=TEST_DATABASE,
        user=str(params.get("user") or "postgres"),
        password=params.get("password"),
        sslmode=str(params.get("sslmode") or "prefer"),
        use_managed_identity=False,
    )
    with psycopg.connect(settings.conninfo(), autocommit=True) as connection:
        apply_schema(connection, SCHEMA_FILE)
    return settings


@pytest.fixture
def db_connection(db_settings: DatabaseSettings) -> Iterator[psycopg.Connection]:
    """A clean database for every test."""
    with psycopg.connect(db_settings.conninfo(), autocommit=True) as connection:
        connection.execute("TRUNCATE students, api_checkpoint, ingest_run RESTART IDENTITY")
        yield connection


@pytest.fixture
def database(db_settings: DatabaseSettings, fast_retryer: Retryer) -> Database:
    return Database(db_settings, fast_retryer)


@pytest.fixture
def pipeline_settings(tmp_path: Path, db_settings: DatabaseSettings) -> Settings:
    """Local folder storage, scratch database, tiny chunks so chunking is actually exercised."""
    return Settings(
        storage=StorageSettings(
            landing_container="landing",
            processed_container="processed",
            quarantine_container="quarantine",
            account_name=None,
            local_root=str(tmp_path / "store"),
        ),
        database=db_settings,
        api=ApiSettings(
            base_url="",
            students_path="/students",
            auth_type="oauth2_client_credentials",
            token_url=None,
            client_id=None,
            client_secret=None,
            static_token=None,
            token_expiry_skew_seconds=0,
            page_size=2,
            timeout_seconds=5.0,
        ),
        retry=RetrySettings(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02),
        chunk_size=2,
        run_stale_after_seconds=3600,
        log_level="WARNING",
        csv_schedule_cron="0 0 2 * * *",
        api_schedule_cron="0 0 * * * *",
    )
