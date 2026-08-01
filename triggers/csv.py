"""Scheduled CSV ingestion. Scans the landing container on the configured CRON."""

import logging

import azure.functions as func

from src.config import load_settings
from src.logging_setup import configure_logging, log_event, new_correlation_id, set_correlation_id
from src.pipeline import build_context, run_csv_job

LOG = logging.getLogger(__name__)

bp = func.Blueprint()


@bp.timer_trigger(
    arg_name="timer",
    schedule="%CSV_SCHEDULE_CRON%",
    run_on_startup=False,
    use_monitor=True,
)
def ingest_csv(timer: func.TimerRequest) -> None:
    """Failures are left to propagate: the failed invocation is what raises the alert."""
    settings = load_settings()
    configure_logging(settings.log_level)
    set_correlation_id(new_correlation_id())

    log_event(
        LOG,
        logging.INFO,
        "trigger.csv_started",
        past_due=timer.past_due,
        schedule=settings.csv_schedule_cron,
    )
    summaries = run_csv_job(build_context(settings))
    log_event(
        LOG,
        logging.INFO,
        "trigger.csv_finished",
        files_processed=len(summaries),
        rows_written=sum(summary.inserted + summary.updated for summary in summaries),
    )
