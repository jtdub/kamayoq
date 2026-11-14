"""Unit tests for the JSON log formatter."""

import json
import logging
import sys
from typing import Any

from kamayoq.log import JsonFormatter


def make_record(**fields: Any) -> logging.LogRecord:
    """Return a log record of the logger kamayoq.test with the given fields."""
    return logging.makeLogRecord(
        {
            "name": "kamayoq.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "ready in %d ms",
            "args": (12,),
            **fields,
        }
    )


def test_record_is_one_json_object_with_required_keys() -> None:
    """Write the time, level, logger, and message keys on one line."""
    line = JsonFormatter().format(make_record())
    fields = json.loads(line)
    assert "\n" not in line
    assert set(fields) == {"time", "level", "logger", "message"}
    assert fields["level"] == "INFO"
    assert fields["logger"] == "kamayoq.test"
    assert fields["message"] == "ready in 12 ms"


def test_exception_and_stack_are_included_in_json() -> None:
    """Add the traceback and the stack when the record has them."""
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = make_record(exc_info=sys.exc_info(), stack_info="Stack (most recent)")
    fields = json.loads(JsonFormatter().format(record))
    assert "RuntimeError: boom" in fields["exc_info"]
    assert fields["stack_info"] == "Stack (most recent)"
