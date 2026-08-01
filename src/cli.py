"""Local entry point. Runs exactly the same jobs the Azure Functions triggers run.

    python -m src.cli init-db
    python -m src.cli csv
    python -m src.cli api
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config import load_settings
from src.logging_setup import configure_logging, log_event, new_correlation_id, set_correlation_id
from src.persist import apply_pending_migrations
from src.pipeline import JobError, build_context, run_api_job, run_csv_job

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is a local convenience only; Azure injects real app settings
    load_dotenv = None

LOG = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli", description="Run a student ingestion job locally."
    )
    parser.add_argument("job", choices=("init-db", "csv", "api"))
    args = parser.parse_args(argv)

    if load_dotenv is not None:
        load_dotenv()

    settings = load_settings()
    configure_logging(settings.log_level)
    set_correlation_id(new_correlation_id())
    context = build_context(settings)

    if args.job == "init-db":
        with context.database.session() as connection:
            applied = apply_pending_migrations(connection, MIGRATIONS_DIR)
        log_event(LOG, logging.INFO, "cli.schema_applied", applied=applied)
        return 0

    try:
        if args.job == "csv":
            summaries = run_csv_job(context)
            log_event(LOG, logging.INFO, "cli.csv_done", files=len(summaries))
        else:
            run_api_job(context)
    except JobError as exc:
        log_event(LOG, logging.ERROR, "cli.job_failed", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
