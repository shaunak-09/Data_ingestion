import json
import logging

from src.logging_setup import JsonFormatter, set_correlation_id


def test_json_formatter_keeps_event_and_adds_human_message():
    set_correlation_id("test-correlation")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="csv.scan_complete",
        args=(),
        exc_info=None,
    )
    record.fields = {"candidates": 1}

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "csv.scan_complete"
    assert payload["message"] == "CSV scan found 1 candidate file."
    assert payload["correlation_id"] == "test-correlation"
    assert payload["candidates"] == 1
