"""Unit tests for the JSON log formatter."""

import json
import logging
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from kamayoq.log import JsonFormatter, configure_logging


@pytest.fixture
def restored_root_logger() -> Iterator[None]:
    """Put back the handlers and the level of the root logger after the test."""
    saved_handlers = logging.root.handlers[:]
    saved_level = logging.root.level
    yield
    for handler in logging.root.handlers:
        if handler not in saved_handlers:
            handler.close()
    logging.root.handlers[:] = saved_handlers
    logging.root.setLevel(saved_level)


def make_record(**fields: Any) -> logging.LogRecord:
    """Return a log record of the logger kamayoq.test with the given fields."""
    return logging.makeLogRecord(
        {
            "name": "kamayoq.test",
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


def test_time_is_utc_iso_8601_with_milliseconds() -> None:
    """Write the time of the record in UTC, to the millisecond."""
    created = datetime(2026, 11, 14, 4, 45, 25, 890123, tzinfo=UTC).timestamp()
    fields = json.loads(JsonFormatter().format(make_record(created=created)))
    assert fields["time"] == "2026-11-14T04:45:25.890+00:00"


@pytest.mark.usefixtures("restored_root_logger")
def test_configure_logging_sends_uvicorn_named_loggers_to_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Write the records of the uvicorn loggers to stderr as JSON."""
    configure_logging("INFO")
    logging.getLogger("uvicorn.error").info("Started server process [%d]", 42)
    logging.getLogger("uvicorn.access").info(
        '%s - "%s" %d', "127.0.0.1:53889", "GET /healthz HTTP/1.1", 200
    )
    logging.getLogger("uvicorn.access").debug("not at the INFO level")
    lines = capsys.readouterr().err.splitlines()
    records = [json.loads(line) for line in lines]
    assert [(r["logger"], r["level"], r["message"]) for r in records] == [
        ("uvicorn.error", "INFO", "Started server process [42]"),
        ("uvicorn.access", "INFO", '127.0.0.1:53889 - "GET /healthz HTTP/1.1" 200'),
    ]
